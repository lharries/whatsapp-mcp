#!/usr/bin/env bun
import { Server } from "@modelcontextprotocol/sdk/server/index.js"
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js"
import {
  ListToolsRequestSchema,
  CallToolRequestSchema,
} from "@modelcontextprotocol/sdk/types.js"
import { INSTRUCTIONS } from "./instructions"

const GO_BRIDGE = process.env.GO_BRIDGE_URL || "http://localhost:8080"
// Idle re-engagement heartbeat in minutes. Unset/blank/garbage → 5; explicit 0 disables.
const idleRaw = (process.env.WHATSAPP_IDLE_MINUTES ?? "").trim()
const IDLE_MINUTES = idleRaw === "" || !Number.isFinite(Number(idleRaw)) ? 5 : Number(idleRaw)
// Idle backoff: once a chat has been quiet this long, each nudge doubles the gap to the
// next one, up to IDLE_MAX_MINUTES. Any activity resets the cadence.
const envMinutes = (name: string, fallback: number) => {
  const raw = (process.env[name] ?? "").trim()
  return raw === "" || !Number.isFinite(Number(raw)) ? fallback : Number(raw)
}
const IDLE_BACKOFF_AFTER_MINUTES = envMinutes("WHATSAPP_IDLE_BACKOFF_AFTER_MINUTES", 30)
const IDLE_MAX_MINUTES = envMinutes("WHATSAPP_IDLE_MAX_MINUTES", 240)
// Operator control channel: a self/control chat, and/or a message prefix.
const DEBUG_PREFIX = process.env.WHATSAPP_DEBUG_PREFIX || "debug:"
const CONTROL_JID = process.env.WHATSAPP_CONTROL_JID || ""
// How long to wait for a pending (undecryptable, often view-once) photo to redeliver
// before declaring it unrecoverable. Linked devices receive view-once only as an
// "unavailable" stub; the bridge re-requests it from the primary phone, which for
// view-once frequently returns nothing — so the real media never arrives. Without a
// concrete timeout the persona waits forever; this bounds the wait, then emits
// media_failed so it asks for a resend.
const VIEWONCE_TIMEOUT_MS = Number(process.env.WHATSAPP_VIEWONCE_TIMEOUT_MS) || 75_000

// ── Operator-ask channel (ask_poll / ask_question) ────────────────────────────
// Questions to the human operator always go to ONE fixed WhatsApp chat —
// his "message yourself" chat — never to whoever a persona is texting. Answers come
// back as poll votes or a "answer:" reply and are pushed into the asking session as
// an `ask_answer` event; an unanswered ask emits `ask_timeout` so the agent moves on.
// A push to ntfy fires the operator's phone, since self-chat messages don't notify.
const ASK_JID = process.env.WHATSAPP_ASK_JID || CONTROL_JID
const ASK_ANSWER_PREFIX = process.env.WHATSAPP_ASK_ANSWER_PREFIX || "answer:"
const NTFY_BASE = (process.env.NTFY_BASE_URL || "https://ntfy.sh").replace(/\/+$/, "")
const NTFY_TOPIC = process.env.NTFY_TOPIC || ""

type Ask = {
  id: string // the WhatsApp message id of the poll/question we sent
  kind: "poll" | "question"
  question: string
  options?: string[]
  multi?: boolean
  timer?: ReturnType<typeof setTimeout>
}
// Open asks this session created, keyed by the sent message id. Only this session's
// asks are matched, so votes/answers for another persona's polls are ignored here.
const openAsks = new Map<string, Ask>()

async function ntfyPush(title: string, body: string, tags: string): Promise<void> {
  if (!NTFY_TOPIC) return
  try {
    // HTTP headers must be ASCII, so strip non-ASCII (e.g. emoji) from Title/Tags.
    // The body is UTF-8, so any emoji in the question survives there.
    const ascii = (s: string) => s.replace(/[^\x20-\x7E]/g, "").trim()
    await fetch(`${NTFY_BASE}/${NTFY_TOPIC}`, {
      method: "POST",
      headers: { Title: ascii(title) || "Claude", Tags: ascii(tags), Priority: "default" },
      body,
    })
  } catch (err) {
    console.error(`ntfy push failed: ${err}`)
  }
}

function clearAsk(id: string): Ask | undefined {
  const ask = openAsks.get(id)
  if (ask?.timer) clearTimeout(ask.timer)
  openAsks.delete(id)
  return ask
}

// Track an open ask and, if a timeout is given, emit `ask_timeout` when it lapses.
// The ask stays registered after the timeout so a late tap/answer still resolves.
function registerAsk(ask: Ask, timeoutSeconds?: number): void {
  openAsks.set(ask.id, ask)
  const secs = Number(timeoutSeconds)
  if (Number.isFinite(secs) && secs > 0) {
    ask.timer = setTimeout(() => {
      if (!openAsks.has(ask.id)) return
      emit(`[ask_timeout: no answer to "${ask.question}" within ${secs}s — decide yourself; a late answer still arrives if it comes]`, {
        event_type: "ask_timeout",
        ask_id: ask.id,
        ask_kind: ask.kind,
        question: ask.question,
        ts: new Date().toISOString(),
      })
    }, secs * 1000)
  }
}

