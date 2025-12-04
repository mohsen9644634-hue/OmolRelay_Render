import os
import time
import hmac
import hashlib
import requests
import numpy as np
from flask import Flask, jsonify

app = Flask(__name__)

API_KEY = os.getenv("API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
BASE_URL = "https://api.coinex.com/perpetual/v1/"
SYMBOL = "BTCUSDT"

# ----------------------------------------------------
# SIGNATURE
# ----------------------------------------------------
def sign(params):
    sorted_params = "&".join([f"{k}={params[k]}" for k in sorted(params)])
    to_sign = sorted_params + f"&secret_key={SECRET_KEY}"
    return hashlib.md5(to_sign.encode()).hexdigest().upper()

# ----------------------------------------------------
# BASIC GET
# ----------------------------------------------------
def ce_get(url, params=None):
    if params is None:
        params = {}
    params["access_id"] = API_KEY
    params["tonce"] = int(time.time() * 1000)
    params["sign"] = sign(params)
    r = requests.get(BASE_URL + url, params=params)
    return r.json()

# ----------------------------------------------------
# BASIC POST
# ----------------------------------------------------
def ce_post(url, params):
    params["access_id"] = API_KEY
    params["tonce"] = int(time.time() * 1000)
    params["sign"] = sign(params)
    r = requests.post(BASE_URL + url, data=params)
    return r.json()

# ----------------------------------------------------
# INDICATORS
# ----------------------------------------------------
def calc_rsi(data, period=14):
    diff = np.diff(data)
    up = np.where(diff > 0, diff, 0)
    down = np.where(diff < 0, -diff, 0)

    avg_up = np.mean(up[-period:])
    avg_down = np.mean(down[-period:])
    rs = avg_up / (avg_down + 1e-9)
    return 100 - (100 / (1 + rs))

def calc_ma(data, period=50):
    return np.mean(data[-period:])

def calc_atr(high, low, close, period=14):
    tr = np.maximum(high[1:] - low[1:], 
                    np.maximum(abs(high[1:] - close[:-1]),
                               abs(low[1:] - close[:-1])))
    return np.mean(tr[-period:])

# ----------------------------------------------------
# KLINE DATA
# ----------------------------------------------------
def fetch_kline():
    r = ce_get("market/kline", {
        "market": SYMBOL,
        "type": "1min",
        "limit": 200
    })
    if r["code"] != 0:
        return None
    return r["data"]

# ----------------------------------------------------
# POSITION SIZE (FULL EQUITY)
# ----------------------------------------------------
def get_equity():
    r = ce_get("account", {})
    if r["code"] != 0:
        return None
    return float(r["data"]["USDT"]["available"])

# ----------------------------------------------------
# STRATEGY
# ----------------------------------------------------
def strategy():
    data = fetch_kline()
    if data is None:
        return {"error": "Failed to fetch kline"}

    close = np.array([float(x["close"]) for x in data])
    high = np.array([float(x["high"]) for x in data])
    low = np.array([float(x["low"]) for x in data])

    rsi = calc_rsi(close)
    ma50 = calc_ma(close)
    atr = calc_atr(high, low, close)

    decision = "HOLD"

    if rsi < 30 and close[-1] > ma50:
        decision = "LONG_SIGNAL"
    elif rsi > 70 and close[-1] < ma50:
        decision = "SHORT_SIGNAL"

    return {
        "rsi": float(rsi),
        "ma50": float(ma50),
        "atr": float(atr),
        "decision": decision,
        "last_price": float(close[-1])
    }

# ----------------------------------------------------
# EXECUTE ORDER (LOG ONLY – SAFE)
# ----------------------------------------------------
def execute_order(side, size):
    return {
        "status": "LOG_ONLY",
        "message": f"READY TO EXECUTE {side} MARKET ORDER (size={size}).",
        "note": "To enable real trading, replace this function with ce_post() call."
    }

# ----------------------------------------------------
# ROUTES
# ----------------------------------------------------
@app.route("/")
def home():
    return "Bot is running successfully on Render."

@app.route("/strategy")
def strategy_route():
    return jsonify(strategy())

@app.route("/trade")
def trade_route():
    st = strategy()
    if "error" in st:
        return jsonify(st)

    equity = get_equity()
    if equity is None:
        return {"error": "Could not fetch equity"}

    size = equity * 15  # 15x leverage size calculation

    if st["decision"] == "LONG_SIGNAL":
        return jsonify(execute_order("LONG", size))
    elif st["decision"] == "SHORT_SIGNAL":
        return jsonify(execute_order("SHORT", size))
    else:
        return {"status": "NO_ACTION", "decision": st["decision"]}

# ----------------------------------------------------
# MAIN
# ----------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
