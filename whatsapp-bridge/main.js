/**
 * WhatsApp bridge — Node + wppconnect (Puppeteer + WhatsApp Web).
 *
 * Replaces the previous whatsmeow bridge to gain support for clicking
 * interactive reply buttons. wppconnect runs the real WhatsApp Web app in
 * a headless Chromium and invokes its internal JS pipeline (WPP.chat.*),
 * so button taps go through the same code path as the official client —
 * unlike protocol-level libraries (whatsmeow/Baileys) which Meta rejects
 * with the `<biz>` node verification (error 479).
 *
 * Contract preserved with the legacy Go bridge:
 *   - Listens on :8080 with POST /api/send
 *   - Writes incoming messages to store/messages.db with the same schema
 *     so the Python MCP server's read tools keep working unchanged.
 *
 * Extra capability over the legacy bridge:
 *   - When the request includes `button_reply_id` + `quoted_id`, the bridge
 *     locates the matching button index in the original message and calls
 *     `WPP.chat.replyToButtonMessage` — a real button tap.
 */

const path = require('path');
const fs = require('fs');
const crypto = require('crypto');
const express = require('express');
const Database = require('better-sqlite3');
const wppconnect = require('@wppconnect-team/wppconnect');

// Moved off 8080 to avoid clashing with the Firebase Firestore emulator
// (firebase emulators:start defaults Firestore to 8080).
const PORT = process.env.WHATSAPP_BRIDGE_PORT ? Number(process.env.WHATSAPP_BRIDGE_PORT) : 8099;
const STORE_DIR = path.join(__dirname, 'store');
const DB_PATH = path.join(STORE_DIR, 'messages.db');
const SESSION_NAME = 'whatsapp-mcp';
const TOKENS_DIR = path.join(__dirname, 'tokens');

fs.mkdirSync(STORE_DIR, { recursive: true });
fs.mkdirSync(TOKENS_DIR, { recursive: true });

// ---------------------------------------------------------------- SQLite
// Schema matches the legacy Go bridge so the Python MCP server's
// read-side queries against this file keep returning identical results.
const db = new Database(DB_PATH);
db.pragma('journal_mode = WAL');
db.exec(`
  CREATE TABLE IF NOT EXISTS chats (
    jid TEXT PRIMARY KEY,
    name TEXT,
    last_message_time TIMESTAMP
  );
  CREATE TABLE IF NOT EXISTS messages (
    id TEXT,
    chat_jid TEXT,
    sender TEXT,
    content TEXT,
    timestamp TIMESTAMP,
    is_from_me BOOLEAN,
    media_type TEXT,
    filename TEXT,
    url TEXT,
    media_key BLOB,
    file_sha256 BLOB,
    file_enc_sha256 BLOB,
    file_length INTEGER,
    PRIMARY KEY (id, chat_jid),
    FOREIGN KEY (chat_jid) REFERENCES chats(jid)
  );
`);

const upsertChat = db.prepare(`
  INSERT INTO chats (jid, name, last_message_time)
  VALUES (?, ?, ?)
  ON CONFLICT(jid) DO UPDATE SET
    name = COALESCE(excluded.name, chats.name),
    last_message_time = MAX(excluded.last_message_time, chats.last_message_time)
`);
const upsertMsg = db.prepare(`
  INSERT INTO messages
    (id, chat_jid, sender, content, timestamp, is_from_me, media_type, filename, url, media_key, file_sha256, file_enc_sha256, file_length)
  VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  ON CONFLICT(id, chat_jid) DO UPDATE SET
    content = COALESCE(excluded.content, messages.content),
    timestamp = excluded.timestamp
`);

// ---------------------------------------------------------------- helpers
function toJID(recipient) {
  if (!recipient) return null;
  if (recipient.includes('@')) return recipient;
  // E.164 without '+' → s.whatsapp.net JID
  return `${String(recipient).replace(/\D/g, '')}@s.whatsapp.net`;
}

function normalizeRecipientForClient(recipient) {
  // wppconnect accepts both phone-only (5511999999999) and JID
  // (5511999999999@c.us or @s.whatsapp.net). We pass through what we got.
  return recipient;
}

function extractText(msg) {
  // wppconnect normalizes various message types to msg.body for the text.
  return msg.body || msg.caption || '';
}