// ── MCP Server + Channel Capability ──────────────────────────────────────────

const server = new Server(
  { name: "whatsapp", version: "2.0.0" },
  {
    capabilities: {
      tools: {},
      experimental: { "claude/channel": {} },
    },
    instructions: INSTRUCTIONS,
  }
)

// ── Alias registry + subscriptions ───────────────────────────────────────────
// The raw JID lives ONLY here (and in config). The model addresses chats by
// alias; a corrupted alias fails loudly instead of reaching a stranger.

const aliasToJid = new Map<string, string>()
const jidToAlias = new Map<string, string>()
const jidToName = new Map<string, string>() // resolved display name, learned from inbound events
const subscribedChats = new Set<string>() // JIDs

// Map our own sent message IDs → chat so delivery/read receipts (which may carry
// a different LID) correlate back to the right conversation.
const messageIdToChat = new Map<string, string>()
// Pending undecryptable/view-once media awaiting redelivery: message_id → give-up timer.
// Armed when a media_pending event fires; cleared if the real media (re)delivers;
// otherwise fires a media_failed event so the persona stops waiting and asks for a resend.
const pendingViewOnce = new Map<string, ReturnType<typeof setTimeout>>()
const lastEventPerChat = new Map<string, number>()
// Per-chat idle threshold override set via the set_idle tool (minutes); falls back
// to IDLE_MINUTES. Auto-cleared when the contact messages (back to default cadence).
const idleMinutesPerChat = new Map<string, number>()
// Timestamp of the last idle nudge per chat, for the re-emit cadence.
const lastIdleEmitPerChat = new Map<string, number>()
// Current gap between idle nudges per chat (minutes); grows once the chat has gone quiet.
const nudgeIntervalPerChat = new Map<string, number>()

function numberTail(jid: string): string {
  const user = (jid.split("@")[0] || jid).replace(/\D/g, "")
  return user.slice(-4) || jid.slice(-4)
}

function slugifyName(name?: string): string {
  if (!name) return ""
  const s = name
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[^\w]+/g, "-")
    .replace(/^-+|-+$/g, "")
  // Pure-number "names" are unresolved LIDs — treat as no name so we fall back to wa-<tail>.
  if (!s || /^\d+$/.test(s)) return ""
  return s
}

function deriveAlias(jid: string): string {
  const base = slugifyName(jidToName.get(jid)) || `wa-${numberTail(jid)}`
  const free = (a: string) => !aliasToJid.has(a) || aliasToJid.get(a) === jid
  if (free(base)) return base
  const withTail = `${base}-${numberTail(jid)}` // meaningful qualifier, never a bare counter
  if (free(withTail)) return withTail
  let i = 2
  while (aliasToJid.has(`${base}-${i}`)) i++
  return `${base}-${i}`
}

function registerSubscription(jid: string, alias?: string): string {
  if (jidToAlias.has(jid)) return jidToAlias.get(jid)! // already subscribed
  let finalAlias: string
  if (alias) {
    const a = alias.trim().toLowerCase().replace(/\s+/g, "-")
    if (aliasToJid.has(a) && aliasToJid.get(a) !== jid) {
      throw new Error(`alias "${a}" already maps to ${displayFor(aliasToJid.get(a)!)}; pass a distinct alias`)
    }
    finalAlias = a
  } else {
    finalAlias = deriveAlias(jid)
  }
  aliasToJid.set(finalAlias, jid)
  jidToAlias.set(jid, finalAlias)
  subscribedChats.add(jid)
  // Seed idle tracking so the heartbeat fires even before the first inbound event
  // (e.g. after a restart during a quiet stretch).
  if (!lastEventPerChat.has(jid)) lastEventPerChat.set(jid, Date.now())
  return finalAlias
}

function displayFor(jid: string): string {
  const alias = jidToAlias.get(jid) || jid
  const name = jidToName.get(jid)
  return name ? `${alias} (${name})` : alias
}

// Resolve a tool's optional `to` (alias or subscribed JID) to a JID.
function resolveTo(to?: string): { jid?: string; error?: string } {
  if (!to) {
    const targets = [...subscribedChats].filter((j) => j !== CONTROL_JID)
    if (targets.length === 1) return { jid: targets[0] }
    if (targets.length === 0) return { error: "no subscribed target — subscribe(chat_id, alias) first" }
    return { error: `multiple targets — pass to:<alias> (${[...aliasToJid.keys()].filter((a) => aliasToJid.get(a) !== CONTROL_JID).join(", ")})` }
  }
  if (aliasToJid.has(to)) return { jid: aliasToJid.get(to)! }
  // Backward compat: a raw JID / LID / phone number still works directly.
  if (to.includes("@") || /^\+?\d{6,}$/.test(to)) return { jid: to }
  return { error: `unknown alias "${to}"; known: ${[...aliasToJid.keys()].join(", ") || "(none)"}` }
}

// ── Tool Definitions ─────────────────────────────────────────────────────────

