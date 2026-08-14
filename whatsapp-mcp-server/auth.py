import base64
import hashlib
import hmac
import html as html_module
import json
import os
import secrets
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

CLIENT_ID: str = os.environ.get("MCP_CLIENT_ID", "claude")
CLIENT_SECRET: str = os.environ.get("MCP_CLIENT_SECRET", "")
TOKEN_TTL: int = int(os.environ.get("MCP_TOKEN_TTL", "3600"))
_TOKEN_FILE: str = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".tokens.json")

_auth_codes: dict[str, dict] = {}


def _load_tokens() -> dict[str, float]:
    try:
        with open(_TOKEN_FILE) as f:
            raw = json.load(f)
        now = time.time()
        return {t: exp for t, exp in raw.items() if exp > now}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_tokens(store: dict[str, float]) -> None:
    try:
        with open(_TOKEN_FILE, "w") as f:
            json.dump(store, f)
    except OSError:
        pass


_token_store: dict[str, float] = _load_tokens()


def _issue_token() -> str:
    token = secrets.token_urlsafe(32)
    _token_store[token] = time.time() + TOKEN_TTL
    _save_tokens(_token_store)
    return token


def _validate_token(token: str) -> bool:
    expiry = _token_store.get(token)
    if expiry is None:
        return False
    if time.time() > expiry:
        _token_store.pop(token, None)
        _save_tokens(_token_store)
        return False
    return True


EXEMPT_PATHS = frozenset([
    "/authorize",
    "/oauth/token",
    "/.well-known/oauth-authorization-server",
    "/.well-known/oauth-protected-resource",
    "/.well-known/openid-configuration",
    "/health",
])


async def authorize_get(request: Request) -> Response:
    """Show approval page for Authorization Code + PKCE flow."""
    p = request.query_params
    response_type = p.get("response_type")
    client_id = p.get("client_id", "")
    redirect_uri = p.get("redirect_uri", "")
    code_challenge = p.get("code_challenge", "")
    code_challenge_method = p.get("code_challenge_method", "S256")
    state = p.get("state", "")

    if response_type != "code":
        return JSONResponse({"error": "unsupported_response_type"}, status_code=400)
    if not hmac.compare_digest(client_id, CLIENT_ID):
        return JSONResponse({"error": "unauthorized_client"}, status_code=400)
    if code_challenge_method != "S256":
        return JSONResponse({"error": "invalid_request", "error_description": "only S256 supported"}, status_code=400)

    e = html_module.escape
    return HTMLResponse(f"""<!DOCTYPE html>
<html>
<head>
  <title>WhatsApp MCP — Authorize</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 420px;
           margin: 80px auto; padding: 24px; color: #333; }}
    h2 {{ margin-bottom: 8px; }}
    p {{ color: #555; line-height: 1.5; }}
    .btn {{ background: #25D366; color: #fff; border: none; padding: 14px 24px;
            border-radius: 8px; font-size: 16px; cursor: pointer; width: 100%;
            margin-top: 16px; }}
    .btn:hover {{ background: #1da851; }}
  </style>
</head>
<body>
  <h2>WhatsApp MCP</h2>
  <p>Claude is requesting access to read and send WhatsApp messages on your behalf.</p>
  <form method="post" action="/authorize">
    <input type="hidden" name="redirect_uri"    value="{e(redirect_uri)}">
    <input type="hidden" name="state"           value="{e(state)}">
    <input type="hidden" name="code_challenge"  value="{e(code_challenge)}">
    <button type="submit" class="btn">Allow Access</button>
  </form>
</body>
</html>""")


async def authorize_post(request: Request) -> Response:
    """Issue an authorization code and redirect back to the client."""
    data = await request.form()
    redirect_uri = str(data.get("redirect_uri", ""))
    state = str(data.get("state", ""))
    code_challenge = str(data.get("code_challenge", ""))

    code = secrets.token_urlsafe(32)
    _auth_codes[code] = {
        "code_challenge": code_challenge,
        "redirect_uri": redirect_uri,
        "expires_at": time.time() + 300,
    }

    sep = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(f"{redirect_uri}{sep}code={code}&state={state}", status_code=302)


async def token_endpoint(request: Request) -> JSONResponse:
    try:
        data = await request.form()
    except Exception:
        return JSONResponse({"error": "invalid_request"}, status_code=400)

    grant_type = data.get("grant_type")

    if grant_type == "authorization_code":
        code = str(data.get("code", ""))
        code_verifier = str(data.get("code_verifier", ""))
        redirect_uri = str(data.get("redirect_uri", ""))

        code_data = _auth_codes.pop(code, None)
        if not code_data:
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        if time.time() > code_data["expires_at"]:
            return JSONResponse({"error": "invalid_grant", "error_description": "code expired"}, status_code=400)
        if redirect_uri != code_data["redirect_uri"]:
            return JSONResponse({"error": "invalid_grant"}, status_code=400)

        # Verify PKCE: base64url(SHA256(code_verifier)) == code_challenge
        digest = hashlib.sha256(code_verifier.encode()).digest()
        computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        if not hmac.compare_digest(computed, code_data["code_challenge"]):
            return JSONResponse({"error": "invalid_grant", "error_description": "PKCE failed"}, status_code=400)

        return JSONResponse({"access_token": _issue_token(), "token_type": "bearer", "expires_in": TOKEN_TTL})

    elif grant_type == "client_credentials":
        if not CLIENT_SECRET:
            return JSONResponse({"error": "server_error", "error_description": "MCP_CLIENT_SECRET not set"}, status_code=500)
        id_ok = hmac.compare_digest(str(data.get("client_id", "")), CLIENT_ID)
        secret_ok = hmac.compare_digest(str(data.get("client_secret", "")), CLIENT_SECRET)
        if not (id_ok and secret_ok):
            return JSONResponse({"error": "invalid_client"}, status_code=401)
        return JSONResponse({"access_token": _issue_token(), "token_type": "bearer", "expires_in": TOKEN_TTL})

    return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)


async def oauth_metadata(request: Request) -> JSONResponse:
    base = str(request.base_url).rstrip("/")
    return JSONResponse({
        "issuer": base,
        "authorization_endpoint": f"{base}/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "grant_types_supported": ["authorization_code", "client_credentials"],
        "response_types_supported": ["code"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["client_secret_post", "none"],
    })


async def protected_resource_metadata(request: Request) -> JSONResponse:
    base = str(request.base_url).rstrip("/")
    return JSONResponse({"resource": base, "authorization_servers": [base], "bearer_methods_supported": ["header"]})


async def health(request: Request) -> Response:
    return Response("ok")


class BearerAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in EXEMPT_PATHS:
            return await call_next(request)

        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return Response("Unauthorized", status_code=401,
                            headers={"WWW-Authenticate": 'Bearer realm="whatsapp-mcp"'})

        if not _validate_token(auth[7:].strip()):
            return Response("Unauthorized", status_code=401,
                            headers={"WWW-Authenticate": 'Bearer realm="whatsapp-mcp", error="invalid_token"'})

        return await call_next(request)
