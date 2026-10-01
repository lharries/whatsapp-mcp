"""Manage this installation's private bridge; never expose its bearer token."""
import json
import os
from functools import lru_cache
from pathlib import Path
import secrets
import socket
import subprocess
import threading
import time
import tempfile
from contextlib import contextmanager

import requests

ROOT = Path(__file__).resolve().parent
STATE = ROOT / ".runtime"
PORT = int(os.environ.get("WHATSAPP_API_PORT", "18765"))
if not 1024 <= PORT <= 65535:
    raise ValueError("WHATSAPP_API_PORT must be between 1024 and 65535")
BASE_URL = f"https://127.0.0.1:{PORT}/api"
_lock = threading.Lock()


def bridge_binary():
    name = "whatsapp-bridge.exe" if os.name == "nt" else "whatsapp-bridge"
    return ROOT / "whatsapp-bridge" / name


@lru_cache(maxsize=None)
def protect_state_directory(path):
    if os.name == "nt":
        # Python <3.13 ignores mkdir's 0700 on Windows; use an owner-only DACL.
        subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r",
                        "*S-1-3-4:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F",
                        "*S-1-5-32-544:(OI)(CI)F"], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        path.chmod(0o700)


@contextmanager
def state_lock(name):
    # Both platforms release the lock if a launcher process exits unexpectedly.
    with (STATE / name).open("a+b") as lock:
        if os.name == "nt":
            import msvcrt
            if lock.seek(0, os.SEEK_END) == 0:
                lock.write(b"\0")
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock, fcntl.LOCK_UN)


def configure():
    binary = bridge_binary()
    if not binary.is_file():
        raise RuntimeError("The WhatsApp bridge has not been built; build the whatsapp-bridge package first")
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    protect_state_directory(STATE)
    with state_lock("configure.lock"):
        return configure_locked(binary)


def configure_locked(binary):
    token_path = STATE / "bridge-token"
    try:
        with token_path.open("x", encoding="ascii") as file:
            os.chmod(token_path, 0o600)
            file.write(secrets.token_hex(32))
    except FileExistsError:
        pass
    token = token_path.read_text(encoding="ascii").strip()
    if len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
        raise RuntimeError("Invalid private bridge credential; installation needs repair")
    if not (STATE / "bridge-cert.pem").is_file():
        subprocess.run([str(binary), "--initialize-tls", str(STATE)], check=True,
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return token


def request(method, endpoint, *, payload=None, start=True):
    if endpoint not in {"status", "send", "download"}:
        raise ValueError("Unknown bridge endpoint")
    token = configure()
    if start:
        ensure_bridge(token)
        if endpoint != "status":
            wait_for_connection()
    with requests.Session() as session:
        session.trust_env = False
        return session.request(method, f"{BASE_URL}/{endpoint}", json=payload,
                               headers={"Authorization": f"Bearer {token}"},
                               timeout=(3, 120), allow_redirects=False,
                               verify=str(STATE / "bridge-cert.pem"))


def ensure_bridge(token=None):
    token = token or configure()
    with _lock, state_lock("launch.lock"):
        try:
            response = request("GET", "status", start=False)
            if response.status_code == 200:
                return
            raise RuntimeError("The bridge port is occupied by a different service")
        except requests.exceptions.SSLError as error:
            raise RuntimeError("The private bridge identity could not be verified") from error
        except requests.ConnectionError:
            pass
        # TLS authenticates every connection before any credentials or body are sent.
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", PORT)) == 0:
                raise RuntimeError("The private bridge port is already in use")
        binary = bridge_binary()
        if not binary.is_file():
            raise RuntimeError("The WhatsApp bridge has not been built")
        env = dict(os.environ, WHATSAPP_API_TOKEN=token, WHATSAPP_API_PORT=str(PORT),
                   WHATSAPP_TLS_CERT=str(STATE / "bridge-cert.pem"),
                   WHATSAPP_TLS_KEY=str(STATE / "bridge-key.pem"))
        with (STATE / "bridge.log").open("ab") as log:
            child = subprocess.Popen([str(binary)], cwd=binary.parent, env=env,
                                     stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        (STATE / "bridge-pid").write_text(str(child.pid), encoding="ascii")
        for _ in range(50):
            if child.poll() is not None:
                raise RuntimeError("Bridge startup failed; inspect the private bridge log")
            try:
                if request("GET", "status", start=False).status_code == 200:
                    return
            except requests.ConnectionError:
                pass
            time.sleep(0.1)
        raise RuntimeError("Bridge startup timed out")


def wait_for_connection():
    for _ in range(100):
        response = request("GET", "status", start=False)
        response.raise_for_status()
        status = response.json()
        if not status.get("paired"):
            raise RuntimeError("WhatsApp needs phone pairing. Run check_connection first.")
        if status.get("connected"):
            return
        time.sleep(0.1)
    raise RuntimeError("WhatsApp is still reconnecting. Check its connection before trying again.")


def connection_status():
    response = request("GET", "status")
    response.raise_for_status()
    status = response.json()
    qr = status.pop("qr_code", "")
    # Pairing secrets stay local; tools return a user-viewable image path only.
    if qr:
        import qrcode
        path = STATE / "pairing.png"
        with tempfile.NamedTemporaryFile(dir=STATE, suffix=".png", delete=False) as temporary:
            temporary_path = Path(temporary.name)
        try:
            qrcode.make(qr).save(temporary_path)
            temporary_path.replace(path)
        finally:
            temporary_path.unlink(missing_ok=True)
        status["pairing_image"] = str(path)
        status["instructions"] = "WhatsApp on your phone: Settings > Linked devices > Link a device. Scan the local image."
    elif status.get("paired"):
        (STATE / "pairing.png").unlink(missing_ok=True)
    return status