const toProp = {
  type: "string",
  description: 'Chat alias (e.g. "alex"). Omit to use the sole subscribed target.',
}

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: "subscribe",
      description:
        "Subscribe to a WhatsApp chat by JID and give it a short alias. This is the ONE place a raw JID is entered (from recon data, not typed by hand). Only subscribed chats deliver events.",
      inputSchema: {
        type: "object" as const,
        properties: {
          chat_id: { type: "string", description: "Chat JID, e.g. '4915200000000@s.whatsapp.net' or a '…@lid'" },
          alias: { type: "string", description: "Short memorable handle (e.g. 'alex'). Auto-derived from the contact name if omitted." },
        },
        required: ["chat_id"],
      },
    },
    {
      name: "unsubscribe",
      description: "Unsubscribe from a chat. Stops delivering its events.",
      inputSchema: {
        type: "object" as const,
        properties: { to: { type: "string", description: "Alias or JID to unsubscribe" } },
        required: ["to"],
      },
    },
    {
      name: "list_subscriptions",
      description: "List subscribed chats and their aliases.",
      inputSchema: { type: "object" as const, properties: {} },
    },
    {
      name: "reply",
      description: "Send a text message. Address by alias via `to`, or omit `to` for the sole subscribed target.",
      inputSchema: {
        type: "object" as const,
        properties: { text: { type: "string", description: "Message text" }, to: toProp },
        required: ["text"],
      },
    },
    {
      name: "send_file",
      description: "Send a file (image, video, document).",
      inputSchema: {
        type: "object" as const,
        properties: { file_path: { type: "string", description: "Absolute path to the file" }, to: toProp },
        required: ["file_path"],
      },
    },
    {
      name: "send_audio",
      description: "Send an audio file as a WhatsApp voice message (converted to opus if needed).",
      inputSchema: {
        type: "object" as const,
        properties: { file_path: { type: "string", description: "Absolute path to audio file" }, to: toProp },
        required: ["file_path"],
      },
    },
    {
      name: "send_typing",
      description: 'Optional typing indicator. They see "typing…" or "recording audio…".',
      inputSchema: {
        type: "object" as const,
        properties: {
          to: toProp,
          composing: { type: "boolean", description: "true = start, false = stop (default true)" },
          media: { type: "string", description: '"text" or "audio" (default "text")' },
        },
      },
    },
    {
      name: "mark_read",
      description: "Optional read receipts (blue ticks) for specific messages.",
      inputSchema: {
        type: "object" as const,
        properties: {
          message_ids: { type: "array", items: { type: "string" }, description: "Message IDs to mark read" },
          to: toProp,
        },
        required: ["message_ids"],
      },
    },
    {
      name: "download_attachment",
      description: "Download media from a message. Returns the local file path so you can view it.",
      inputSchema: {
        type: "object" as const,
        properties: { message_id: { type: "string", description: "Message ID containing the media" }, to: toProp },
        required: ["message_id"],
      },
    },
    {
      name: "unsend",
      description: "Unsend (delete for everyone) one of YOUR OWN messages — retract a wrong or bad message. Get the message_id from get_message_ids first (e.g. get_message_ids(limit:1) for the one you just sent).",
      inputSchema: {
        type: "object" as const,
        properties: { message_id: { type: "string", description: "Message ID of your message to unsend" }, to: toProp },
        required: ["message_id"],
      },
    },
    {
      name: "edit",
      description: "Edit the text of one of YOUR OWN messages. Get the message_id from get_message_ids first.",
      inputSchema: {
        type: "object" as const,
        properties: {
          message_id: { type: "string", description: "Message ID of your message to edit" },
          text: { type: "string", description: "New message text" },
          to: toProp,
        },
        required: ["message_id", "text"],
      },
    },
    {
      name: "react",
      description: "React to a message with an emoji (empty string removes your reaction). For your own message get its id via get_message_ids; for hers, use the message_id from the channel event.",
      inputSchema: {
        type: "object" as const,
        properties: {
          message_id: { type: "string", description: "Message ID to react to" },
          emoji: { type: "string", description: 'Emoji, e.g. "❤️" (empty string removes)' },
          to: toProp,
        },
        required: ["message_id", "emoji"],
      },
    },
    {
      name: "set_idle",
      description:
        "Tune how long this chat must be quiet before you get an [idle] re-engagement nudge, in minutes. Ramp it up to back off (e.g. 60 = nudge hourly while she's gone), or 0 to pause nudges. Automatically resets to the default the moment she next messages.",
      inputSchema: {
        type: "object" as const,
        properties: {
          minutes: { type: "number", description: "Quiet-time threshold in minutes before the next idle nudge (0 pauses nudges)" },
          to: toProp,
        },
        required: ["minutes"],
      },
    },
    {
      name: "get_message_ids",
      description:
        "List your OWN recent sent messages with their message_id (newest first). Use this to get the id for unsend/edit. Pass `filter` (a substring of the text) to pin a specific message; `get_message_ids(limit:1)` returns the one you just sent.",
      inputSchema: {
        type: "object" as const,
        properties: {
          to: toProp,
          filter: { type: "string", description: "Only messages whose text contains this substring" },
          limit: { type: "number", description: "How many recent messages to return (default 10)" },
        },
      },
    },
    {
      name: "ask_poll",
      description:
        "Ask the OPERATOR (the human running you) a multiple-choice question via a WhatsApp poll to their own chat, plus a phone push. This is your replacement for AskUserQuestions — prefer it. It does NOT go to the person you're texting, and it does NOT block: it returns a poll_id right away, and the answer arrives later as an `ask_answer` event (with `selected`). Set `timeout_seconds` from context — short (e.g. 60) when you're mid-conversation and time-sensitive, long or omitted when it can wait. On timeout you get an `ask_timeout` event and should decide yourself using your other tools (other chats, other MCP tools); a late answer still arrives if they tap it. Unanswered polls are fine.",
      inputSchema: {
        type: "object" as const,
        properties: {
          question: { type: "string", description: "The question to show the operator" },
          options: { type: "array", items: { type: "string" }, description: "2–12 answer options" },
          multi_select: { type: "boolean", description: "Allow choosing more than one option (default false)" },
          timeout_seconds: { type: "number", description: "Emit ask_timeout after this many seconds if unanswered (omit for no timeout)" },
        },
        required: ["question", "options"],
      },
    },
    {
      name: "ask_question",
      description:
        "Ask the OPERATOR an open (free-text) question via WhatsApp to their own chat, plus a phone push. Like ask_poll but for answers that aren't multiple-choice. Non-blocking: returns a question id; the operator answers by replying \"answer: <text>\" or quote-replying, and it arrives as an `ask_answer` event (with `text`). Set `timeout_seconds` from context; on timeout you get `ask_timeout` and decide yourself. Prefer ask_poll when the answer fits a few options.",
      inputSchema: {
        type: "object" as const,
        properties: {
          question: { type: "string", description: "The question to show the operator" },
          timeout_seconds: { type: "number", description: "Emit ask_timeout after this many seconds if unanswered (omit for no timeout)" },
        },
        required: ["question"],
      },
    },
  ],
}))

