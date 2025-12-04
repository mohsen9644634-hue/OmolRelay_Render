from flask import Flask, request, jsonify
import os, time, requests, hmac, hashlib
import statistics

app = Flask(__name__)

# -----------------------
#   CONFIG
# -----------------------
BASE_URL = "https://api.coinex.com/v1"
SYMBOL = "BTCUSDT"
TIMEFRAME = "1min"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = "7156028278"

# -----------------------
#   COINEX AUTH (not trading)
# -----------------------
API_KEY = os.getenv("COINEX_KEY", "")
SECRET = os.getenv("COINEX_SECRET", "").encode()


def sign(params):
    items = sorted(params.items())
    qs = '&'.join([f"{k}={v}" for k,v in items])
    return hmac.new(SECRET, qs.encode(), hashlib.sha256).hexdigest()


def ce_request(url, params=None):
    if params is None: params = {}
    params['access_id'] = API_KEY
    params['tonce'] = int(time.time()*1000)
    params['sign'] = sign(params)
    r = requests.get(BASE_URL+url, params=params, timeout=10)
    return r.json()


# -----------------------
#   TECHNICAL CALC
# -----------------------

def sma(arr, n):
    if len(arr) < n: return None
    return sum(arr[-n:]) / n

def rsi(prices, period=14):
    if len(prices) < period + 1: return None
    gains = []
    losses = []
    for i in range(1, period+1):
        diff = prices[-i] - prices[-i-1]
        if diff >= 0: gains.append(diff)
        else: losses.append(abs(diff))
    avg_gain = sum(gains)/period if len(gains)>0 else 0.0000001
    avg_loss = sum(losses)/period if len(losses)>0 else 0.0000001
    rs = avg_gain / avg_loss
    return 100 - (100/(1+rs))

def ema(arr, n):
    if len(arr) < n: return None
    k = 2/(n+1)
    e = arr[-n]
    for i in range(-n+1, 0):
        e = arr[i]*k + e*(1-k)
    return e

def macd(arr):
    if len(arr) < 40: return None,None,None
    ema12 = ema(arr,12)
    ema26 = ema(arr,26)
    if ema12 is None or ema26 is None: return None,None,None
    macd_line = ema12 - ema26
    # signal 9
    # approximate: rebuild last 9 macd values using rolling ema
    # (simple method, enough for signal generation)
    hist = []
    for i in range(30):
        if len(arr) < 26+i: break
        e12 = ema(arr[:-(i)],12)
        e26 = ema(arr[:-(i)],26)
        if e12 is None or e26 is None: break
        hist.append(e12 - e26)
    if len(hist) < 9: return macd_line,None,None
    sig = ema(hist[::-1],9)
    if sig is None: return macd_line,None,None
    return macd_line, sig, macd_line - sig

def atr(highs, lows, closes, period=14):
    if len(highs) < period+1: return None
    trs = []
    for i in range(-period, 0):
        h = highs[i]
        l = lows[i]
        pc = closes[i-1]
        tr = max(h-l, abs(h-pc), abs(l-pc))
        trs.append(tr)
    return sum(trs)/period


# -----------------------
#   FETCH CANDLES
# -----------------------
def fetch_candles():
    url = f"/market/kline?market={SYMBOL}&type={TIMEFRAME}&limit=100"
    r = requests.get(BASE_URL + url, timeout=10).json()
    if r.get("code") != 0: return None
    data = r["data"]
    closes = [float(x[2]) for x in data]
    highs  = [float(x[3]) for x in data]
    lows   = [float(x[4]) for x in data]
    return closes, highs, lows


# -----------------------
#   TELEGRAM SENDER
# -----------------------
def send_telegram(msg):
    if TELEGRAM_TOKEN == "":
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": msg,
        "parse_mode": "HTML"
    }
    try:
        requests.post(url, json=payload, timeout=10)
        return True
    except:
        return False


# -----------------------
#   GENERATE SIGNAL
# -----------------------
def generate_signal():
    candles = fetch_candles()
    if candles is None: 
        return {"signal":"error","msg":"cannot fetch candles"}

    closes, highs, lows = candles

    r = rsi(closes)
    m_line, m_sig, hist = macd(closes)
    a = atr(highs, lows, closes)

    if r is None or m_sig is None or a is None:
        return {"signal":"neutral"}

    price = closes[-1]

    long_ok  = (r < 30) and (m_line > m_sig) and (hist > 0)
    short_ok = (r > 70) and (m_line < m_sig) and (hist < 0)

    direction = "neutral"
    if long_ok: direction = "long"
    if short_ok: direction = "short"

    if direction == "neutral":
        return {"signal":"neutral"}

    sl = price - 1.2*a if direction=="long" else price + 1.2*a
    tp = price + 2.2*a if direction=="long" else price - 2.2*a

    conf = 0.85 if (long_ok or short_ok) else 0.0

    return {
        "signal": direction,
        "entry": price,
        "sl": sl,
        "tp": tp,
        "rsi": r,
        "macd_line": m_line,
        "macd_signal": m_sig,
        "hist": hist,
        "atr": a,
        "confidence": conf,
        "timestamp": int(time.time())
    }


# -----------------------
#   ROUTES
# -----------------------
@app.route("/")
def home():
    return "ربات اجرا شد (Render OK)."


@app.route("/signal")
def sig():
    s = generate_signal()
    return jsonify(s)


@app.route("/scan")
def scan():
    s = generate_signal()
    if s.get("signal") in ["long","short"]:
        msg = f"""
🚀 <b>Strong {s['signal'].upper()} Signal</b>

Pair: BTC/USDT
Entry: {s['entry']:.2f}
TP: {s['tp']:.2f}
SL: {s['sl']:.2f}

RSI: {s['rsi']:.2f}
MACD: {s['macd_line']:.2f} → {s['macd_signal']:.2f}
ATR: {s['atr']:.2f}

Confidence: {s['confidence']}
Time: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(s['timestamp']))}
"""
        send_telegram(msg)

    return jsonify(s)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
