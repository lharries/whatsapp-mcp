"""Turn media into something a model can actually look at: video frames, transcripts, images."""
import json
import os
import re
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

# Sampling a long video every few seconds would flood the context, so the frame
# count is capped and the interval derived from it unless one is given.
DEFAULT_MAX_FRAMES = 8
DEFAULT_MAX_DIMENSION = 640
# Scene detection decodes the whole file, which is not worth it for long videos.
SCENE_DETECT_MAX_DURATION = 600.0
SCENE_THRESHOLD = 0.3


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def _require_ffmpeg() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise RuntimeError(f"{tool} is required for video inspection but was not found on PATH")


def probe(path: str) -> Dict[str, Any]:
    """Read duration, geometry and stream layout without decoding the video."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", path],
        capture_output=True,
        stdin=subprocess.DEVNULL,
    )
    if out.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {out.stderr.decode('utf-8', 'replace')[-300:]}")
    data = json.loads(out.stdout.decode("utf-8", "replace"))

    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    if video is None:
        raise RuntimeError("file has no video stream")

    duration = float(data.get("format", {}).get("duration") or video.get("duration") or 0.0)
    fps = 0.0
    rate = video.get("avg_frame_rate") or "0/0"
    if "/" in rate:
        num, den = rate.split("/", 1)
        fps = float(num) / float(den) if float(den or 0) else 0.0

    return {
        "duration_seconds": round(duration, 1),
        "width": video.get("width"),
        "height": video.get("height"),
        "fps": round(fps, 2),
        "has_audio": audio is not None,
        "video_codec": video.get("codec_name"),
    }


def _scene_timestamps(path: str, threshold: float = SCENE_THRESHOLD) -> List[float]:
    """Timestamps where the picture changes substantially."""
    out = subprocess.run(
        ["ffmpeg", "-nostdin", "-i", path, "-vf", f"select='gt(scene,{threshold})',showinfo",
         "-an", "-f", "null", "-"],
        capture_output=True,
        stdin=subprocess.DEVNULL,
    )
    stderr = out.stderr.decode("utf-8", "replace")
    return [float(m) for m in re.findall(r"pts_time:([0-9.]+)", stderr)]


def _pick_times(duration: float, max_frames: int, interval: Optional[float],
                scenes: Optional[List[float]]) -> Tuple[List[float], str]:
    if scenes:
        if len(scenes) <= max_frames:
            return scenes, "scenes"
        # More scene changes than we can show: spread the picks across them all
        # rather than taking the first N, which would only cover the opening.
        step = len(scenes) / max_frames
        return [scenes[int(i * step)] for i in range(max_frames)], "scenes"

    if interval and interval > 0:
        times = [t for t in _frange(interval / 2, duration, interval)][:max_frames]
    else:
        # Sample at the midpoint of equal slices so the first frame is not the
        # black frame videos often start with.
        step = duration / max_frames if max_frames else duration
        times = [step * (i + 0.5) for i in range(max_frames)]
    return [t for t in times if t < duration] or [duration / 2], "interval"


def _frange(start: float, stop: float, step: float):
    t = start
    while t < stop:
        yield t
        t += step


def scale_filter(max_dimension: int) -> str:
    """Cap the longest side at max_dimension, keeping the aspect ratio and even sides."""
    return (f"scale='if(gt(iw,ih),min({max_dimension},iw),-2)'"
            f":'if(gt(iw,ih),-2,min({max_dimension},ih))'")


def _grab_frame(path: str, when: float, max_dimension: int) -> Optional[bytes]:
    """Decode a single frame at `when`, downscaled, as JPEG bytes."""
    out = subprocess.run(
        ["ffmpeg", "-nostdin", "-ss", f"{when:.3f}", "-i", path, "-frames:v", "1",
         "-vf", scale_filter(max_dimension), "-q:v", "4", "-f", "image2",
         "-c:v", "mjpeg", "pipe:1"],
        capture_output=True,
        stdin=subprocess.DEVNULL,
    )
    if out.returncode != 0 or not out.stdout:
        _log(f"[video] no frame at {when:.1f}s: {out.stderr.decode('utf-8','replace')[-200:]}")
        return None
    return out.stdout


def extract_frames(
    path: str,
    max_frames: int = DEFAULT_MAX_FRAMES,
    interval_seconds: Optional[float] = None,
    max_dimension: int = DEFAULT_MAX_DIMENSION,
    mode: str = "auto",
) -> Dict[str, Any]:
    """Return JPEG frames with their timestamps, plus how they were chosen."""
    _require_ffmpeg()
    info = probe(path)
    duration = info["duration_seconds"]
    if duration <= 0:
        raise RuntimeError("could not determine video duration")

    scenes: Optional[List[float]] = None
    wants_scenes = mode in ("auto", "scenes") and interval_seconds is None
    if wants_scenes and duration <= SCENE_DETECT_MAX_DURATION:
        found = _scene_timestamps(path)
        # One or two hits means a mostly static video; even sampling tells more.
        if len(found) >= 3 or mode == "scenes":
            scenes = found or None

    times, how = _pick_times(duration, max_frames, interval_seconds, scenes)

    frames = []
    for t in times:
        data = _grab_frame(path, t, max_dimension)
        if data:
            frames.append({"time": round(t, 1), "jpeg": data})

    info["frames"] = frames
    info["sampling"] = how
    info["frame_count"] = len(frames)
    return info


def format_timestamp(seconds: float) -> str:
    return f"{int(seconds) // 60:d}:{int(seconds) % 60:02d}"


def load_image(path: str, max_dimension: int = 1024) -> Dict[str, Any]:
    """Read a still image, downscaled to JPEG bytes a model can be shown.

    One full-resolution photo would otherwise take far more context than it is
    worth, so the longest side is capped before encoding.
    """
    _require_ffmpeg()
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", path],
        capture_output=True,
        stdin=subprocess.DEVNULL,
    )
    width = height = None
    if out.returncode == 0:
        streams = json.loads(out.stdout.decode("utf-8", "replace")).get("streams", [])
        still = next((s for s in streams if s.get("codec_type") == "video"), None)
        if still:
            width, height = still.get("width"), still.get("height")

    encoded = subprocess.run(
        ["ffmpeg", "-nostdin", "-i", path, "-vf", scale_filter(max_dimension), "-q:v", "4",
         "-frames:v", "1", "-f", "image2", "-c:v", "mjpeg", "pipe:1"],
        capture_output=True,
        stdin=subprocess.DEVNULL,
    )
    if encoded.returncode != 0 or not encoded.stdout:
        raise RuntimeError(
            f"could not read image: {encoded.stderr.decode('utf-8', 'replace')[-300:]}"
        )

    return {
        "jpeg": encoded.stdout,
        "width": width,
        "height": height,
        "bytes": len(encoded.stdout),
    }
