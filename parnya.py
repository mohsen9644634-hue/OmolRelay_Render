from flask import Flask, jsonify
import requests, time, hmac, hashlib, threading, os

app = Flask(__name__)

BASE_URL = "https://api.coinex.com/v1"
SYMBOL = "BTCUSDT"
PERIOD_MAIN = "15min"
PERIOD_HTF = "1hour"

API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

position = None
stop_loss = None
take_profit = None

def send_telegram(msg):
    try:
        requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                     params={"chat_id": CHAT_ID, "text": msg})
    except:
        pass

def signed(params):
    query = "&".join([f"{k}={params[k]}" for k in sorted(params)])
    sign = hmac.new(API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
    params["signature"] = sign
    return params

def get_klines(period):
    try:
        r = requests.get(f"{BASE_URL}/market/kline", params={
            "market": SYMBOL,
            "type": period,
            "limit": 120
        }).json()
        return [float(cand[2]) for cand in r["data"]]
    except:
        return []

def ema(data, period):
    k = 2 / (period + 1)
    ema_val = data[0]
    for p in data[1:]:
        ema_val = p*k + ema_val*(1-k)
    return ema_val

def macd_fast(close):
    ema12 = ema(close[-60:], 12)
    ema26 = ema(close[-60:], 26)
    macd_line = ema12 - ema26
    signal = ema([macd_line]*9, 9)
    hist = macd_line - signal
    return macd_line, signal, hist

def rsi_wilder(close, period=14):
    deltas = [close[i]-close[i-1] for i in range(1, len(close))]
    ups = [d if d>0 else 0 for d in deltas]
    downs = [-d if d<0 else 0 for d in deltas]
    avg_up = sum(ups[:period])/period
    avg_down = sum(downs[:period])/period
    for i in range(period, len(deltas)):
        avg_up = (avg_up*(period-1)+ups[i])/period
        avg_down = (avg_down*(period-1)+downs[i])/period
    if avg_down == 0:
        return 100
    rs = avg_up/avg_down
    return 100 - (100/(1+rs))

def atr(close, period=14):
    trs = [abs(close[i]-close[i-1]) for i in range(1, len(close))]
    atr_val = sum(trs[:period]) / period
    for i in range(period, len(trs)):
        atr_val = (atr_val*(period-1)+trs[i]) / period
    return atr_val

def supertrend(close, atr_val, factor=3):
    mid = close[-1]
    up = mid + factor * atr_val
    dn = mid - factor * atr_val
    return "UP" if close[-1] > dn else "DOWN"

def get_balance():
    try:
        r = requests.get(f"{BASE_URL}/balance/info", params=signed({"access_id": API_KEY})).json()
        return float(r["data"]["USDT"]["available"])
    except:
        return 0

def signals():
    c_main = get_klines(PERIOD_MAIN)
    c_htf = get_klines(PERIOD_HTF)
    if len(c_main)<60 or len(c_htf)<60:
        return "NONE"

    macd_line, sig, hist = macd_fast(c_main)
    rsi_val = rsi_wilder(c_main)
    atr_val = atr(c_main)
    st = supertrend(c_main, atr_val)

    trend_htf = "UP" if c_htf[-1] > ema(c_htf[-50:], 50) else "DOWN"

    if (
        hist>0 and
        st=="UP" and
        rsi_val<65 and
        trend_htf=="UP"
    ):
        return "BUY"

    if (
        hist<0 and
        st=="DOWN" and
        rsi_val>35 and
        trend_htf=="DOWN"
    ):
        return "SELL"

    return "NONE"

def open_order(side):
    global position, stop_loss, take_profit
    bal = get_balance()
    if bal < 20:
        return

    size = round(bal * 0.10, 2)

    try:
        r = requests.post(f"{BASE_URL}/order/limit", data=signed({
            "access_id": API_KEY,
            "market": SYMBOL,
            "type": "buy" if side=="BUY" else "sell",
            "amount": size,
            "price": 0
        })).json()
    except:
        return

    c = get_klines(PERIOD_MAIN)
    atr_val = atr(c)
    if side=="BUY":
        stop_loss = c[-1] - 2*atr_val
        take_profit = c[-1] + 4*atr_val
    else:
        stop_loss = c[-1] + 2*atr_val
        take_profit = c[-1] - 4*atr_val

    position = side
    send_telegram(f"{side} OPENED\nSL={stop_loss}\nTP={take_profit}")

def close_order():
    global position
    if position is None:
        return
    side = "sell" if position=="BUY" else "buy"
    try:
        requests.post(f"{BASE_URL}/order/limit", data=signed({
            "access_id": API_KEY,
            "market": SYMBOL,
            "type": side,
            "amount": 0.1,
            "price": 0
        }))
    except:
        pass
    send_telegram("Closed Position")
    position = None

def check_tp_sl():
    global position
    if position is None:
        return
    c = get_klines(PERIOD_MAIN)
    price = c[-1]
    if position=="BUY":
        if price <= stop_loss or price >= take_profit:
            close_order()
    if position=="SELL":
        if price >= stop_loss or price <= take_profit:
            close_order()

def loop():
    try:
        check_tp_sl()
        if position is None:
            sig = signals()
            if sig in ["BUY","SELL"]:
                open_order(sig)
    except:
        pass
    threading.Timer(20, loop).start()

def heartbeat():
    send_telegram("ULTRA PRO Running")
    threading.Timer(300, heartbeat).start()

loop()
heartbeat()

@app.route("/")
def home():
    return "ULTRA PRO BOT RUNNING"

@app.route("/status")
def status():
    return jsonify({
        "position": position,
        "stop_loss": stop_loss,
        "take_profit": take_profit
    })

@app.route("/env")
def env():
    return jsonify({
        "API_KEY": bool(API_KEY),
        "SECRET": bool(API_SECRET),
        "TELEGRAM": bool(TELEGRAM_TOKEN),
        "CHAT_ID": bool(CHAT_ID)
    })

@app.route("/signal")
def signal_view():
    return jsonify({"signal": signals()})

@app.route("/debug")
def debug():
    c = get_klines(PERIOD_MAIN)
    return jsonify({"candles": len(c)})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
