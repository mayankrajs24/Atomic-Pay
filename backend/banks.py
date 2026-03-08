import httpx
import threading
import json
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from backend.config import BANK_A_URL, BANK_B_URL, GATEWAY_TIMEOUT

AVAILABLE_BANKS = {
    "bank_a": {
        "id": "bank_a",
        "name": "Bharatiya Gramin Bank",
        "short": "BGB",
        "label": "Bank A",
        "url": BANK_A_URL,
        "color": "#3b7fff",
        "icon": "🏦",
    },
    "bank_b": {
        "id": "bank_b",
        "name": "Rashtriya Vyapar Bank",
        "short": "RVB",
        "label": "Bank B",
        "url": BANK_B_URL,
        "color": "#f472b6",
        "icon": "🏛️",
    },
}

bank_a_accounts = {
    "RAM_001": {"name": "Ram Kumar", "balance": 10000.0, "active": True},
    "ARJUN_01": {"name": "Arjun Seth", "balance": 5000.0, "active": True},
}

bank_b_accounts = {
    "SITA_001": {"name": "Sita Devi", "balance": 2000.0, "active": True},
    "SHOP_001": {"name": "Krishna Stores", "balance": 1000.0, "active": True},
    "SHOP_002": {"name": "Arjuna Traders", "balance": 500.0, "active": True},
}

bank_a_lock = threading.Lock()
bank_b_lock = threading.Lock()
bank_a_log = []
bank_b_log = []


def _bank_log(log_list, msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    log_list.append(line)
    if len(log_list) > 100:
        log_list.pop(0)


def _process_bank_action(accounts, lock, log_list, action, body):
    acc_id = body.get("account_id", "")
    amount = float(body.get("amount", 0))
    tx_id = body.get("tx_id", "?")[:8]

    if action == "DEBIT":
        with lock:
            acc = accounts.get(acc_id)
            if not acc:
                _bank_log(log_list, f"  DEBIT FAIL  [{tx_id}]  Account '{acc_id}' not found")
                return {"state": -1, "reason": "ACCOUNT_NOT_FOUND"}
            if not acc["active"]:
                _bank_log(log_list, f"  DEBIT FAIL  [{tx_id}]  {acc['name']} — frozen")
                return {"state": -1, "reason": "ACCOUNT_FROZEN"}
            if acc["balance"] < amount:
                _bank_log(log_list, f"  DEBIT FAIL  [{tx_id}]  {acc['name']} — insufficient")
                return {"state": -1, "reason": "INSUFFICIENT_FUNDS",
                        "available": acc["balance"], "required": amount}
            acc["balance"] -= amount
            _bank_log(log_list, f"  DEBIT OK    [{tx_id}]  {acc['name']}  -Rs.{amount:.0f}  =>  Rs.{acc['balance']:.0f}")
            return {"state": 1, "reason": "DEBITED", "name": acc["name"], "new_balance": acc["balance"]}

    elif action == "CREDIT":
        with lock:
            acc = accounts.get(acc_id)
            if not acc:
                _bank_log(log_list, f"  CREDIT FAIL [{tx_id}]  Account '{acc_id}' not found")
                return {"state": -1, "reason": "ACCOUNT_NOT_FOUND"}
            acc["balance"] += amount
            _bank_log(log_list, f"  CREDIT OK   [{tx_id}]  {acc['name']}  +Rs.{amount:.0f}  =>  Rs.{acc['balance']:.0f}")
            return {"state": 1, "reason": "CREDITED", "name": acc["name"], "new_balance": acc["balance"]}

    elif action == "UNLOCK":
        with lock:
            acc = accounts.get(acc_id)
            if acc:
                acc["balance"] += amount
                _bank_log(log_list, f"  ROLLBACK    [{tx_id}]  {acc['name']}  +Rs.{amount:.0f} RETURNED")
        return {"state": 1, "reason": "UNLOCKED"}

    elif action == "STATUS":
        with lock:
            if acc_id:
                acc = accounts.get(acc_id)
                if not acc:
                    return {"state": -1, "reason": "NOT_FOUND"}
                return {"state": 1, "name": acc["name"], "balance": acc["balance"], "active": acc["active"]}
            return {"state": 1, "accounts": {k: {"name": v["name"], "balance": v["balance"]} for k, v in accounts.items()}}

    return {"state": -1, "reason": "UNKNOWN_ACTION"}


class BankHandler(BaseHTTPRequestHandler):
    bank_accounts = None
    bank_lock = None
    bank_log = None
    bank_name = ""

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"state": 1, "service": self.bank_name}).encode())

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        action = body.get("action", "")
        resp = _process_bank_action(self.bank_accounts, self.bank_lock, self.bank_log, action, body)
        raw = json.dumps(resp).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):
        pass


