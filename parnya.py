# ===========================
#   FUTURES PRO+ BOT — Version 2
#   Improved EMA + MACD (REAL)
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
# ===========================
#   FUTURES PRO+ BOT — Version 2
#   Improved EMA + MACD (REAL)
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
        closes = [float(c[2]) for c in data]
        highs  = [float(c[3]) for c in data]
        lows   = [float(c[4]) for c in data]
        return np.array(closes), np.array(highs), np.array(lows)
    except:
        return None, None, None

# ===========================
#   REAL EMA
# ===========================
def EMA(series, period):
    ema = []
    k = 2 / (period + 1)
    ema.append(np.mean(series[:period]))
    for price in series[period:]:
        ema.append((price - ema[-1]) * k + ema[-1])
    return np.array(ema)

# ===========================
#   RSI (Wilder's)
# ===========================
def RSI(closes, period=14):
    delta = np.diff(closes)
    up = np.where(delta > 0, delta, 0)
    down = np.where(delta < 0, -delta, 0)

    roll_up = np.mean(up[:period])
    roll_down = np.mean(down[:period])
    rsi_list = []

    rsi = 100 - (100 / (1 + (roll_up / (roll_down + 1e-9))))
    rsi_list.append(rsi)

    for i in range(period, len(delta)):
        roll_up = (roll_up * (period - 1) + up[i]) / period
        roll_down = (roll_down * (period - 1) + down[i]) / period
        rsi = 100 - (100 / (1 + (roll_up / (roll_down + 1e-9))))
        rsi_list.append(rsi)

    return np.array(rsi_list)

# ===========================
#   MACD (REAL)
# ===========================
def MACD(closes):
    ema12 = EMA(closes, 12)
    ema26 = EMA(closes, 26)

    macd_line = ema12[-len(ema26):] - ema26
    signal_line = EMA(macd_line, 9)
    hist = macd_line[-1] - signal_line[-1]

    return macd_line[-1], signal_line[-1], hist

# ===========================
#   ATR (REAL)
# ===========================
def ATR(highs, lows, closes, period=14):
    tr = np.maximum(highs[1:], closes[:-1]) - np.minimum(lows[1:], closes[:-1])
    atr = EMA(tr, period)
    return atr[-1]

# ===========================
#   SIGNAL ENGINE (PRO MODE V2)
# ===========================
def generate_signal():
    closes, highs, lows = get_klines()
    if closes is None:
        return None

    price = closes[-1]

    ema20  = EMA(closes, 20)[-1]
    ema50  = EMA(closes, 50)[-1]
    rsi14  = RSI(closes, 14)[-1]
    macd, macd_signal, macd_hist = MACD(closes)
    atr14 = ATR(highs, lows, closes, 14)

    trend_up = ema20 > ema50
    trend_down = ema20 < ema50

    buy = (
        trend_up and
        macd > macd_signal and
        macd_hist > 0 and
        45 < rsi14 < 70
    )

    sell = (
        trend_down and
        macd < macd_signal and
        macd_hist < 0 and
        30 < rsi14 < 55
    )

    if buy or sell:
        return {
            "signal": "BUY" if buy else "SELL",
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
#   PART 2 – TRADE ENGINE
# ===========================

API_KEY = os.getenv("API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
BASE_URL = "https://api.coinex.com/perpetual/v1"

current_position = None
entry_price = None
position_size = 0
trailing_active = False
trailing_price = None
last_signal_time = 0

def send_telegram(msg):
    print("TELEGRAM OFF:", msg)

import hmac, hashlib

def sign_request(params):
    sorted_params = "&".join([f"{k}={v}" for k,v in sorted(params.items())])
    return hashlib.md5((sorted_params + SECRET_KEY).encode()).hexdigest()

def get_balance():
    try:
        url = f"{BASE_URL}/asset/query"
        params = {
            "access_id": API_KEY,
            "timestamp": int(time.time()*1000)
        }
        params["sign"] = sign_request(params)
        r = requests.get(url, params=params, timeout=5).json()
        return float(r["data"]["assets"][0]["available"])
    except:
        return 0

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

def close_position():
    global current_position, position_size
    if current_position == "LONG":
        place_order("sell", position_size)
    elif current_position == "SHORT":
        place_order("buy", position_size)
    current_position = None
    position_size = 0

def open_position(direction, price, atr):
    global current_position, entry_price, trailing_active, trailing_price, position_size
    balance = get_balance()
    if balance <= 1:
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

def trailing_system(current_price, atr):
    global trailing_price, trailing_active

    if not trailing_active:
        return False

    if current_position == "LONG":
        if current_price - atr > trailing_price:
            trailing_price = current_price - atr
        if current_price < trailing_price:
            return True

    if current_position == "SHORT":
        if current_price + atr < trailing_price:
            trailing_price = current_price + atr
        if current_price > trailing_price:
            return True

    return False

def execute_trade(signal):
    global current_position, entry_price, last_signal_time

    if time.time() - last_signal_time < 30:
        return
    last_signal_time = time.time()

    action = signal["signal"]
    price = signal["price"]
    atr = signal["atr"]

    if current_position is not None:
        if trailing_system(price, atr):
            close_position()
            return

    if action == "BUY":
        if current_position == "SHORT":
            close_position()
        if current_position is None:
            open_position("BUY", price, atr)

    elif action == "SELL":
        if current_position == "LONG":
            close_position()
        if current_position is None:
            open_position("SELL", price, atr)

# ===========================
#   PART 3 – SERVER + LOOP
# ===========================

from flask import Flask, jsonify
import threading

bot_running = True
last_heartbeat_time = 0
HEARTBEAT_INTERVAL = 600

app = Flask(__name__)
start_time = datetime.now()

def bot_loop():
    global bot_running, last_heartbeat_time
    print("Bot loop started.")
    while bot_running:
        try:
            now = time.time()
            if now - last_heartbeat_time > HEARTBEAT_INTERVAL:
                closes,_,_ = get_klines()
                if closes is not None:
                    print("HB:", closes[-1])
                last_heartbeat_time = now

            signal = generate_signal()
            if signal:
                execute_trade(signal)

            time.sleep(30)

        except Exception as e:
            print("Error:", e)
            time.sleep(60)

    print("Bot loop stopped.")

@app.route("/")
def home():
    status = "Running" if bot_running else "Stopped"
    return f"Ultra PRO++ Render Bot V2 – Status: {status}"

@app.route("/status")
def status():
    return jsonify({
        "status": "Running" if bot_running else "Stopped",
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
    return "Bot stopping..."

@app.route("/start")
def start_bot():
    global bot_running
    if not bot_running:
        bot_running = True
        threading.Thread(target=bot_loop).start()
        return "Bot starting..."
    return "Already running"

if __name__ == "__main__":
    threading.Thread(target=bot_loop, daemon=True).start()
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