function storeMessage(msg) {
  try {
    const chatJID = msg.from || msg.chatId || '';
    const fromMe = msg.fromMe ? 1 : 0;
    const tsSec = msg.t || msg.timestamp || Math.floor(Date.now() / 1000);
    const ts = new Date(tsSec * 1000).toISOString().slice(0, 19).replace('T', ' ');

    upsertChat.run(chatJID, msg.chat?.name || msg.notifyName || null, ts);
    upsertMsg.run(
      msg.id?._serialized || msg.id || '',
      chatJID,
      msg.author || msg.from || '',
      extractText(msg),
      ts,
      fromMe,
      msg.type && msg.type !== 'chat' ? msg.type : null,
      msg.filename || null,
      msg.deprecatedMms3Url || null,
      null, null, null, null
    );
  } catch (e) {
    console.warn('[store] failed:', e.message);
  }
}

// ---------------------------------------------------------------- wppconnect
let waClient = null;

async function startClient() {
  const client = await wppconnect.create({
    session: SESSION_NAME,
    folderNameToken: TOKENS_DIR,
    headless: 'new',
    logQR: true,                    // ASCII QR in terminal on first pair
    autoClose: 0,                   // never auto-close QR
    disableWelcome: true,
    updatesLog: false,
    catchQR: (base64Qrimg, asciiQR) => {
      console.log('\n=== Scan this QR with WhatsApp on your phone ===');
      console.log(asciiQR);
      try {
        const qrPath = path.join(__dirname, 'qr.png');
        const data = base64Qrimg.replace(/^data:image\/png;base64,/, '');
        fs.writeFileSync(qrPath, Buffer.from(data, 'base64'));
        console.log(`QR also saved as PNG: ${qrPath}`);
      } catch (e) {
        console.warn('Failed to save QR PNG:', e.message);
      }
    },
    statusFind: (status) => {
      console.log('[status]', status);
      // These statuses mean the browser/session died. wppconnect does NOT
      // auto-recover: the process would linger alive with a dead browser, so
      // launchd's KeepAlive never restarts it and message sync silently stops
      // (this is exactly what happened at ~07:01 on 2026-07-05). Exiting lets
      // launchd relaunch us, and we reconnect using the saved token (no QR).
      const TERMINAL = ['browserClose', 'serverClose', 'desconnectedMobile', 'autocloseCalled', 'deleteToken', 'qrReadError'];
      if (TERMINAL.includes(status)) {
        console.error(`[watchdog] terminal status "${status}" — exiting so launchd restarts the bridge`);
        setTimeout(() => process.exit(1), 500);
      }
    },
    puppeteerOptions: {
      args: ['--no-sandbox', '--disable-setuid-sandbox'],
    },
  });

  client.onMessage((msg) => storeMessage(msg));
  client.onAnyMessage((msg) => storeMessage(msg));

  // Redirect ANY browser-initiated download away from the OS default folder
  // (~/Downloads). WhatsApp Web, running inside this headless Chromium, fires a
  // native "save" for some media flows; without an explicit download path the
  // files leak into ~/Downloads as "WhatsApp Image/Audio/Video ...". We don't
  // even rely on these on-disk files (/api/download reads the blob via dataUrl
  // and writes to store/ itself), so we pen them into a throwaway subfolder.
  try {
    const dlDir = path.join(STORE_DIR, 'chromium-downloads');
    fs.mkdirSync(dlDir, { recursive: true });
    const cdp = await (client.page.createCDPSession
      ? client.page.createCDPSession()
      : client.page.target().createCDPSession());
    await cdp.send('Page.setDownloadBehavior', { behavior: 'allow', downloadPath: dlDir });
    console.log(`[download] Chromium downloads redirected to ${dlDir}`);
  } catch (e) {
    console.warn('[download] failed to set download behavior:', e.message);
  }

  // --- resilience: another WhatsApp Web session took over, or we got unpaired
  try {
    client.onStateChange((state) => {
      console.log('[state]', state);
      if (['CONFLICT', 'UNPAIRED', 'UNLAUNCHED'].includes(state)) {
        try { client.useHere(); } catch (_) {}
      }
    });
  } catch (e) {
    console.warn('[watchdog] onStateChange unavailable:', e.message);
  }

  // Periodic health check: if the socket silently drops (no browserClose event
  // fires), isConnected() flips to false. Exit → launchd relaunches → we
  // reconnect via the saved token. Backstop for silent sync death.
  setInterval(async () => {
    try {
      const ok = await client.isConnected();
      if (!ok) {
        console.error('[watchdog] isConnected=false — exiting so launchd restarts the bridge');
        process.exit(1);
      }
    } catch (e) {
      console.error('[watchdog] health check failed:', e?.message || e, '— exiting');
      process.exit(1);
    }
  }, 60000).unref();

  return client;
}

