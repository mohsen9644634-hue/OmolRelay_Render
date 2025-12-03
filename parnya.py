import time
import hashlib
import requests
import os
from flask import Flask, jsonify
import numpy as np

# -----------------------------------------
# CONFIG (NO API KEY IN CODE)
# -----------------------------------------
API_KEY = os.getenv("API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")

BASE_URL = "https://api.coinex.com/perpetual/v1"
SYMBOL = "BTCUSDT"

LEVERAGE = 10
POSITION_SIZE_PERCENT = 0.1

# FINAL TIMEFRAME
TIMEFRAME = "15m"

RSI_PERIOD = 14
MA_PERIOD = 50

app = Flask(__name__)

# -----------------------------------------
# SIGN FUNCTION
# -----------------------------------------
def sign(params):
    query = "&".join([f"{k}={params[k]}" for k in sorted(params)])
    to_sign = query + SECRET_KEY
    return hashlib.md5(to_sign.encode()).hexdigest()

# -----------------------------------------
# BASIC GET REQUEST (SIGNED)
# -----------------------------------------
def ce_request(url, params=None):
    if params is None:
        params = {}

    params["access_id"] = API_KEY
    params["tonce"] = int(time.time() * 1000)
    params["sign"] = sign(params)

    r = requests.get(BASE_URL + url, params=params)
    return r.json()

# -----------------------------------------
# GET KLINES (15m)
# -----------------------------------------
def get_klines():
    r = ce_request("/market/kline", {
        "market": SYMBOL,
        "limit": 200,
        "interval": TIMEFRAME
    })
    closes = [float(c[4]) for c in r["data"]]
    return closes

# -----------------------------------------
# INDICATORS
# -----------------------------------------
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

# -----------------------------------------
# ACCOUNT & POSITION
# -----------------------------------------
def get_balance():
    r = ce_request("/account/balance")
    usdt = float(r["data"]["USDT"]["available"])
    return usdt

def get_position():
    r = ce_request("/position/list", {"market": SYMBOL})
    if len(r["data"]) == 0:
        return None
    return r["data"][0]

# -----------------------------------------
# SEND MARKET ORDER
# side = buy / sell / close
# -----------------------------------------
def place_order(side, size):
    params = {
        "market": SYMBOL,
        "side": side,
        "amount": size,
        "type": 1,
        "leverage": LEVERAGE,
        "tonce": int(time.time() * 1000),
        "access_id": API_KEY
    }
    params["sign"] = sign(params)
    r = requests.post(BASE_URL + "/order/put", data=params)
    return r.json()

# -----------------------------------------
# STRATEGY CORE
# -----------------------------------------
def run_strategy():

    closes = get_klines()
    rsi = calc_rsi(closes, RSI_PERIOD)
    ma50 = calc_ma(closes, MA_PERIOD)
    last = closes[-1]

    position = get_position()
    balance = get_balance()
    size = (balance * POSITION_SIZE_PERCENT) / last

    # EXIT LOGIC
    if position:
        entry = float(position["entry_price"])
        side = position["side"]

        atr = abs(closes[-1] - closes[-2]) * 2
        tp = entry + atr if side == 1 else entry - atr
        sl = entry - atr if side == 1 else entry + atr

        # Take Profit / Stop Loss / RSI neutral exit
        if (side == 1 and (last >= tp or last <= sl)) or \
           (side == 2 and (last <= tp or last >= sl)) or \
           (45 < rsi < 55):

            place_order("close", abs(float(position["amount"])))
            return "Exited position"

        return "Holding position"

    # ENTRY LONG
    if rsi < 30 and last > ma50:
        place_order("buy", size)
        return "Opened LONG"

    # ENTRY SHORT
    if rsi > 70 and last < ma50:
        place_order("sell", size)
        return "Opened SHORT"

    return "No signal"

# -----------------------------------------
# FLASK ROUTES
# -----------------------------------------
@app.route("/status")
def status():
    return jsonify({"status": "running", "symbol": SYMBOL})

@app.route("/test")
def test():
    return jsonify({"ok": True})

@app.route("/trade")
def trade():
    result = run_strategy()
    return jsonify({"result": result})

# -----------------------------------------
# MAIN
# -----------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)

