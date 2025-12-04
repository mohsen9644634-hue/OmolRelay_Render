from flask import Flask, request, jsonify
import os, time, requests, hmac, hashlib
import numpy as np
import pandas as pd

app = Flask(__name__)

# =============================
#  TELEGRAM  (SECURE)
# =============================
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "7156028278")

def send_telegram(text):
    if not BOT_TOKEN or not CHAT_ID:
        return {"sent": False, "error": "TOKEN/CHATID missing"}
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": CHAT_ID, "text": text})
        return r.json()
    except Exception as e:
        return {"sent": False, "error": str(e)}

# =============================
#  COINEX CONFIG
# =============================
BASE = "https://api.coinex.com/v1"
KEY = os.getenv("COINEX_KEY", "")
SECRET = os.getenv("COINEX_SECRET", "").encode()
SYMBOL = "BTCUSDT"

def sign(p):
    s = "&".join([f"{k}={v}" for k, v in sorted(p.items())])
    return hmac.new(SECRET, s.encode(), hashlib.sha256).hexdigest()

def ce(path, params=None):
    if params is None: params = {}
    params["access_id"] = KEY
    params["tonce"] = int(time.time()*1000)
    params["sign"] = sign(params)
    try:
        r = requests.get(BASE + path, params=params)
        return r.json()
    except:
        return {"code": 500, "data": []}

# =============================
#  INDICATORS
# =============================
def calc_rsi(closes, period=14):
    closes = np.array(closes, float)
    diff = np.diff(closes)
    gain = np.where(diff > 0, diff, 0)
    loss = np.where(diff < 0, -diff, 0)
    ag = np.mean(gain[-period:])
    al = np.mean(loss[-period:])
    if al == 0:
        return 100
    return 100 - (100 / (1 + (ag/al)))

def calc_macd(closes):
    s = pd.Series(closes)
    ema12 = s.ewm(span=12).mean()
    ema26 = s.ewm(span=26).mean()
    return float(ema12.iloc[-1] - ema26.iloc[-1])

def calc_atr(klines, period=14):
    highs = np.array([float(x[2]) for x in klines])
    lows  = np.array([float(x[3]) for x in klines])
    closes = np.array([float(x[4]) for x in klines])
    prev = closes[:-1]
    tr = np.maximum(highs[1:] - lows[1:], np.maximum(abs(highs[1:] - prev), abs(lows[1:] - prev)))
    return float(np.mean(tr[-period:]))

# =============================
#  ROUTES
# =============================
@app.route("/")
def home():
    return "سرور فعال است"

@app.route("/status")
def status():
    return jsonify({"running": True})

@app.route("/scan")
def scan():
    k = ce("/market/kline", {"market": SYMBOL, "type": "1min", "limit": 200})

    if "data" not in k or not k["data"]:
        return jsonify({"error": "CoinEx error", "raw": k})

    data = k["data"]

    if data[0][0] > data[-1][0]:
        data.reverse()

    closes = [float(x[4]) for x in data]

    macd = calc_macd(closes)
    rsi  = calc_rsi(closes)
    atr  = calc_atr(data)
    price = closes[-1]

    signal = "none"
    if macd > 0 and rsi < 35:
        signal = "BUY"
    elif macd < 0 and rsi > 65:
        signal = "SELL"

    message = f"""
📊 Signal Alert
Coin: {SYMBOL}
Price: {price}

MACD: {macd:.4f}
RSI:  {rsi:.2f}
ATR:  {atr:.2f}

Signal → {signal}
"""
    send_telegram(message)

    return jsonify({
        "signal": signal,
        "price": price,
        "macd": macd,
        "rsi": rsi,
        "atr": atr
    })
@app.route('/telegram', methods=['GET', 'POST'])
def telegram():
    text = request.args.get('text', 'no-text')
    out = send_telegram(text)
    return jsonify(out)

# =============================
#  RUN
# =============================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