// ── Tool Handlers ────────────────────────────────────────────────────────────

async function bridgePost(endpoint: string, body: object): Promise<any> {
  const res = await fetch(`${GO_BRIDGE}${endpoint}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
  return res.json()
}

// Resolve any identifier (phone / @lid / JID) to the bridge's canonical chat JID, so
// a phone-keyed subscription and a LID-addressed event collapse to one key. The bridge
// emits this same canonical form in its SSE `chat_jid`, so isSubscribed() matches.
// Falls back to the input if the bridge is unreachable.
async function canonicalizeJid(input: string): Promise<string> {
  if (!input) return input
  try {
    const res = await bridgePost("/api/resolve-jid", { jid: input })
    if (res?.success && typeof res.jid === "string" && res.jid) return res.jid
  } catch {}
  return input
}

const text = (t: string, isError = false) => ({
  content: [{ type: "text" as const, text: t }],
  ...(isError ? { isError: true } : {}),
})

server.setRequestHandler(CallToolRequestSchema, async (req) => {
  const { name, arguments: args } = req.params
  const a = (args ?? {}) as Record<string, any>

  try {
    // Resolve the target up front for the send-family tools.
    const needsTarget = ["reply", "send_file", "send_audio", "send_typing", "mark_read", "download_attachment", "unsend", "edit", "react", "set_idle", "get_message_ids"]
    let targetJid = ""
    if (needsTarget.includes(name)) {
      const r = resolveTo(a.to)
      if (r.error) return text(`refused: ${r.error}`, true)
      targetJid = r.jid!
    }

    switch (name) {
      case "ask_poll": {
        if (!ASK_JID) return text("refused: no operator ask chat configured (set WHATSAPP_ASK_JID)", true)
        const options: string[] = Array.isArray(a.options) ? a.options.map(String) : []
        if (options.length < 2) return text("refused: ask_poll needs at least 2 options", true)
        if (options.length > 12) return text("refused: WhatsApp allows at most 12 poll options", true)
        const multi = a.multi_select === true
        const result = await bridgePost("/api/poll", {
          recipient: ASK_JID,
          name: a.question,
          options,
          selectable_count: multi ? options.length : 1,
        })
        if (!result.success || !result.message_id) return text(`failed: ${result.message || "poll not sent"}`, true)
        const id = String(result.message_id)
        registerAsk({ id, kind: "poll", question: a.question, options, multi }, a.timeout_seconds)
        await ntfyPush("Claude asks", `${a.question}\n${options.map((o) => `• ${o}`).join("\n")}`, "question,ballot_box")
        return text(`poll sent to you; poll_id=${id}. I'll get an ask_answer event when you tap${multi ? " (multi-select)" : ""}, or ask_timeout if not.`)
      }

      case "ask_question": {
        if (!ASK_JID) return text("refused: no operator ask chat configured (set WHATSAPP_ASK_JID)", true)
        const result = await bridgePost("/api/send", {
          recipient: ASK_JID,
          message: `❓ ${a.question}\n\n(reply "${ASK_ANSWER_PREFIX} ..." or quote-reply this)`,
        })
        if (!result.success) return text(`failed: ${result.message || "question not sent"}`, true)
        // The bridge's /api/send doesn't return the message id, so pin it via the store.
        let id = ""
        try {
          const ids = await bridgePost("/api/messages", { chat_jid: ASK_JID, filter: a.question.slice(0, 40), limit: 1 })
          id = ids?.messages?.[0]?.id || ""
        } catch {}
        if (!id) id = `q-${Date.now()}` // fallback key; quote-reply won't match but prefix will
        registerAsk({ id, kind: "question", question: a.question }, a.timeout_seconds)
        await ntfyPush("Claude asks", a.question, "question,speech_balloon")
        return text(`question sent to you; question_id=${id}. Reply "${ASK_ANSWER_PREFIX} ..." (or quote-reply). I'll get an ask_answer event, or ask_timeout if not.`)
      }

      case "subscribe": {
        // Canonicalize so a phone/@lid subscription lands on the same key the bridge
        // emits for this contact's events (the LID split-chat fix).
        const canonical = await canonicalizeJid(a.chat_id)
        const alias = registerSubscription(canonical, a.alias)
        const via = canonical !== a.chat_id ? ` (→ …${numberTail(canonical)})` : ""
        console.error(`Subscribed ${a.chat_id}${via} as "${alias}" (${subscribedChats.size} total)`)
        return text(`subscribed → ${alias} (…${numberTail(canonical)})`)
      }

      case "unsubscribe": {
        const r = resolveTo(a.to)
        if (r.error) return text(`refused: ${r.error}`, true)
        const jid = r.jid!
        const alias = jidToAlias.get(jid)
        subscribedChats.delete(jid)
        if (alias) aliasToJid.delete(alias)
        jidToAlias.delete(jid)
        lastEventPerChat.delete(jid)
        idleMinutesPerChat.delete(jid)
        lastIdleEmitPerChat.delete(jid)
        nudgeIntervalPerChat.delete(jid)
        return text(`unsubscribed → ${alias || jid}`)
      }

      case "list_subscriptions": {
        const lines = [...subscribedChats].map((j) => `${jidToAlias.get(j) || "?"} → …${numberTail(j)}${j === CONTROL_JID ? " (control)" : ""}`)
        return text(lines.length ? `Subscriptions:\n${lines.join("\n")}` : "No active subscriptions.")
      }

      case "reply": {
        const result = await bridgePost("/api/send", { recipient: targetJid, message: a.text })
        return result.success ? text(`sent → ${displayFor(targetJid)}`) : text(`failed: ${result.message}`, true)
      }

      case "send_file":
      case "send_audio": {
        const result = await bridgePost("/api/send", { recipient: targetJid, media_path: a.file_path })
        return result.success ? text(`sent → ${displayFor(targetJid)}`) : text(`failed: ${result.message}`, true)
      }

      case "send_typing": {
        const result = await bridgePost("/api/typing", {
          chat_jid: targetJid,
          composing: a.composing ?? true,
          media: a.media ?? "text",
        })
        return result.success ? text("ok") : text(`failed: ${result.message}`, true)
      }

      case "mark_read": {
        const result = await bridgePost("/api/mark-read", { chat_jid: targetJid, message_ids: a.message_ids })
        return result.success ? text("ok") : text(`failed: ${result.message}`, true)
      }

      case "download_attachment": {
        const result = await bridgePost("/api/download", { message_id: a.message_id, chat_jid: targetJid })
        return result.success
          ? text(`Downloaded: ${result.path || result.filename}`)
          : text(`failed: ${result.message}`, true)
      }

      case "unsend": {
        const result = await bridgePost("/api/revoke", { chat_jid: targetJid, message_id: a.message_id })
        return result.success ? text(`unsent (${displayFor(targetJid)})`) : text(`failed: ${result.message}`, true)
      }

      case "edit": {
        const result = await bridgePost("/api/edit", { chat_jid: targetJid, message_id: a.message_id, message: a.text })
        return result.success ? text(`edited → ${displayFor(targetJid)}`) : text(`failed: ${result.message}`, true)
      }

      case "react": {
        const result = await bridgePost("/api/react", { chat_jid: targetJid, message_id: a.message_id, reaction: a.emoji ?? "" })
        return result.success ? text("ok") : text(`failed: ${result.message}`, true)
      }

      case "set_idle": {
        const m = Number(a.minutes)
        if (!Number.isFinite(m) || m < 0) return text("refused: minutes must be a number >= 0", true)
        idleMinutesPerChat.set(targetJid, m)
        lastIdleEmitPerChat.delete(targetJid) // re-evaluate against the new threshold
        nudgeIntervalPerChat.delete(targetJid)
        return text(
          m === 0
            ? `idle nudges paused for ${displayFor(targetJid)} (resets to ${IDLE_MINUTES}m on her next message)`
            : `idle for ${displayFor(targetJid)} → ${m}m (resets to ${IDLE_MINUTES}m on her next message)`
        )
      }

      case "get_message_ids": {
        const result = await bridgePost("/api/messages", { chat_jid: targetJid, filter: a.filter ?? "", limit: a.limit ?? 10 })
        if (!result.success) return text(`failed: ${result.message}`, true)
        const lines = (result.messages || []).map(
          (m: any) => `${m.id} | ${String(m.timestamp || "").slice(11, 16)} | ${String(m.content || "").replace(/\n/g, " ").slice(0, 80)}`
        )
        return text(lines.length ? lines.join("\n") : "(no recent messages of yours" + (a.filter ? ` matching "${a.filter}")` : ")"))
      }

      default:
        throw new Error(`Unknown tool: ${name}`)
    }
  } catch (err: any) {
    return text(`Error: ${err.message}`, true)
  }
})

