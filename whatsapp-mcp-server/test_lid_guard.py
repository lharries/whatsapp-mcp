"""Guard check: a @lid recipient is resolved to a real phone, or refused loudly.

Run: uv run python test_lid_guard.py

Sends nothing. Unknown LIDs are refused before any network call, and the
known-LID path is exercised with requests.post patched out.
"""

import sys
from unittest.mock import MagicMock, patch

import whatsapp

UNKNOWN_LID = "999999999999@lid"
UNCHANGED = [
    "1234567890",
    "1234567890@s.whatsapp.net",
    "120363000000000000@g.us",
]


def check(condition: bool, detail: str) -> None:
    if not condition:
        raise AssertionError(detail)


def a_known_lid() -> tuple[str, str] | None:
    """Pick any real lid→phone pair from whatsmeow's own mapping, or None.

    Returns None when the bridge has never run here — the resolution half of
    the check is then skipped rather than failing.
    """
    import sqlite3

    try:
        with sqlite3.connect(
            f"file:{whatsapp.SESSION_DB_PATH}?mode=ro", uri=True
        ) as conn:
            return conn.execute(
                "SELECT lid, pn FROM whatsmeow_lid_map LIMIT 1"
            ).fetchone()
    except sqlite3.Error:
        return None


def main() -> None:
    for recipient in UNCHANGED:
        resolved, error = whatsapp._resolve_recipient(recipient)
        check(error is None, f"{recipient} wrongly refused: {error}")
        check(resolved == recipient, f"{recipient} wrongly rewritten to {resolved}")

    _, error = whatsapp._resolve_recipient(UNKNOWN_LID)
    check(error is not None, "unknown LID was not refused")
    _, error = whatsapp._resolve_recipient(UNKNOWN_LID.upper())
    check(error is not None, "guard is case-sensitive")

    # No send path may report success for an unresolvable LID.
    paths = {
        "send_message": lambda: whatsapp.send_message(UNKNOWN_LID, "x"),
        "send_file": lambda: whatsapp.send_file(UNKNOWN_LID, ""),
        "send_audio_message": lambda: whatsapp.send_audio_message(UNKNOWN_LID, ""),
        "_ssh_send_text": lambda: whatsapp._ssh_send_text(UNKNOWN_LID, "x"),
    }
    for name, send in paths.items():
        ok, reason = send()
        check(ok is False, f"{name} reported success for an unknown LID: {reason}")
        check("LID" in reason, f"{name} refused for the wrong reason: {reason}")

    pair = a_known_lid()
    if pair is None:
        sys.stdout.write("warn — lid map empty, resolution path not exercised\n")
        return
    lid, phone = pair
    resolved, error = whatsapp._resolve_recipient(f"{lid}@lid")
    check(error is None, f"known LID refused: {error}")
    check(resolved == f"{phone}@s.whatsapp.net", f"resolved to {resolved}")

    # The resolved phone — not the lid — is what actually reaches the bridge.
    response = MagicMock(status_code=200)
    response.json.return_value = {"success": True, "message": "Sent"}
    with patch.object(whatsapp.requests, "post", return_value=response) as post:
        _, receipt = whatsapp.send_message(f"{lid}@lid", "x")
    sent_to = post.call_args.kwargs["json"]["recipient"]
    check(sent_to == f"{phone}@s.whatsapp.net", f"bridge would receive {sent_to}")
    # A success must always name the line it went out on — a server pointed at
    # the wrong bridge is otherwise indistinguishable from a correct one.
    check(f"[line: {whatsapp._sending_line()}]" in receipt, f"line hidden: {receipt}")

    sys.stdout.write(
        f"ok — {len(paths)} paths refuse unknown LIDs, "
        f"{len(UNCHANGED)} formats pass through, known LID resolves to a phone\n"
    )


if __name__ == "__main__":
    main()
