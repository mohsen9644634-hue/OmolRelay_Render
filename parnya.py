import time
import hmac
import hashlib
import requests
import threading
from flask import Flask, jsonify, request

# -----------------------------------------
#   FUTURES REAL MODE SETTINGS
# -----------------------------------------
API_KEY = "YOUR_KEY"
API_SECRET = "YOUR_SECRET"
BASE_URL = "https://api.coinex.com/v2/futures"

SYMBOL = "BTCUSDT"
LEVERAGE = 20
POSITION_SIZE_USDT = 50   # مقدار پوزیشن

# -----------------------------------------
#  FLASK APP + SHARED STATE
# -----------------------------------------
app = Flask(__name__)

state = {
    "position": None,
    "entry_price": None,
    "sl": None,
    "tp": None,
    "confidence": 0,
    "status": "idle",
    "last_signal": None,
    "mtf": {"m5": None, "m15": None, "h1": None}
}

# -----------------------------------------
#   AUTH SIGNING FOR FUTURES
# -----------------------------------------
def sign(payload: dict):
    query = "&".join([f"{k}={v}" for k, v in payload.items()])
    signature = hmac.new(
        API_SECRET.encode(),
        query.encode(),
        hashlib.sha256
    ).hexdigest()
    return signature

# -----------------------------------------
#  BASIC FUTURES GET PRICE
# -----------------------------------------
def get_price():
    try:
        url = f"{BASE_URL}/market/ticker"
        r = requests.get(url, params={"market": SYMBOL}, timeout=5)
        p = r.json()["data"]["ticker"]["last"]
        return float(p)
    except:
        return None

# -----------------------------------------
#  FETCH CANDLES  (FIXED)
# -----------------------------------------
def get_klines(timeframe="5m", limit=100):
    try:
        r = requests.get(
            "https://api.coinex.com/v1/market/kline",   # FIX 1
            params={"market": SYMBOL, "period": timeframe, "limit": limit},
            timeout=7
        )
        return r.json()["data"]
    except:
        return []

# -----------------------------------------
import time
import hmac
import hashlib
import requests
import threading
from flask import Flask, jsonify, request

# -----------------------------------------
#   FUTURES REAL MODE SETTINGS
# -----------------------------------------
API_KEY = "YOUR_KEY"
API_SECRET = "YOUR_SECRET"
BASE_URL = "https://api.coinex.com/v2/futures"

SYMBOL = "BTCUSDT"
LEVERAGE = 20
POSITION_SIZE_USDT = 50   # مقدار پوزیشن

# -----------------------------------------
#  FLASK APP + SHARED STATE
# -----------------------------------------
app = Flask(__name__)

state = {
    "position": None,
    "entry_price": None,
    "sl": None,
    "tp": None,
    "confidence": 0,
    "status": "idle",
    "last_signal": None,
    "mtf": {"m5": None, "m15": None, "h1": None}
}

# -----------------------------------------
#   AUTH SIGNING FOR FUTURES
# -----------------------------------------
def sign(payload: dict):
    query = "&".join([f"{k}={v}" for k, v in payload.items()])
    signature = hmac.new(
        API_SECRET.encode(),
        query.encode(),
        hashlib.sha256
    ).hexdigest()
    return signature

# -----------------------------------------
#  BASIC FUTURES GET PRICE
# -----------------------------------------
def get_price():
    try:
        url = f"{BASE_URL}/market/ticker"
        r = requests.get(url, params={"market": SYMBOL}, timeout=5)
        p = r.json()["data"]["ticker"]["last"]
        return float(p)
    except:
        return None

# -----------------------------------------
#  FETCH CANDLES  (FIXED)
# -----------------------------------------
def get_klines(timeframe="5m", limit=100):
    try:
        r = requests.get(
            "https://api.coinex.com/v1/market/kline",   # FIX 1
            params={"market": SYMBOL, "period": timeframe, "limit": limit},
            timeout=7
        )
        return r.json()["data"]
    except:
        return []

# -----------------------------------------
#   SIMPLE INDICATOR CALC
# -----------------------------------------
def sma(data, length):
    if len(data) < length:
        return None
    return sum(data[-length:]) / length

