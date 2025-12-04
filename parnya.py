from flask import Flask, request, jsonify
import os, time, requests, hmac, hashlib
import numpy as np
import pandas as pd

app = Flask(__name__)

BASE_URL = "https://api.coinex.com/v1"
API_KEY = os.getenv("COINEX_KEY", "")
SECRET = os.getenv("COINEX_SECRET", "").encode()
BOT_TOKEN = os.getenv("TG_TOKEN", "")
CHAT_ID = "7156028278"

SYMBOL = "BTCUSDT"
TIMEFRAME = "1min"

def sign(params):
    items = sorted(params.items())
    qs = "&".join([f"{k}={v}" for k,v in items])
    return hmac.new(SECRET, qs.encode(), hashlib.sha256).hexdigest()

def ce_request(url, params=None):
    if params is None: params = {}
    params["access_id"] = API_KEY
    params["tonce"] = int(time.time()*1000)
    params["sign"] = sign(params)
    r = requests.get(BASE_URL + url, params=params, timeout=10)
    return r.json()

def EMA(data, period):
    return data.ewm(span=period, adjust=False).mean()

def RSI(series, period=14):
    delta = series.diff()
    gain = np.where(delta>0, delta, 0)
    loss = np.where(delta<0, -delta, 0)
    avg_gain = EMA(pd.Series(gain), period)
    avg_loss = EMA(pd.Series(loss), period)
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def ATR(df, period=14):
    high = df["high"]
    low = df["low"]
    close = df["close"].shift(1)
    tr = np.maximum(high - low, np.maximum(abs(high - close), abs(low - close)))
    return EMA(pd.Series(tr), period)

def get_ohlc():
    params = {"market": SYMBOL, "limit": 200, "type": TIMEFRAME}
    r = ce_request("/market/kline", params)
    if "data" not in r:
        return None
    rows = r["data"]
    closes = [float(x[2]) for x in rows]
    highs  = [float(x[3]) for x in rows]
    lows   = [float(x[4]) for x in rows]
    df = pd.DataFrame({"close": closes, "high": highs, "low": lows})
    return df

def generate_signal():
    df = get_ohlc()
    if df is None or len(df) < 50:
        return {"error": "not enough data"}

    df["ema12"] = EMA(df["close"], 12)
    df["ema26"] = EMA(df["close"], 26)
    df["macd"] = df["ema12"] - df["ema26"]
    df["signal"] = EMA(df["macd"], 9)
    df["hist"] = df["macd"] - df["signal"]
    df["rsi"] = RSI(df["close"], 14)
    df["atr"] = ATR(df, 14)

    last = df.iloc[-1]

    price = float(last["close"])
    atr = float(last["atr"])

    SL_long = price - 1.2 * atr
    TP_long = price + 2.2 * atr

    SL_short = price + 1.2 * atr
    TP_short = price - 2.2 * atr

    long_cond = last["hist"] > 0 and last["rsi"] > 55
    short_cond = last["hist"] < 0 and last["rsi"] < 45

    signal = "none"
    if long_cond:
        signal = "long"
    elif short_cond:
        signal = "short"

    return {
        "signal": signal,
        "price": price,
        "rsi": float(last["rsi"]),
        "macd": float(last["macd"]),
        "atr": atr,
        "sl_long": SL_long,
        "tp_long": TP_long,
        "sl_short": SL_short,
        "tp_short": TP_short
    }

def send_telegram(msg):
    if not BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.get(url, params={"chat_id": CHAT_ID, "text": msg})

@app.route("/")
def home():
    return "Bot is running."

@app.route("/status")
def status():
    return jsonify({"running": True, "symbol": SYMBOL})

@app.route("/scan")
def scan():
    return jsonify(generate_signal())

@app.route("/signal")
def signal():
    r = generate_signal()
    return jsonify({"signal": r.get("signal", "none")})

@app.route("/telegram")
def tele():
    txt = request.args.get("text","")
    send_telegram(txt)
    return jsonify({"sent": True})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
