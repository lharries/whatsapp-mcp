# Security Notes — DjinnSix Fork

This is a hardened fork of [`lharries/whatsapp-mcp`](https://github.com/lharries/whatsapp-mcp). The original project is MIT licensed and is functionally unmaintained as of 2026‑04 (last upstream push 2025‑07‑13, with 10+ outstanding fix PRs).

This fork incorporates the community fixes that have been waiting upstream plus a small set of security and reliability changes that we needed in order to run the bridge safely on personal machines.

## Threat model

The bridge stores a decrypted copy of all your WhatsApp messages and an active session token in a local SQLite database. Anyone who can either:

* read files from your machine, **or**
* reach the bridge's REST API on the network it binds to,

can read every message in your account and (via `/api/send`) send messages from your number. The original upstream is designed for *personal*, *single-user* installs. We have hardened the defaults to make accidental over-exposure harder, but the underlying threat model has not changed: keep this on a machine where only you have access.

## Changes vs upstream

### 1. Bridge binds to `127.0.0.1` instead of `0.0.0.0`

**File:** `whatsapp-bridge/main.go` (`startRESTServer`)

The upstream bridge calls `http.ListenAndServe(":8080", …)` which Go interprets as binding to *all* interfaces. On a laptop on a coffee-shop or hotel network, anyone else on that network can reach `/api/send` and send WhatsApp messages from your account, with no authentication.

We bind to `127.0.0.1:8080` only, so only processes on the local machine can reach the API.

If you want to expose it intentionally — for example to run the bridge in a container and have a host-side MCP server reach it — flip the bind address back deliberately, ideally behind a token, a reverse proxy or a Wireguard tunnel.

### 2. Python dependency CVEs patched

**File:** `whatsapp-mcp-server/pyproject.toml`

Upstream pinned minimum versions of `mcp`, `urllib3`, `h11`, `starlette`, `requests`, and `pygments` that have since had multiple advisories published, including two **Critical** issues (`urllib3 GHSA-gm62-xv2j-4w53` CVSS 8.9; `h11 GHSA-vqfr-h8mv-ghfj` CVSS 9.1) and three **High** issues in the `mcp` library itself.

This fork pins:

| Package    | Old min | New min |
|------------|---------|---------|
| `mcp[cli]` | 1.6.0   | 1.23.0  |
| `urllib3`  | 2.3.0   | 2.6.3   |
| `h11`      | 0.14.0  | 0.16.0  |
| `starlette`| 0.46.1  | 0.49.1  |
| `requests` | 2.32.3  | 2.33.0  |
| `pygments` | 2.19.1  | 2.20.0  |

Verified clean with `osv-scanner` and `govulncheck`.

### 3. `mcp >= 1.10` Pydantic compatibility fix

**File:** `whatsapp-mcp-server/main.py`

The `mcp` library bumped its strictness around tool return types. The upstream MCP wrappers in `main.py` declare return types like `List[Dict[str, Any]]` but the underlying functions in `whatsapp.py` return raw `Contact`, `Chat`, `Message` and `MessageContext` dataclasses. Under the new `mcp` strict validation every contact / chat / message tool fails with `Input should be a valid dictionary`, which means you cannot list chats or contacts at all once the security CVEs above are patched.

This fork adds a `_serialize()` helper that recursively converts dataclasses to dicts and `datetime` objects to ISO‑8601 strings, and uses it as a thin wrapper inside each affected MCP tool. The schema declared in `main.py` matches what is actually returned, and the type hints have been corrected for `list_messages` (returns text, not a list) and `get_last_interaction` (returns text, not a list).

### 4. Media filename collision fix

**File:** `whatsapp-bridge/main.go` (`extractMediaInfo`)

Upstream generates media filenames with `time.Now().Format("20060102_150405")`. During the initial history sync, hundreds of messages are processed in the same second and end up with identical filenames. The download path then uses an `os.Stat()` cache check that returns the (single) existing file rather than fetching the new media — so all but one image / video / audio per second of sync time are silently lost.

This fork uses the WhatsApp message ID as the filename suffix (`image_<msgid>.jpg`, `video_<msgid>.mp4`, etc.). Filenames are now guaranteed unique per message, with a defensive `time.Now()` fallback in the impossible case where no message ID is supplied.

### 5. whatsmeow API + version updates

**Files:** `whatsapp-bridge/main.go`, `whatsapp-bridge/go.mod`

Picked up community PRs that have been waiting upstream since early 2026:

* Bumped `go.mau.fi/whatsmeow` to a current version so the bridge does not get rejected by WhatsApp with `Client outdated (405)`.
* Added the `context.Context` arguments that newer `whatsmeow` requires on `client.Download`, `client.GetGroupInfo`, `Store.Contacts.GetContact`, `sqlstore.New` and `Container.GetFirstDevice`. (Equivalent to upstream PRs #194, #207, #208 — not yet merged at time of fork.)

### 6. `.gitignore` hardened

**File:** `.gitignore`

The store directory containing the WhatsApp session and the entire decrypted message history is now explicitly excluded (alongside the built binary, logs, virtualenvs and IDE files). The upstream `.gitignore` matched `*.db` only, which would have missed any other media or log artefacts in `store/`.

## Things this fork does **not** fix

These would be welcome contributions:

* **Session and message DB are stored unencrypted on disk.** Anyone who can read your home directory can clone an active WhatsApp session. The right fix is SQLCipher (or similar) with a key derived from a user-supplied passphrase. Out of scope for this fork — would require larger changes to `whatsmeow` integration.
* **The bridge REST API has no authentication.** Even on `127.0.0.1`, any local process on your machine can hit `/api/send` and send messages from your account. A bearer token (env-var driven) is the obvious next step.
* **Prompt injection via incoming WhatsApp content.** Any LLM agent that consumes message content via this MCP is exposed to the standard "lethal trifecta" — untrusted input + tool access + outbound capability. Mitigations are at the agent / agent-policy layer, not the MCP itself.

## Reporting issues

If you find a security issue specific to this fork, please open a GitHub issue or contact the maintainers privately. Issues that are present in upstream `lharries/whatsapp-mcp` should be reported there as well.
