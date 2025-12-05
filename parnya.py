import sys
import os
import time
import json
import hashlib
import requests
import threading
from flask import Flask, request, jsonify

############################################################
# CONFIG
############################################################

LIVE = True

API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
CHAT_ID = os.getenv("CHAT_ID")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

SYMBOL = "BTCUSDT"
INTERVAL = "15m"
LIMIT = 500

LEVERAGE = 15
POSITION_RISK = 0.70

TP_PERCENT = 1.2
SL_PERCENT = 0.7
TRIGGER_TRAIL = 0.6
TRAIL_DISTANCE = 0.3

current_position = None
entry_price = None
entry_amount = None
trailing_active = False

app = Flask(__name__)


############################################################
# TELEGRAM
############################################################

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.get(url, params={"chat_id": CHAT_ID, "text": msg})
        print("TG:", msg)
    except Exception as e:
        print("Telegram error:", e)


############################################################
# COINEX CORE
############################################################

def cx_sign(params):
    s = "".join(f"{k}{params[k]}" for k in sorted(params))
    return hashlib.md5((s + API_SECRET).encode()).hexdigest()


def cx_post(path, params):
    if not LIVE:
        return {"code": 0, "message": "SIMULATED"}

    base = "https://api.coinex.com/perpetual/v1"
    params["access_id"] = API_KEY
    params["timestamp"] = int(time.time() * 1000)
    sign = cx_sign(params)

    r = requests.post(base + path, json=params, headers={"Authorization": sign})
    return r.json()


def get_balance():
    try:
        p = {"market": SYMBOL.replace("USDT", ""), "asset": "USDT"}
        res = cx_post("/asset/query", p)
        if res.get("code") == 0:
            bal = float(res["data"]["available"])
            return bal
    except:
        pass
    return 100.0   # fallback safe


############################################################
# MARKET DATA
############################################################

def get_price():
    r = requests.get(f"https://api.binance.com/api/v3/ticker/price", params={"symbol": SYMBOL})
    return float(r.json()["price"])


def get_klines():
    r = requests.get("https://api.binance.com/api/v3/klines", params={
        "symbol": SYMBOL,
        "interval": INTERVAL,
        "limit": LIMIT
    })
    return [float(k[4]) for k in r.json()]


############################################################
# INDICATORS — PRO VERSION
############################################################

def ema(data, period):
    if len(data) < period:
        return data[-1]
    k = 2 / (period + 1)
    val = sum(data[:period]) / period
    for p in data[period:]:
        val = p * k + val * (1 - k)
    return val


def macd(data):
    ema12 = []
    ema26 = []
    macd_line = []

    for i in range(len(data)):
        slice_data = data[: i + 1]
        ema12.append(ema(slice_data, 12))
        ema26.append(ema(slice_data, 26))
        macd_line.append(ema12[-1] - ema26[-1])

    signal = ema(macd_line[-35:], 9)
    return macd_line[-1], signal


def rsi(data, period=14):
    if len(data) < period + 1:
        return 50

    gains = []
    losses = []

    for i in range(1, period + 1):
        diff = data[-i] - data[-i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


############################################################
# TRADING
############################################################

def open_position(direction, price):
    global current_position, entry_price, entry_amount, trailing_active

    if current_position:
        return

    balance = get_balance()
    amount = (balance * POSITION_RISK * LEVERAGE) / price
    amount = round(amount, 3)

    side = "buy" if direction == "LONG" else "sell"

    res = cx_post("/order/put_market", {
        "market": SYMBOL,
        "side": side,
        "type": "market",
        "amount": amount,
        "client_id": str(int(time.time()))
    })

    if res.get("code") == 0:
        current_position = direction
        entry_price = price
        entry_amount = amount
        trailing_active = False

        send_telegram(f"OPEN {direction}\nPrice: {price}\nLev: {LEVERAGE}x")


def close_position():
    global current_position, entry_amount, trailing_active

    if not current_position:
        return

    side = "sell" if current_position == "LONG" else "buy"

    cx_post("/order/put_market", {
        "market": SYMBOL,
        "side": side,
        "type": "market",
        "amount": entry_amount,
        "client_id": str(int(time.time()))
    })

    send_telegram(f"Closed {current_position}")
    current_position = None
    trailing_active = False


def manage_trade(price):
    global trailing_active, entry_price, current_position

    if not current_position or not entry_price:
        return

    if current_position == "LONG":
        profit = (price - entry_price) / entry_price * 100
    else:
        profit = (entry_price - price) / entry_price * 100

    if profit >= TP_PERCENT:
        send_telegram("TP HIT")
        close_position()
        return

    if profit <= -SL_PERCENT:
        send_telegram("SL HIT")
        close_position()
        return

    if not trailing_active and profit >= TRIGGER_TRAIL:
        trailing_active = True
        send_telegram("Trailing Started")

    if trailing_active and profit <= (TRIGGER_TRAIL - TRAIL_DISTANCE):
        send_telegram("Trailing Stop Hit")
        close_position()


############################################################
# STRATEGY — Model 1 (Strong)
############################################################

def strategy():
    k = get_klines()
    last = k[-1]

    macd_line, signal_line = macd(k)
    ema50 = ema(k, 50)
    rsi_value = rsi(k)

    if macd_line > signal_line and last > ema50 and rsi_value > 50:
        return "BUY"

    if macd_line < signal_line and last < ema50 and rsi_value < 50:
        return "SELL"

    return "NONE"


############################################################
# MAIN LOOP
############################################################

def main_loop():
    while True:
        try:
            price = get_price()
            manage_trade(price)

            sig = strategy()

            if sig == "BUY" and current_position != "LONG":
                close_position()
                open_position("LONG", price)

            elif sig == "SELL" and current_position != "SHORT":
                close_position()
                open_position("SHORT", price)

        except Exception as e:
            print("Loop Error:", e)

        time.sleep(20)


############################################################
# HEARTBEAT (Final Fixed)
############################################################

def heartbeat():
    send_telegram("Heartbeat: Running")
    threading.Timer(300, heartbeat).start()


############################################################
# ROUTES
############################################################

@app.route("/")
def home():
    return "Bot OK — PRO EDITION — M15"

@app.route("/status")
def status():
    return jsonify({
        "position": current_position,
        "entry_price": entry_price,
        "amount": entry_amount
    })

@app.route("/debug")
def debug():
    k = get_klines()
    macd_line, signal_line = macd(k)
    return jsonify({
        "last": k[-1],
        "macd": macd_line,
        "signal": signal_line,
        "ema50": ema(k, 50),
        "rsi": rsi(k)
    })

@app.route("/heartbeat")
def hb():
    send_telegram("Heartbeat route triggered")
    return "OK"

@app.route("/env")
def env():
    return jsonify({
        "API_KEY": bool(API_KEY),
        "API_SECRET": bool(API_SECRET),
        "CHAT_ID": bool(CHAT_ID),
        "TOKEN": bool(TELEGRAM_TOKEN)
    })


############################################################
# STARTUP
############################################################

if __name__ == "__main__":
    threading.Thread(target=main_loop, daemon=True).start()
    heartbeat()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
