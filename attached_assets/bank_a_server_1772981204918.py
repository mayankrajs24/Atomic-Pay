"""
AtomicPay Network Demo — Bank A Server
========================================
bank_a_server.py

RAM's bank — Bharatiya Gramin Bank.
RAM has account RAM_001 here with Rs. 10,000

Run this FIRST:
    python bank_a_server.py

Dashboard: http://localhost:6001
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json, threading, time

HOST      = "0.0.0.0"
PORT      = 6001
BANK_NAME = "Bharatiya Gramin Bank"
BANK_ID   = "A"

# ── ACCOUNTS ──────────────────────────────────────────────────────────────────
# These are the people who have accounts at Bank A
accounts = {
    "RAM_001":  {"name": "Ram Kumar",  "balance": 10000.0, "active": True},
    "ARJUN_01": {"name": "Arjun Seth", "balance":  5000.0, "active": True},
}
lock   = threading.Lock()
tx_log = []

def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    tx_log.append(line)
    print(line)

# ── REQUEST HANDLER ────────────────────────────────────────────────────────────
class BankAHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(self._dashboard().encode("utf-8"))

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body   = json.loads(self.rfile.read(length))
        action = body.get("action", "")

        if   action == "DEBIT":  resp = self._debit(body)
        elif action == "CREDIT": resp = self._credit(body)
        elif action == "UNLOCK": resp = self._unlock(body)
        elif action == "STATUS": resp = self._status(body)
        else: resp = {"state": -1, "reason": "UNKNOWN_ACTION"}

        raw = json.dumps(resp).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    # ── DEBIT — take money from account ───────────────────────────────────────
    def _debit(self, body):
        acc_id = body.get("account_id", "")
        amount = float(body.get("amount", 0))
        tx_id  = body.get("tx_id", "?")[:8]

        with lock:
            acc = accounts.get(acc_id)

            if not acc:
                log(f"  DEBIT FAIL  [{tx_id}]  Account '{acc_id}' not found")
                return {"state": -1, "reason": "ACCOUNT_NOT_FOUND"}

            if not acc["active"]:
                log(f"  DEBIT FAIL  [{tx_id}]  {acc['name']} — account frozen")
                return {"state": -1, "reason": "ACCOUNT_FROZEN"}

            if acc["balance"] < amount:
                log(f"  DEBIT FAIL  [{tx_id}]  {acc['name']} — "
                    f"insufficient funds (has Rs.{acc['balance']:.0f}, "
                    f"needs Rs.{amount:.0f})")
                return {"state": -1, "reason": "INSUFFICIENT_FUNDS",
                        "available": acc["balance"], "required": amount}

            # Debit the account
            acc["balance"] -= amount
            log(f"  DEBIT OK    [{tx_id}]  {acc['name']}  "
                f"-Rs.{amount:.0f}  =>  balance Rs.{acc['balance']:.0f}")
            return {"state": +1, "reason": "DEBITED",
                    "name": acc["name"], "new_balance": acc["balance"]}

    # ── CREDIT — add money to account ─────────────────────────────────────────
    def _credit(self, body):
        acc_id = body.get("account_id", "")
        amount = float(body.get("amount", 0))
        tx_id  = body.get("tx_id", "?")[:8]

        with lock:
            acc = accounts.get(acc_id)

            if not acc:
                log(f"  CREDIT FAIL [{tx_id}]  Account '{acc_id}' not found")
                return {"state": -1, "reason": "ACCOUNT_NOT_FOUND"}

            acc["balance"] += amount
            log(f"  CREDIT OK   [{tx_id}]  {acc['name']}  "
                f"+Rs.{amount:.0f}  =>  balance Rs.{acc['balance']:.0f}")
            return {"state": +1, "reason": "CREDITED",
                    "name": acc["name"], "new_balance": acc["balance"]}

    # ── UNLOCK — rollback a failed debit ──────────────────────────────────────
    def _unlock(self, body):
        acc_id = body.get("account_id", "")
        amount = float(body.get("amount", 0))
        tx_id  = body.get("tx_id", "?")[:8]

        with lock:
            acc = accounts.get(acc_id)
            if acc:
                acc["balance"] += amount
                log(f"  ROLLBACK    [{tx_id}]  {acc['name']}  "
                    f"+Rs.{amount:.0f} RETURNED  =>  balance Rs.{acc['balance']:.0f}")
        return {"state": +1, "reason": "UNLOCKED"}

    # ── STATUS — get account info ─────────────────────────────────────────────
    def _status(self, body):
        acc_id = body.get("account_id")
        with lock:
            if acc_id:
                acc = accounts.get(acc_id)
                if not acc:
                    return {"state": -1, "reason": "NOT_FOUND"}
                return {"state": +1, "name": acc["name"],
                        "balance": acc["balance"], "active": acc["active"]}
            return {"state": +1, "accounts": {
                k: {"name": v["name"], "balance": v["balance"]}
                for k, v in accounts.items()
            }}

    def log_message(self, *a): pass

    # ── DASHBOARD ─────────────────────────────────────────────────────────────
    def _dashboard(self):
        rows = ""
        with lock:
            for aid, acc in accounts.items():
                bal   = acc["balance"]
                color = "#00cc44" if bal > 500 else "#ffcc00" if bal > 0 else "#ff4444"
                rows += f"""<tr>
                  <td class="mono">{aid}</td>
                  <td>{acc['name']}</td>
                  <td style="color:{color};font-weight:bold">
                    Rs. {bal:,.2f}</td>
                  <td>{'🟢 Active' if acc['active'] else '🔴 Frozen'}</td>
                </tr>"""

        logs = ""
        for line in reversed(tx_log[-25:]):
            if "OK" in line:   c = "#00cc44"
            elif "FAIL" in line: c = "#ff6644"
            elif "ROLLBACK" in line: c = "#ffcc00"
            else: c = "#8899bb"
            logs += f"<tr><td style='color:{c}'>{line}</td></tr>"
        if not logs:
            logs = "<tr><td style='color:#444'>Waiting for transactions...</td></tr>"

        return f"""<!DOCTYPE html>
