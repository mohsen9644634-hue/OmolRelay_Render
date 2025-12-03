import time
import hashlib
import requests
import os
import numpy as np
from flask import Flask, jsonify

# ----------------------------------------------------
# CONFIG
# ----------------------------------------------------
API_KEY = os.getenv("API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")

BASE_URL = "https://api.coinex.com/perpetual/v1"
SYMBOL = "BTCUSDT"
LEVERAGE = 10
TIMEFRAME = "15m"

RSI_PERIOD = 14
MA_PERIOD = 50
ATR_PERIOD = 14

app = Flask(__name__)


# ----------------------------------------------------
# SIGN FUNCTION
# ----------------------------------------------------
def sign(params):
    query = "&".join([f"{k}={params[k]}" for k in sorted(params)])
    to_sign = query + SECRET_KEY
    return hashlib.md5(to_sign.encode()).hexdigest()


# ----------------------------------------------------
# BASIC GET REQUEST
# ----------------------------------------------------
def ce_request(url, params=None):
    if params is None:
        params = {}

    params["access_id"] = API_KEY
    params["tonce"] = int(time.time() * 1000)
    params["sign"] = sign(params)

    r = requests.get(BASE_URL + url, params=params)
    return r.json()


# ----------------------------------------------------
# BASIC POST REQUEST
# ----------------------------------------------------
def ce_post(url, params=None):
    if params is None:
        params = {}

    params["access_id"] = API_KEY
    params["tonce"] = int(time.time() * 1000)
    params["sign"] = sign(params)

    r = requests.post(BASE_URL + url, data=params)
    return r.json()


# ----------------------------------------------------
# GET KLINES
# ----------------------------------------------------
def get_klines():
    r = ce_request("/market/kline", {
        "market": SYMBOL,
        "limit": 200,
        "interval": TIMEFRAME
    })
    closes = [float(c[4]) for c in r["data"]]
    return closes


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


def calc_atr(data, period=14):
    tr = []
    for i in range(1, period + 1):
        tr.append(abs(data[-i] - data[-i - 1]))
    return np.mean(tr)


# ----------------------------------------------------
# ACCOUNT
# ----------------------------------------------------
def get_balance():
    r = ce_request("/account/balance")
    return float(r["data"]["USDT"]["available"])


def get_position():
    r = ce_request("/position/list", {"market": SYMBOL})
    if len(r["data"]) == 0:
        return None
    return r["data"][0]


# ----------------------------------------------------
# PLACE ORDER (MARKET)
# ----------------------------------------------------
def place_order(side, size):
    params = {
        "market": SYMBOL,
        "side": side,  # buy / sell / close
        "amount": size,
        "type": 1,      # market order
        "leverage": LEVERAGE,
    }
    return ce_post("/order/put", params)


# ----------------------------------------------------
# STRATEGY
# ----------------------------------------------------
def run_strategy():
    closes = get_klines()
    last = closes[-1]

    rsi = calc_rsi(closes, RSI_PERIOD)
    ma50 = calc_ma(closes, MA_PERIOD)
    atr = calc_atr(closes, ATR_PERIOD)

    position = get_position()
    balance = get_balance()

    # سایز پوزیشن = کل موجودی × لوریج / قیمت
    size = (balance * LEVERAGE) / last

    # ---------------------------
    # EXIT (اگر پوزیشن باز است)
    # ---------------------------
    if position:
        entry = float(position["entry_price"])
        side = position["side"]  # 1 = LONG / 2 = SHORT

        if side == 1:
            tp = entry + (atr * 2)
            sl = entry - atr
        else:
            tp = entry - (atr * 2)
            sl = entry + atr

        # خروج بر اساس TP/SL
        if (side == 1 and (last >= tp or last <= sl)) or \
           (side == 2 and (last <= tp or last >= sl)):
            place_order("close", abs(float(position["amount"])))
            return "Exited position (TP/SL hit)"

        # خروج خنثی RSI
        if 45 < rsi < 55:
            place_order("close", abs(float(position["amount"])))
            return "Exited neutral RSI"

        return "Holding position"

    # ---------------------------
    # ENTRY LONG
    # ---------------------------
    if rsi < 30 and last > ma50:
        place_order("buy", size)
        return "Opened LONG"

    # ---------------------------
    # ENTRY SHORT
    # ---------------------------
    if rsi > 70 and last < ma50:
        place_order("sell", size)
        return "Opened SHORT"

    return "No signal"


# ----------------------------------------------------
# ROUTES
# ----------------------------------------------------
@app.route("/")
def home():
    return "سلام پویا! ربات Render با موفقیت اجرا شد."

@app.route("/status")
def status():
    return jsonify({"running": True, "symbol": SYMBOL})

@app.route("/trade")
def trade():
    result = run_strategy()
    return jsonify({"result": result})


# ----------------------------------------------------
# MAIN
# ----------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)

