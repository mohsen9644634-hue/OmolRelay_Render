# ===========================
#   FUTURES PRO+ BOT (PART 1)
#   Indicators + Signal Engine
#   M15 – MACD/EMA/RSI/ATR
#   Ultra PRO+ REAL MODE
# ===========================

import os
import time
import requests
import numpy as np
from datetime import datetime

PAIR = "BTCUSDT"
TIMEFRAME = "15min"

# ===========================
#   FETCH KLINES (SPOT)
# ===========================
def get_klines():
    try:
        url = f"https://api.coinex.com/v1/market/kline?market={PAIR}&type={TIMEFRAME}&limit=120"
        r = requests.get(url, timeout=5).json()
        data = r["data"]["kline"]
        closes = [float(c[2]) for c in data]  # close price
        highs  = [float(c[3]) for c in data]
        lows   = [float(c[4]) for c in data]
        return np.array(closes), np.array(highs), np.array(lows)
    except:
        return None, None, None

# ===========================
#   EMA FUNCTION
# ===========================
def EMA(series, period):
    return np.convolve(series, np.ones(period)/period, mode='valid')

# ===========================
#   RSI FUNCTION
# ===========================
def RSI(closes, period=14):
    delta = np.diff(closes)
    up = np.where(delta > 0, delta, 0)
    down = np.where(delta < 0, -delta, 0)
    avg_up = np.convolve(up, np.ones(period)/period, mode="valid")
    avg_down = np.convolve(down, np.ones(period)/period, mode="valid")
    rs = avg_up / (avg_down + 1e-9)
    rsi = 100 - (100 / (1 + rs))
    return rsi

# ===========================
#   MACD FUNCTION
# ===========================
def MACD(closes):
    ema12 = EMA(closes, 12)
    ema26 = EMA(closes, 26)
    macd_line = ema12[-len(ema26):] - ema26
    signal = EMA(macd_line, 9)
    hist = macd_line[-len(signal):] - signal
    return macd_line[-1], signal[-1], hist[-1]

# ===========================
#   ATR FUNCTION
# ===========================
def ATR(highs, lows, closes, period=14):
    tr = np.maximum(highs[1:], closes[:-1]) - np.minimum(lows[1:], closes[:-1])
    atr = EMA(tr, period)
    return atr[-1]

# ===========================
#   SIGNAL ENGINE (PRO MODE)
# ===========================
def generate_signal():
    closes, highs, lows = get_klines()
    if closes is None:
        return None

    price = closes[-1]

    # Indicators
    ema20  = EMA(closes, 20)[-1]
    ema50  = EMA(closes, 50)[-1]
    rsi14  = RSI(closes, 14)[-1]
    macd, macd_signal, macd_hist = MACD(closes)
    atr14 = ATR(highs, lows, closes, 14)

    trend_up = ema20 > ema50
    trend_down = ema20 < ema50

    # BUY
    buy = (
        trend_up and
        macd > macd_signal and
        macd_hist > 0 and
        45 < rsi14 < 70
    )

    # SELL
    sell = (
        trend_down and
        macd < macd_signal and
        macd_hist < 0 and
        30 < rsi14 < 55
    )

    if buy:
        return {
            "signal": "BUY",
            "price": price,
            "atr": atr14,
            "ema20": ema20,
            "ema50": ema50,
            "rsi": rsi14,
            "macd": macd,
            "macd_signal": macd_signal,
            "macd_hist": macd_hist
        }

    if sell:
        return {
            "signal": "SELL",
            "price": price,
            "atr": atr14,
            "ema20": ema20,
            "ema50": ema50,
            "rsi": rsi14,
            "macd": macd,
            "macd_signal": macd_signal,
            "macd_hist": macd_hist
        }

    return None

# ===========================
#   FUTURES PRO+ BOT (PART 2)
#   Trade Executor + REAL MODE
# ===========================

API_KEY = os.getenv("API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")  # unused now
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")  # unused now

BASE_URL = "https://api.coinex.com/perpetual/v1"

current_position = None
entry_price = None
position_size = 0
trailing_active = False
trailing_price = None
last_signal_time = 0

# ===========================
#   SEND TELEGRAM (DISABLED)
# ===========================
def send_telegram(msg):
    print("TELEGRAM OFF:", msg)  # FIXED
    return

# ===========================
#   AUTH SIGN FUNCTION
# ===========================
import hmac
import hashlib

def sign_request(params):
    sorted_params = "&".join([f"{k}={v}" for k,v in sorted(params.items())])
    to_sign = sorted_params + SECRET_KEY
    return hashlib.md5(to_sign.encode()).hexdigest()

# ===========================
#   FUTURES BALANCE
# ===========================
def get_balance():
    url = f"{BASE_URL}/asset/query"
    params = {
        "access_id": API_KEY,
        "timestamp": int(time.time()*1000)
    }
    params["sign"] = sign_request(params)
    r = requests.get(url, params=params, timeout=5).json()
    try:
        return float(r["data"]["assets"][0]["available"])
    except:
        return 0