// ---------------------------------------------------------------- send paths
async function sendText(recipient, message, quotedId) {
  if (quotedId) {
    return await waClient.reply(recipient, message, quotedId);
  }
  return await waClient.sendText(recipient, message);
}

async function sendFile(recipient, mediaPath, caption) {
  const fileName = path.basename(mediaPath);
  return await waClient.sendFile(recipient, mediaPath, fileName, caption || '');
}

/**
 * Click a quick-reply button. We need:
 *   - `quoted_id` (msg id of the message that carries the button) — required
 *   - `button_reply_id` (the button's internal id like 'confirm_appt_xxx')
 *
 * Strategy: ask the WhatsApp Web page itself to find the right button index
 * inside the message's hydratedButtons and invoke WPP.chat.replyToButtonMessage.
 * Doing the lookup inside page.evaluate keeps us in sync with WA Web's model.
 */
async function clickButton(recipient, messageId, buttonReplyId, fallbackText) {
  if (!waClient.page) {
    throw new Error('Puppeteer page not exposed on wppconnect client');
  }
  const result = await waClient.page.evaluate(
    async (chatId, msgId, targetId) => {
      const chat = window.WPP?.chat?.get?.(chatId);
      if (!chat) throw new Error(`chat ${chatId} not found in WPP model`);
      const msg = chat.msgs?.get?.(msgId);
      if (!msg) throw new Error(`message ${msgId} not found in chat ${chatId}`);

      // Path 1: legacy hydrated template buttons (WPP has a built-in helper).
      if (Array.isArray(msg.hydratedButtons) && msg.hydratedButtons.length > 0) {
        const idx = msg.hydratedButtons.findIndex(
          (b) => b?.quickReplyButton?.id === targetId
        );
        if (idx === -1) {
          const ids = msg.hydratedButtons.map((b) => b?.quickReplyButton?.id);
          throw new Error(`button_reply_id "${targetId}" not in hydratedButtons. Available: ${JSON.stringify(ids)}`);
        }
        const res = await window.WPP.chat.replyToButtonMessage(chatId, msgId, { buttonIndex: idx });
        return { ok: true, path: 'hydrated', buttonIndex: idx, result: res };
      }

      // Path 2: dynamic reply buttons (Cloud API interactive type=button). WA-JS
      // does NOT expose a helper for these, so we call the same internal
      // sendTextMsgToChat that replyToButtonMessage uses, with a manually
      // assembled replyOptions { quotedMsg, selectedIndex, selectedId }.
      const drb = msg.dynamicReplyButtons || msg.__x_dynamicReplyButtons || [];
      if (Array.isArray(drb) && drb.length > 0) {
        const idx = drb.findIndex((b) => b?.buttonId === targetId);
        if (idx === -1) {
          const ids = drb.map((b) => b?.buttonId);
          throw new Error(`button_reply_id "${targetId}" not in dynamicReplyButtons. Available: ${JSON.stringify(ids)}`);
        }
        const button = drb[idx];
        const displayText = button?.buttonText?.displayText || button?.displayText || targetId;

        // Resolve the internal sender. wa-js bundles WhatsApp Web functions
        // under WPP.whatsapp.functions; the function name may be minified in
        // production builds, so we look it up by common aliases.
        const fn = window.WPP?.whatsapp?.functions?.sendTextMsgToChat
          || window.WPP?.whatsapp?.SendTextMsgToChat
          || window.require?.('WAWebSendTextMessage')?.sendTextMsgToChat;
        if (typeof fn !== 'function') {
          // Last-resort fallback: send a normal text + quote — bot at least
          // sees the display text; loses the selectedId metadata.
          await window.WPP.chat.sendTextMessage(chatId, displayText, { quotedMsg: msgId });
          return { ok: true, path: 'dynamic-fallback-text', buttonIndex: idx };
        }

        const replyOptions = {
          quotedMsg: msg,
          selectedIndex: idx,
          selectedId: targetId,
        };
        const res = await fn(chat, displayText, replyOptions);
        return { ok: true, path: 'dynamic', buttonIndex: idx, result: res };
      }

      // Neither shape — dump diagnostics.
      const keys = Object.keys(msg).filter((k) => /button|interactive|template|reply|hydrated|native|nfm/i.test(k));
      const dump = {};
      for (const k of keys) {
        try { dump[k] = JSON.parse(JSON.stringify(msg[k])); }
        catch { dump[k] = String(msg[k]); }
      }
      throw new Error(`message has no buttons. Candidate fields: ${JSON.stringify(dump).substring(0, 1500)}`);
    },
    recipient,
    messageId,
    buttonReplyId
  );
  return result;
}

