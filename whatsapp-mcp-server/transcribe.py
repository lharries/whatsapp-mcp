"""Local speech-to-text for WhatsApp voice messages (faster-whisper / CTranslate2)."""
import os
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional

# Windows without Developer Mode cannot create the symlinks the HF cache uses by
# default, which otherwise fails the model download with WinError 1314.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

# Env overrides: WHISPER_MODEL (e.g. tiny/base/small/medium/large-v3/large-v3-turbo),
# WHISPER_DEVICE (cuda/cpu/auto), WHISPER_COMPUTE_TYPE (float16/int8_float16/int8).
DEFAULT_MODEL = os.environ.get("WHISPER_MODEL", "large-v3-turbo")
DEFAULT_DEVICE = os.environ.get("WHISPER_DEVICE", "auto")
DEFAULT_COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE_TYPE", "")

# Loaded models are cached per (name, device, compute_type) - loading costs seconds.
_models: Dict[tuple, Any] = {}


def _register_cuda_dlls() -> None:
    """Expose the pip-installed CUDA runtime to CTranslate2.

    The nvidia-* wheels ship cuBLAS/cuDNN/nvrtc inside site-packages rather than
    on PATH, so Windows cannot resolve them unless we add the directories.
    """
    if not hasattr(os, "add_dll_directory"):
        return
    try:
        import nvidia
    except ImportError:
        return
    # nvidia is a namespace package, so it has __path__ but no __file__.
    for root in list(getattr(nvidia, "__path__", [])):
        for lib in ("cublas", "cudnn", "cuda_nvrtc", "cuda_runtime"):
            bin_dir = os.path.join(root, lib, "bin")
            if not os.path.isdir(bin_dir):
                continue
            try:
                os.add_dll_directory(bin_dir)
            except OSError:
                pass
            os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")


_register_cuda_dlls()


def _log(msg: str) -> None:
    # stdout carries the worker protocol, so diagnostics go to stderr, which the
    # client redirects to a log file.
    print(f"{time.strftime('%H:%M:%S')} {msg}", file=sys.stderr)


def _smoke_test(model) -> None:
    """Decode a second of silence so missing CUDA libs surface at load time."""
    import numpy as np

    list(model.transcribe(np.zeros(16000, dtype=np.float32), vad_filter=False)[0])


def _load_model(model_size: str, device: str, compute_type: str):
    from faster_whisper import WhisperModel

    candidates: List[tuple] = []
    if device in ("auto", "cuda"):
        candidates.append(("cuda", compute_type or "float16"))
    if device in ("auto", "cpu"):
        candidates.append(("cpu", compute_type or "int8"))

    last_error: Optional[Exception] = None
    for dev, ctype in candidates:
        key = (model_size, dev, ctype)
        if key in _models:
            return _models[key], dev, ctype
        try:
            _log(f"[transcribe] loading {model_size} on {dev} ({ctype})")
            model = WhisperModel(model_size, device=dev, compute_type=ctype)
            if dev == "cuda":
                _smoke_test(model)
            _models[key] = model
            return model, dev, ctype
        except Exception as e:  # CUDA/cuDNN missing, unsupported arch, OOM
            last_error = e
            _log(f"[transcribe] {dev} unavailable: {e}")

    raise RuntimeError(f"could not load whisper model {model_size}: {last_error}")


def _to_wav(src_path: str) -> str:
    """Normalise any audio container to 16 kHz mono WAV, which whisper expects."""
    if not shutil.which("ffmpeg"):
        return src_path
    fd, out_path = tempfile.mkstemp(suffix=".wav", prefix="wa_voice_")
    os.close(fd)
    result = subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-i", src_path, "-ar", "16000", "-ac", "1", "-f", "wav", out_path],
        capture_output=True,
        stdin=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        os.unlink(out_path)
        raise RuntimeError(f"ffmpeg failed: {result.stderr.decode('utf-8', 'replace')[-400:]}")
    return out_path


def transcribe_file(
    audio_path: str,
    language: Optional[str] = None,
    translate_to_english: bool = False,
    model_size: Optional[str] = None,
    with_timestamps: bool = False,
) -> Dict[str, Any]:
    if not os.path.isfile(audio_path):
        return {"success": False, "message": f"file not found: {audio_path}"}

    wav_path = None
    try:
        _log(f"transcribe: start {os.path.basename(audio_path)}")
        model, device, compute_type = _load_model(
            model_size or DEFAULT_MODEL, DEFAULT_DEVICE, DEFAULT_COMPUTE_TYPE
        )
        _log("transcribe: model ready, converting audio")
        wav_path = _to_wav(audio_path)
        _log("transcribe: audio converted, decoding")

        segments, info = model.transcribe(
            wav_path,
            language=language,
            task="translate" if translate_to_english else "transcribe",
            vad_filter=True,
            beam_size=5,
        )
        segments = list(segments)  # the generator is what actually runs inference
        _log("transcribe: decode finished")
        text = " ".join(s.text.strip() for s in segments).strip()

        result: Dict[str, Any] = {
            "success": True,
            "text": text,
            "language": info.language,
            "language_probability": round(info.language_probability, 3),
            "duration_seconds": round(info.duration, 1),
            "device": device,
            "model": model_size or DEFAULT_MODEL,
        }
        if with_timestamps:
            result["segments"] = [
                {"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()}
                for s in segments
            ]
        if not text:
            result["message"] = "no speech detected in the audio"
        return result
    except Exception as e:
        return {"success": False, "message": str(e)}
    finally:
        if wav_path and wav_path != audio_path and os.path.exists(wav_path):
            os.unlink(wav_path)
