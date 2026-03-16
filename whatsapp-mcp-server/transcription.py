import os
import sqlite3
from typing import Optional

WHISPER_MODEL_NAME = os.environ.get("WHISPER_MODEL", "base")

_model = None


def get_transcription_model():
    """Lazy-load and cache the WhisperModel instance."""
    global _model
    if _model is None:
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise ImportError(
                "faster-whisper is not installed. "
                "Install it with: uv sync --extra transcription"
            )
        _model = WhisperModel(WHISPER_MODEL_NAME, device="auto", compute_type="int8")
    return _model


def transcribe_audio_file(path: str, language: Optional[str] = None) -> dict:
    """Transcribe an audio file using faster-whisper.

    Returns:
        dict with keys: text, language, segments
    """
    model = get_transcription_model()
    segments, info = model.transcribe(path, language=language, beam_size=5)
    segment_list = [{"start": s.start, "end": s.end, "text": s.text} for s in segments]
    full_text = "".join(s["text"] for s in segment_list).strip()
    return {
        "text": full_text,
        "language": info.language,
        "segments": segment_list,
    }


def ensure_transcriptions_table(db_path: str) -> None:
    """Create the transcriptions cache table if it doesn't exist."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS transcriptions (
                message_id TEXT,
                chat_jid TEXT,
                transcription TEXT,
                language TEXT,
                model TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (message_id, chat_jid)
            )
        """)
        conn.commit()
    finally:
        conn.close()


def get_cached_transcription(db_path: str, message_id: str, chat_jid: str) -> Optional[dict]:
    """Return cached transcription or None."""
    ensure_transcriptions_table(db_path)
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            "SELECT transcription, language, model FROM transcriptions WHERE message_id = ? AND chat_jid = ?",
            (message_id, chat_jid),
        )
        row = cursor.fetchone()
        if row:
            return {"text": row[0], "language": row[1], "model": row[2]}
        return None
    finally:
        conn.close()


def cache_transcription(
    db_path: str, message_id: str, chat_jid: str, text: str, language: str, model: str
) -> None:
    """Store a transcription in the cache."""
    ensure_transcriptions_table(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO transcriptions (message_id, chat_jid, transcription, language, model) VALUES (?, ?, ?, ?, ?)",
            (message_id, chat_jid, text, language, model),
        )
        conn.commit()
    finally:
        conn.close()