// ---------------------------------------------------------------- HTTP
const app = express();
app.use(express.json({ limit: '50mb' }));

app.get('/api/health', (_req, res) => res.json({
  ok: !!waClient,
  connected: waClient ? true : false,
}));

app.post('/api/send', async (req, res) => {
  const {
    recipient,
    message,
    media_path,
    quoted_id,
    button_reply_id,
    button_reply_display_text,
  } = req.body || {};

  if (!recipient) {
    return res.status(400).json({ success: false, message: 'recipient required' });
  }
  if (!waClient) {
    return res.status(503).json({ success: false, message: 'WhatsApp client not ready' });
  }

  try {
    const to = normalizeRecipientForClient(recipient);

    if (button_reply_id) {
      if (!quoted_id) {
        return res.status(400).json({
          success: false,
          message: 'button_reply_id requires quoted_id (the message that carries the button)',
        });
      }
      const r = await clickButton(to, quoted_id, button_reply_id, button_reply_display_text);
      return res.json({
        success: true,
        message: `Button clicked (index ${r.buttonIndex})`,
      });
    }

    if (media_path) {
      await sendFile(to, media_path, message);
      return res.json({ success: true, message: `Media sent to ${recipient}` });
    }

    await sendText(to, message || '', quoted_id || null);
    return res.json({ success: true, message: `Message sent to ${recipient}` });
  } catch (e) {
    console.error('[/api/send] error:', e?.message || e);
    return res.status(500).json({ success: false, message: `Error: ${e?.message || e}` });
  }
});

// ---------------------------------------------------------------- TEMP: history + media fetch
// Temporary endpoints to pull chat history loaded in WhatsApp Web (the DB only
// holds live-captured messages) and to decrypt/download media by message id.
app.get('/api/chats', async (req, res) => {
  try {
    if (!waClient?.page) return res.status(503).json({ ok: false, error: 'page not ready' });
    const q = (req.query.q || '').toLowerCase();
    const out = await waClient.page.evaluate(async (query) => {
      const list = await window.WPP.chat.list();
      return list.map((c) => {
        const id = c.id?._serialized || (c.id?.toString ? c.id.toString() : String(c.id));
        const name = c.name || c.formattedTitle || c.contact?.name || c.contact?.pushname || c.contact?.formattedName || '';
        return { id, name, t: c.t || null };
      }).filter((c) => !query || (c.name && c.name.toLowerCase().includes(query)) || (c.id && c.id.toLowerCase().includes(query)));
    }, q);
    res.json({ ok: true, count: out.length, chats: out });
  } catch (e) {
    res.status(500).json({ ok: false, error: e?.message || String(e) });
  }
});

app.get('/api/messages', async (req, res) => {
  try {
    if (!waClient?.page) return res.status(503).json({ ok: false, error: 'page not ready' });
    const chatId = req.query.chat;
    const limit = parseInt(req.query.limit || '40', 10);
    const out = await waClient.page.evaluate(async (cid, lim) => {
      const msgs = await window.WPP.chat.getMessages(cid, { count: lim });
      return msgs.map((m) => ({
        id: m.id?._serialized || (m.id?.toString ? m.id.toString() : String(m.id)),
        t: m.t,
        iso: m.t ? new Date(m.t * 1000).toISOString() : null,
        type: m.type,
        mimetype: m.mimetype || null,
        duration: m.duration || null,
        fromMe: !!m.id?.fromMe,
        sender: m.from?._serialized || m.author?._serialized || null,
        body: (m.body || '').slice(0, 120),
      }));
    }, chatId, limit);
    res.json({ ok: true, count: out.length, messages: out });
  } catch (e) {
    res.status(500).json({ ok: false, error: e?.message || String(e) });
  }
});

