"""Transcription worker: one request per line of JSON in, one line of JSON out.

Whisper is loaded here rather than in the MCP server so that the server process
never imports CUDA libraries, never blocks its event loop on a long decode, and
survives a crash in the speech stack. The worker stays alive between requests,
so the model is loaded once.
"""
import json
import sys

from transcribe import transcribe_file


def main() -> None:
    # Windows would otherwise encode replies in the console codepage, which the
    # client reads as UTF-8 and chokes on the first Cyrillic transcript.
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            result = transcribe_file(
                request["audio_path"],
                language=request.get("language"),
                translate_to_english=request.get("translate_to_english", False),
                model_size=request.get("model_size"),
                with_timestamps=request.get("with_timestamps", False),
            )
        except Exception as e:  # never die on one bad request
            result = {"success": False, "message": f"worker error: {e}"}

        sys.stdout.write(json.dumps(result, ensure_ascii=True) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
