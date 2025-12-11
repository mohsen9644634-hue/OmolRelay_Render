import time
import hmac
import hashlib
import requests
import threading
from flask import Flask, jsonify, request

# -----------------------------------------
#   FUTURES REAL SETTINGS
# -----------------------------------------
API_KEY = "YOUR_KEY"
API_SECRET = "YOUR_SECRET"
BASE_URL = "https://api.coinex.com/v2/futures"

SYMBOL = "BTCUSDT"
LEVERAGE = 20
POSITION_SIZE_USDT = 50

# -----------------------------------------
#   FLASK APP
# -----------------------------------------
app = Flask(__name__)

state = {
    "position": None,
    "entry_price": None,
    "tp_levels": [],
    "sl_levels": [],
    "breakeven": False,
    "trailing": False,
    "mtf": {"m5": None, "m15": None, "h1": None},
    "confidence": 0,
}

# -----------------------------------------
#   SIGN
# -----------------------------------------
def sign(payload: dict):
    query = "&".join([f"{k}={v}" for k, v in payload.items()])
    signature = hmac.new(API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
    return signature

# -----------------------------------------
#   GET PRICE
# -----------------------------------------
def get_price():
    try:
        r = requests.get(f"{BASE_URL}/market/ticker", params={"market": SYMBOL}, timeout=5)
        return float(r.json()["data"]["ticker"]["last"])
    except:
        return None

# -----------------------------------------
#   GET KLINES
# -----------------------------------------
def get_klines(tf="5m", limit=100):
    try:
        r = requests.get(
            "https://api.coinex.com/v1/market/kline",
            params={"market": SYMBOL, "period": tf, "limit": limit},
            timeout=7
        )
        return r.json()["data"]
    except:
        return []

def sma(data, length):
    if len(data) < length:
        return None
    return sum(data[-length:]) / length

def analyze_trend(candles):
    closes = [float(c["close"]) for c in candles]
    ma20 = sma(closes, 20)
    ma50 = sma(closes, 50)
    if not ma20 or not ma50: return None
    return "up" if ma20 > ma50 else "down" if ma20 < ma50 else None

# -----------------------------------------
#   FETCH MTF
# -----------------------------------------
def fetch_mtf():
    try:
        m5 = analyze_trend(get_klines("5min"))
        m15 = analyze_trend(get_klines("15min"))
        h1 = analyze_trend(get_klines("1hour"))
        state["mtf"] = {"m5": m5, "m15": m15, "h1": h1}
        return m5, m15, h1
    except:
        return None, None, None

# -----------------------------------------
#   LEVERAGE
# -----------------------------------------
def set_leverage():
    payload = {"market": SYMBOL, "leverage": LEVERAGE, "position_type": "isolated"}
    payload["timestamp"] = int(time.time()*1000)
    payload["signature"] = sign(payload)
    try:
        requests.post(f"{BASE_URL}/position/set-leverage", data=payload, timeout=5)
    except:
        pass

# -----------------------------------------
#   OPEN / CLOSE ORDERS
# -----------------------------------------
def open_long(amount):
    payload = {"market": SYMBOL, "side": "buy", "type": "market", "amount": amount}
    payload["timestamp"] = int(time.time()*1000)
    payload["signature"] = sign(payload)
    try:
        return requests.post(f"{BASE_URL}/order/put", data=payload, timeout=5).json()
    except:
        return None

def open_short(amount):
    payload = {"market": SYMBOL, "side": "sell", "type": "market", "amount": amount}
    payload["timestamp"] = int(time.time()*1000)
    payload["signature"] = sign(payload)
    try:
        return requests.post(f"{BASE_URL}/order/put", data=payload, timeout=5).json()
    except:
        return None

def close_position(side, amount):
    payload = {"market": SYMBOL, "side": side, "type": "market", "amount": amount}
    payload["timestamp"] = int(time.time()*1000)
    payload["signature"] = sign(payload)
    try:
        return requests.post(f"{BASE_URL}/order/put", data=payload, timeout=5).json()
    except:
        return None

# -----------------------------------------
#   SET REAL SL/TP
# -----------------------------------------
def set_sl_tp(pid, sl, tp):
    payload = {
        "market": SYMBOL,
        "position_id": pid,
        "stop_loss_price": sl,
        "take_profit_price": tp,
    }
    payload["timestamp"] = int(time.time()*1000)
    payload["signature"] = sign(payload)
    try:
        requests.post(f"{BASE_URL}/position/set-stop-loss-take-profit", data=payload, timeout=5)
    except:
        pass

# -----------------------------------------
#   GET POSITION
# -----------------------------------------
def get_position():
    payload = {"market": SYMBOL}
    payload["timestamp"] = int(time.time()*1000)
    payload["signature"] = sign(payload)
    try:
        data = requests.get(f"{BASE_URL}/position/list", params=payload, timeout=5).json()["data"]
        return data[0] if len(data) else None
    except:
        return None
# -----------------------------------------
#   MULTI TP / SL CONFIG
# -----------------------------------------
TP_STEPS = [
    {"profit": 0.004, "close": 0.40},  # TP1
    {"profit": 0.008, "close": 0.30},  # TP2
    {"profit": 0.012, "close": 0.30},  # TP3
]

SL_LEVEL = 0.006  # SL پایه

# -----------------------------------------
#   CONFIDENCE
# -----------------------------------------
def compute_confidence():
    m5, m15, h1 = fetch_mtf()
    score = 0
    for tf in [m5, m15, h1]:
        if tf == "up": score += 1
        if tf == "down": score -= 1
    conf = abs(score)/3
    state["confidence"] = round(conf, 2)
    if score > 0: return "long", conf
    if score < 0: return "short", conf
    return None, 0

def required_confidence(m5, m15, h1):
    up = [m5, m15, h1].count("up")
    dn = [m5, m15, h1].count("down")
    if up == 3 or dn == 3: return 0.50
    if up == 2 or dn == 2: return 0.60
    return 0.75

# -----------------------------------------
#   TRADING LOOP
# -----------------------------------------
def trading_loop():
    print("BOT STARTED")

    while True:
        try:
            direction, conf = compute_confidence()
            m5 = state["mtf"]["m5"]
            m15 = state["mtf"]["m15"]
            h1 = state["mtf"]["h1"]
            req = required_confidence(m5, m15, h1)

            price = get_price()
            pos = get_position()

            # --------------------------------- NO POSITION
            if pos is None:
                if direction and conf >= req*0.7:
                    amount = POSITION_SIZE_USDT / price

                    if direction == "long":
                        open_long(amount)
                        state["position"] = "long"
                    else:
                        open_short(amount)
                        state["position"] = "short"

                    time.sleep(2)
                    pos = get_position()
                    if not pos:
                        time.sleep(3)
                        continue

                    entry = float(pos["entry_price"])
                    pid = pos["position_id"]

                    sl = entry * (1 - SL_LEVEL) if direction=="long" else entry*(1+SL_LEVEL)
                    tp = entry * (1 + TP_STEPS[0]["profit"]) if direction=="long" else entry*(1-TP_STEPS[0]["profit"])

                    set_sl_tp(pid, sl, tp)

                    state["entry_price"] = entry
                    state["tp_level"] = 0
                    state["breakeven"] = False
                    state["trailing"] = False

                time.sleep(3)
                continue

            # --------------------------------- POSITION ALREADY OPEN
            entry = float(pos["entry_price"])
            amount = float(pos["amount"])
            pid = pos["position_id"]

            # ---------- REVERSE SIGNAL
            if state["position"] == "long" and direction=="short" and conf>=req:
                close_position("sell", amount)
                open_short(POSITION_SIZE_USDT/price)
                time.sleep(2)
                continue

            if state["position"] == "short" and direction=="long" and conf>=req:
                close_position("buy", amount)
                open_long(POSITION_SIZE_USDT/price)
                time.sleep(2)
                continue

            # ---------- MULTI TP
            for i, step in enumerate(TP_STEPS):
                if i < state.get("tp_level", 0):
                    continue

                target = entry*(1+step["profit"]) if state["position"]=="long" else entry*(1-step["profit"])

                if (state["position"]=="long" and price>=target) or (state["position"]=="short" and price<=target):
                    close_amount = amount * step["close"]
                    close_position("sell" if state["position"]=="long" else "buy", close_amount)

                    state["tp_level"] = i+1

                    # ---------- BREAKEVEN
                    if not state["breakeven"]:
                        be = entry
                        set_sl_tp(pid, be, pos["take_profit_price"])
                        state["breakeven"] = True

                    # ---------- TRAILING
                    if i == 0:
                        state["trailing"] = True

            # ---------- TRAILING STOP
            if state["trailing"]:
                trail_dist = 0.004
                new_sl = price*(1-trail_dist) if state["position"]=="long" else price*(1+trail_dist)
                set_sl_tp(pid, new_sl, pos["take_profit_price"])

            time.sleep(2)

        except Exception as e:
            print("ERR:", e)
            time.sleep(4)
# -----------------------------------------
#   ROUTES
# -----------------------------------------
@app.get("/")
def home():
    return jsonify(state)

@app.get("/test-tf")
def test_tf():
    return jsonify({
        "m5": analyze_trend(get_klines("5min")),
        "m15": analyze_trend(get_klines("15min")),
        "h1": analyze_trend(get_klines("1hour"))
    })

@app.get("/force-close")
def force_close():
    pos = get_position()
    if pos:
        side = "sell" if pos["side"]=="long" else "buy"
        close_position(side, pos["amount"])
        return "closed"
    return "no position"

# -----------------------------------------
#   START BOT
# -----------------------------------------
def start_bot():
    t = threading.Thread(target=trading_loop)
    t.daemon = True
    t.start()

if __name__ == "__main__":
    set_leverage()
    start_bot()
    app.run(host="0.0.0.0", port=5000)