app.get('/api/msgraw', async (req, res) => {
  try {
    if (!waClient?.page) return res.status(503).json({ ok: false, error: 'page not ready' });
    const cid = req.query.chat;
    const wantHash = req.query.hash;
    const out = await waClient.page.evaluate(async (cid, wantHash) => {
      const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
      let list = null;
      for (let i = 0; i < 12; i++) {
        try { list = await window.WPP.chat.getMessages(cid, { count: 80 }); break; }
        catch (e) { if (!/not found/i.test(e.message)) throw e; await sleep(2000); }
      }
      if (!list) return { found: false, reason: 'chat never synced' };
      const m = list.find((x) => (x.id?._serialized || String(x.id)).split('_').pop() === wantHash);
      if (!m) return { found: false, count: list.length, sampleHashes: list.slice(-5).map((x)=>(x.id?._serialized||'').split('_').pop()) };
      const pick = {};
      for (const k of ['type','mimetype','directPath','clientUrl','deprecatedMms3Url','mediaKey','encFilehash','filehash','mediaKeyTimestamp','size','duration']) {
        const v = m[k];
        if (v === undefined || v === null) continue;
        pick[k] = typeof v === 'string' || typeof v === 'number' ? v : '[non-string ' + (v.length || '') + ']';
      }
      return { found: true, keys: Object.keys(m), pick };
    }, cid, wantHash);
    res.json({ ok: true, ...out });
  } catch (e) {
    res.status(500).json({ ok: false, error: e?.message || String(e) });
  }
});