def _make_handler(accounts, lock, log_list, name):
    class Handler(BankHandler):
        bank_accounts = accounts
        bank_lock = lock
        bank_log = log_list
        bank_name = name
    return Handler


def start_bank_simulators():
    import socket
    handler_a = _make_handler(bank_a_accounts, bank_a_lock, bank_a_log, "Bharatiya Gramin Bank")
    handler_b = _make_handler(bank_b_accounts, bank_b_lock, bank_b_log, "Rashtriya Vyapar Bank")

    for port in [6001, 6002]:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(("0.0.0.0", port))
        except OSError:
            sock.close()
            continue
        sock.close()

    try:
        server_a = HTTPServer(("0.0.0.0", 6001), handler_a)
        t_a = threading.Thread(target=server_a.serve_forever, daemon=True)
        t_a.start()
        print("[AtomicPay] Bank A simulator running on port 6001")
    except OSError:
        print("[AtomicPay] Bank A simulator port 6001 already in use, reusing existing")

    try:
        server_b = HTTPServer(("0.0.0.0", 6002), handler_b)
        t_b = threading.Thread(target=server_b.serve_forever, daemon=True)
        t_b.start()
        print("[AtomicPay] Bank B simulator running on port 6002")
    except OSError:
        print("[AtomicPay] Bank B simulator port 6002 already in use, reusing existing")


async def call_bank(url: str, payload: dict) -> dict:
    try:
        async with httpx.AsyncClient(timeout=GATEWAY_TIMEOUT) as client:
            r = await client.post(url, json=payload)
            return r.json()
    except Exception:
        return {"state": -1, "reason": "BANK_UNREACHABLE"}


async def ping_bank(url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=1.0) as client:
            r = await client.get(url)
            return r.status_code == 200
    except Exception:
        return False


async def verify_account(bank_id: str, account_id: str):
    bank = AVAILABLE_BANKS.get(bank_id)
    if not bank:
        return False, "BANK_NOT_FOUND"
    r = await call_bank(bank["url"], {"action": "STATUS", "account_id": account_id})
    if r.get("state") == 1:
        return True, r.get("name", account_id)
    return False, r.get("reason", "ACCOUNT_NOT_FOUND")


async def get_bank_balance(bank_id: str, account_id: str):
    bank = AVAILABLE_BANKS.get(bank_id)
    if not bank:
        return None
    r = await call_bank(bank["url"], {"action": "STATUS", "account_id": account_id})
    if r.get("state") == 1:
        return r.get("balance")
    return None


def get_bank_logs(bank_id: str):
    if bank_id == "bank_a":
        return list(bank_a_log)
    elif bank_id == "bank_b":
        return list(bank_b_log)
    return []


def get_all_bank_accounts():
    result = {}
    with bank_a_lock:
        result["bank_a"] = {k: {"name": v["name"], "balance": v["balance"], "active": v["active"]} for k, v in bank_a_accounts.items()}
    with bank_b_lock:
        result["bank_b"] = {k: {"name": v["name"], "balance": v["balance"], "active": v["active"]} for k, v in bank_b_accounts.items()}
    return result