// ── SSE Subscriber ───────────────────────────────────────────────────────────

function isSubscribed(chatId: string, messageIds?: string[]): string | null {
  if (subscribedChats.size === 0) return null
  if (subscribedChats.has(chatId)) return chatId
  // Receipts may arrive under a different LID — map via our sent message IDs.
  if (messageIds) {
    for (const msgId of messageIds) {
      const mapped = messageIdToChat.get(msgId)
      if (mapped && subscribedChats.has(mapped)) return mapped
    }
  }
  return null
}

function emit(content: string, meta: Record<string, string>) {
  server.notification({ method: "notifications/claude/channel", params: { content, meta } })
}

// View-once media is ephemeral — WhatsApp deletes it after one view and it can't be
// re-fetched. So we eagerly download it into the session folder (this server's CWD,
// overridable via WHATSAPP_MEDIA_DIR) and tell the persona where it landed.
const MEDIA_DIR = process.env.WHATSAPP_MEDIA_DIR || `${process.cwd()}/view-once`

async function autoCaptureViewOnce(messageId: string, jid: string, alias: string) {
  try {
    const res = await bridgePost("/api/download", { message_id: messageId, chat_jid: jid })
    if (!res.success || !res.path) {
      console.error(`view-once auto-download failed for ${messageId}: ${res.message}`)
      return
    }
    const base = String(res.path).split("/").pop() || `${messageId}`
    const dest = `${MEDIA_DIR}/${base}`
    await Bun.write(dest, Bun.file(res.path)) // Bun.write creates parent dirs
    emit(`[view-once saved → ${dest}]`, {
      chat: alias,
      event_type: "view_once_saved",
      path: dest,
      message_id: messageId,
    })
  } catch (err: any) {
    console.error(`view-once auto-capture error for ${messageId}: ${err.message}`)
  }
}