def analyze_trend(candles):
    closes = [float(c["close"]) for c in candles]
    ma20 = sma(closes, 20)
    ma50 = sma(closes, 50)

    if not ma20 or not ma50:
        return None

    if ma20 > ma50:
        return "up"
    elif ma20 < ma50:
        return "down"
    return None

# -----------------------------------------
#   MTF FETCHER BASE  (FIXED)
# -----------------------------------------
def fetch_mtf():
    try:
        m5 = analyze_trend(get_klines("5m"))
        m15 = analyze_trend(get_klines("15m"))
        h1 = analyze_trend(get_klines("1hour"))   # FIX 2

        state["mtf"] = {"m5": m5, "m15": m15, "h1": h1}
        return m5, m15, h1
    except:
        return None, None, None

# -----------------------------------------
#   SET LEVERAGE (REAL FUTURES)
# -----------------------------------------
def set_leverage():
    payload = {
        "market": SYMBOL,
        "leverage": LEVERAGE,
        "position_type": "isolated",
    }
    payload["timestamp"] = int(time.time() * 1000)
    payload["signature"] = sign(payload)

    try:
        url = f"{BASE_URL}/position/set-leverage"
        r = requests.post(url, data=payload, timeout=7)
        return True
    except:
        return False

# -----------------------------------------
#   OPEN LONG
# -----------------------------------------
def open_long(amount):
    payload = {
        "market": SYMBOL,
        "side": "buy",
        "type": "market",
        "amount": amount,
    }
    payload["timestamp"] = int(time.time() * 1000)
    payload["signature"] = sign(payload)

    try:
        r = requests.post(f"{BASE_URL}/order/put", data=payload, timeout=7)
        return r.json()
    except:
        return None

# -----------------------------------------
#   OPEN SHORT
# -----------------------------------------
def open_short(amount):
    payload = {
        "market": SYMBOL,
        "side": "sell",
        "type": "market",
        "amount": amount,
    }
    payload["timestamp"] = int(time.time() * 1000)
    payload["signature"] = sign(payload)

    try:
        r = requests.post(f"{BASE_URL}/order/put", data=payload, timeout=7)
        return r.json()
    except:
        return None

# -----------------------------------------
#   CLOSE POSITION
# -----------------------------------------
def close_position(side, amount):
    payload = {
        "market": SYMBOL,
        "side": side,
        "type": "market",
        "amount": amount,
    }
    payload["timestamp"] = int(time.time() * 1000)
    payload["signature"] = sign(payload)

    try:
        r = requests.post(f"{BASE_URL}/order/put", data=payload, timeout=7)
        return r.json()
    except:
        return None

# -----------------------------------------
#   SET REAL STOP LOSS & TAKE PROFIT
# -----------------------------------------
def set_sl_tp(position_id, sl_price, tp_price):

    payload = {
        "market": SYMBOL,
        "position_id": position_id,
        "stop_loss_price": sl_price,
        "take_profit_price": tp_price,
    }
    payload["timestamp"] = int(time.time() * 1000)
    payload["signature"] = sign(payload)

    try:
        r = requests.post(f"{BASE_URL}/position/set-stop-loss-take-profit", data=payload, timeout=7)
        return True
    except:
        return False

# -----------------------------------------
#   GET CURRENT POSITION INFO (REAL)
# -----------------------------------------
def get_position():
    payload = {"market": SYMBOL}
    payload["timestamp"] = int(time.time() * 1000)
    payload["signature"] = sign(payload)

    try:
        r = requests.get(f"{BASE_URL}/position/list", params=payload, timeout=7)
        data = r.json()["data"]
        if len(data) > 0:
            return data[0]
        return None
    except:
        return None

# -----------------------------------------
#  SMART-DYNAMIC AI SIGNAL SYSTEM
# -----------------------------------------
def compute_confidence():
    m5, m15, h1 = fetch_mtf()

    score = 0
    if m5 == "up": score += 1
    if m15 == "up": score += 1
    if h1 == "up": score += 1

    if m5 == "down": score -= 1
    if m15 == "down": score -= 1
    if h1 == "down": score -= 1

    conf = abs(score) / 3
    state["confidence"] = round(conf, 2)

    if score > 0:
        return "long", conf
    elif score < 0:
        return "short", conf
    return None, 0

