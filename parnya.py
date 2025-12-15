import time, hmac, hashlib, threading, requests, psutil, os
from flask import Flask, jsonify
from collections import deque
from datetime import datetime, timedelta

# =================================================
# CONFIG
# =================================================
API_KEY = os.getenv("COINEX_API_KEY")
API_SECRET = os.getenv("COINEX_API_SECRET")
if not API_KEY or not API_SECRET:
    raise RuntimeError("COINEX_API_KEY / COINEX_API_SECRET not set")

BASE_URL = "https://api.coinex.com/v2/futures"
SPOT_URL = "https://api.coinex.com/v1/market"

SYMBOL = "BTCUSDT"
LEVERAGE = 10
POSITION_SIZE_PERCENT = 0.25
SL_CORE = 0.006

SIGNAL_HISTORY_DAYS = 5
signal_history = deque()

# =================================================
# FLASK
# =================================================
app = Flask(__name__)

state = {
    "loop_running": False,
    "position": None,
    "confidence": 0.0,
    "trade": {"type": None, "tp_index": 0, "sl_set": False},
    "entry_lock": False,
    "snap": {"long_used": False, "short_used": False, "last_reset_day": None}
}

# =================================================
# SIGNAL LOGGER
# =================================================
def log_signal(signal_type, side=None, price=None, confidence=None):
    signal_history.append({
        "time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "signal": signal_type,
        "side": side,
        "price": price,
        "confidence": confidence
    })

    cutoff = datetime.utcnow() - timedelta(days=SIGNAL_HISTORY_DAYS)
    while signal_history:
        t = datetime.strptime(signal_history[0]["time"], "%Y-%m-%d %H:%M:%S")
        if t < cutoff:
            signal_history.popleft()
        else:
            break

# =================================================
# AUTH
# =================================================
def sign(p):
    q = "&".join(f"{k}={v}" for k, v in p.items())
    return hmac.new(API_SECRET.encode(), q.encode(), hashlib.sha256).hexdigest()

# =================================================
# BASIC API
# =================================================
def set_leverage():
    p = {
        "market": SYMBOL,
        "leverage": LEVERAGE,
        "timestamp": int(time.time() * 1000)
    }
    p["signature"] = sign(p)
    requests.post(f"{BASE_URL}/position/adjust-leverage", data=p)

def get_price():
    r = requests.get(f"{BASE_URL}/market/ticker", params={"market": SYMBOL}).json()
    return float(r["data"]["ticker"]["last"])

def get_balance():
    p = {"asset": "USDT", "timestamp": int(time.time() * 1000)}
    p["signature"] = sign(p)
    r = requests.get(f"{BASE_URL}/asset/query", params=p).json()
    return float(r["data"]["available"])

def get_klines(tf, limit=300):
    r = requests.get(
        f"{BASE_URL}/market/kline",
        params={"market": SYMBOL, "type": tf, "limit": limit}
    ).json()
    return [float(c[2]) for c in r.get("data", [])]

# =================================================
# INDICATORS
# =================================================
def ema(data, n):
    if len(data) < n:
        return None
    k = 2 / (n + 1)
    e = sum(data[:n]) / n
    for v in data[n:]:
        e = v * k + e * (1 - k)
    return e

def rsi(data, n=14):
    if len(data) < n + 1:
        return 50
    gains, losses = [], []
    for i in range(1, len(data)):
        d = data[i] - data[i-1]
        gains.append(max(d, 0))
        losses.append(abs(min(d, 0)))

    avg_gain = sum(gains[:n]) / n
    avg_loss = sum(losses[:n]) / n

    for i in range(n, len(gains)):
        avg_gain = (avg_gain*(n-1) + gains[i]) / n
        avg_loss = (avg_loss*(n-1) + losses[i]) / n

    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

# =================================================
# STRATEGY
# =================================================
def core_strategy():
    m15 = get_klines("15min")
    h1 = get_klines("1hour")

    ema50 = ema(m15, 50)
    ema200 = ema(h1, 200)
    r = rsi(m15)

    if not ema50 or not ema200:
        return None, 0.0

    last = m15[-1]

    if last > ema50 and h1[-1] > ema200 and r < 70:
        return "long", 0.8

    if last < ema50 and h1[-1] < ema200 and r > 30:
        return "short", 0.8

    return None, 0.0