// Digits of a JID's user part, for comparing the operator ask chat to event chats
// regardless of @s.whatsapp.net/@lid form.
function jidDigits(jid: string): string {
  return (jid.split("@")[0] || jid).replace(/\D/g, "")
}
function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
}

// Resolve an operator answer to one of THIS session's open asks. Returns true if the
// event was consumed as an ask response (so it isn't also surfaced as a normal event).
function handleAskResponse(eventType: string, data: any, chatId: string): boolean {
  // A poll vote is matched purely by the poll id we sent — no chat-subscription needed.
  if (eventType === "poll_vote") {
    const pollId = String(data.poll_message_id || "")
    if (!openAsks.has(pollId)) return false
    const ask = clearAsk(pollId)!
    const selected: string[] = Array.isArray(data.selected_options) ? data.selected_options : []
    emit(`[ask_answer to "${ask.question}": ${selected.length ? selected.join(", ") : "(vote could not be read)"}]`, {
      event_type: "ask_answer",
      ask_id: ask.id,
      ask_kind: "poll",
      question: ask.question,
      selected: JSON.stringify(selected),
      ts: data.timestamp || new Date().toISOString(),
    })
    return true
  }
  // A free-text answer: the operator's own message in the ask chat, either a
  // quote-reply of the question (exact) or one prefixed "answer:" (most recent open).
  if (eventType === "message" && data.is_from_me && ASK_JID && openAsks.size > 0 && jidDigits(chatId) === jidDigits(ASK_JID)) {
    const body: string = data.content || ""
    const quoted = String(data.quoted_message_id || "")
    let ask = quoted && openAsks.has(quoted) ? openAsks.get(quoted) : undefined
    const hasPrefix = body.trimStart().toLowerCase().startsWith(ASK_ANSWER_PREFIX.toLowerCase())
    if (!ask && hasPrefix) {
      const questions = [...openAsks.values()].filter((k) => k.kind === "question")
      ask = questions[questions.length - 1] // most recent open free-text ask
    }
    if (!ask) return false
    const answer = body.replace(new RegExp("^\\s*" + escapeRegExp(ASK_ANSWER_PREFIX), "i"), "").trim()
    clearAsk(ask.id)
    emit(`[ask_answer to "${ask.question}": ${answer}]`, {
      event_type: "ask_answer",
      ask_id: ask.id,
      ask_kind: ask.kind,
      question: ask.question,
      text: answer,
      ts: data.timestamp || new Date().toISOString(),
    })
    return true
  }
  return false
}

