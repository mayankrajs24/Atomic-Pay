"""
AtomicPay Bank SDK v1.0
========================
Python SDK for banks integrating with the AtomicPay payment network.

Usage:
    from atomicpay_bank_sdk import AtomicPayBankSDK

    sdk = AtomicPayBankSDK(bank_name="My Bank", port=6003)
    sdk.set_accounts({
        "ACC_001": {"name": "John Doe", "balance": 5000.0, "active": True}
    })
    sdk.start()
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import threading
import time


class AtomicPayBankSDK:
    def __init__(self, bank_name="My Bank", port=6003):
        self.bank_name = bank_name
        self.port = port
        self.accounts = {}
        self.lock = threading.Lock()
        self.tx_log = []

    def set_accounts(self, accounts: dict):
        self.accounts = accounts

    def handle_debit(self, account_id: str, amount: float, tx_id: str) -> dict:
        with self.lock:
            acc = self.accounts.get(account_id)
            if not acc:
                return {"state": -1, "reason": "ACCOUNT_NOT_FOUND"}
            if not acc.get("active", True):
                return {"state": -1, "reason": "ACCOUNT_FROZEN"}
            if acc["balance"] < amount:
                return {"state": -1, "reason": "INSUFFICIENT_FUNDS",
                        "available": acc["balance"], "required": amount}
            acc["balance"] -= amount
            self._log(f"DEBIT OK [{tx_id[:8]}] {acc['name']} -Rs.{amount:.0f}")
            return {"state": 1, "reason": "DEBITED",
                    "name": acc["name"], "new_balance": acc["balance"]}

    def handle_credit(self, account_id: str, amount: float, tx_id: str) -> dict:
        with self.lock:
            acc = self.accounts.get(account_id)
            if not acc:
                return {"state": -1, "reason": "ACCOUNT_NOT_FOUND"}
            acc["balance"] += amount
            self._log(f"CREDIT OK [{tx_id[:8]}] {acc['name']} +Rs.{amount:.0f}")
            return {"state": 1, "reason": "CREDITED",
                    "name": acc["name"], "new_balance": acc["balance"]}

    def handle_unlock(self, account_id: str, amount: float, tx_id: str) -> dict:
        with self.lock:
            acc = self.accounts.get(account_id)
            if acc:
                acc["balance"] += amount
                self._log(f"ROLLBACK [{tx_id[:8]}] {acc['name']} +Rs.{amount:.0f}")
        return {"state": 1, "reason": "UNLOCKED"}

    def handle_status(self, account_id: str = None) -> dict:
        with self.lock:
            if account_id:
                acc = self.accounts.get(account_id)
                if not acc:
                    return {"state": -1, "reason": "NOT_FOUND"}
                return {"state": 1, "name": acc["name"],
                        "balance": acc["balance"], "active": acc.get("active", True)}
            return {"state": 1, "accounts": {
                k: {"name": v["name"], "balance": v["balance"]}
                for k, v in self.accounts.items()
            }}

    def _log(self, msg):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        self.tx_log.append(line)
        print(line)

    def start(self):
        sdk = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"state": 1, "service": sdk.bank_name}).encode())

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length))
                action = body.get("action", "")
                acc_id = body.get("account_id", "")
                amount = float(body.get("amount", 0))
                tx_id = body.get("tx_id", "?")

                if action == "DEBIT":
                    resp = sdk.handle_debit(acc_id, amount, tx_id)
                elif action == "CREDIT":
                    resp = sdk.handle_credit(acc_id, amount, tx_id)
                elif action == "UNLOCK":
                    resp = sdk.handle_unlock(acc_id, amount, tx_id)
                elif action == "STATUS":
                    resp = sdk.handle_status(acc_id or None)
                else:
                    resp = {"state": -1, "reason": "UNKNOWN_ACTION"}

                raw = json.dumps(resp).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *a):
                pass

        print(f"[AtomicPay SDK] {sdk.bank_name} starting on port {sdk.port}")
        HTTPServer(("0.0.0.0", sdk.port), Handler).serve_forever()


if __name__ == "__main__":
    sdk = AtomicPayBankSDK(bank_name="Demo Bank", port=6003)
    sdk.set_accounts({
        "DEMO_001": {"name": "Demo User", "balance": 10000.0, "active": True},
    })
    print("AtomicPay Bank SDK Demo")
    print(f"Running on port {sdk.port}")
    sdk.start()
