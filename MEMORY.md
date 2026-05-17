# Memory - WhatsApp MCP Multi-Tenant Project

## What

Multi-tenant WhatsApp MCP server - allow multiple users to connect WhatsApp via QR code, exposed via MCP protocol over HTTP.

## Architecture

- **Django** (port 18080): Admin UI, user management, QR display, REST API
- **Bridge** (port 18081): WhatsApp connections, per-user goroutines, polls Django
- **MCP** (port 18082): HTTP MCP endpoint for AI agents, JWT validation

## Key Docs

- `IMPLEMENTATION_PLAN.md` - Full implementation plan with Phase 1-4 breakdown
- `whatsapp-bridge/BRIDGE_ARCHITECTURE.md` - Bridge architecture details, migration strategy

## Git Setup

- Fork: https://github.com/rdar-lab/whatsapp-remote-mcp
- Branch: `multi-tenant`
- API fix commit: `56660d3` (cherry-picked from original fork)

## Security

- Service-to-service auth via `X-Service-Key` header (timing-safe comparison)
- JWT tokens (no expiration - simplify operations)
- Path traversal prevention: user_id must match `^[a-zA-Z0-9\-_]{1,64}$`
- Max 5 concurrent users (configurable via `MAX_CONCURRENT_USERS`)

## User Flow (Admin-Centric)

Admin creates user in Django Admin → Admin triggers "Show WhatsApp QR" action → scans with phone → Admin triggers "Generate API Key" action → copies JWT to LLM client server.json config

## Success Probability Analysis

| Component | Probability | Notes |
|-----------|-------------|-------|
| Django Server | 90-95% | Standard patterns, well-documented |
| WhatsApp Bridge | 85-90% | Detailed arch doc, phased migration with backward compat |
| MCP Server | 85% | Transport fallback (WebSocket), clear JWT validation |
| Integration | 80% | All pieces must work together |
| **Overall (5 users)** | **92-95%** | Limiting to 5 users significantly increases success |

## Risk Mitigations

| Risk | Mitigation |
|------|------------|
| QR expires before scan (~60s) | Poll more frequently (5s) when user in `pending_handshake` state |
| WhatsApp session expires (~30 days) | Admin resets status to `pending_init_request`, user re-scans |
| Bridge crash/restart | Sessions persisted in `whatsapp.db`, auto-reconnect |
| Memory exhaustion | Max 5 users × ~50MB = ~250MB max |
| Go goroutine leaks | Strict lifecycle via StopChan, monitor goroutine count |
| Django unavailable at startup | Soft failure, retry loop |
| SQLite corruption | Delete and recreate DB, request history re-sync |
| User accesses another user's data | Bridge validates user_id matches JWT subject |
| Path traversal attack | Regex validation on user_id before filesystem access |

## Bridge Key Decisions

1. **SQLite Per User** (`store/{user_id}/messages.db`) - True isolation, easy cleanup
2. **One Goroutine Per User** - Natural lifecycle management via StopChan
3. **QR Push to Django** - Bridge generates QR, PATCH to Django via API
4. **Max 5 Concurrent Users** - Configurable, prevents resource exhaustion

## MCP Transport

- Primary: streamable-http (if available in MCP SDK)
- Fallback: WebSocket (documented fallback if streamable-http unavailable)

## Status

Planning complete. Ready to build.

## Environment Variables

```env
JWT_SECRET=<shared-secret>
SERVICE_KEY=<shared-service-key>
DJANGO_SECRET_KEY=<django-secret>
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,django,bridge,mcp
BRIDGE_POLL_INTERVAL=60
DJANGO_API_URL=http://django:8000
MAX_CONCURRENT_USERS=5
```

## Implementation Order

Phase 1: Django Server (5 steps with unit tests at each step)
Phase 2: WhatsApp Bridge (6 steps with unit tests at each step)
Phase 3: MCP Server (6 steps with unit tests at each step)
Phase 4: Integration (Docker Compose, end-to-end testing)

## User Status States

- `pending_init_request` - User created, waiting for bridge to pick up
- `pending_handshake` - QR generated, waiting for phone scan
- `connected` - WhatsApp connected and synced
- `sync_error` - Error state, admin can reset via edit form

## Important Notes

- Admin does everything (create user, scan QR, get API key, configure LLM client)
- No user self-service portal
- No JWT revocation - delete and recreate user to revoke
- QR display: manual refresh (F5 or close/reopen modal), no AJAX polling
- Status field is editable in user change form - admin can force state changes
- Only 2 admin actions: "Show WhatsApp QR", "Generate API Key"