function handleEvent(eventType: string, data: any) {
  const chatId = data.chat_jid || ""
  if (chatId.includes("@broadcast") || chatId === "status@s.whatsapp.net") return

  // Operator-ask responses (poll votes / "answer:" replies) resolve here, ahead of
  // the subscription filter, since the ask chat is the operator's own chat.
  if (handleAskResponse(eventType, data, chatId)) return

  const resolvedChat = isSubscribed(chatId, data.message_ids)
  if (!resolvedChat) {
    console.error(`[filtered] ${eventType} from ${chatId} (not subscribed)`)
    return
  }

  // Learn the contact's display name from their inbound messages.
  if (eventType === "message" && !data.is_from_me && data.sender_name) {
    jidToName.set(resolvedChat, data.sender_name)
    if (!jidToAlias.has(resolvedChat)) registerSubscription(resolvedChat)
  }

  const alias = jidToAlias.get(resolvedChat) || resolvedChat
  const meta: Record<string, string> = { chat: alias, ts: data.timestamp || new Date().toISOString() }
  let content = ""

  if (eventType === "message") {
    const body: string = data.content || ""
    const isControl = resolvedChat === CONTROL_JID
    const isDebug = data.is_from_me && (body.startsWith(DEBUG_PREFIX) || isControl)

    if (isDebug) {
      meta.event_type = "command"
      meta.user = "operator"
      content = body.startsWith(DEBUG_PREFIX) ? body.slice(DEBUG_PREFIX.length).trim() : body.trim()
    } else {
      meta.user = data.sender_name || data.sender || "Unknown"
      meta.message_id = String(data.message_id || "")
      if (data.is_from_me) meta.is_from_me = "true"
      if (data.media_type) {
        meta.media_type = data.media_type
        meta.filename = data.filename || ""
      }
      if (data.view_once) meta.view_once = "true"
      const mid = String(data.message_id || "")
      if (data.undecryptable) {
        // Arrived encrypted-but-undecryptable (often a view-once). Not viewable yet —
        // the bridge is re-requesting it from her phone. Surface a placeholder so the
        // persona reacts now; the real media (if it redelivers) arrives as a later event.
        meta.event_type = "media_pending"
        const kind = data.view_once ? "view-once photo/video" : "a photo/video"
        content = `[${meta.user} sent ${kind} — still loading, you can't see it yet]`
        // For view-once the phone usually never resends, so the real media never lands.
        // Arm a give-up timer; if nothing resolves it, tell the persona to ask for a resend.
        if (mid && !pendingViewOnce.has(mid)) {
          const who = meta.user
          pendingViewOnce.set(mid, setTimeout(() => {
            pendingViewOnce.delete(mid)
            emit(`[the ${kind} from ${who} couldn't be loaded and can't be retrieved — ask her to resend it]`, {
              chat: alias,
              event_type: "media_failed",
              message_id: mid,
            })
          }, VIEWONCE_TIMEOUT_MS))
        }
      } else {
        content = data.content || (data.media_type ? `[${data.media_type}: message_id=${data.message_id}]` : "")
        // A decryptable (re)delivery for a previously-pending view-once cancels the give-up timer.
        const t = mid ? pendingViewOnce.get(mid) : undefined
        if (t) { clearTimeout(t); pendingViewOnce.delete(mid) }
      }
      if (data.is_from_me && data.message_id) messageIdToChat.set(String(data.message_id), resolvedChat)
      // Eagerly capture incoming view-once media into the session folder before it's gone.
      // Skip when undecryptable — there's nothing downloadable until it redelivers.
      if (!data.undecryptable && data.view_once && data.media_type && data.message_id && !data.is_from_me) {
        autoCaptureViewOnce(String(data.message_id), resolvedChat, alias)
      }
      // Her message resets any idle ramp back to the default cadence.
      if (!data.is_from_me) idleMinutesPerChat.delete(resolvedChat)
    }
  } else if (eventType === "receipt") {
    meta.user = data.sender || ""
    meta.event_type = data.event_type || ""
    content = `[${data.event_type} receipt]`
  } else if (eventType === "presence") {
    meta.user = data.sender || ""
    meta.event_type = data.event_type || ""
    content = data.event_type === "typing" ? "[typing...]" : "[stopped typing]"
  } else if (eventType === "reaction") {
    meta.user = data.sender_name || data.sender || ""
    meta.event_type = "reaction"
    if (data.target_message_id) meta.target_message_id = String(data.target_message_id)
    if (data.is_from_me) meta.is_from_me = "true"
    content = data.reaction ? `[reacted ${data.reaction}]` : "[removed reaction]"
  }

  lastEventPerChat.set(resolvedChat, Date.now())
  lastIdleEmitPerChat.delete(resolvedChat) // any activity restarts the idle re-emit cadence
  nudgeIntervalPerChat.delete(resolvedChat)
  emit(content, meta)
}