def required_confidence(m5, m15, h1):
    align = [m5, m15, h1]

    if align.count("up") == 3 or align.count("down") == 3:
        return 0.50

    if align.count("up") == 2 or align.count("down") == 2:
        return 0.60

    return 0.75

# -----------------------------------------
#  MAIN EXECUTION LOGIC
# -----------------------------------------
def trading_loop():
    print("Robot started...")

    while True:
        try:
            direction, conf = compute_confidence()

            m5, m15, h1 = state["mtf"]["m5"], state["mtf"]["m15"], state["mtf"]["h1"]
            req_conf = required_confidence(m5, m15, h1)

            price = get_price()
            pos = get_position()

            # -------------------------------------
            #  NO POSITION → check entry
            # -------------------------------------
            if pos is None:
                if direction and conf >= (req_conf * 0.7):   # FIX 3
                    amount = POSITION_SIZE_USDT / price

                    if direction == "long":
                        r = open_long(amount)
                        state["position"] = "long"
                    else:
                        r = open_short(amount)
                        state["position"] = "short"

                    state["entry_price"] = price

                    time.sleep(1)
                    pos = get_position()

                    if pos:
                        pid = pos["position_id"]
                        sl = price * 0.99 if direction == "long" else price * 1.01
                        tp = price * 1.02 if direction == "long" else price * 0.98
                        set_sl_tp(pid, sl, tp)

                time.sleep(3)
                continue

            # -------------------------------------
            #  HAVE POSITION → manage + reverse
            # -------------------------------------
            entry = float(pos["entry_price"])
            amount = float(pos["amount"])
            pid = pos["position_id"]

            if state["position"] == "long" and direction == "short" and conf >= req_conf:
                close_position("sell", amount)
                open_short(POSITION_SIZE_USDT / price)
                state["position"] = "short"
                state["entry_price"] = price
                time.sleep(2)
                continue

            if state["position"] == "short" and direction == "long" and conf >= req_conf:
                close_position("buy", amount)
                open_long(POSITION_SIZE_USDT / price)
                state["position"] = "long"
                state["entry_price"] = price
                time.sleep(2)
                continue

            if state["position"] == "long" and price >= entry * 1.003:
                set_sl_tp(pid, entry, pos["take_profit_price"])

            if state["position"] == "short" and price <= entry * 0.997:
                set_sl_tp(pid, entry, pos["take_profit_price"])

            if state["position"] == "long":
                new_tp = price * 0.995
                set_sl_tp(pid, pos["stop_loss_price"], new_tp)

            if state["position"] == "short":
                new_tp = price * 1.005
                set_sl_tp(pid, pos["stop_loss_price"], new_tp)

            time.sleep(3)

        except Exception as e:
            print("ERR LOOP:", e)
            time.sleep(5)

# -----------------------------------------
#       FLASK ROUTES
# -----------------------------------------
@app.get("/")
def home():
    return jsonify({
        "status": "running",
        "position": state["position"],
        "entry": state["entry_price"],
        "sl": state["sl"],
        "tp": state["tp"],
        "confidence": state["confidence"],
        "mtf": state["mtf"]
    })

@app.get("/force-close")
def force_close():
    pos = get_position()
    if pos:
        side = "sell" if pos["side"] == "long" else "buy"
        close_position(side, pos["amount"])
        state["position"] = None
        state["entry_price"] = None
        return "CLOSED"
    return "NO POSITION"

@app.get("/test")
def test():
    return "OK Bot Running"

# -----------------------------------------
#  START THREAD
# -----------------------------------------
def start_bot():
    t = threading.Thread(target=trading_loop)
    t.daemon = True
    t.start()

# -----------------------------------------
#  MAIN
# -----------------------------------------
if __name__ == "__main__":
    set_leverage()
    start_bot()
    app.run(host="0.0.0.0", port=5000)