<html><head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="2">
<title>Bank A — {BANK_NAME}</title>
<style>
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body  {{ background:#050d1a; color:#ccd; font-family:monospace;
           padding:24px; }}
  h1    {{ color:#4499ff; font-size:20px; margin-bottom:4px; }}
  .sub  {{ color:#335; font-size:12px; margin-bottom:22px; }}
  h2    {{ color:#6688cc; font-size:13px; margin:18px 0 8px;
           border-bottom:1px solid #0d1a30; padding-bottom:6px; }}
  table {{ border-collapse:collapse; width:100%; }}
  th    {{ background:#0a1830; color:#5577aa; padding:8px 14px;
           text-align:left; font-size:11px; letter-spacing:.5px; }}
  td    {{ padding:8px 14px; border-bottom:1px solid #0a1428;
           font-size:13px; }}
  .mono {{ font-family:monospace; color:#7799bb; }}
  .tag  {{ background:#0a2244; color:#4488dd; padding:2px 8px;
           border-radius:10px; font-size:10px; }}
</style>
</head><body>
<h1>🏦 {BANK_NAME}</h1>
<div class="sub">
  Port {PORT} &nbsp;·&nbsp; AtomicPay Network Demo
  &nbsp;·&nbsp; <span class="tag">Bank A</span>
  &nbsp;·&nbsp; Refreshes every 2s
</div>

<h2>Accounts</h2>
<table>
  <tr><th>Account ID</th><th>Name</th><th>Balance</th><th>Status</th></tr>
  {rows}
</table>

<h2>Transaction Log</h2>
<table><tr><th>Event</th></tr>{logs}</table>
</body></html>"""

# ── MAIN ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    log("=" * 55)
    log(f"  {BANK_NAME} (Bank A)")
    log(f"  Port    : {PORT}")
    log(f"  Dashboard: http://localhost:{PORT}")
    log(f"  Accounts:")
    for k, v in accounts.items():
        log(f"    {k}  {v['name']}  Rs.{v['balance']:.0f}")
    log("=" * 55)
    HTTPServer((HOST, PORT), BankAHandler).serve_forever()
