package main

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"sync"
	"time"

	"go.mau.fi/whatsmeow"
	waLog "go.mau.fi/whatsmeow/util/log"
	"rsc.io/qr"
)

// pairState tracks the pairing of this process's single account so a remote
// browser can watch it over HTTP (a headless server has no terminal to show a QR
// code in). One account per process keeps this simple.
type pairState struct {
	mu       sync.Mutex
	client   *whatsmeow.Client
	logger   waLog.Logger
	started  bool
	qr       string
	code     string
	errMsg   string
	expires  time.Time
	onPaired func()
}

var pairing = &pairState{}

// StartPairing begins the QR pairing flow (idempotent). onPaired runs once the
// phone has linked, so the caller can persist state and reconnect.
func (p *pairState) StartPairing(client *whatsmeow.Client, logger waLog.Logger, onPaired func()) {
	p.mu.Lock()
	if p.started {
		p.mu.Unlock()
		return
	}
	p.started = true
	p.client = client
	p.logger = logger
	p.onPaired = onPaired
	p.mu.Unlock()

	go func() {
		qrChan, err := client.GetQRChannel(context.Background())
		if err != nil {
			p.setErr(fmt.Sprintf("could not start pairing: %v", err))
			return
		}
		if err := client.Connect(); err != nil {
			p.setErr(fmt.Sprintf("could not connect: %v", err))
			return
		}
		for evt := range qrChan {
			switch evt.Event {
			case "code":
				p.setQR(evt.Code)
			case "success":
				p.markPaired()
				if p.onPaired != nil {
					go p.onPaired()
				}
				return
			case "timeout":
				p.setErr("pairing window expired — reload the page to get a fresh code")
				return
			}
		}
	}()
}

// StartPairCode requests an 8-digit pairing code for a phone number (an
// alternative to scanning). The code is shown on the pairing page.
func (p *pairState) StartPairCode(client *whatsmeow.Client, logger waLog.Logger, phone string, onPaired func()) {
	p.mu.Lock()
	p.client = client
	p.logger = logger
	p.onPaired = onPaired
	p.mu.Unlock()

	go func() {
		if err := client.Connect(); err != nil {
			p.setErr(fmt.Sprintf("could not connect: %v", err))
			return
		}
		time.Sleep(1 * time.Second)
		code, err := client.PairPhone(context.Background(), phone, true, whatsmeow.PairClientChrome, "Chrome (Linux)")
		if err != nil {
			p.setErr(fmt.Sprintf("could not generate pairing code: %v", err))
			return
		}
		p.mu.Lock()
		p.code = code
		p.mu.Unlock()
	}()
}

func (p *pairState) setQR(qr string) {
	p.mu.Lock()
	p.qr = qr
	p.errMsg = ""
	p.expires = time.Now().Add(60 * time.Second)
	p.mu.Unlock()
}

func (p *pairState) setErr(msg string) {
	p.mu.Lock()
	p.errMsg = msg
	p.mu.Unlock()
}

func (p *pairState) markPaired() {
	p.mu.Lock()
	p.errMsg = ""
	p.mu.Unlock()
}

// HandlePairStatus serves JSON the pairing page polls: whether the account is
// paired, the current QR as a data URI, a pairing code if one was requested, and
// any error.
func (p *pairState) HandlePairStatus(client *whatsmeow.Client, w http.ResponseWriter, r *http.Request) {
	phone := strings.TrimSpace(r.URL.Query().Get("phone"))

	p.mu.Lock()
	paired := client.Store.ID != nil
	qrStr := p.qr
	code := p.code
	errMsg := p.errMsg
	started := p.started

	// Kick off pairing lazily on first look, unless a phone number starts the
	// code flow instead.
	if !paired && phone != "" && code == "" {
		clientRef, logger, onPaired := p.client, p.logger, p.onPaired
		p.mu.Unlock()
		p.StartPairCode(clientRef, logger, phone, onPaired)
		p.mu.Lock()
	} else if !paired && !started {
		clientRef, logger, onPaired := p.client, p.logger, p.onPaired
		p.mu.Unlock()
		p.StartPairing(clientRef, logger, onPaired)
		p.mu.Lock()
	}
	p.mu.Unlock()

	resp := map[string]interface{}{
		"paired": paired,
		"jid":    "",
		"code":   code,
		"error":  errMsg,
	}
	if client.Store.ID != nil {
		resp["jid"] = client.Store.ID.String()
	}
	if qrStr != "" {
		if img, err := qr.Encode(qrStr, qr.L); err == nil {
			resp["qr_png"] = "data:image/png;base64," + base64.StdEncoding.EncodeToString(img.PNG())
		}
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(resp)
}

const pairPageHTML = `<!doctype html>
<html><head><meta charset="utf-8"><title>Link WhatsApp</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
 body{font-family:system-ui,sans-serif;background:#0b141a;color:#e9edef;display:flex;
   min-height:100vh;align-items:center;justify-content:center;margin:0}
 .card{background:#111b21;padding:28px 32px;border-radius:14px;max-width:420px;text-align:center;
   box-shadow:0 8px 30px rgba(0,0,0,.5)}
 img{width:260px;height:260px;background:#fff;border-radius:10px;padding:10px}
 .muted{color:#8696a0;font-size:14px}
 .code{font-size:26px;letter-spacing:3px;font-weight:700;margin:10px 0}
 input{padding:10px;border-radius:8px;border:1px solid #2a3942;background:#202c33;color:#e9edef;width:60%}
 button{padding:10px 14px;border:0;border-radius:8px;background:#00a884;color:#0b141a;font-weight:600;cursor:pointer}
</style></head>
<body><div class="card">
 <h2 id="title">Link this device</h2>
 <p class="muted" id="hint">Open WhatsApp → Settings → Linked devices → Link a device, then scan:</p>
 <img id="qr" alt="QR code" style="display:none">
 <p class="code" id="code" style="display:none"></p>
 <p class="muted" id="err" style="color:#f15c6d"></p>
 <form id="codeform" style="margin-top:14px">
   <input id="phone" placeholder="phone e.g. 26481xxxxxxx" inputmode="numeric">
   <button type="submit">Get code</button>
 </form>
 <p class="muted" id="status">starting…</p>
</div>
<script>
 let phone = "";
 async function tick(){
   const r = await fetch("/api/pair/status" + (phone ? "?phone="+encodeURIComponent(phone) : ""));
   const s = await r.json();
   const qr = document.getElementById("qr"), code = document.getElementById("code"), st = document.getElementById("status");
   if (s.paired){ document.getElementById("title").textContent="Linked ✓";
     document.getElementById("hint").textContent="This device is connected.";
     qr.style.display="none"; code.style.display="none";
     document.getElementById("codeform").style.display="none";
     st.textContent = "jid: " + (s.jid||""); return; }
   if (s.qr_png){ qr.src = s.qr_png; qr.style.display="block"; }
   if (s.code){ code.textContent = s.code; code.style.display="block"; }
   st.textContent = s.code ? "Enter this code in WhatsApp → Linked devices → Link with phone number."
                            : (s.qr_png ? "Scan the QR code." : "preparing…");
   document.getElementById("err").textContent = s.error || "";
 }
 document.getElementById("codeform").addEventListener("submit", e=>{
   e.preventDefault(); phone = document.getElementById("phone").value.trim(); tick(); });
 tick(); setInterval(tick, 3000);
</script></body></html>`

// HandlePairPage serves the HTML pairing page.
func (p *pairState) HandlePairPage(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.Write([]byte(pairPageHTML))
}