# ===========================
#   PLACE ORDER
# ===========================
def place_order(side, amount):
    url = f"{BASE_URL}/order/put_market"

    params = {
        "access_id": API_KEY,
        "market": PAIR,
        "side": side,
        "amount": amount,
        "timestamp": int(time.time()*1000)
    }
    params["sign"] = sign_request(params)

    try:
        return requests.post(url, data=params, timeout=5).json()
    except:
        return None

# ===========================
#   CLOSE ANY OPEN ORDER
# ===========================
def close_position():
    global current_position, position_size

    if current_position == "LONG":
        place_order("sell", position_size)

    elif current_position == "SHORT":
        place_order("buy", position_size)

    current_position = None
    position_size = 0

# ===========================
#   START NEW POSITION
# ===========================
def open_position(direction, price, atr):
    global current_position, entry_price, trailing_active, trailing_price, position_size

    balance = get_balance()
    if balance <= 1:
        send_telegram("Low balance")  # remains harmless
        return

    position_size = round(balance * 0.8 / price * 15, 3)

    if direction == "BUY":
        place_order("buy", position_size)
        current_position = "LONG"

    elif direction == "SELL":
        place_order("sell", position_size)
        current_position = "SHORT"

    entry_price = price
    trailing_active = True
    trailing_price = entry_price + atr if current_position == "LONG" else entry_price - atr

    send_telegram("NEW POSITION OPENED")  # harmless

# ===========================
#   TRAILING SYSTEM
# ===========================
def trailing_system(current_price, atr):
    global trailing_price, trailing_active

    if not trailing_active:
        return False

    if current_position == "LONG":
        if current_price - atr > trailing_price:
            trailing_price = current_price - atr
        if current_price < trailing_price:
            send_telegram("Trailing (LONG)")
            return True

    if current_position == "SHORT":
        if current_price + atr < trailing_price:
            trailing_price = current_price + atr
        if current_price > trailing_price:
            send_telegram("Trailing (SHORT)")
            return True

    return False

# ===========================
#   MASTER EXECUTOR
# ===========================
def execute_trade(signal):
    global current_position, entry_price, last_signal_time

    if signal is None:
        return

    action = signal["signal"]
    price = signal["price"]
    atr = signal["atr"]

    if time.time() - last_signal_time < 30:
        return
    last_signal_time = time.time()

    if current_position is not None:
        hit = trailing_system(price, atr)
        if hit:
            close_position()
            send_telegram("Trailing closed")
            return

    if action == "BUY":
        if current_position == "SHORT":
            close_position()
            send_telegram("Reverse SHORT→LONG")
            open_position("BUY", price, atr)
            return
        if current_position is None:
            open_position("BUY", price, atr)
            return

    if action == "SELL":
        if current_position == "LONG":
            close_position()
            send_telegram("Reverse LONG→SHORT")
            open_position("SELL", price, atr)
            return
        if current_position is None:
            open_position("SELL", price, atr)
            return

# ===========================
#   PART 3 – SERVER + LOOP
# ===========================

from flask import Flask, jsonify, request
import threading
import sys
import time
import os
import requests
from datetime import datetime

bot_running = True
last_heartbeat_time = 0
HEARTBEAT_INTERVAL = 600

app = Flask(__name__)
start_time = datetime.now()

# ===========================
#   BOT LOOP
# ===========================
def bot_loop():
    global bot_running, last_heartbeat_time

    print("Bot loop started.")
    send_telegram("BOT STARTED")  # harmless

    while bot_running:
        try:
            now = time.time()
            if now - last_heartbeat_time > HEARTBEAT_INTERVAL:
                closes,_,_ = get_klines()
                if closes is not None:
                    send_telegram(f"Heartbeat {closes[-1]}")
                last_heartbeat_time = now

            signal = generate_signal()
            if signal:
                execute_trade(signal)

            time.sleep(30)

        except Exception as e:
            send_telegram(f"Error: {e}")
            print("Error:", e)
            time.sleep(60)

    send_telegram("BOT STOPPED")  # harmless
    print("Bot loop stopped.")

# ===========================
#   ROUTES
# ===========================
@app.route("/")
def home():
    status = "Running" if bot_running else "Stopped"
    return f"Ultra PRO++ Render Bot. Status: {status}"

@app.route("/status")
def status():
    status_text = "Running" if bot_running else "Stopped"
    return jsonify({
        "status": status_text,
        "uptime": str(datetime.now() - start_time),
        "current_position": current_position,
        "entry_price": entry_price,
        "position_size": position_size,
        "trailing_active": trailing_active,
        "trailing_price": trailing_price
    })

@app.route("/kill")
def kill_bot():
    global bot_running
    bot_running = False
    send_telegram("Kill command")  # harmless
    return "Bot stopping..."

@app.route("/start")
def start_bot():
    global bot_running
    if not bot_running:
        bot_running = True
        threading.Thread(target=bot_loop).start()
        send_telegram("Start command")  # harmless
        return "Bot starting..."
    return "Already running"

# ===========================
#   REMOVED TELEGRAM WEBHOOK
# ===========================
# FIXED: Entire /telegram route removed

# ===========================
#   MAIN ENTRY
# ===========================
if __name__ == "__main__":
    start_time = datetime.now()

    t = threading.Thread(target=bot_loop)
    t.daemon = True
    t.start()

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
