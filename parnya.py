import time
import hmac
import hashlib
import requests
import pandas as pd
from flask import Flask, request, jsonify

# -----------------------------------------
# CONFIG
# -----------------------------------------
API_KEY = "YOUR_API_KEY"
SECRET_KEY = "YOUR_SECRET_KEY"
BASE_URL = "https://api.coinex.com/perpetual/v1"
SYMBOL = "BTCUSDT"
LEVERAGE = 15
MARGIN_MODE = 1  # isolated
TOKEN = "Mp0551977"

app = Flask(__name__)

# -----------------------------------------
# SIGN FUNCTION
# -----------------------------------------
def sign(params: dict) -> str:
    query = "&".join([f"{k}={params[k]}" for k in sorted(params)])
    query += f"&secret_key={SECRET_KEY}"
    return hashlib.md5(query.encode()).hexdigest()


# -----------------------------------------
# BASIC GET
# -----------------------------------------
def ce_get(path: str, params: dict | None = None):
    if params is None:
        params = {}

    params["access_id"] = API_KEY
    params["tonce"] = int(time.time() * 1000)
    params["sign"] = sign(params)

    r = requests.get(BASE_URL + path, params=params, timeout=10)
    r.raise_for_status()
    return r.json()


# -----------------------------------------
# REAL POST (OPTION A ACTIVATED)
# -----------------------------------------
def ce_post(path: str, params: dict | None = None):
    if params is None:
        params = {}

    params["access_id"] = API_KEY
    params["tonce"] = int(time.time() * 1000)
    params["sign"] = sign(params)

    r = requests.post(BASE_URL + path, data=params, timeout=10)
    r.raise_for_status()
    return r.json()


# -----------------------------------------
# GET KLINES
# -----------------------------------------
def get_klines():
    r = ce_get("/market/kline", {
        "market": SYMBOL,
        "type": "1min",
        "limit": 200
    })
    data = r["data"]

    df = pd.DataFrame(data, columns=[
        "timestamp","open","close","high","low","volume","unknown"
    ])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df["open"]  = df["open"].astype(float)
    df["close"] = df["close"].astype(float)
    df["high"]  = df["high"].astype(float)
    df["low"]   = df["low"].astype(float)
    return df


# -----------------------------------------
# INDICATORS
# -----------------------------------------
def rsi(series, period=14):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    ma_up = up.rolling(period).mean()
    ma_down = down.rolling(period).mean()
    rs = ma_up / ma_down
    return 100 - (100 / (1 + rs))

def ema(series, period=50):
    return series.ewm(span=period, adjust=False).mean()

def atr(df, period=14):
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    tr = high_low.to_frame()
    tr["hc"] = high_close
    tr["lc"] = low_close
    tr = tr.max(axis=1)
    return tr.rolling(period).mean()


# -----------------------------------------
# STRATEGY
# -----------------------------------------
def run_strategy(df):
    df["ema50"] = ema(df["close"], 50)
    df["ema200"] = ema(df["close"], 200)
    df["rsi"] = rsi(df["close"])
    df["atr"] = atr(df)

    c = df["close"].iloc[-1]
    e50 = df["ema50"].iloc[-1]
    e200 = df["ema200"].iloc[-1]
    r = df["rsi"].iloc[-1]

    if c > e50 > e200 and r > 60:
        return "LONG"
    if c < e50 < e200 and r < 40:
        return "SHORT"
    return "NONE"


# -----------------------------------------
# POSITION SIZE
# -----------------------------------------
def get_balance():
    r = ce_get("/account/balance")
    return float(r["data"]["USDT"]["available"])

def calc_size(usdt: float, price: float):
    coin = (usdt * LEVERAGE) / price
    return round(coin, 3)


# -----------------------------------------
# FLASK ROUTES
# -----------------------------------------
@app.route("/")
def home():
    return "ربات سالم روی Render اجرا شد!"

@app.route("/status")
def status():
    return jsonify({"running": True, "symbol": SYMBOL})


@app.route("/trade")
def trade():
    if request.args.get("token") != TOKEN:
        return jsonify({"error": "invalid token"}), 401

    df = get_klines()
    sig = run_strategy(df)
    price = df["close"].iloc[-1]

    if sig == "NONE":
        return jsonify({"signal": "NONE", "price": price})

    usdt = get_balance()
    size = calc_size(usdt, price)
    side = "buy" if sig == "LONG" else "sell"

    # ----- REAL ORDER -----
    resp = ce_post("/order/put", {
        "market": SYMBOL,
        "side": side,
        "type": 1,
        "amount": size,
        "leverage": LEVERAGE,
        "client_id": int(time.time() * 1000)
    })

    return jsonify({
        "executed": True,
        "signal": sig,
        "side": side,
        "price": price,
        "size_coin": size,
        "resp": resp
    })


# -----------------------------------------
# MAIN
# -----------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