# =================================================
# ORDERS
# =================================================
def open_order(side, amount, reduce_only=False):
    p = {
        "market": SYMBOL,
        "side": side,
        "type": "market",
        "amount": amount,
        "reduce_only": reduce_only,
        "timestamp": int(time.time() * 1000),
    }
    p["signature"] = sign(p)
    requests.post(f"{BASE_URL}/order/put", data=p)

def get_position():
    p = {"market": SYMBOL, "timestamp": int(time.time() * 1000)}
    p["signature"] = sign(p)
    r = requests.get(f"{BASE_URL}/position/list", params=p).json()
    for x in r.get("data", []):
        if float(x["amount"]) != 0:
            return {
                "side": x["side"],
                "amount": float(x["amount"]),
                "entry": float(x["avg_entry_price"]),
                "pid": x["position_id"],
            }
    return None

def set_sl(pid, price):
    p = {
        "market": SYMBOL,
        "position_id": pid,
        "stop_loss_price": round(price, 2),
        "timestamp": int(time.time()*1000)
    }
    p["signature"] = sign(p)
    requests.post(f"{BASE_URL}/position/set-stop-loss", data=p)

# =================================================
# TRADE MANAGEMENT
# =================================================
TP_CORE = [{"p":0.004,"c":0.4},{"p":0.008,"c":0.3},{"p":0.012,"c":0.3}]

def set_initial_sl(pos):
    if pos["side"] == "buy":
        sl = pos["entry"] * (1 - SL_CORE)
    else:
        sl = pos["entry"] * (1 + SL_CORE)
    set_sl(pos["pid"], sl)

def manage_trade(price):
    pos = get_position()
    if not pos:
        return

    i = state["trade"]["tp_index"]
    if i >= len(TP_CORE):
        return

    entry = pos["entry"]
    side = pos["side"]
    t = TP_CORE[i]

    target = entry*(1+t["p"]) if side=="buy" else entry*(1-t["p"])
    hit = price >= target if side=="buy" else price <= target
    if not hit:
        return

    amt = max(round(pos["amount"] * t["c"], 3), 0.001)
    open_order("sell" if side=="buy" else "buy", amt, reduce_only=True)

    if i == 0:
        set_sl(pos["pid"], entry)

    state["trade"]["tp_index"] += 1

# =================================================
# MAIN LOOP
# =================================================
def trading_loop():
    print("BOT STARTED")
    state["loop_running"] = True
    set_leverage()

    while True:
        try:
            price = get_price()
            balance = get_balance()
            pos = get_position()

            if not pos:
                state["trade"] = {"type": None, "tp_index": 0, "sl_set": False}
                state["entry_lock"] = False

            direction, conf = core_strategy()
            state["confidence"] = conf

            if not pos:
                log_signal("NONE", confidence=conf)

            if not pos and direction and conf >= 0.7 and not state["entry_lock"]:
                state["entry_lock"] = True
                value = balance * POSITION_SIZE_PERCENT * LEVERAGE
                amount = max(round(value / price, 3), 0.001)
                open_order("buy" if direction=="long" else "sell", amount)

                log_signal("ENTRY", side=direction.upper(), price=price, confidence=conf)
                state["trade"]["type"] = "core"

                time.sleep(1)
                if not get_position():
                    state["entry_lock"] = False

            pos = get_position()
            if pos and not state["trade"]["sl_set"]:
                set_initial_sl(pos)
                state["trade"]["sl_set"] = True

            if pos:
                manage_trade(price)

            time.sleep(3)

        except Exception as e:
            print("ERROR:", e)
            state["entry_lock"] = False
            time.sleep(5)

# =================================================
# ROUTES
# =================================================
@app.get("/status")
def status():
    return jsonify({
        "running": state["loop_running"],
        "confidence": state["confidence"],
        "cpu": psutil.cpu_percent(),
        "ram": psutil.virtual_memory().percent
    })

@app.get("/signal")
def signal():
    pos = get_position()
    if not pos:
        return {"signal": "NONE", "time": time.strftime("%Y-%m-%d %H:%M")}
    return {
        "signal": "ACTIVE",
        "side": pos["side"],
        "entry": round(pos["entry"], 2),
        "amount": pos["amount"],
        "time": time.strftime("%Y-%m-%d %H:%M")
    }

@app.get("/signals")
def signals():
    return {
        "days": SIGNAL_HISTORY_DAYS,
        "count": len(signal_history),
        "signals": list(signal_history)
    }

# =================================================
# START
# =================================================
if __name__ == "__main__":
    threading.Thread(target=trading_loop, daemon=True).start()
    app.run("0.0.0.0", 5000)

