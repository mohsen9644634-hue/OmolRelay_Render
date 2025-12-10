###########################################################
#  PARNYA FUTURES AUTOTRADE BOT — FINAL REAL LIVE VERSION  #
#  Render-Optimized / Clean / No Debug / True Trading      #
###########################################################

import time, hmac, hashlib, requests, os
from flask import Flask, jsonify
from threading import Thread

# =========================== CONFIG =============================
BASE_URL = "https://api.coinex.com/perpetual/v1"
SPOT_URL = "https://api.coinex.com/v1"
SYMBOL = "BTCUSDT"
LEVERAGE = 10
AMOUNT = 0.01

API_KEY = os.getenv("COINEX_KEY")
API_SECRET = os.getenv("COINEX_SECRET").encode()

position = None
entry_price = None


# ==================== SIGN + PRIVATE REQUEST ====================
def sign_request(params):
    sorted_params = sorted(params.items())
    query = "&".join([f"{k}={v}" for k, v in sorted_params])
    signature = hmac.new(API_SECRET, query.encode(), hashlib.sha256).hexdigest()
    return signature

def private_request(method, endpoint, params=None):
    if params is None:
        params = {}
    params["access_id"] = API_KEY
    params["timestamp"] = int(time.time() * 1000)
    params["tonce"] = int(time.time() * 1000)
    params["signature"] = sign_request(params)

    url = f"{BASE_URL}{endpoint}"

    try:
        if method == "GET":
            r = requests.get(url, params=params, timeout=8)
        else:
            r = requests.post(url, data=params, timeout=8)
        if r.status_code != 200:
            return {}
        return r.json()
    except:
        return {}


# =========================== INDICATORS ===========================
def ema_series(values, period):
    if len(values) < period:
        return [values[-1]]
    k = 2 / (period + 1)
    ema_list = [values[0]]
    for v in values[1:]:
        ema_list.append(v * k + ema_list[-1] * (1 - k))
    return ema_list

def macd(candles):
    closes = [float(c[2]) for c in candles]
    ema12 = ema_series(closes, 12)
    ema26 = ema_series(closes, 26)
    macd_line = [a - b for a, b in zip(ema12, ema26)]
    signal = ema_series(macd_line, 9)
    hist = [m - s for m, s in zip(macd_line, signal)]
    return macd_line[-1], signal[-1], hist[-3:]

def rsi(candles, period=14):
    closes = [float(c[2]) for c in candles]
    if len(closes) <= period:
        return 50
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [d for d in deltas if d > 0]
    losses = [-d for d in deltas if d < 0]
    avg_gain = sum(gains[-period:]) / period if gains else 0
    avg_loss = sum(losses[-period:]) / period if losses else 0
    rs = avg_gain / avg_loss if avg_loss != 0 else 100
    return 100 - (100 / (1 + rs))

def atr(candles, period=14):
    if len(candles) <= period:
        return 0
    trs = []
    for i in range(1, len(candles)):
        high = float(candles[i][0])
        low = float(candles[i][1])
        prev_close = float(candles[i-1][2])
        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close)
        )
        trs.append(tr)
    return sum(trs[-period:]) / period


# ============================ MARKET ===============================
def get_candles(symbol, limit=160):
    url = f"{SPOT_URL}/market/kline?market={symbol}&type=5min&limit={limit}"
    try:
        r = requests.get(url, timeout=8)
        if r.status_code != 200:
            return []
        d = r.json()
        return d.get("data", [])
    except:
        return []

def get_current_price(symbol):
    try:
        url = f"{BASE_URL}/market/ticker?market={symbol}"
        r = requests.get(url, timeout=8)
        d = r.json()
        return float(d["data"]["ticker"]["last"])
    except:
        return None


# ========================== ORDERS ================================
def create_order(symbol, side):
    direction = "buy" if side == "LONG" else "sell"
    params = {
        "market": symbol,
        "side": direction,
        "amount": AMOUNT,
        "type": "market",
        "leverage": LEVERAGE
    }
    return private_request("POST", "/order/put_market", params)

def close_order(symbol):
    params = {"market": symbol, "side": "close", "amount": AMOUNT}
    return private_request("POST", "/position/close", params)


# =========================== SIGNAL ENGINE =========================
def super_signal(candles):
    close_prices = [float(c[2]) for c in candles]
    ema20 = ema_series(close_prices, 20)[-1]
    ema50 = ema_series(close_prices, 50)[-1]
    ema20p = ema_series(close_prices[:-1], 20)[-1]
    ema50p = ema_series(close_prices[:-1], 50)[-1]

    macd_l, macd_s, hist_list = macd(candles)
    hist = sum(hist_list) / len(hist_list)

    r = rsi(candles)
    a = atr(candles)
    last_close = close_prices[-1]
    last_open = float(candles[-1][1])

    if abs(last_close - last_open) > 2 * a:
        return None

    vol = a / last_close

    if vol < 0.002:
        if ema20p < ema50p and ema20 > ema50 and hist > 0 and 48 < r < 67:
            return "LONG"
        if ema20p > ema50p and ema20 < ema50 and hist < 0 and 33 < r < 52:
            return "SHORT"
    else:
        if ema20 > ema50 and hist >= 0 and 45 < r < 70:
            return "LONG"
        if ema20 < ema50 and hist <= 0 and 30 < r < 55:
            return "SHORT"

    return None


# ============================ POSITION MANAGER ======================
def manage_position(signal):
    global position, entry_price

    candles = get_candles(SYMBOL)
    if not candles:
        return

    a = atr(candles)
    last_price = float(candles[-1][2])

    # open
    if position is None and signal in ["LONG", "SHORT"]:
        entry_price = last_price
        position = signal
        create_order(SYMBOL, signal)
        return

    # manage / close
    if position:
        current = get_current_price(SYMBOL)
        if current is None:
            return

        macd_l, macd_s, hist_list = macd(candles)
        hist = sum(hist_list) / len(hist_list)

        if position == "LONG":
            if hist < 0:
                close_order(SYMBOL)
                position = None

        if position == "SHORT":
            if hist > 0:
                close_order(SYMBOL)
                position = None


# ============================== WEB SERVER =========================
app = Flask(__name__)

@app.route("/")
def home():
    return "OK"

@app.route("/status")
def status():
    return jsonify({
        "running": True,
        "position": position,
        "entry_price": entry_price,
    })


# ============================== MAIN LOOP ==========================
def trade_loop():
    while True:
        candles = get_candles(SYMBOL)
        sig = super_signal(candles) if candles else None
        manage_position(sig)
        time.sleep(15)


if __name__ == "__main__":
    Thread(target=trade_loop).start()
    from waitress import serve
    serve(app, host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
