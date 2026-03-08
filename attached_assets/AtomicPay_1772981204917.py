"""
AtomicPay.py
=============
The AtomicPay Standalone App.

Run this file:
    python AtomicPay.py

Browser opens automatically at http://localhost:7000

This app:
  - Runs completely standalone
  - User registers with name, mobile, PIN
  - Links their bank account
  - Sends money to anyone
  - Receives money and sees balance

This app talks to the Gateway (port 5000).
Gateway talks to Bank A and Bank B.

Architecture:
  AtomicPay.py  (port 7000)  ← YOU ARE HERE
       ↓
  gateway_server.py  (port 5000)
       ↓           ↓
  bank_a_server  bank_b_server
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.request, json, webbrowser, threading, time

# ── CONFIG ────────────────────────────────────────────────────────────────────
APP_PORT     = 7000
GATEWAY_URL  = "http://127.0.0.1:5000"   # Gateway handles all payments

# ── GATEWAY COMMUNICATION ─────────────────────────────────────────────────────

def gw(path, data):
    """Call the payment gateway."""
    try:
        raw = json.dumps(data).encode()
        req = urllib.request.Request(
            f"{GATEWAY_URL}{path}", data=raw,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())
    except urllib.error.URLError:
        return {"state": -1, "reason": "GATEWAY_OFFLINE"}
    except Exception as e:
        return {"state": -1, "reason": str(e)[:60]}

def gw_get(path):
    """GET request to gateway."""
    try:
        with urllib.request.urlopen(f"{GATEWAY_URL}{path}", timeout=3) as r:
            return json.loads(r.read())
    except:
        return []

def gateway_online():
    try:
        urllib.request.urlopen(GATEWAY_URL, timeout=1)
        return True
    except:
        return False

# ── HTTP HANDLER ──────────────────────────────────────────────────────────────

class AtomicPayHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        if self.path in ("/", "/app"):
            self._html(APP_HTML)
        elif self.path == "/gateway_status":
            self._json({"online": gateway_online()})
        elif self.path == "/banks":
            data = gw_get("/banks")
            self._json(data)
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body   = json.loads(self.rfile.read(length))
        path   = self.path

        # Pass through to gateway
        if path in ("/register", "/login", "/link_bank",
                    "/balance",  "/pay",   "/find_user",
                    "/history",  "/contacts"):
            self._json(gw(path, body))
        else:
            self.send_response(404); self.end_headers()

    def _html(self, c):
        raw = c.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers(); self.wfile.write(raw)

    def _json(self, d):
        raw = json.dumps(d).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers(); self.wfile.write(raw)

    def log_message(self, *a): pass

# ── THE APP ───────────────────────────────────────────────────────────────────

APP_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>AtomicPay</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Sora:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap');

:root {
  --bg:     #06080e;
  --sur:    #0c0f1a;
  --card:   #101525;
  --bdr:    #1a2040;
  --txt:    #e2e8f8;
  --muted:  #3a4560;
  --accent: #4f7fff;
  --green:  #10d078;
  --red:    #ff4560;
  --gold:   #ffb830;
}
*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
body{font-family:'Sora',sans-serif;background:var(--bg);color:var(--txt);min-height:100vh;display:flex;justify-content:center}
.phone{width:100%;max-width:400px;min-height:100vh;background:var(--bg);position:relative;overflow-x:hidden}

/* SCREENS */
.scr{display:none;flex-direction:column;min-height:100vh;animation:fi .25s ease}
.scr.on{display:flex}
@keyframes fi{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:translateY(0)}}

/* ── GATEWAY BANNER ── */
.gw-banner{
  background:#1a0808;border-bottom:1px solid #3a1010;
  padding:10px 16px;font-size:12px;color:var(--red);
  display:none;align-items:center;gap:8px;
}
.gw-banner.show{display:flex}

/* ── WELCOME ── */
#scrWelcome{
  justify-content:center;align-items:center;
  padding:48px 28px;gap:32px;
  background:radial-gradient(ellipse at 50% 0%,#0d1840 0%,var(--bg) 70%);
}
.wlogo{text-align:center}
.wlogo .bolt{
  font-size:64px;display:block;margin-bottom:16px;
  filter:drop-shadow(0 0 28px rgba(79,127,255,.65));
  animation:float 3s ease-in-out infinite;
}
@keyframes float{0%,100%{transform:translateY(0)}50%{transform:translateY(-8px)}}
.wlogo h1{font-size:34px;font-weight:800;letter-spacing:-1px;color:#fff}
.wlogo .wtag{display:block;margin-top:8px;font-size:10px;font-weight:600;letter-spacing:3px;color:var(--muted)}
.wbtns{display:flex;flex-direction:column;gap:10px;width:100%}
.wfoot{text-align:center;font-size:11px;color:var(--muted);line-height:1.9}

/* ── BUTTONS ── */
.btn{width:100%;padding:14px;font-family:'Sora',sans-serif;font-size:14px;font-weight:600;border:none;border-radius:12px;cursor:pointer;transition:all .15s;letter-spacing:.2px}
.btn:active{transform:scale(.98)}
.btn-p{background:var(--accent);color:#fff}
.btn-p:hover{background:#5f8fff}
.btn-o{background:transparent;color:var(--txt);border:1.5px solid var(--bdr)}
.btn-o:hover{border-color:var(--accent)}
.btn-g{background:var(--green);color:#000;font-weight:700}
.btn-g:hover{background:#20e088}
.btn:disabled{background:var(--card);color:var(--muted);cursor:not-allowed}

/* ── SCREEN HEADER ── */
.scrh{display:flex;align-items:center;gap:14px;padding:20px 20px 16px;border-bottom:1px solid var(--bdr);flex-shrink:0}
.back{width:36px;height:36px;border-radius:50%;background:var(--sur);border:1px solid var(--bdr);color:var(--txt);font-size:16px;cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0}
.scrh h2{font-size:17px;font-weight:700}

/* ── FORM ── */
.fbody{padding:24px 20px;display:flex;flex-direction:column;gap:16px;flex:1}
.field{display:flex;flex-direction:column;gap:7px}
.flbl{font-size:10px;font-weight:700;letter-spacing:.8px;text-transform:uppercase;color:var(--muted)}
.fi{background:var(--sur);border:1.5px solid var(--bdr);border-radius:12px;padding:13px 15px;font-family:'Sora',sans-serif;font-size:14px;color:var(--txt);-webkit-appearance:none;transition:border-color .2s;width:100%}
.fi:focus{outline:none;border-color:var(--accent)}
.fi.mono{font-family:'JetBrains Mono',monospace;letter-spacing:5px;font-size:18px}
.fi::placeholder{color:var(--muted);letter-spacing:normal;font-size:13px}
.hint{font-size:11px;color:var(--muted);line-height:1.6}
.err{background:#1a080e;border:1px solid #3a1020;border-radius:10px;padding:10px 14px;font-size:12px;color:var(--red);display:none}
.ok {background:#081a10;border:1px solid #103a20;border-radius:10px;padding:10px 14px;font-size:12px;color:var(--green);display:none}

/* ── LINK BANK ── */
.bank-grid{display:flex;flex-direction:column;gap:10px}
.bcard{background:var(--sur);border:2px solid var(--bdr);border-radius:14px;padding:16px;cursor:pointer;transition:all .2s;display:flex;align-items:center;gap:14px}
.bcard:hover{border-color:var(--accent)}
.bcard.sel{border-color:var(--accent);background:#0d1530}
.bico{font-size:28px;flex-shrink:0}
.binf{flex:1}
.bnm{font-size:14px;font-weight:600}
.bsh{font-size:11px;color:var(--muted);margin-top:2px}
.bonl{font-size:10px;margin-top:4px}
.online{color:var(--green)}
.offline{color:var(--red)}
.bchk{font-size:20px;opacity:0;color:var(--accent);transition:opacity .15s}
.bcard.sel .bchk{opacity:1}

/* ── HOME ── */
#scrHome{padding-bottom:72px}
.topbar{display:flex;align-items:center;justify-content:space-between;padding:18px 20px 0}
.tl{display:flex;align-items:center;gap:12px}
.av{width:42px;height:42px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:17px;font-weight:700;color:#fff;flex-shrink:0}
.tname{font-size:15px;font-weight:600}
.tsub{font-size:11px;color:var(--muted);margin-top:1px}
.logbtn{background:none;border:none;color:var(--muted);font-size:22px;cursor:pointer;padding:8px}

/* BALANCE CARD */
.balcard{margin:16px 20px 0;border-radius:20px;padding:22px;position:relative;overflow:hidden;background:linear-gradient(135deg,#0e1e50 0%,#091230 60%,#060a1e 100%);border:1px solid #1a2860}
.balcard::after{content:'⚡';position:absolute;right:-10px;bottom:-20px;font-size:120px;opacity:.04;line-height:1;pointer-events:none}
.bal-l{font-size:10px;font-weight:700;letter-spacing:.8px;text-transform:uppercase;color:#3a5080}
.bal-a{font-size:38px;font-weight:800;color:#fff;margin:6px 0 2px;font-family:'JetBrains Mono',monospace;letter-spacing:-2px}
.bal-s{font-size:11px;color:#2a4070}
.bal-r{margin-top:14px;display:flex;gap:8px;flex-wrap:wrap}
.chip{font-family:'JetBrains Mono',monospace;font-size:10px;color:#3a5a7a;background:#060e1c;padding:4px 10px;border-radius:8px}
.refb{position:absolute;top:18px;right:18px;background:rgba(255,255,255,.06);border:none;color:#3a5a7a;width:30px;height:30px;border-radius:50%;cursor:pointer;font-size:14px;display:flex;align-items:center;justify-content:center}
.refb:hover{color:#fff;background:rgba(255,255,255,.12)}

/* QUICK ACTIONS */
.qa{display:flex;gap:10px;padding:14px 20px 0}
.qab{flex:1;background:var(--sur);border:1.5px solid var(--bdr);border-radius:14px;padding:14px 10px;text-align:center;cursor:pointer;transition:all .2s;color:var(--txt)}
.qab:hover{border-color:var(--accent)}
.qaic{font-size:22px;margin-bottom:5px}
.qalb{font-size:10px;font-weight:700;color:var(--muted);letter-spacing:.3px}

.stitle{padding:16px 20px 8px;font-size:10px;font-weight:700;letter-spacing:.8px;text-transform:uppercase;color:var(--muted)}

/* TX LIST */
.txlist{padding:0 20px;display:flex;flex-direction:column;gap:8px}
.txi{background:var(--sur);border:1px solid var(--bdr);border-radius:14px;padding:13px 15px;display:flex;align-items:center;gap:12px}
.txic{width:40px;height:40px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:15px;font-weight:700;flex-shrink:0}
.txic.s{background:#1a0810;color:var(--red)}
.txic.r{background:#081a10;color:var(--green)}
.txinf{flex:1}
.txnm{font-size:13px;font-weight:600}
.txdt{font-size:10px;color:var(--muted);margin-top:2px}
.txnt{font-size:10px;color:#2a3a50;margin-top:2px;font-style:italic}
.txamt{text-align:right}
.txa{font-family:'JetBrains Mono',monospace;font-size:14px;font-weight:600}
.txa.s{color:var(--red)}
.txa.r{color:var(--green)}
.txst{font-size:10px;color:var(--muted);margin-top:2px}
.txmt{text-align:center;padding:36px 20px;color:var(--muted);font-size:13px;line-height:1.8}

/* SEND SCREEN */
#scrSend{padding-bottom:80px}
.cpick{margin:0 20px;background:var(--sur);border:1.5px solid var(--bdr);border-radius:14px;padding:14px 15px;display:flex;align-items:center;gap:10px;cursor:pointer;transition:border-color .2s}
.cpick:hover{border-color:var(--accent)}
.cpav{width:38px;height:38px;border-radius:50%;background:var(--card);display:flex;align-items:center;justify-content:center;font-size:18px;color:var(--muted);flex-shrink:0}
.cpnm{font-size:14px;font-weight:600}
.cpsb{font-size:11px;color:var(--muted);margin-top:2px}

.amtcard{margin:12px 20px 0;background:var(--sur);border:1px solid var(--bdr);border-radius:16px;padding:18px}
.amtcard h3{font-size:10px;font-weight:700;letter-spacing:.8px;text-transform:uppercase;color:var(--muted);margin-bottom:12px}
.amtrow{display:flex;align-items:center;gap:10px;margin-bottom:10px}
.amtrs{font-size:24px;color:var(--muted);font-family:'JetBrains Mono',monospace}
.amtinp{flex:1;background:var(--card);border:1.5px solid var(--bdr);border-radius:10px;padding:10px 12px;font-family:'JetBrains Mono',monospace;font-size:26px;font-weight:700;color:#fff;-webkit-appearance:none;transition:border-color .2s}
.amtinp:focus{outline:none;border-color:var(--accent)}
.noteinp{width:100%;background:var(--card);border:1.5px solid var(--bdr);border-radius:10px;padding:10px 12px;font-family:'Sora',sans-serif;font-size:13px;color:var(--txt);-webkit-appearance:none}
.noteinp:focus{outline:none;border-color:var(--accent)}
.sact{padding:14px 20px 0}

/* FIND USER MODAL */
.moverlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.82);z-index:200;justify-content:center;align-items:flex-end}
.moverlay.on{display:flex}
.modal{background:var(--sur);border:1px solid var(--bdr);border-radius:22px 22px 0 0;padding:24px 20px 40px;width:100%;max-width:400px;animation:sUp .25s ease}
@keyframes sUp{from{transform:translateY(100%)}to{transform:translateY(0)}}
.modal h3{font-size:16px;font-weight:700;margin-bottom:16px}
.fcard{background:var(--card);border:1px solid var(--bdr);border-radius:12px;padding:14px 16px;display:flex;align-items:center;gap:12px;margin-bottom:14px}
.fav{width:44px;height:44px;border-radius:50%;background:var(--accent);display:flex;align-items:center;justify-content:center;font-size:18px;font-weight:700;color:#fff;flex-shrink:0}
.fnm{font-size:15px;font-weight:600}
.fsb{font-size:11px;color:var(--muted);margin-top:3px}

/* RESULT OVERLAY */
.rov{display:none;position:fixed;inset:0;background:rgba(0,0,0,.88);z-index:100;justify-content:center;align-items:flex-end}
.rov.on{display:flex}
.rsheet{background:var(--sur);border:1px solid var(--bdr);border-radius:24px 24px 0 0;padding:26px 22px 40px;width:100%;max-width:400px;animation:sUp .3s ease;max-height:92vh;overflow-y:auto}
.rico{text-align:center;font-size:54px;margin-bottom:10px;animation:pop .4s cubic-bezier(.175,.885,.32,1.275)}
@keyframes pop{from{transform:scale(0);opacity:0}to{transform:scale(1);opacity:1}}
.rtitle{text-align:center;font-size:20px;font-weight:800;margin-bottom:4px}
.rsub{text-align:center;font-size:12px;color:var(--muted);margin-bottom:18px}
.ramt{text-align:center;font-family:'JetBrains Mono',monospace;font-size:36px;font-weight:800;margin-bottom:18px;letter-spacing:-1px}
.bupd{display:flex;gap:8px;margin-bottom:14px}
.bucard{flex:1;background:var(--card);border-radius:12px;padding:12px;text-align:center}
.bunm{font-size:10px;color:var(--muted)}
.buarr{font-size:16px;margin:4px 0}
.bubal{font-family:'JetBrains Mono',monospace;font-size:14px;font-weight:700}
.rdets{background:var(--card);border-radius:12px;padding:12px 14px;margin-bottom:12px}
.rdrow{display:flex;justify-content:space-between;padding:5px 0;font-size:12px}
.rdrow+.rdrow{border-top:1px solid var(--bdr)}
.rdlbl{color:var(--muted)}
.rdval{font-family:'JetBrains Mono',monospace;font-size:11px}
.rsteps{background:var(--bg);border-radius:10px;padding:10px;font-family:'JetBrains Mono',monospace;font-size:10px;color:#2a3a55;line-height:1.9;max-height:120px;overflow-y:auto;margin-bottom:16px}

/* BOTTOM NAV */
.bnav{position:fixed;bottom:0;left:50%;transform:translateX(-50%);width:100%;max-width:400px;background:var(--sur);border-top:1px solid var(--bdr);display:flex;z-index:50}
.ni{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:10px 8px 16px;cursor:pointer;color:var(--muted);font-size:10px;font-weight:600;gap:3px;background:none;border:none;letter-spacing:.3px;transition:color .15s}
.ni .ic{font-size:20px}
.ni.on{color:var(--accent)}

@keyframes spin{to{transform:rotate(360deg)}}
.spin{display:inline-block;animation:spin .7s linear infinite}
</style>
</head>
<body>
<div class="phone">

<!-- GATEWAY BANNER -->
<div class="gw-banner" id="gwBanner">
  ⚠️ Gateway offline. Start gateway_server.py first.
</div>

<!-- ══ WELCOME ══ -->
<div class="scr on" id="scrWelcome">
  <div class="wlogo">
    <span class="bolt">⚡</span>
    <h1>AtomicPay</h1>
    <span class="wtag">Tamas · Rajas · Sattva</span>
  </div>
  <div class="wbtns">
    <button class="btn btn-p" onclick="show('scrRegister')">Create Account</button>
    <button class="btn btn-o" onclick="show('scrLogin')">Sign In</button>
  </div>
  <div class="wfoot">
    -1 · 0 · +1 &nbsp;|&nbsp; No suspense. No float.<br>
    Hari Om Namah Shivaye 🙏
  </div>
</div>

<!-- ══ REGISTER ══ -->
<div class="scr" id="scrRegister">
  <div class="scrh">
    <button class="back" onclick="show('scrWelcome')">←</button>
    <h2>Create Account</h2>
  </div>
  <div class="fbody">
    <div class="err" id="regErr"></div>
    <div class="field">
      <div class="flbl">Full Name</div>
      <input class="fi" type="text" id="regName" placeholder="Ram Kumar" autocomplete="off">
    </div>
    <div class="field">
      <div class="flbl">Mobile Number</div>
      <input class="fi mono" type="tel" id="regMobile" placeholder="9876543210" maxlength="10" inputmode="numeric">
    </div>
    <div class="field">
      <div class="flbl">Create PIN</div>
      <input class="fi mono" type="password" id="regPin" placeholder="· · · ·" maxlength="4" inputmode="numeric">
    </div>
    <button class="btn btn-p" id="regBtn" onclick="doRegister()">Create Account</button>
  </div>
</div>

<!-- ══ LOGIN ══ -->
<div class="scr" id="scrLogin">
  <div class="scrh">
    <button class="back" onclick="show('scrWelcome')">←</button>
    <h2>Sign In</h2>
  </div>
  <div class="fbody">
    <div class="err" id="loginErr"></div>
    <div class="field">
      <div class="flbl">Mobile Number</div>
      <input class="fi mono" type="tel" id="loginMobile" placeholder="9876543210" maxlength="10" inputmode="numeric">
    </div>
    <div class="field">
      <div class="flbl">PIN</div>
      <input class="fi mono" type="password" id="loginPin" placeholder="· · · ·" maxlength="4" inputmode="numeric">
    </div>
    <button class="btn btn-p" id="loginBtn" onclick="doLogin()">Sign In</button>
  </div>
</div>

<!-- ══ LINK BANK ══ -->
<div class="scr" id="scrLinkBank">
  <div class="scrh">
    <div style="width:36px"></div>
    <h2>Link Your Bank</h2>
  </div>
  <div class="fbody">
    <div class="err" id="linkErr"></div>
    <div class="ok"  id="linkOk"></div>

    <div class="field">
      <div class="flbl">Select Your Bank</div>
      <div class="bank-grid" id="bankGrid">
        <div style="color:var(--muted);font-size:13px;padding:8px">Loading banks...</div>
      </div>
    </div>

    <div class="field">
      <div class="flbl">Your Account Number</div>
      <input class="fi mono" type="text" id="linkAcc"
             placeholder="e.g. RAM_001" autocomplete="off" autocapitalize="characters">
      <div class="hint">
        Demo accounts: RAM_001 (Bank A) · SITA_001 (Bank B) · ARJUN_01 (Bank A)
      </div>
    </div>

    <button class="btn btn-g" id="linkBtn" onclick="doLinkBank()">
      Verify &amp; Link Bank
    </button>
  </div>
</div>

<!-- ══ HOME ══ -->
<div class="scr" id="scrHome">
  <div class="topbar">
    <div class="tl">
      <div class="av" id="hAv">?</div>
      <div>
        <div class="tname" id="hName">—</div>
        <div class="tsub"  id="hSub">—</div>
      </div>
    </div>
    <button class="logbtn" onclick="doLogout()" title="Sign out">⎋</button>
  </div>

  <div class="balcard">
    <button class="refb" onclick="loadBal()" title="Refresh balance">↻</button>
    <div class="bal-l">Account Balance</div>
    <div class="bal-a" id="bAmt">Rs. —</div>
    <div class="bal-s" id="bSub">—</div>
    <div class="bal-r">
      <span class="chip" id="bAccId"></span>
      <span class="chip" id="bBank"></span>
    </div>
  </div>

  <div class="qa">
    <div class="qab" onclick="goSend()">
      <div class="qaic">↑</div><div class="qalb">SEND</div>
    </div>
    <div class="qab" onclick="loadHistory()">
      <div class="qaic">↓</div><div class="qalb">RECEIVE</div>
    </div>
    <div class="qab" onclick="loadHistory()">
      <div class="qaic">📋</div><div class="qalb">HISTORY</div>
    </div>
  </div>

  <div class="stitle">Recent Transactions</div>
  <div class="txlist" id="txList">
    <div class="txmt">No transactions yet.<br>Send your first payment.</div>
  </div>
</div>

<!-- ══ SEND ══ -->
<div class="scr" id="scrSend">
  <div class="scrh">
    <button class="back" onclick="goHome()">←</button>
    <h2>Send Money</h2>
  </div>

  <div class="stitle" style="padding-top:14px">Pay To</div>
  <div class="cpick" id="cpick" onclick="openFind()">
    <div class="cpav" id="cpAv">👤</div>
    <div>
      <div class="cpnm" id="cpNm">Select Recipient</div>
      <div class="cpsb" id="cpSb">Enter mobile number to find</div>
    </div>
    <span style="color:var(--muted);font-size:18px;margin-left:auto">›</span>
  </div>

  <div class="amtcard">
    <h3>Amount &amp; Note</h3>
    <div class="amtrow">
      <span class="amtrs">₹</span>
      <input type="number" class="amtinp" id="sAmt"
             placeholder="0" min="1" inputmode="decimal">
    </div>
    <input type="text" class="noteinp" id="sNote" placeholder="Add a note (optional)">
  </div>

  <div class="sact">
    <button class="btn btn-p" id="sendBtn" onclick="doSend()">Send Payment</button>
  </div>
</div>

<!-- ══ FIND USER MODAL ══ -->
<div class="moverlay" id="findModal" onclick="closeFind()">
  <div class="modal" onclick="event.stopPropagation()">
    <h3>Find Recipient</h3>
    <div class="field" style="margin-bottom:10px">
      <div class="flbl">Mobile Number</div>
      <input class="fi mono" type="tel" id="findMob"
             placeholder="9876543210" maxlength="10"
             inputmode="numeric" oninput="findUser()">
    </div>
    <div class="err" id="findErr" style="margin-bottom:10px"></div>
    <div id="foundDiv" style="display:none">
      <div class="fcard">
        <div class="fav" id="fAv">?</div>
        <div>
          <div class="fnm" id="fNm"></div>
          <div class="fsb" id="fSb"></div>
        </div>
      </div>
      <button class="btn btn-g" onclick="pickRecipient()">Select This Person</button>
    </div>
    <button class="btn btn-o" style="margin-top:10px" onclick="closeFind()">Cancel</button>
  </div>
</div>

<!-- ══ RESULT OVERLAY ══ -->
<div class="rov" id="rov" onclick="closeResult()">
  <div class="rsheet" onclick="event.stopPropagation()">
    <div class="rico"   id="rico"></div>
    <div class="rtitle" id="rtitle"></div>
    <div class="rsub"   id="rsub"></div>
    <div class="ramt"   id="ramt"></div>
    <div class="bupd"   id="bupd"></div>
    <div class="rdets"  id="rdets"></div>
    <div class="rsteps" id="rsteps"></div>
    <button class="btn btn-p" onclick="closeResult()">Done</button>
  </div>
</div>

<!-- ══ BOTTOM NAV ══ -->
<div class="bnav" id="bnav" style="display:none">
  <button class="ni on" id="n0" onclick="goHome();navOn(0)"><span class="ic">⌂</span>HOME</button>
  <button class="ni"    id="n1" onclick="goSend();navOn(1)"><span class="ic">↑</span>SEND</button>
  <button class="ni"    id="n2" onclick="loadHistory();navOn(2)"><span class="ic">📋</span>HISTORY</button>
</div>

</div><!-- /phone -->

<script>
let ME=null, RECV=null, FOUND=null, SEL_BANK=null;

// ── GATEWAY CHECK ─────────────────────────────────────────────────────────────
async function checkGateway(){
  try{
    const r=await fetch('/gateway_status').then(x=>x.json());
    const b=document.getElementById('gwBanner');
    b.classList.toggle('show',!r.online);
  }catch(e){}
}
checkGateway();
setInterval(checkGateway,5000);

// ── SCREENS ───────────────────────────────────────────────────────────────────
function show(id){
  document.querySelectorAll('.scr').forEach(s=>s.classList.remove('on'));
  document.getElementById(id).classList.add('on');
}
function navOn(i){[0,1,2].forEach(j=>document.getElementById('n'+j).classList.toggle('on',i===j))}

// ── REGISTER ─────────────────────────────────────────────────────────────────
async function doRegister(){
  const name  =document.getElementById('regName').value.trim();
  const mobile=document.getElementById('regMobile').value.trim();
  const pin   =document.getElementById('regPin').value.trim();
  const err   =document.getElementById('regErr');
  const btn   =document.getElementById('regBtn');
  err.style.display='none';
  if(!name||!mobile||!pin){showErr(err,'Please fill all fields.');return}
  if(mobile.length<10){showErr(err,'Enter a valid 10-digit mobile number.');return}
  if(pin.length<4){showErr(err,'PIN must be 4 digits.');return}
  btn.disabled=true;btn.innerHTML='<span class="spin">⚙</span> Creating...';
  const r=await api('/register',{name,mobile,pin});
  btn.disabled=false;btn.innerHTML='Create Account';
  if(r.state!==1){
    showErr(err,r.reason==='MOBILE_EXISTS'?'Mobile already registered. Please sign in.':r.reason);
    return;
  }
  ME={name,mobile,bank_linked:false,avatar_color:hslColor(name)};
  goLinkBank();
}

// ── LOGIN ─────────────────────────────────────────────────────────────────────
async function doLogin(){
  const mobile=document.getElementById('loginMobile').value.trim();
  const pin   =document.getElementById('loginPin').value.trim();
  const err   =document.getElementById('loginErr');
  const btn   =document.getElementById('loginBtn');
  err.style.display='none';
  if(!mobile||!pin){showErr(err,'Enter mobile and PIN.');return}
  btn.disabled=true;btn.innerHTML='<span class="spin">⚙</span> Signing in...';
  const r=await api('/login',{mobile,pin});
  btn.disabled=false;btn.innerHTML='Sign In';
  if(r.state!==1){
    showErr(err,r.reason==='WRONG_PIN'?'Incorrect PIN.':r.reason==='USER_NOT_FOUND'?'No account found. Please register.':r.reason);
    return;
  }
  ME=r;
  document.getElementById('loginMobile').value='';
  document.getElementById('loginPin').value='';
  if(!ME.bank_linked){goLinkBank();}
  else{goHomeSetup();}
}

function doLogout(){
  ME=null;RECV=null;
  document.getElementById('bnav').style.display='none';
  show('scrWelcome');
}

// ── LINK BANK ─────────────────────────────────────────────────────────────────
async function goLinkBank(){
  SEL_BANK=null;
  document.getElementById('linkErr').style.display='none';
  document.getElementById('linkOk').style.display='none';
  document.getElementById('linkAcc').value='';
  show('scrLinkBank');
  // Load available banks
  const banks=await fetch('/banks').then(r=>r.json()).catch(()=>[]);
  const grid=document.getElementById('bankGrid');
  if(!banks.length){
    grid.innerHTML='<div style="color:var(--red);font-size:13px">Cannot load banks. Is gateway running?</div>';
    return;
  }
  grid.innerHTML=banks.map(b=>`
    <div class="bcard" id="bc_${b.id}" onclick="selBank('${b.id}')">
      <div class="bico">${b.icon}</div>
      <div class="binf">
        <div class="bnm">${b.name}</div>
        <div class="bsh">${b.short} · ${b.label}</div>
        <div class="bonl ${b.online?'online':'offline'}">${b.online?'● Online':'● Offline'}</div>
      </div>
      <div class="bchk">✓</div>
    </div>`).join('');
}

function selBank(id){
  SEL_BANK=id;
  document.querySelectorAll('.bcard').forEach(c=>c.classList.remove('sel'));
  document.getElementById('bc_'+id)?.classList.add('sel');
}

async function doLinkBank(){
  const accId=document.getElementById('linkAcc').value.trim().toUpperCase();
  const err  =document.getElementById('linkErr');
  const ok   =document.getElementById('linkOk');
  const btn  =document.getElementById('linkBtn');
  err.style.display='none';ok.style.display='none';
  if(!SEL_BANK){showErr(err,'Please select your bank.');return}
  if(!accId){showErr(err,'Please enter your account number.');return}
  btn.disabled=true;btn.innerHTML='<span class="spin">⚙</span> Verifying with bank...';
  const r=await api('/link_bank',{mobile:ME.mobile,bank_id:SEL_BANK,account_id:accId});
  btn.disabled=false;btn.innerHTML='Verify & Link Bank';
  if(r.state!==1){
    showErr(err,
      r.reason==='ACCOUNT_NOT_FOUND'?'Account not found at this bank. Check your account number.':
      r.reason==='BANK_UNREACHABLE'?'Bank is offline. Please try later.':
      r.reason);
    return;
  }
  ok.textContent='✅  Bank linked!  Account: '+r.account_id+'  ·  '+r.holder;
  ok.style.display='block';
  ME.bank_linked=true;
  ME.account_id =r.account_id;
  ME.bank_name  =r.bank_name;
  ME.bank_label =r.bank_label;
  setTimeout(()=>goHomeSetup(),1000);
}

// ── HOME ─────────────────────────────────────────────────────────────────────
function goHomeSetup(){
  const av=document.getElementById('hAv');
  av.textContent=ME.name[0].toUpperCase();
  av.style.background=ME.avatar_color||hslColor(ME.name);
  document.getElementById('hName').textContent=ME.name;
  document.getElementById('hSub').textContent =ME.mobile;
  document.getElementById('bAccId').textContent=ME.account_id||'—';
  document.getElementById('bBank').textContent =ME.bank_label||'—';
  document.getElementById('bnav').style.display='flex';
  show('scrHome');navOn(0);
  loadBal();loadHistory();
}

function goHome(){
  show('scrHome');navOn(0);
  loadBal();loadHistory();
}

async function loadBal(){
  if(!ME)return;
  const el =document.getElementById('bAmt');
  const sub=document.getElementById('bSub');
  el.innerHTML='<span class="spin">⚙</span>';
  const r=await api('/balance',{mobile:ME.mobile});
  if(r.state===1){
    el.textContent='Rs. '+Number(r.balance).toLocaleString('en-IN',{minimumFractionDigits:2});
    sub.textContent=r.account_id+' · '+r.bank_name;
    document.getElementById('bAccId').textContent=r.account_id;
    document.getElementById('bBank').textContent =r.bank_label;
  }else{
    el.textContent='Rs. —';sub.textContent='Could not fetch balance';
  }
}

async function loadHistory(){
  if(!ME)return;
  const txns=await api('/history',{mobile:ME.mobile});
  const el=document.getElementById('txList');
  if(!txns||!txns.length){
    el.innerHTML='<div class="txmt">No transactions yet.<br>Send your first payment.</div>';
    return;
  }
  el.innerHTML=txns.map(t=>{
    const sent=t.sender_mobile===ME.mobile;
    const ok=t.state===1;
    const other=sent?t.receiver_name:t.sender_name;
    const dir=sent?'s':'r';
    const sign=sent?'−':'+';
    return `<div class="txi">
      <div class="txic ${ok?dir:'s'}">${sent?'↑':'↓'}</div>
      <div class="txinf">
        <div class="txnm">${other}</div>
        <div class="txdt">${t.date} ${t.time}</div>
        ${t.note?`<div class="txnt">${t.note}</div>`:''}
      </div>
      <div class="txamt">
        <div class="txa ${ok?dir:''}">${ok?sign:''}Rs.${Number(t.amount).toLocaleString('en-IN')}</div>
        <div class="txst">${ok?(sent?'Sent':'Received'):'Reversed'}</div>
      </div>
    </div>`;
  }).join('');
}

// ── SEND ─────────────────────────────────────────────────────────────────────
function goSend(){
  RECV=null;
  document.getElementById('cpAv').textContent='👤';
  document.getElementById('cpAv').style.background='var(--card)';
  document.getElementById('cpNm').textContent='Select Recipient';
  document.getElementById('cpSb').textContent='Enter mobile number to find';
  document.getElementById('sAmt').value='';
  document.getElementById('sNote').value='';
  document.getElementById('sendBtn').disabled=false;
  document.getElementById('sendBtn').innerHTML='Send Payment';
  show('scrSend');navOn(1);
}

// ── FIND USER MODAL ───────────────────────────────────────────────────────────
function openFind(){
  document.getElementById('findMob').value='';
  document.getElementById('findErr').style.display='none';
  document.getElementById('foundDiv').style.display='none';
  FOUND=null;
  document.getElementById('findModal').classList.add('on');
  setTimeout(()=>document.getElementById('findMob').focus(),300);
}
function closeFind(){document.getElementById('findModal').classList.remove('on')}

let ftimer=null;
function findUser(){
  clearTimeout(ftimer);
  ftimer=setTimeout(async()=>{
    const mob=document.getElementById('findMob').value.trim();
    const err=document.getElementById('findErr');
    const fd =document.getElementById('foundDiv');
    err.style.display='none';fd.style.display='none';FOUND=null;
    if(mob.length<10)return;
    if(mob===ME.mobile){showErr(err,"You can't send to yourself.");return}
    const r=await api('/find_user',{mobile:mob});
    if(r.state!==1){showErr(err,'No user found with this mobile number.');return}
    FOUND=r;
    document.getElementById('fAv').textContent=r.name[0].toUpperCase();
    document.getElementById('fAv').style.background=hslColor(r.name);
    document.getElementById('fNm').textContent=r.name;
    document.getElementById('fSb').textContent=mob+' · '+r.bank;
    fd.style.display='block';
  },500);
}

function pickRecipient(){
  RECV=FOUND;
  const av=document.getElementById('cpAv');
  av.textContent=RECV.name[0].toUpperCase();
  av.style.background=hslColor(RECV.name);
  document.getElementById('cpNm').textContent=RECV.name;
  document.getElementById('cpSb').textContent=RECV.mobile+' · '+RECV.bank;
  closeFind();
}

async function doSend(){
  if(!RECV){alert('Please select a recipient.');return}
  const amount=parseFloat(document.getElementById('sAmt').value);
  if(!amount||amount<=0){alert('Please enter a valid amount.');return}
  const note=document.getElementById('sNote').value;
  const btn=document.getElementById('sendBtn');
  btn.disabled=true;btn.innerHTML='<span class="spin">⚙</span> Processing...';
  const r=await api('/pay',{sender_mobile:ME.mobile,receiver_mobile:RECV.mobile,amount,note});
  showResult(r);loadBal();loadHistory();
  btn.disabled=false;btn.innerHTML='Send Payment';
}

// ── RESULT ────────────────────────────────────────────────────────────────────
function showResult(r){
  const ok=r.state===1;
  const fmt=n=>n!=null?'Rs. '+Number(n).toLocaleString('en-IN',{minimumFractionDigits:2}):'—';
  document.getElementById('rico').textContent=ok?'✅':'↩️';
  const t=document.getElementById('rtitle');
  t.textContent=ok?'Payment Sent!':'Payment Reversed';
  t.style.color=ok?'var(--green)':'var(--red)';
  document.getElementById('rsub').textContent=ok?'Money transferred atomically':'No money moved — '+r.reason;
  const a=document.getElementById('ramt');
  a.textContent=fmt(r.amount);a.style.color=ok?'var(--green)':'var(--red)';
  const bu=document.getElementById('bupd');
  if(ok&&r.new_sender_bal!=null){
    bu.style.display='flex';
    bu.innerHTML=`
      <div class="bucard"><div class="bunm">${r.sender_name}</div><div class="buarr" style="color:var(--red)">↓ Debited</div><div class="bubal" style="color:var(--red)">${fmt(r.new_sender_bal)}</div></div>
      <div class="bucard"><div class="bunm">${r.receiver_name}</div><div class="buarr" style="color:var(--green)">↑ Credited</div><div class="bubal" style="color:var(--green)">${fmt(r.new_receiver_bal)}</div></div>`;
  }else bu.style.display='none';
  document.getElementById('rdets').innerHTML=`
    <div class="rdrow"><span class="rdlbl">From</span><span class="rdval">${r.sender_name}</span></div>
    <div class="rdrow"><span class="rdlbl">To</span><span class="rdval">${r.receiver_name}</span></div>
    <div class="rdrow"><span class="rdlbl">Transit (0)</span><span class="rdval" style="color:var(--gold)">${r.transit_ms}ms</span></div>
    <div class="rdrow"><span class="rdlbl">TX ID</span><span class="rdval">${r.tx_id.substring(0,16)}...</span></div>
    <div class="rdrow"><span class="rdlbl">Signature</span><span class="rdval">${r.signature}</span></div>`;
  document.getElementById('rsteps').innerHTML=(r.steps||[]).map(s=>{
    let c='#2a3a55';
    if(s.includes('+1')||s.includes('Confirmed')||s.includes('COMMIT'))c='#1a5a2a';
    else if(s.includes('-1')||s.includes('FAIL')||s.includes('REVERSED'))c='#5a1a1a';
    else if(s.includes('Phase')||s.includes('Rajas'))c='#4a4010';
    return `<span style="color:${c}">${s}</span>`;
  }).join('<br>');
  document.getElementById('rov').classList.add('on');
}
function closeResult(){document.getElementById('rov').classList.remove('on');goHome();}

// ── HELPERS ───────────────────────────────────────────────────────────────────
function showErr(el,msg){el.textContent=msg;el.style.display='block'}
function hslColor(name){return `hsl(${name.charCodeAt(0)*47%360},55%,45%)`}
async function api(url,data){
  const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  return r.json();
}
document.getElementById('loginPin').addEventListener('keydown',e=>{if(e.key==='Enter')doLogin()});
document.getElementById('findMob').addEventListener('keydown',e=>{if(e.key==='Enter')findUser()});
</script>
</body>
</html>"""

# ── MAIN ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 55)
    print("  ⚡ AtomicPay — Standalone App")
    print("=" * 55)
    print(f"  App     : http://localhost:{APP_PORT}")
    print(f"  Gateway : {GATEWAY_URL}")
    print()
    print("  Make sure these are running first:")
    print("    python bank_a_server.py")
    print("    python bank_b_server.py")
    print("    python gateway_server.py")
    print()
    print("  Opening browser...")
    print("  Hari Om Namah Shivaye. 🙏")
    print("=" * 55)

    # Open browser automatically
    def open_browser():
        time.sleep(1.2)
        webbrowser.open(f"http://localhost:{APP_PORT}")
    threading.Thread(target=open_browser, daemon=True).start()

    HTTPServer(("0.0.0.0", APP_PORT), AtomicPayHandler).serve_forever()
