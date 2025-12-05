import sys
import os
import time
import json
import hashlib
import requests
import threading
from flask import Flask, request

############################################################
# CONFIG
############################################################

LIVE = True   # Toggle for real orders

API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

SYMBOL = "BTCUSDT"
LEVERAGE = 15
POSITION_SIZE_PERCENT = 0.70

TP_PERCENT = 1.2
SL_PERCENT = 0.7
TRIGGER_TRAIL = 0.6
TRAIL_DISTANCE = 0.3

BINANCE_INTERVAL = "15m"
BINANCE_LIMIT = 300  # more data = better MACD/RSI

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
        params = {"chat_id": CHAT_ID, "text": msg}
        requests.get(url, params=params)
    except Exception as e:
        print("Telegram error:", e)
        sys.stdout.flush()


############################################################
# COINEX SIGN + REQUEST
############################################################

def coinex_sign(params: dict):
    sorted_params = "".join([f"{k}{params[k]}" for k in sorted(params)])
    return hashlib.md5((sorted_params + API_SECRET).encode()).hexdigest()


def coinex_request(path, params):
    if not LIVE:
        print("[SIMULATION] LIVE=False → Order skipped")
        return {"code": 0, "message": "SIMULATED"}

    base = "https://api.coinex.com/perpetual/v1"
    params["access_id"] = API_KEY
    params["timestamp"] = int(time.time() * 1000)
    sign = coinex_sign(params)

    headers = {"Content-Type": "application/json", "Authorization": sign}
    r = requests.post(base + path, json=params, headers=headers).json()
    print("CoinEx Response:", r)
    return r


############################################################
# MARKET DATA
############################################################

def get_price():
    r = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={SYMBOL}")
    return float(r.json()["price"])


def get_klines():
    url = "https://api.binance.com/api/v3/klines"
    r = requests.get(url, params={
        "symbol": SYMBOL,
        "interval": BINANCE_INTERVAL,
        "limit": BINANCE_LIMIT
    })
    return [float(k[4]) for k in r.json()]  # close prices only


############################################################
# INDICATORS — FIXED & CLEAN
############################################################

def ema(data, period):
    k = 2 / (period + 1)
    val = sum(data[:period]) / period
    for p in data[period:]:
        val = p * k + val * (1 - k)
    return val


def macd(data):
    ema12 = ema(data, 12)
    ema26 = ema(data, 26)
    macd_line = ema12 - ema26

    # Signal line = EMA9 of historical MACD (approx)
    last_values = []
    for i in range(35):
        chunk = data[-(35 - i):]
        if len(chunk) >= 26:
            last_values.append(ema(chunk, 12) - ema(chunk, 26))

    signal_line = ema(last_values, 9)
    return macd_line, signal_line


def rsi(data, period=14):
    gains, losses = [], []
    for i in range(1, period + 1):
        diff = data[-i] - data[-i - 1]
        if diff >= 0:
            gains.append(diff)
        else:
            losses.append(abs(diff))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


############################################################
# TRADING ACTIONS
############################################################

def close_position():
    global current_position, entry_amount
    if current_position is None:
        return

    print("[CLOSE] Closing position:", current_position)

    side = "sell" if current_position == "LONG" else "buy"

    params = {
        "market": SYMBOL,
        "side": side,
        "type": "market",
        "amount": entry_amount,
        "client_id": str(int(time.time()))
    }

    coinex_request("/order/put_market", params)
    send_telegram(f"Position closed ({current_position}).")

    current_position = None


def open_position(direction, price):
    global current_position, entry_price, trailing_active, entry_amount

    balance = 100  # backtest baseline
    amount = (balance * POSITION_SIZE_PERCENT * LEVERAGE) / price
    entry_amount = round(amount, 3)

    side = "buy" if direction == "LONG" else "sell"

    params = {
        "market": SYMBOL,
        "side": side,
        "type": "market",
        "amount": entry_amount,
        "client_id": str(int(time.time()))
    }

    coinex_request("/order/put_market", params)

    current_position = direction
    entry_price = price
    trailing_active = False

    send_telegram(
        f"NEW {direction}\nEntry: {price}\nLeverage: {LEVERAGE}x\nTP: {TP_PERCENT}%\nSL: {SL_PERCENT}%"
    )


############################################################
# TP / SL / TRAILING
############################################################

def check_tp_sl_trailing(current_price):
    global current_position, entry_price, trailing_active

    if current_position is None:
        return

    if current_position == "LONG":
        profit = ((current_price - entry_price) / entry_price) * 100
    else:
        profit = ((entry_price - current_price) / entry_price) * 100

    if not trailing_active and profit >= TRIGGER_TRAIL:
        trailing_active = True
        send_telegram("Trailing Activated")

    if profit >= TP_PERCENT:
        close_position()
        send_telegram("TP HIT")
        return

    if profit <= -SL_PERCENT:
        close_position()
        send_telegram("SL HIT")
        return

    if trailing_active and profit <= (TRIGGER_TRAIL - TRAIL_DISTANCE):
        close_position()
        send_telegram("TRAILING STOP HIT")
        return


############################################################
# STRATEGY — VERY STRONG MODEL
############################################################

def strategy():
    prices = get_klines()
    last = prices[-1]

    macd_line, signal_line = macd(prices)
    ema50 = ema(prices, 50)
    rsi_value = rsi(prices)

    print("MACD:", macd_line, "Signal:", signal_line, "RSI:", rsi_value)

    # BUY
    if macd_line > signal_line and last > ema50 and rsi_value > 50:
        return "BUY"

    # SELL
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
            check_tp_sl_trailing(price)

            sig = strategy()

            # OPEN LONG
            if sig == "BUY" and current_position != "LONG":
                close_position()
                open_position("LONG", price)

            # OPEN SHORT
            elif sig == "SELL" and current_position != "SHORT":
                close_position()
                open_position("SHORT", price)

        except Exception as e:
            print("Main Loop Error:", e)

        time.sleep(20)


############################################################
# HEARTBEAT
############################################################

def heartbeat():
    send_telegram("Heartbeat: Running")
    threading.Timer(300, heartbeat).start()


############################################################
# ROUTES
############################################################

@app.route("/")
def home():
    return "Bot Running"

@app.route("/status")
def status():
    return f"Position: {current_position}, LIVE={LIVE}"

@app.route("/test")
def test():
    send_telegram("Test OK")
    return "OK"


############################################################
# STARTUP
############################################################

if __name__ == "__main__":
    threading.Thread(target=main_loop).start()
    heartbeat()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
#########################################
# EXTRA ROUTES (STATUS + DEBUG + TOOLS)
#########################################

from flask import jsonify

@app.route("/")
def home():
    return "Bot is running — Model: M15 — Status: OK"

@app.route("/envcheck")
def envcheck():
    return jsonify({
        "API_KEY": "OK" if API_KEY else "Missing",
        "API_SECRET": "OK" if API_SECRET else "Missing",
        "TELEGRAM_TOKEN": "OK" if TELEGRAM_TOKEN else "Missing",
        "CHAT_ID": "OK" if CHAT_ID else "Missing"
    })

@app.route("/debug")
def debug():
    try:
        k = get_klines("BTCUSDT", "15m", 100)
        macd_line, signal_line = macd(k)
        rsi_value = rsi(k)
        ema50_value = ema(k, 50)

        return jsonify({
            "last_price": k[-1]["close"],
            "ema50": ema50_value,
            "macd": macd_line,
            "signal": signal_line,
            "rsi": rsi_value
        })
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/heartbeat")
def heartbeat():
    send_telegram("Heartbeat: Running")
    return "Heartbeat sent"
