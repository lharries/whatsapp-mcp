"""Unit tests for the security helpers in whatsapp.py.

These cover the two pure, side-effect-free guards added for hardening:
  - _clamp_pagination: bounds caller-supplied limit/page
  - _resolve_outbound_media_path: confines outbound files to an allowlist

The module imports optional runtime deps (`audio`, `requests`) that aren't
needed for these helpers, so we stub them before import.
"""
import os
import sys
import types

# Make whatsapp.py importable and stub its optional deps.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.modules.setdefault("audio", types.ModuleType("audio"))
_requests_stub = types.ModuleType("requests")
_requests_stub.RequestException = Exception
_requests_stub.post = lambda *a, **k: None
sys.modules.setdefault("requests", _requests_stub)

import pytest  # noqa: E402

import whatsapp  # noqa: E402


# --- _clamp_pagination ------------------------------------------------------

@pytest.mark.parametrize("limit,page,expected", [
    (20, 0, (20, 0)),                       # normal values pass through
    (10 ** 9, 0, (whatsapp.MAX_PAGE_SIZE, 0)),  # huge limit is capped
    (0, 0, (1, 0)),                         # limit floored to 1
    (20, -5, (20, 0)),                      # negative page floored to 0
    ("abc", None, (20, 0)),                 # junk input falls back to defaults
    (50.9, 2.0, (50, 2)),                   # floats truncate via int()
])
def test_clamp_pagination(limit, page, expected):
    assert whatsapp._clamp_pagination(limit, page) == expected


# --- _resolve_outbound_media_path -------------------------------------------

@pytest.fixture
def allowed_dir(tmp_path, monkeypatch):
    """Point the media allowlist at an isolated temp dir."""
    root = os.path.realpath(str(tmp_path))
    monkeypatch.setattr(whatsapp, "WHATSAPP_ALLOWED_MEDIA_DIRS", [root])
    return tmp_path


def test_allowed_file_is_resolved(allowed_dir):
    f = allowed_dir / "ok.txt"
    f.write_text("hi")
    resolved, err = whatsapp._resolve_outbound_media_path(str(f))
    assert err is None
    assert resolved == os.path.realpath(str(f))


def test_empty_path_rejected(allowed_dir):
    resolved, err = whatsapp._resolve_outbound_media_path("")
    assert resolved is None
    assert "must be provided" in err


def test_missing_file_rejected(allowed_dir):
    resolved, err = whatsapp._resolve_outbound_media_path(str(allowed_dir / "nope.txt"))
    assert resolved is None
    assert "not found" in err


def test_file_outside_allowlist_rejected(allowed_dir, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside") / "secret.txt"
    outside.write_text("secret")
    resolved, err = whatsapp._resolve_outbound_media_path(str(outside))
    assert resolved is None
    assert "outside the allowed" in err


def test_traversal_escape_rejected(allowed_dir, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside") / "secret.txt"
    outside.write_text("secret")
    sneaky = os.path.join(str(allowed_dir), "..", os.path.basename(str(outside.parent)), "secret.txt")
    resolved, err = whatsapp._resolve_outbound_media_path(sneaky)
    assert resolved is None


def test_symlink_pointing_outside_rejected(allowed_dir, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside") / "secret.txt"
    outside.write_text("secret")
    link = allowed_dir / "link.txt"
    os.symlink(str(outside), str(link))
    resolved, err = whatsapp._resolve_outbound_media_path(str(link))
    assert resolved is None
    assert "outside the allowed" in err


def test_sibling_prefix_dir_rejected(allowed_dir):
    # A dir whose name shares the allowlist root as a string prefix must not match.
    sibling = str(allowed_dir) + "-evil"
    os.makedirs(sibling, exist_ok=True)
    f = os.path.join(sibling, "x.txt")
    with open(f, "w") as fh:
        fh.write("x")
    resolved, err = whatsapp._resolve_outbound_media_path(f)
    assert resolved is None
