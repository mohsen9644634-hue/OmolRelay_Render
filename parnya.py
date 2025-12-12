import time
import psutil
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
LEVERAGE = 10
POSITION_SIZE_PERCENT = 0.80

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
    "peak": None,          # ADDED FOR PRO-TRAILING
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
#   CONTRACT SIZE (ADDED)
# -----------------------------------------
def get_contract_size():
    try:
        r = requests.get("https://api.coinex.com/v2/futures/market/list", timeout=5).json()
        for m in r["data"]:
            if m["market"] == SYMBOL:
                return float(m["contract_size"])
    except:
        pass
    return 0.001   # default BTC

CONTRACT_SIZE = get_contract_size()

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
#   GET BALANCE
# -----------------------------------------
def get_balance():
    payload = {"asset": "USDT"}
    payload["timestamp"] = int(time.time()*1000)
    payload["signature"] = sign(payload)
    try:
        r = requests.get(f"{BASE_URL}/asset/query", params=payload, timeout=5).json()
        return float(r["data"]["available"])
    except:
        return 0

# -----------------------------------------
#   GET KLINES (FIXED)
# -----------------------------------------
def get_klines(tf="5min", limit=100):
    try:
        r = requests.get(
            "https://api.coinex.com/v1/market/kline",
            params={"market": SYMBOL, "type": tf, "limit": limit},
            timeout=7
        )
        return r.json().get("data", [])
    except:
        return []

def sma(data, length):
    if len(data) < length:
        return None
    return sum(data[-length:]) / length

def analyze_trend(candles):
    if not candles:
        return None
    closes = [float(c[2]) for c in candles]     # FIX because v1 returns array
    ma20 = sma(closes, 20)
    ma50 = sma(closes, 50)
    if not ma20 or not ma50:
        return None
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
#   SET REAL SL/TP  (FIXED precision)
# -----------------------------------------
def set_sl_tp(pid, sl, tp):
    sl = round(float(sl), 2)
    tp = round(float(tp), 2)

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
#   GET POSITION (FIXED MAPPING)
# -----------------------------------------
def get_position():
    payload = {"market": SYMBOL}
    payload["timestamp"] = int(time.time()*1000)
    payload["signature"] = sign(payload)

    try:
        r = requests.get(f"{BASE_URL}/position/list", params=payload, timeout=5).json()
        if not r["data"]:
            return None
        p = r["data"][0]

        # NORMALIZE TO ORIGINAL KEYS
        p["entry_price"] = float(p["avg_entry_price"])
        p["side"] = p["side"]
        p["amount"] = float(p["amount"])
        p["position_id"] = p["position_id"]

        return p

    except:
        return None

# -----------------------------------------
#   MULTI TP / SL CONFIG
# -----------------------------------------
TP_STEPS = [
    {"profit": 0.004, "close": 0.40},
    {"profit": 0.008, "close": 0.30},
    {"profit": 0.012, "close": 0.30},
]

SL_LEVEL = 0.006

# -----------------------------------------
#   CONFIDENCE
# -----------------------------------------
def compute_confidence():
    m5, m15, h1 = fetch_mtf()
    
    current_direction = None
    current_confidence = 0.0 # Default confidence when no signal or bias is set

    if h1 is None:
        state["confidence"] = round(current_confidence, 2)
        return current_direction, current_confidence

    # H1 acts as the primary BIAS filter
    if h1 == "up":
        # If H1 is 'up', look for 'long' triggers from M15 and M5
        if m15 == "up" and m5 == "up":
            current_direction = "long"
            current_confidence = 0.8 # High confidence for a clear trigger
    elif h1 == "down":
        # If H1 is 'down', look for 'short' triggers from M15 and M5
        if m15 == "down" and m5 == "down":
            current_direction = "short"
            current_confidence = 0.8 # High confidence for a clear trigger

    # Update the global state with the calculated confidence
    state["confidence"] = round(current_confidence, 2)
    return current_direction, current_confidence

# =================================================================
# End of compute_confidence() replacement
# =================================================================


