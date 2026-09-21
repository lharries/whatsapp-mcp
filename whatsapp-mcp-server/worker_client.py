"""Client side of the transcription worker: keeps one worker alive and talks to it."""
import json
import os
import subprocess
import sys
import threading
from typing import Any, Dict, Optional

_WORKER_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "whisper_worker.py")
_LOG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "whatsapp-bridge", "store", "transcribe-worker.log")
# Loading the model takes seconds and a long recording takes longer still, so the
# ceiling is generous; it exists only so a wedged worker cannot hang the server.
_TIMEOUT_SECONDS = float(os.environ.get("WHISPER_WORKER_TIMEOUT", "900"))

_process: Optional[subprocess.Popen] = None
_lock = threading.Lock()


def _start() -> subprocess.Popen:
    log = open(_LOG_PATH, "a", encoding="utf-8", buffering=1)
    return subprocess.Popen(
        [sys.executable, _WORKER_SCRIPT],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=log,  # a pipe nobody drains would eventually block the worker
        text=True,
        encoding="utf-8",
        cwd=os.path.dirname(_WORKER_SCRIPT),
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )


def _ensure_worker() -> subprocess.Popen:
    global _process
    if _process is None or _process.poll() is not None:
        _process = _start()
    return _process


def _shutdown() -> None:
    global _process
    if _process is not None:
        try:
            _process.kill()
        except OSError:
            pass
        _process = None


def transcribe(audio_path: str, **kwargs: Any) -> Dict[str, Any]:
    """Send one transcription request to the worker, starting it if needed."""
    request = {"audio_path": audio_path, **kwargs}

    with _lock:  # one request at a time: the protocol is a single pipe
        for attempt in (1, 2):  # a worker that died between calls gets one restart
            worker = _ensure_worker()
            try:
                worker.stdin.write(json.dumps(request) + "\n")
                worker.stdin.flush()
                reply = worker.stdout.readline()
            except (BrokenPipeError, OSError, ValueError) as e:
                _shutdown()
                if attempt == 2:
                    return {"success": False, "message": f"transcription worker failed: {e}"}
                continue

            if not reply:  # worker exited without answering
                _shutdown()
                if attempt == 2:
                    return {"success": False,
                            "message": "transcription worker exited; see transcribe-worker.log"}
                continue

            try:
                return json.loads(reply)
            except json.JSONDecodeError:
                _shutdown()
                return {"success": False,
                        "message": f"unreadable worker reply: {reply[:200]}"}

    return {"success": False, "message": "transcription worker unavailable"}
