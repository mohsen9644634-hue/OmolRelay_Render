import time
import hmac
import hashlib
import threading
import requests
import psutil
from flask import Flask, jsonify

# =================================================
# CONFIG
# =================================================
API_KEY = "YOUR_KEY"
API_SECRET = "YOUR_SECRET"
BASE_URL = "https://api.coinex.com/v2/futures"

SYMBOL = "BTCUSDT"
LEVERAGE = 10
POSITION_SIZE_PERCENT = 0.8

# =================================================
# FLASK
# =================================================
app = Flask(__name__)

state = {
    "loop_running": False,
    "position": None,
    "entry_price": None,
    "confidence": 0.0,
    "mtf": {"m5": None, "m15": None, "h1": None},
    "trade": {
        "type": None,  # core / snap
        "tp_index": 0
    },
    "snap": {
        "long_used": False,
        "short_used": False,
        "last_reset_day": None
    }
}

# =================================================
# AUTH
# =================================================
def sign(payload: dict):
    query = "&".join(f"{k}={v}" for k, v in payload.items())
    return hmac.new(API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()

# =================================================
# MARKET DATA
# =================================================
def get_price():
    try:
        r = requests.get(
            f"{BASE_URL}/market/ticker",
            params={"market": SYMBOL},
            timeout=5
        ).json()
        return float(r["data"]["ticker"]["last"])
    except:
        return None


def get_balance():
    try:
        payload = {"asset": "USDT", "timestamp": int(time.time() * 1000)}
        payload["signature"] = sign(payload)
        r = requests.get(f"{BASE_URL}/asset/query", params=payload, timeout=5).json()
        return float(r["data"]["available"])
    except:
        return 0.0


def get_klines(tf, limit=100):
    try:
        r = requests.get(
            "https://api.coinex.com/v1/market/kline",
            params={"market": SYMBOL, "type": tf, "limit": limit},
            timeout=5
        ).json()
        return r.get("data", [])
    except:
        return []


def sma(arr, n):
    if len(arr) < n:
        return None
    return sum(arr[-n:]) / n


def analyze_trend(tf):
    data = get_klines(tf)
    closes = [float(c[2]) for c in data]
    ma20 = sma(closes, 20)
    ma50 = sma(closes, 50)
    if ma20 is None or ma50 is None:
        return None
    return "up" if ma20 > ma50 else "down"


def fetch_mtf():
    state["mtf"]["m5"] = analyze_trend("5min")
    state["mtf"]["m15"] = analyze_trend("15min")
    state["mtf"]["h1"] = analyze_trend("1hour")
    return state["mtf"]["m5"], state["mtf"]["m15"], state["mtf"]["h1"]

# =================================================
# SIGNAL LOGIC
# =================================================
def compute_confidence(m5, m15, h1):  # FIXED: no duplicate fetch
    direction = None
    confidence = 0.0

    if h1 == "up" and m15 == "up" and m5 == "up":
        direction = "long"
        confidence = 0.8

    elif h1 == "down" and m15 == "down" and m5 == "down":
        direction = "short"
        confidence = 0.8

    state["confidence"] = confidence
    return direction, confidence


def snap_signal(m15, h1):
    if h1 == "up" and m15 == "up" and not state["snap"]["long_used"]:
        return "long"
    if h1 == "down" and m15 == "down" and not state["snap"]["short_used"]:
        return "short"
    return None


def reset_snap_daily():
    today = time.strftime("%Y-%m-%d")
    if state["snap"]["last_reset_day"] != today:
        state["snap"] = {
            "long_used": False,
            "short_used": False,
            "last_reset_day": today
        }

# =================================================
# TRADE PLAN
# =================================================
TP_CORE = [
    {"p": 0.004, "close": 0.4},
    {"p": 0.008, "close": 0.3},
    {"p": 0.012, "close": 0.3},
]

TP_SNAP = [
    {"p": 0.003, "close": 0.5},
    {"p": 0.006, "close": 0.5},
]

SL_CORE = 0.006
SL_SNAP = 0.004

# =================================================
# ORDERS
# =================================================
def open_order(side, amount):
    payload = {
        "market": SYMBOL,
        "side": side,
        "type": "market",
        "amount": amount,
        "timestamp": int(time.time() * 1000),
    }
    payload["signature"] = sign(payload)
    return requests.post(f"{BASE_URL}/order/put", data=payload).json()


def get_position():
    payload = {"market": SYMBOL, "timestamp": int(time.time() * 1000)}
    payload["signature"] = sign(payload)
    try:
        r = requests.get(f"{BASE_URL}/position/list", params=payload).json()
        for p in r.get("data", []):  # FIXED: safe check
            if float(p["amount"]) != 0:
                return {
                    "side": p["side"],
                    "amount": float(p["amount"]),
                    "entry": float(p["avg_entry_price"]),
                    "pid": p["position_id"],
                }
        return None
    except:
        return None


def set_sl(pid, entry, side):  # FIXED
    payload = {
        "market": SYMBOL,
        "position_id": pid,
        "stop_loss_price": round(entry, 2),
        "timestamp": int(time.time() * 1000),
    }
    payload["signature"] = sign(payload)
    requests.post(f"{BASE_URL}/position/set-stop-loss", data=payload)

# =================================================
# TP MANAGEMENT
# =================================================
def manage_trade(price, pos):
    plan = TP_CORE if state["trade"]["type"] == "core" else TP_SNAP
    i = state["trade"]["tp_index"]
    if i >= len(plan):
        return

    entry = pos["entry"]
    side = pos["side"]

    target = entry * (1 + plan[i]["p"]) if side == "buy" else entry * (1 - plan[i]["p"])
    hit = price >= target if side == "buy" else price <= target
    if not hit:
        return

    close_amt = round(pos["amount"] * plan[i]["close"], 3)
    open_order("sell" if side == "buy" else "buy", close_amt)
    state["trade"]["tp_index"] += 1

    if i == 0:
        set_sl(pos["pid"], entry, side)  # FIXED: BE correctly

# =================================================
# MAIN LOOP
# =================================================
def trading_loop():
    print("BOT STARTED")
    state["loop_running"] = True

    while True:
        try:
            reset_snap_daily()

            price = get_price()
            pos = get_position()
            balance = get_balance()

            # RESET STATE AFTER FULL CLOSE
            if not pos and state["trade"]["type"]:
                state["trade"] = {"type": None, "tp_index": 0}  # FIXED

            m5, m15, h1 = fetch_mtf()
            direction, conf = compute_confidence(m5, m15, h1)

            entered = False  # FIXED: prevent double entry

            # SNAP ENTRY
            snap_dir = snap_signal(m15, h1)
            if not pos and snap_dir and not entered:
                value = balance * POSITION_SIZE_PERCENT * LEVERAGE * 0.5
                amount = round(value / price, 3)
                open_order("buy" if snap_dir == "long" else "sell", amount)

                pos = get_position()
                if pos:
                    sl = pos["entry"] * (1 - SL_SNAP) if pos["side"] == "buy" else pos["entry"] * (1 + SL_SNAP)
                    set_sl(pos["pid"], sl, pos["side"])  # FIXED

                state["trade"] = {"type": "snap", "tp_index": 0}
                state["snap"]["long_used"] |= snap_dir == "long"
                state["snap"]["short_used"] |= snap_dir == "short"
                entered = True

            # CORE ENTRY
            if not pos and direction and conf >= 0.8 and not entered:
                value = balance * POSITION_SIZE_PERCENT * LEVERAGE
                amount = round(value / price, 3)
                open_order("buy" if direction == "long" else "sell", amount)
                state["trade"] = {"type": "core", "tp_index": 0}

            # MANAGE TRADE
            pos = get_position()
            if pos:
                manage_trade(price, pos)

            time.sleep(3)

        except Exception as e:
            print("ERROR:", e)
            time.sleep(5)

# =================================================
# ROUTES
# =================================================
@app.get("/status")
def status():
    return jsonify({
        "loop": "active" if state["loop_running"] else "stopped",
        "mtf": state["mtf"],
        "confidence": state["confidence"],
        "snap": state["snap"],
        "cpu": psutil.cpu_percent(),
        "memory": psutil.virtual_memory().percent
    })


@app.get("/health")
def health():
    return "OK"

# =================================================
# START
# =================================================
if __name__ == "__main__":
    threading.Thread(target=trading_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=5000)