def required_confidence(m5, m15, h1):
    up = [m5, m15, h1].count("up")
    dn = [m5, m15, h1].count("down")

    if up == 3 or dn == 3: return 0.60
    if up == 2 or dn == 2: return 0.50
    return 0.75

# -----------------------------------------
#   TRADING LOOP
# -----------------------------------------
def trading_loop():
    print("BOT STARTED")
    state["loop_running"] = True

    while True:
        try:
            direction, conf = compute_confidence()
            m5 = state["mtf"]["m5"]
            m15 = state["mtf"]["m15"]
            h1 = state["mtf"]["h1"]
            req = required_confidence(m5, m15, h1)

            price = get_price()
            pos = get_position()
            balance = get_balance()

            # ----------------- NO POSITION -----------------
            if pos is None:
                if direction and conf >= req:

                    position_value = balance * POSITION_SIZE_PERCENT * LEVERAGE
                    amount = round((position_value / price) / CONTRACT_SIZE, 3)

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
                    state["peak"] = entry  # INIT PEAK

                time.sleep(3)
                continue

            # ----------------- HAVE POSITION -----------------
            entry = float(pos["entry_price"])
            amount = float(pos["amount"])
            pid = pos["position_id"]

            # -----------------------------------------
            #   REVERSAL ENTRY
            # -----------------------------------------
            if state["position"] == "long" and direction=="short" and conf>=req:
                close_position("sell", amount)
                position_value = balance * POSITION_SIZE_PERCENT * LEVERAGE
                open_short(round((position_value/price)/CONTRACT_SIZE,3))
                time.sleep(2)
                continue

            if state["position"] == "short" and direction=="long" and conf>=req:
                close_position("buy", amount)
                position_value = balance * POSITION_SIZE_PERCENT * LEVERAGE
                open_long(round((position_value/price)/CONTRACT_SIZE,3))
                time.sleep(2)
                continue

            # -----------------------------------------
            #   TAKE PROFITS
            # -----------------------------------------
            for i, step in enumerate(TP_STEPS):
                if i < state.get("tp_level", 0):
                    continue

                target = entry*(1+step["profit"]) if state["position"]=="long" else entry*(1-step["profit"])

                if (state["position"]=="long" and price>=target) or (state["position"]=="short" and price<=target):

                    close_amount = amount * step["close"]
                    close_position("sell" if state["position"]=="long" else "buy", close_amount)

                    state["tp_level"] = i+1

                    if not state["breakeven"]:
                        be = entry
                        set_sl_tp(pid, be, pos["take_profit_price"])
                        state["breakeven"] = True

                    if i == 0:   # start trailing
                        state["trailing"] = True

            # -----------------------------------------
            #   TRAILING STOP PRO (MODEL B)
            # -----------------------------------------
            if state["trailing"]:
                if state["position"] == "long":
                    if price > state["peak"]:
                        state["peak"] = price
                        new_sl = price * (1 - 0.004)
                        set_sl_tp(pid, new_sl, pos["take_profit_price"])

                else:  # short
                    if price < state["peak"]:
                        state["peak"] = price
                        new_sl = price * (1 + 0.004)
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

@app.get("/health")   # ADDED
def health():
    return "OK"

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
    
@app.get("/status")
def status():
    # وضعیت حلقه معامله‌گری
    loop_state = "active" if state.get("loop_running", False) else "stopped"

    # وضعیت پوزیشن فعلی
    try:
        pos = get_position()
        if pos:
            position_info = {
                "side": pos.get("side"),
                "amount": pos.get("amount"),
                "entry_price": pos.get("entry_price"),
                "unrealized_pnl": pos.get("unrealized_pnl")
            }
        else:
            position_info = None
    except Exception as e:
        position_info = f"error: {str(e)}"

    # خروجی اصلی
    return jsonify({
        "status": "Running",
        "service": "CoinEx Futures Bot",
        "mode": "production",
        "loop": loop_state,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "position": position_info,
        "cpu_load": psutil.cpu_percent(interval=0.1),
        "memory_usage": psutil.virtual_memory().percent
    })

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
