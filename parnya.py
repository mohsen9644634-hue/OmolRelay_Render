import time
import hmac
import hashlib
import requests
from flask import Flask, jsonify
import threading

# =========================
# Configuration
# =========================
API_KEY = "YOUR_API_KEY"
SECRET_KEY = "YOUR_SECRET_KEY"
BASE_URL = "https://api.coinex.com/perpetual/v1"

SYMBOL = "BTCUSDT"
INTERVAL = "1min"
LIMIT = 200

LEVERAGE = 15
MARGIN_MODE = "isolated"

app = Flask(__name__)

# =========================
# Signature
# =========================
def sign(params):
    keys = sorted(params.keys())
    payload = ""
    for k in keys:
        payload += k + "=" + str(params[k]) + "&"
    payload = payload[:-1] + SECRET_KEY
    return hashlib.md5(payload.encode()).hexdigest().upper()

# =========================
# Basic GET
# =========================
def ce_get(url, params=None):
    if params is None:
        params = {}
    params["access_id"] = API_KEY
    params["tonce"] = int(time.time() * 1000)
    params["sign"] = sign(params)
    r = requests.get(BASE_URL + url, params=params)
    return r.json()

# =========================
# Basic POST
# =========================
def ce_post(url, params=None):
    if params is None:
        params = {}
    params["access_id"] = API_KEY
    params["tonce"] = int(time.time() * 1000)
    params["sign"] = sign(params)
    r = requests.post(BASE_URL + url, data=params)
    return r.json()

# =========================
# Get Klines
# =========================
def get_klines():
    return ce_get("/market/kline", {
        "market": SYMBOL,
        "period": INTERVAL,
        "limit": LIMIT
    })

# =========================
# Indicators
# =========================
def rsi(values, period=14):
    deltas = [values[i] - values[i - 1] for i in range(1, len(values))]
    ups = [d if d > 0 else 0 for d in deltas]
    downs = [-d if d < 0 else 0 for d in deltas]

    avg_up = sum(ups[:period]) / period
    avg_down = sum(downs[:period]) / period

    for i in range(period, len(deltas)):
        avg_up = ((avg_up * (period - 1)) + ups[i]) / period
        avg_down = ((avg_down * (period - 1)) + downs[i]) / period

    rs = avg_up / avg_down if avg_down != 0 else 0
    return 100 - (100 / (1 + rs))

def ma(values, period=50):
    if len(values) < period:
        return None
    return sum(values[-period:]) / period

def atr(highs, lows, closes, period=14):
    trs = []
    for i in range(1, len(highs)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        trs.append(tr)
    if len(trs) < period:
        return None
    return sum(trs[-period:]) / period

# =========================
# Account / Position
# =========================
def get_position():
    return ce_get("/position/list", {"market": SYMBOL})

def get_balance():
    return ce_get("/account/balance", {})

# =========================
# Place Order (LOG ONLY)
# =========================
def place_order(side, amount):
    print("[LOG] Order:", side, "amount:", amount)
    # To enable real order:
    # return ce_post("/order/put_market", {...})
    return {"success": True, "msg": "LOG_ONLY"}

# =========================
# Strategy Core
# =========================
def run_strategy():
    try:
        data = get_klines()
        items = data["data"]

        closes = [float(i[4]) for i in items]
        highs = [float(i[2]) for i in items]
        lows = [float(i[3]) for i in items]

        last_close = closes[-1]
        rsi_value = rsi(closes)
        ma_value = ma(closes, 50)
        atr_value = atr(highs, lows, closes)

        pos = get_position()
        have_pos = pos["data"]["positions"]

        # ========================
        # ENTRY LOGIC
        # ========================
        if not have_pos:
            if rsi_value < 30 and last_close > ma_value:
                place_order("buy", 1)
                print("[LOG] LONG signal – not executed.")
            elif rsi_value > 70 and last_close < ma_value:
                place_order("sell", 1)
                print("[LOG] SHORT signal – not executed.")

        # ========================
        # EXIT LOGIC
        # ========================
        else:
            if rsi_value > 55:
                print("[LOG] Exit LONG")
            if rsi_value < 45:
                print("[LOG] Exit SHORT")

        return {
            "rsi": rsi_value,
            "ma50": ma_value,
            "atr": atr_value,
            "last_price": last_close
        }

    except Exception as e:
        return {"error": str(e)}

# =========================
# Auto Loop (60 seconds)
# =========================
def loop_worker():
    while True:
        result = run_strategy()
        print("Strategy:", result)
        time.sleep(60)

threading.Thread(target=loop_worker, daemon=True).start()

# =========================
# Flask Routes
# =========================
@app.route("/")
def home():
    return "Robot OK – running 24/7."

@app.route("/strategy")
def st():
    return jsonify(run_strategy())

@app.route("/status")
def status():
    return jsonify({"running": True, "symbol": SYMBOL})

# =========================
# Main
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