app.get('/api/download', async (req, res) => {
  try {
    if (!waClient?.page) return res.status(503).json({ ok: false, error: 'page not ready' });
    const id = req.query.id;
    // Derive chatId from the serialized msg id: `<bool>_<chatId>_<hash>`
    const parts = String(id).split('_');
    const chatId = req.query.chat || (parts.length >= 3 ? parts[1] : null);
    const result = await waClient.page.evaluate(async (msgId, cid) => {
      // We need the LIVE MsgModel (it carries downloadMedia + mediaKey).
      // getMessages() only returns serialized data and leaves chat.msgs with
      // just the latest model, so page in history with loadEarlierMsgs() until
      // our target (matched by message HASH — the last id segment) shows up.
      const wantHash = String(msgId).split('_').pop();
      const matchByHash = (arr) => arr.find((m) => (m.id?._serialized || '').split('_').pop() === wantHash);
      const chat = window.WPP.whatsapp.ChatStore.get(cid);
      if (!chat) return { __err: 'chat not in ChatStore', cid };
      let msg = null;
      let liveCount = 0;
      for (let i = 0; i < 25 && !msg; i++) {
        const arr = chat.msgs?.getModelsArray ? chat.msgs.getModelsArray() : [];
        liveCount = arr.length;
        msg = matchByHash(arr);
        if (msg) break;
        try {
          const older = await chat.loadEarlierMsgs();
          if (!older || (Array.isArray(older) && older.length === 0)) break;
        } catch (e) { return { __err: 'loadEarlierMsgs failed: ' + e.message, liveCount }; }
      }
      if (!msg) {
        const arr = chat.msgs?.getModelsArray ? chat.msgs.getModelsArray() : [];
        return { __err: 'live message model not found', wantHash, liveCount: arr.length,
          sample: arr.slice(-4).map((m) => m.id?._serialized) };
      }

      const tries = [];
      let blob = null;
      // 1) message-level download (needs the options object)
      try {
        if (typeof msg.downloadMedia === 'function') {
          blob = await msg.downloadMedia({ downloadEvenIfExpensive: true, isUserInitiated: true });
        }
      } catch (e) { tries.push('msg.downloadMedia: ' + e.message); }
      // 1b) force mediaData load then read mediaObject blob
      if (!blob) {
        try {
          if (msg.mediaData && typeof msg.mediaData.mediaStage !== 'undefined') {
            await window.WPP.whatsapp.functions?.downloadMedia?.(msg);
          }
        } catch (e) { tries.push('functions.downloadMedia: ' + e.message); }
      }
      // 2) WPP.chat.downloadMedia with serialized id string
      if (!blob) {
        try { blob = await window.WPP.chat.downloadMedia(msg.id._serialized); }
        catch (e) { tries.push('WPP.chat.downloadMedia(idstr): ' + e.message); }
      }
      // 3) downloadManager direct
      if (!blob) {
        try {
          const dm = window.WPP?.whatsapp?.downloadManager;
          if (dm?.downloadAndMaybeDecrypt) {
            const data = await dm.downloadAndMaybeDecrypt({
              directPath: msg.directPath, encFilehash: msg.encFilehash,
              filehash: msg.filehash, mediaKey: msg.mediaKey,
              mediaKeyTimestamp: msg.mediaKeyTimestamp, type: msg.type,
              signal: (new AbortController()).signal,
            });
            blob = new Blob([data], { type: msg.mimetype || 'application/octet-stream' });
          }
        } catch (e) { tries.push('downloadManager: ' + e.message); }
      }
      if (!blob) {
        const b64 = (u8) => { try { let s=''; const a=new Uint8Array(u8); for(let i=0;i<a.length;i++) s+=String.fromCharCode(a[i]); return btoa(s); } catch(_) { return null; } };
        const media = {
          type: msg.type, mimetype: msg.mimetype,
          directPath: msg.directPath, clientUrl: msg.clientUrl || msg.deprecatedMms3Url,
          mediaKeyB64: typeof msg.mediaKey === 'string' ? msg.mediaKey : b64(msg.mediaKey),
          encFilehashB64: typeof msg.encFilehash === 'string' ? msg.encFilehash : b64(msg.encFilehash),
          filehashB64: typeof msg.filehash === 'string' ? msg.filehash : b64(msg.filehash),
          size: msg.size,
        };
        return { __err: 'all download paths failed', tries, media };
      }

      const dataUrl = await new Promise((resolve) => {
        const r = new FileReader();
        r.onloadend = () => resolve(r.result);
        r.readAsDataURL(blob);
      });
      return { mimetype: blob.type || msg.mimetype || '', dataUrl };
    }, id, chatId);
    if (result && result.__err) {
      const { __err, ...rest } = result;
      return res.status(500).json({ ok: false, error: __err, ...rest });
    }
    if (!result) return res.status(404).json({ ok: false, error: 'no media for message' });
    const mime = result.mimetype || '';
    const b64 = result.dataUrl.split(',')[1] || '';
    const buf = Buffer.from(b64, 'base64');
    const ext = mime.includes('ogg') ? '.ogg'
      : mime.includes('mpeg') || mime.includes('mp3') ? '.mp3'
      : mime.includes('mp4') || mime.includes('m4a') ? '.m4a'
      : mime.includes('wav') ? '.wav' : '.bin';
    const outPath = path.join(STORE_DIR, 'dl_' + String(id).replace(/[^A-Za-z0-9]/g, '_').slice(-30) + ext);
    fs.writeFileSync(outPath, buf);
    res.json({ ok: true, path: outPath, mimetype: mime, bytes: buf.length });
  } catch (e) {
    res.status(500).json({ ok: false, error: e?.message || String(e) });
  }
});

// ---------------------------------------------------------------- TEMP: group enum + full history (scroll-up backfill)
// Enumerate ALL groups via wppconnect's high-level list (fuller than the sparse
// WPP.chat.list), so we can find a group JID that never synced live.
app.get('/api/groups', async (req, res) => {
  try {
    if (!waClient) return res.status(503).json({ ok: false, error: 'not ready' });
    let groups = null;
    try { groups = await waClient.listChats({ onlyGroups: true }); } catch (e) { /* older api */ }
    if (!groups || !groups.length) {
      try {
        const all = await waClient.getAllChats();
        groups = (all || []).filter((c) => String(c.id?._serialized || c.id || '').endsWith('@g.us'));
      } catch (e) { /* ignore */ }
    }
    const q = (req.query.q || '').toLowerCase();
    const out = (groups || []).map((c) => ({
      id: c.id?._serialized || String(c.id),
      name: c.name || c.formattedTitle || c.groupMetadata?.subject || c.contact?.name || '',
    })).filter((c) => !q || (c.name && c.name.toLowerCase().includes(q)) || c.id.toLowerCase().includes(q));
    res.json({ ok: true, count: out.length, groups: out });
  } catch (e) {
    res.status(500).json({ ok: false, error: e?.message || String(e) });
  }
});

