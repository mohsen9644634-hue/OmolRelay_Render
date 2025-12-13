import time, hmac, hashlib, threading, requests, psutil, os
from flask import Flask, jsonify

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
    "mtf": {"m15": None, "h1": None},
    "trade": {"type": None, "tp_index": 0},
    "snap": {"long_used": False, "short_used": False, "last_reset_day": None}
}

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

def get_klines(tf, limit=200):
    r = requests.get(
        f"{SPOT_URL}/kline",
        params={"market": SYMBOL, "type": tf, "limit": limit}
    ).json()
    return [float(c[2]) for c in r.get("data", [])]

# =================================================
# INDICATORS (NEW STRATEGY)
# =================================================
def ema(data, n):
    k = 2 / (n + 1)
    e = data[0]
    for v in data[1:]:
        e = v * k + e * (1 - k)
    return e

def rsi(data, n=14):
    g = l = 0
    for i in range(-n, 0):
        d = data[i] - data[i-1]
        g += max(d, 0)
        l += max(-d, 0)
    if l == 0:
        return 100
    rs = (g/n) / (l/n)
    return 100 - (100 / (1 + rs))

def core_strategy():
    m15 = get_klines("15min")
    h1 = get_klines("1hour")

    if len(m15) < 60 or len(h1) < 220:
        return None, 0.0

    ema50 = ema(m15, 50)
    ema200 = ema(h1, 200)
    r = rsi(m15)

    last = m15[-1]

    # ✅ LONG
    if last > ema50 > ema200 and r < 70:
        return "long", 0.8

    # ✅ SHORT
    if last < ema50 < ema200 and r > 30:
        return "short", 0.8

    return None, 0.0

# =================================================
# SNAP
# =================================================
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
SL_CORE = 0.006

def manage_trade(price, pos):
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

    amt = round(pos["amount"] * t["c"], 3)
    open_order("sell" if side=="buy" else "buy", amt, reduce_only=True)

    if i == 0:
        set_sl(pos["pid"], entry)  # ✅ BE

    state["trade"]["tp_index"] += 1

# =================================================
# MAIN LOOP
# =================================================
def trading_loop():
    print("BOT STARTED")
    state["loop_running"] = True
    set_leverage()  # ✅ REAL LEVERAGE

    while True:
        try:
            reset_snap_daily()

            price = get_price()
            balance = get_balance()
            pos = get_position()

            if not pos:
                state["trade"] = {"type": None, "tp_index": 0}

            direction, conf = core_strategy()
            state["confidence"] = conf

            if not pos and direction and conf >= 0.7:
                value = balance * POSITION_SIZE_PERCENT * LEVERAGE
                amount = round(value / price, 3)
                open_order("buy" if direction=="long" else "sell", amount)
                state["trade"]["type"] = "core"

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

# =================================================
# START
# =================================================
if __name__ == "__main__":
    threading.Thread(target=trading_loop, daemon=True).start()
    app.run("0.0.0.0", 5000)