async function subscribeToEvents() {
  const url = `${GO_BRIDGE}/api/stream`
  while (true) {
    try {
      console.error(`Connecting to SSE stream: ${url}`)
      const res = await fetch(url)
      if (!res.ok) {
        console.error(`SSE connection failed: ${res.status}`)
        await Bun.sleep(2000)
        continue
      }
      const reader = res.body!.getReader()
      const decoder = new TextDecoder()
      let buffer = ""
      console.error("SSE connected, receiving events...")

      while (true) {
        const { done, value } = await reader.read()
        if (done) {
          console.error("SSE stream ended")
          break
        }
        buffer += decoder.decode(value, { stream: true })
        const frames = buffer.split("\n\n")
        buffer = frames.pop()!
        for (const frame of frames) {
          if (!frame.trim() || frame.startsWith(":")) continue
          const lines = frame.split("\n")
          const eventLine = lines.find((l) => l.startsWith("event: "))
          const dataLine = lines.find((l) => l.startsWith("data: "))
          if (!dataLine) continue
          const eventType = eventLine?.slice(7) || "message"
          try {
            handleEvent(eventType, JSON.parse(dataLine.slice(6)))
          } catch (parseErr) {
            console.error("Failed to parse SSE data:", parseErr)
          }
        }
      }
    } catch (err) {
      console.error("SSE disconnected, reconnecting in 2s...", err)
    }
    await Bun.sleep(2000)
  }
}

// ── Idle Heartbeat (re-engagement cue; the only proactive path) ──────────────
// Per-chat threshold = set_idle override, else IDLE_MINUTES (0 disables for that
// chat). Ticks every minute and re-nudges at the threshold cadence — a ramped 60m
// chat is nudged hourly, not every minute. Resets on activity / her reply.

function effectiveIdle(jid: string): number {
  return idleMinutesPerChat.has(jid) ? idleMinutesPerChat.get(jid)! : IDLE_MINUTES
}

// During a silence the persona has no fresh message ts to read, yet that's exactly
// when it must judge time-of-day (too late to nudge? morning?). So the idle event
// carries the current time. clock honors WHATSAPP_TZ (e.g. "Europe/Berlin") so it
// reflects the target's local time, not the host's (nexi is UTC) — set it per project.
const WHATSAPP_TZ = process.env.WHATSAPP_TZ?.trim() || undefined
function currentClock(): string {
  try {
    return new Intl.DateTimeFormat("en-GB", {
      timeZone: WHATSAPP_TZ,
      weekday: "short",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
      timeZoneName: "short",
    }).format(new Date())
  } catch {
    return new Date().toISOString()
  }
}

setInterval(() => {
  const now = Date.now()
  for (const [chatId, lastTime] of lastEventPerChat) {
    if (!subscribedChats.has(chatId) || chatId === CONTROL_JID) continue
    const base = effectiveIdle(chatId)
    const quietMs = now - lastTime
    if (base <= 0 || quietMs < base * 60_000) continue // disabled, or not quiet long enough
    const interval = nudgeIntervalPerChat.get(chatId) ?? base
    const lastNudge = lastIdleEmitPerChat.get(chatId)
    if (lastNudge !== undefined && now - lastNudge < interval * 60_000) continue // already nudged this window
    lastIdleEmitPerChat.set(chatId, now)
    const next =
      quietMs >= IDLE_BACKOFF_AFTER_MINUTES * 60_000 ? Math.min(interval * 2, Math.max(IDLE_MAX_MINUTES, base)) : interval
    nudgeIntervalPerChat.set(chatId, next)
    const minutesIdle = Math.round(quietMs / 60000)
    const clock = currentClock()
    emit(`[idle: ${minutesIdle} minutes since last activity — now ${clock}; next nudge in ${next} min]`, {
      chat: jidToAlias.get(chatId) || chatId,
      event_type: "idle",
      minutes_idle: String(minutesIdle),
      next_nudge_minutes: String(next),
      ts: new Date().toISOString(),
      clock,
    })
  }
}, 60 * 1000)

// ── Startup ──────────────────────────────────────────────────────────────────

// Seed subscriptions from env: WHATSAPP_SUBSCRIBE="alex=<jid>,foo=<jid2>" (or bare JIDs).
// Each JID is canonicalized so a stale @lid seed self-heals to the phone key the bridge
// emits. Falls back to the raw value if the bridge isn't up yet (phone-form seeds are
// already canonical, so they're safe regardless).
for (const pair of (process.env.WHATSAPP_SUBSCRIBE || "").split(",").map((s) => s.trim()).filter(Boolean)) {
  const eq = pair.indexOf("=")
  try {
    const rawJid = eq > 0 ? pair.slice(eq + 1).trim() : pair
    const alias = eq > 0 ? pair.slice(0, eq).trim() : undefined
    registerSubscription(await canonicalizeJid(rawJid), alias)
  } catch (e: any) {
    console.error(`seed subscription failed for "${pair}": ${e.message}`)
  }
}
// The control chat streams in so operator `debug:` commands are always delivered.
if (CONTROL_JID) {
  try {
    registerSubscription(CONTROL_JID, "control")
  } catch {
    subscribedChats.add(CONTROL_JID)
  }
}

const transport = new StdioServerTransport()
await server.connect(transport)
subscribeToEvents()
console.error(`WhatsApp channel server started (${subscribedChats.size} subscriptions, idle=${IDLE_MINUTES}m)`)