// Hydrate a chat by JID (even if it never synced live) and page its history up
// with loadEarlierMsgs() — the programmatic equivalent of scrolling up. Returns
// FULL message bodies (no 120-char truncation).
app.get('/api/history', async (req, res) => {
  try {
    if (!waClient?.page) return res.status(503).json({ ok: false, error: 'page not ready' });
    const chatId = req.query.chat;
    const pages = parseInt(req.query.pages || '10', 10);
    const count = parseInt(req.query.count || '500', 10);
    const out = await waClient.page.evaluate(async (cid, maxPages, cnt) => {
      const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
      const CS = window.WPP.whatsapp.ChatStore;
      let chat = CS.get(cid);
      if (!chat) {
        try { await window.WPP.chat.find(cid); } catch (e) { /* find may still populate store */ }
        for (let i = 0; i < 6 && !chat; i++) { chat = CS.get(cid); if (chat) break; await sleep(1000); }
      }
      if (!chat) return { error: 'chat not found after find', cid };
      // getMessages fetches from the server once the chat is in the store; count
      // pages back through history (the programmatic "scroll up"). Right after a
      // fresh find() the msg store needs a beat to prime (the server round-trip
      // triggered by the first getMessages resolves a few seconds later), so
      // trigger once, then retry until non-empty. Kept under puppeteer's 30s cap.
      let msgs = [];
      try { await window.WPP.chat.getMessages(cid, { count: cnt }); } catch (e) { return { error: 'getMessages: ' + e.message, cid }; }
      for (let i = 0; i < 9; i++) {
        await sleep(2500);
        try { msgs = await window.WPP.chat.getMessages(cid, { count: cnt }); } catch (e) { break; }
        if (msgs && msgs.length) break;
      }
      return {
        chatName: chat.name || chat.formattedTitle || chat.groupMetadata?.subject || '',
        count: msgs.length,
        messages: msgs.map((m) => ({
          id: m.id?._serialized || String(m.id),
          t: m.t,
          iso: m.t ? new Date(m.t * 1000).toISOString() : null,
          type: m.type,
          mimetype: m.mimetype || null,
          filename: m.filename || null,
          fromMe: !!m.id?.fromMe,
          sender: m.from?._serialized || m.author?._serialized || null,
          body: m.body || m.caption || '',
        })),
      };
    }, chatId, pages, count);
    res.json({ ok: true, ...out });
  } catch (e) {
    res.status(500).json({ ok: false, error: e?.message || String(e) });
  }
});

