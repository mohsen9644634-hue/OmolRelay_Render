from flask import Flask, request, jsonify
import os, time, requests, hmac, hashlib
import numpy as np
import pandas as pd

app = Flask(__name__)

# ---------------------------
#   Telegram Settings
# ---------------------------
BOT_TOKEN = "7565436021:AAFEEUPaMDtEBX1nHzAiHdRqaD6MSDR-WS8"
CHAT_ID = "7156028278"

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": text}
    try:
        r = requests.post(url, data=data)
        return r.json()
    except:
        return {"sent": False}

# ---------------------------
#   CoinEx Settings
# ---------------------------
BASE_URL = "https://api.coinex.com/v1"
API_KEY = os.getenv("COINEX_KEY", "")
SECRET = os.getenv("COINEX_SECRET", "").encode()
SYMBOL = "BTCUSDT"

def sign(params):
    items = sorted(params.items())
    qs = "&".join([f"{k}={v}" for k, v in items])
    return hmac.new(SECRET, qs.encode(), hashlib.sha256).hexdigest()

def ce_request(url, params=None):
    if params is None:
        params = {}
    params["access_id"] = API_KEY
    params["tonce"] = int(time.time() * 1000)
    params["sign"] = sign(params)
    r = requests.get(BASE_URL + url, params=params)
    return r.json()

# ---------------------------
#   Indicators: MACD, RSI, ATR
# ---------------------------
def calc_rsi(prices, period=14):
    diff = np.diff(prices)
    gain = np.where(diff > 0, diff, 0)
    loss = np.where(diff < 0, -diff, 0)
    avg_gain = np.mean(gain[-period:])
    avg_loss = np.mean(loss[-period:])
    rs = avg_gain / avg_loss if avg_loss != 0 else 0
    return 100 - (100 / (1 + rs))

def calc_macd(prices):
    ema12 = pd.Series(prices).ewm(span=12).mean()
    ema26 = pd.Series(prices).ewm(span=26).mean()
    macd = ema12 - ema26
    return macd.iloc[-1]

def calc_atr(data, period=14):
    highs = np.array([c["high"] for c in data])
    lows = np.array([c["low"] for c in data])
    closes = np.array([c["close"] for c in data])

    tr = np.maximum(highs[1:], closes[:-1]) - np.minimum(lows[1:], closes[:-1])
    return np.mean(tr[-period:])

# ---------------------------
#   Flask Routes
# ---------------------------

@app.route("/")
def home():
    return "ربات فعال است!"

@app.route("/status")
def status():
    return jsonify({"running": True})

@app.route("/telegram")
def telegram():
    text = request.args.get("text", "")
    res = send_telegram_message(text)
    return jsonify({"sent": True, "telegram_response": res})

@app.route("/scan")
def scan():
    # دریافت کندل‌ها
    k = ce_request("/market/kline", {"market": SYMBOL, "type": "1min", "limit": 150})
    if "data" not in k:
        return jsonify({"error": "CoinEx API error"})
    
    data = k["data"]
    closes = [c["close"] for c in data]

    macd = calc_macd(closes)
    rsi = calc_rsi(closes)
    atr = calc_atr(data)

    price = closes[-1]

    sl_long = round(price - atr * 1.2, 2)
    tp_long = round(price + atr * 2.2, 2)
    sl_short = round(price + atr * 1.2, 2)
    tp_short = round(price - atr * 2.2, 2)

    signal = "none"
    if macd > 0 and rsi < 35:
        signal = "buy"
    elif macd < 0 and rsi > 65:
        signal = "sell"

    return jsonify({
        "signal": signal,
        "price": price,
        "macd": float(macd),
        "rsi": float(rsi),
        "atr": float(atr),
        "sl_long": sl_long,
        "tp_long": tp_long,
        "sl_short": sl_short,
        "tp_short": tp_short
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
