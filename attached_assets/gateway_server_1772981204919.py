"""
gateway_server.py
==================
AtomicPay Payment Gateway.

Runs on port 5000.
Handles: register, login, link_bank, balance, pay, history, find_user, banks

Run order:
  Terminal 1:  python bank_a_server.py
  Terminal 2:  python bank_b_server.py
  Terminal 3:  python gateway_server.py
  Terminal 4:  python AtomicPay.py
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json, urllib.request, urllib.error
import time, uuid, hashlib, hmac, threading

BANK_A_URL   = "http://127.0.0.1:6001"
BANK_B_URL   = "http://127.0.0.1:6002"
GATEWAY_PORT = 5000
TIMEOUT_SEC  = 3.0

# Available banks
AVAILABLE_BANKS = {
    "bank_a": {
        "id"   : "bank_a",
        "name" : "Bharatiya Gramin Bank",
        "short": "BGB",
        "label": "Bank A",
        "url"  : BANK_A_URL,
        "color": "#3b7fff",
        "icon" : "🏦",
    },
    "bank_b": {
        "id"   : "bank_b",
        "name" : "Rashtriya Vyapar Bank",
        "short": "RVB",
        "label": "Bank B",
        "url"  : BANK_B_URL,
        "color": "#f472b6",
        "icon" : "🏛️",
    },
}

# In-memory user store  {mobile: {name, mobile, pin, bank_id, account_id, avatar_color}}
users       = {}
users_lock  = threading.Lock()

# In-memory ledger
ledger      = []
ledger_lock = threading.Lock()


# ── BANK HELPERS ──────────────────────────────────────────────────────────────

def call_bank(url, payload):
    try:
        data = json.dumps(payload).encode()
        req  = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as r:
            return json.loads(r.read())
    except Exception:
        return {"state": -1, "reason": "BANK_UNREACHABLE"}


def ping(url):
    try:
        urllib.request.urlopen(url, timeout=1)
        return True
    except Exception:
        return False


def verify_account(bank_id, account_id):
    """Ask the bank if account exists. Returns (ok, holder_name_or_reason)."""
    bank = AVAILABLE_BANKS.get(bank_id)
    if not bank:
        return False, "BANK_NOT_FOUND"
    r = call_bank(bank["url"], {"action": "STATUS", "account_id": account_id})
    if r.get("state") == 1:
        return True, r.get("name", account_id)
    return False, r.get("reason", "ACCOUNT_NOT_FOUND")


def get_balance(mobile):
    with users_lock:
        u = users.get(mobile)
    if not u or not u.get("bank_id"):
        return None, None, None
    bank = AVAILABLE_BANKS[u["bank_id"]]
    r = call_bank(bank["url"], {"action": "STATUS", "account_id": u["account_id"]})
    if r.get("state") == 1:
        return r.get("balance"), u["account_id"], bank
    return None, u["account_id"], bank


# ── ATOMIC PAYMENT ────────────────────────────────────────────────────────────

def execute_payment(sender_mobile, receiver_mobile, amount, note=""):
    with users_lock:
        s = users.get(sender_mobile)
        r = users.get(receiver_mobile)

    if not s:
        return _fail("SENDER_NOT_FOUND")
    if not r:
        return _fail("RECEIVER_NOT_FOUND")
    if not s.get("bank_id"):
        return _fail("SENDER_BANK_NOT_LINKED")
    if not r.get("bank_id"):
        return _fail("RECEIVER_BANK_NOT_LINKED")

    sb    = AVAILABLE_BANKS[s["bank_id"]]
    rb    = AVAILABLE_BANKS[r["bank_id"]]
    tx_id = str(uuid.uuid4())
    t0    = time.time()
    steps = []

    steps.append(f"Tx {tx_id[:8]}  |  State: 0 (Rajas)")
    steps.append(f"From : {s['name']} ({s['account_id']}) @ {sb['name']}")
    steps.append(f"To   : {r['name']} ({r['account_id']}) @ {rb['name']}")
    steps.append(f"Amt  : Rs.{amount:,.2f}")
    steps.append("-" * 42)
    steps.append("Phase 1 PREPARE")
    steps.append(f"  Debit {s['name']} @ {sb['name']}...")

    debit = call_bank(sb["url"], {
        "action": "DEBIT", "tx_id": tx_id,
        "account_id": s["account_id"], "amount": amount
    })
    elapsed = (time.time() - t0) * 1000

    if debit.get("state") != 1:
        reason = debit.get("reason", "DEBIT_FAILED")
        avail  = debit.get("available")
        steps.append(f"  REJECTED: {reason}")
        if avail is not None:
            steps.append(f"  Has Rs.{avail:.0f}  Needs Rs.{amount:.0f}")
        steps.append("State: -1 (Tamas REVERSED)")
        return _seal(tx_id, -1, amount, sender_mobile, receiver_mobile,
                     elapsed, reason, steps, note, s, r)

    nsb = debit.get("new_balance")
    steps.append(f"  Confirmed. {s['name']} balance: Rs.{nsb:,.0f}")
    steps.append(f"  Credit {r['name']} @ {rb['name']}...")

    credit = call_bank(rb["url"], {
        "action": "CREDIT", "tx_id": tx_id,
        "account_id": r["account_id"], "amount": amount
    })
    elapsed = (time.time() - t0) * 1000

    if credit.get("state") != 1:
        reason = credit.get("reason", "CREDIT_FAILED")
        steps.append(f"  REJECTED: {reason}")
        steps.append("  Rolling back debit...")
        call_bank(sb["url"], {
            "action": "UNLOCK", "tx_id": tx_id,
            "account_id": s["account_id"], "amount": amount
        })
        steps.append("  Rollback complete.")
        steps.append("State: -1 (Tamas REVERSED)")
        return _seal(tx_id, -1, amount, sender_mobile, receiver_mobile,
                     elapsed, reason, steps, note, s, r)

    nrb = credit.get("new_balance")
    steps.append(f"  Confirmed. {r['name']} balance: Rs.{nrb:,.0f}")
    elapsed = (time.time() - t0) * 1000
    steps.append("-" * 42)
    steps.append("Phase 2 COMMIT — Both banks confirmed")
    steps.append(f"Transit (Rajas 0): {elapsed:.1f}ms")
    steps.append("State: +1 (Sattva COMPLETED)")

    return _seal(tx_id, +1, amount, sender_mobile, receiver_mobile,
                 elapsed, "COMPLETED", steps, note, s, r,
                 new_sender_bal=nsb, new_receiver_bal=nrb)


def _fail(reason):
    return {"state": -1, "reason": reason, "steps": [reason],
            "tx_id": str(uuid.uuid4()), "transit_ms": 0,
            "sender_name": "", "receiver_name": "", "amount": 0,
            "time": time.strftime("%H:%M:%S"), "date": time.strftime("%d %b %Y"),
            "signature": "", "new_sender_bal": None, "new_receiver_bal": None}


def _seal(tx_id, state, amount, sm, rm, transit_ms, reason, steps, note, s, r,
          new_sender_bal=None, new_receiver_bal=None):
    sig = hmac.new(
        b"atomicpay",
        f"{tx_id}|{state}|{amount}".encode(),
        hashlib.sha256
    ).hexdigest()[:16]
    rec = {
        "tx_id"          : tx_id,
        "state"          : state,
        "amount"         : amount,
        "sender_mobile"  : sm,
        "receiver_mobile": rm,
        "sender_name"    : s["name"],
        "receiver_name"  : r["name"],
        "new_sender_bal" : new_sender_bal,
        "new_receiver_bal": new_receiver_bal,
        "note"           : note,
        "transit_ms"     : round(transit_ms, 2),
        "time"           : time.strftime("%H:%M:%S"),
        "date"           : time.strftime("%d %b %Y"),
        "reason"         : reason,
        "signature"      : sig,
        "steps"          : steps,
    }
    with ledger_lock:
        ledger.insert(0, rec)
    return rec


# ── HTTP HANDLER ──────────────────────────────────────────────────────────────

class GatewayHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        if self.path in ("/", "/ping"):
            # AtomicPay.py pings this to check if gateway is online
            self._json({"state": 1, "service": "AtomicPay Gateway", "port": GATEWAY_PORT})
        elif self.path == "/banks":
            self._json([
                {
                    "id"    : b["id"],
                    "name"  : b["name"],
                    "short" : b["short"],
                    "label" : b["label"],
                    "color" : b["color"],
                    "icon"  : b["icon"],
                    "online": ping(b["url"]),
                }
                for b in AVAILABLE_BANKS.values()
            ])
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body   = json.loads(self.rfile.read(length))

        routes = {
            "/register"  : self._register,
            "/login"     : self._login,
            "/link_bank" : self._link_bank,
            "/balance"   : self._balance,
            "/pay"       : self._pay,
            "/find_user" : self._find_user,
            "/history"   : self._history,
        }
        handler = routes.get(self.path)
        if handler:
            handler(body)
        else:
            self.send_response(404)
            self.end_headers()

    # ── ROUTES ────────────────────────────────────────────────────────────────

    def _register(self, body):
        name   = body.get("name", "").strip()
        mobile = body.get("mobile", "").strip()
        pin    = body.get("pin", "").strip()

        if not name or not mobile or not pin:
            self._json({"state": -1, "reason": "MISSING_FIELDS"})
            return
        if len(mobile) < 10:
            self._json({"state": -1, "reason": "INVALID_MOBILE"})
            return

        with users_lock:
            if mobile in users:
                self._json({"state": -1, "reason": "MOBILE_EXISTS"})
                return
            colors = ["#3b7fff","#f472b6","#34d399","#f59e0b","#a78bfa","#fb923c"]
            color  = colors[sum(ord(c) for c in name) % len(colors)]
            users[mobile] = {
                "name"        : name,
                "mobile"      : mobile,
                "pin"         : pin,
                "bank_id"     : None,
                "account_id"  : None,
                "avatar_color": color,
            }

        print(f"[{time.strftime('%H:%M:%S')}] REGISTER  {name} ({mobile})")
        self._json({"state": 1, "name": name, "mobile": mobile})

    def _login(self, body):
        mobile = body.get("mobile", "").strip()
        pin    = body.get("pin", "").strip()

        with users_lock:
            u = users.get(mobile)

        if not u:
            self._json({"state": -1, "reason": "USER_NOT_FOUND"})
            return
        if u["pin"] != pin:
            self._json({"state": -1, "reason": "WRONG_PIN"})
            return

        bank = AVAILABLE_BANKS.get(u.get("bank_id") or "", {})
        print(f"[{time.strftime('%H:%M:%S')}] LOGIN     {u['name']} ({mobile})")
        self._json({
            "state"       : 1,
            "name"        : u["name"],
            "mobile"      : mobile,
            "bank_linked" : u["bank_id"] is not None,
            "bank_id"     : u.get("bank_id"),
            "bank_name"   : bank.get("name", ""),
            "bank_label"  : bank.get("label", ""),
            "account_id"  : u.get("account_id", ""),
            "avatar_color": u.get("avatar_color", "#3b7fff"),
        })

    def _link_bank(self, body):
        mobile     = body.get("mobile", "").strip()
        bank_id    = body.get("bank_id", "").strip()
        account_id = body.get("account_id", "").strip().upper()

        with users_lock:
            u = users.get(mobile)

        if not u:
            self._json({"state": -1, "reason": "USER_NOT_FOUND"})
            return
        if bank_id not in AVAILABLE_BANKS:
            self._json({"state": -1, "reason": "BANK_NOT_FOUND"})
            return

        ok, result = verify_account(bank_id, account_id)
        if not ok:
            self._json({"state": -1, "reason": result})
            return

        with users_lock:
            users[mobile]["bank_id"]    = bank_id
            users[mobile]["account_id"] = account_id

        bank = AVAILABLE_BANKS[bank_id]
        print(f"[{time.strftime('%H:%M:%S')}] LINK      {u['name']} → {account_id} @ {bank['name']}")
        self._json({
            "state"     : 1,
            "account_id": account_id,
            "bank_name" : bank["name"],
            "bank_label": bank["label"],
            "holder"    : result,
        })

    def _balance(self, body):
        mobile = body.get("mobile", "").strip()
        bal, acc_id, bank = get_balance(mobile)
        if bal is not None:
            self._json({
                "state"     : 1,
                "balance"   : bal,
                "account_id": acc_id,
                "bank_name" : bank["name"],
                "bank_label": bank["label"],
            })
        else:
            self._json({"state": -1, "reason": "BALANCE_UNAVAILABLE"})

    def _pay(self, body):
        sm     = body.get("sender_mobile", "").strip()
        rm     = body.get("receiver_mobile", "").strip()
        amount = float(body.get("amount", 0))
        note   = body.get("note", "")

        if amount <= 0:
            self._json({"state": -1, "reason": "INVALID_AMOUNT"})
            return

        result = execute_payment(sm, rm, amount, note)
        self._json(result)

    def _find_user(self, body):
        mobile = body.get("mobile", "").strip()
        with users_lock:
            u = users.get(mobile)
        if not u or not u.get("bank_id"):
            self._json({"state": -1, "reason": "USER_NOT_FOUND"})
            return
        bank = AVAILABLE_BANKS.get(u["bank_id"], {})
        self._json({
            "state" : 1,
            "name"  : u["name"],
            "mobile": mobile,
            "bank"  : bank.get("name", ""),
        })

    def _history(self, body):
        mobile = body.get("mobile", "").strip()
        with ledger_lock:
            txns = [
                t for t in ledger
                if t["sender_mobile"] == mobile
                or t["receiver_mobile"] == mobile
            ]
        self._json(txns[:20])

    # ── RESPONSE HELPERS ──────────────────────────────────────────────────────

    def _json(self, data):
        raw = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):
        pass


# ── MAIN ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 55)
    print("  AtomicPay Gateway")
    print("=" * 55)
    print(f"  Port   : {GATEWAY_PORT}")
    print(f"  Bank A : {BANK_A_URL}")
    print(f"  Bank B : {BANK_B_URL}")
    print()
    print("  Routes: /banks /register /login /link_bank")
    print("          /balance /pay /find_user /history")
    print()
    print("  Waiting for AtomicPay.py to connect...")
    print("  Hari Om Namah Shivaye. 🙏")
    print("=" * 55)
    HTTPServer(("0.0.0.0", GATEWAY_PORT), GatewayHandler).serve_forever()