// Download media by message id. wa-js's own downloadMedia is buggy for old
// group messages (missing author model → "_serialized" error), so we extract
// the media crypto fields from the MsgModel and decrypt in Node ourselves
// (the standard WhatsApp media scheme: HKDF-SHA256 → AES-256-CBC).
const MEDIA_HKDF_INFO = {
  image: 'WhatsApp Image Keys', video: 'WhatsApp Video Keys',
  audio: 'WhatsApp Audio Keys', ptt: 'WhatsApp Audio Keys',
  document: 'WhatsApp Document Keys', sticker: 'WhatsApp Image Keys',
};
app.get('/api/media', async (req, res) => {
  try {
    if (!waClient?.page) return res.status(503).json({ ok: false, error: 'page not ready' });
    const id = req.query.id;
    const parts = String(id).split('_');
    const chatId = req.query.chat || (parts.length >= 3 ? parts[1] : null);
    if (!chatId) return res.status(400).json({ ok: false, error: 'cannot derive chat from id; pass &chat=' });
    // Pull the crypto fields off the live MsgModel (found by hash) in the page.
    const meta = await waClient.page.evaluate(async (cid, fid) => {
      const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
      const CS = window.WPP.whatsapp.ChatStore;
      if (!CS.get(cid)) { try { await window.WPP.chat.find(cid); } catch (e) {} }
      const wantHash = String(fid).split('_')[2];
      // The message models returned by getMessages()/MsgStore often have an EMPTY
      // id._serialized, so matching on it silently fails. String(x.id) (the MsgKey
      // toString) yields the full serialized id — use that to pull the hash segment.
      const hashOf = (x) => {
        try {
          const s = x?.id?._serialized || (x?.id != null ? String(x.id) : '');
          const parts = s.split('_');
          return parts.length >= 3 ? parts[2] : (parts.pop() || '');
        } catch (e) { return ''; }
      };
      let list = [];
      for (let i = 0; i < 8; i++) { try { list = await window.WPP.chat.getMessages(cid, { count: 500 }); if (list && list.length) break; } catch (e) {} await sleep(2000); }
      let m = (list || []).find((x) => hashOf(x) === wantHash);
      // Fall back to the canonical MsgStore: direct by id, then by hash across all models.
      if (!m) { try { m = window.WPP.whatsapp.MsgStore.get(fid); } catch (e) {} }
      if (!m) {
        try {
          const MS = window.WPP.whatsapp.MsgStore;
          const arr = MS.getModelsArray ? MS.getModelsArray() : [];
          m = arr.find((x) => hashOf(x) === wantHash);
        } catch (e) {}
      }
      if (!m) return { __err: 'msg not in list for hash ' + wantHash + ' (list ' + (list || []).length + ')' };
      const toB64 = (v) => {
        if (v == null) return null;
        if (typeof v === 'string') return v;
        try { const u8 = v instanceof Uint8Array ? v : new Uint8Array(v.buffer || v); let s = ''; for (const b of u8) s += String.fromCharCode(b); return btoa(s); } catch (e) { return null; }
      };
      return {
        type: m.type, mimetype: m.mimetype || null,
        directPath: m.directPath || null,
        url: m.clientUrl || m.deprecatedMms3Url || null,
        mediaKey: toB64(m.mediaKey),
        filename: m.filename || null, size: m.size || null, duration: m.duration || null,
      };
    }, chatId, id);
    if (meta && meta.__err) return res.status(404).json({ ok: false, error: meta.__err });
    if (!meta || !meta.mediaKey || (!meta.url && !meta.directPath)) {
      return res.status(404).json({ ok: false, error: 'missing crypto fields', meta });
    }
    // Fetch the encrypted blob, then HKDF-expand the mediaKey and AES-CBC decrypt.
    const encUrl = meta.url || ('https://mmg.whatsapp.net' + meta.directPath);
    const encResp = await fetch(encUrl);
    if (!encResp.ok) return res.status(502).json({ ok: false, error: 'enc fetch ' + encResp.status, encUrl });
    const enc = Buffer.from(await encResp.arrayBuffer());
    const info = MEDIA_HKDF_INFO[meta.type] || 'WhatsApp Audio Keys';
    const expanded = Buffer.from(crypto.hkdfSync('sha256', Buffer.from(meta.mediaKey, 'base64'), Buffer.alloc(0), Buffer.from(info), 112));
    const iv = expanded.subarray(0, 16);
    const cipherKey = expanded.subarray(16, 48);
    const file = enc.subarray(0, enc.length - 10); // strip 10-byte MAC
    const decipher = crypto.createDecipheriv('aes-256-cbc', cipherKey, iv);
    const dec = Buffer.concat([decipher.update(file), decipher.final()]);
    const mime = meta.mimetype || 'application/octet-stream';
    const ext = mime.includes('ogg') ? '.ogg'
      : mime.includes('mpeg') || mime.includes('mp3') ? '.mp3'
      : mime.includes('mp4') || mime.includes('m4a') ? '.m4a'
      : mime.includes('wav') ? '.wav'
      : mime.includes('jpeg') ? '.jpg'
      : mime.includes('png') ? '.png'
      : mime.includes('webp') ? '.webp'
      : mime.includes('pdf') ? '.pdf'
      : mime.includes('video') ? '.mp4' : '.bin';
    const outPath = path.join(STORE_DIR, 'dl_' + String(id).replace(/[^A-Za-z0-9]/g, '_').slice(-30) + ext);
    fs.writeFileSync(outPath, dec);
    res.json({ ok: true, path: outPath, mimetype: mime, bytes: dec.length, type: meta.type });
  } catch (e) {
    res.status(500).json({ ok: false, error: e?.message || String(e) });
  }
});

// ---------------------------------------------------------------- bootstrap
(async () => {
  app.listen(PORT, () => {
    console.log(`REST server is running on :${PORT}`);
  });
  console.log('Starting WhatsApp client…');
  try {
    waClient = await startClient();
    console.log('✓ Connected to WhatsApp! Ready.');
  } catch (e) {
    console.error('Failed to start WhatsApp client:', e?.message || e);
    process.exit(1);
  }
})();
