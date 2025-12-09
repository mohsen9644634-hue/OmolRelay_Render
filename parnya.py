import time
import hmac
import hashlib
import requests
import threading
import os
import math
from flask import Flask, jsonify

API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")

BASE = "https://api.coinex.com/perpetual/v1"
pair = "BTCUSDT"

LIVE = True
LEVERAGE = 10
USE_CAPITAL = 0.8

bot_running = False
current_position = None  # LONG / SHORT / None
entry_price = None
trail_active = False
breakeven_done = False

app = Flask(__name__)

# ----------------------------------------------------------
# SIGN
# ----------------------------------------------------------
def sign(params):
    keys = sorted(params.keys())
    query = "&".join([f"{k}={params[k]}" for k in keys])
    raw = query + "&secret_key=" + API_SECRET
    return hashlib.md5(raw.encode()).hexdigest()

# ----------------------------------------------------------
# PRICE
# ----------------------------------------------------------
def get_price():
    url = "https://api.coinex.com/perpetual/v1/market/ticker"
    r = requests.get(url, params={"market": pair}).json()
    return float(r["data"]["ticker"]["last"])

# ----------------------------------------------------------
# BALANCE
# ----------------------------------------------------------
def get_balance():
    url = BASE + "/asset/query"
    p = {"access_id": API_KEY, "timestamp": int(time.time()*1000)}
    p["signature"] = sign(p)
    r = requests.get(url, params=p).json()
    try:
        return float(r["data"]["USDT"]["available_balance"])
    except:
        return 0

# ----------------------------------------------------------
# POSITIONS
# ----------------------------------------------------------
def get_positions():
    url = BASE + "/position/pending"
    p = {"access_id": API_KEY, "market": pair, "timestamp": int(time.time()*1000)}
    p["signature"] = sign(p)
    r = requests.get(url, params=p).json()
    return r

# ----------------------------------------------------------
# OHLC
# ----------------------------------------------------------
def get_ohlc():
    url = "https://api.coinex.com/perpetual/v1/market/kline"
    r = requests.get(url, params={"market": pair, "type": "15min", "limit": 200}).json()
    return r["data"]

# ----------------------------------------------------------
# EMA
# ----------------------------------------------------------
def ema(values, period):
    k = 2 / (period + 1)
    ema_values = [values[0]]
    for v in values[1:]:
        ema_values.append(v * k + ema_values[-1] * (1 - k))
    return ema_values[-1]

# ----------------------------------------------------------
# MACD
# ----------------------------------------------------------
def macd(candles):
    closes = [float(c[2]) for c in candles]
    ema12 = ema(closes, 12)
    ema26 = ema(closes, 26)
    macd_line = ema12 - ema26
    signal = ema([macd_line]*9, 9)
    hist = macd_line - signal
    return macd_line, signal, hist

# ----------------------------------------------------------
# RSI
# ----------------------------------------------------------
def rsi(candles, period=14):
    closes = [float(c[2]) for c in candles]
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(max(diff, 0))
        losses.append(abs(min(diff, 0)))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

# ----------------------------------------------------------
# ATR
# ----------------------------------------------------------
def atr(candles, period=14):
    trs = []
    for i in range(1, len(candles)):
        h = float(candles[i][0])
        l = float(candles[i][1])
        c_prev = float(candles[i-1][2])
        tr = max(h-l, abs(h-c_prev), abs(l-c_prev))
        trs.append(tr)
    return sum(trs[-period:]) / period

# ----------------------------------------------------------
# OPEN ORDER
# ----------------------------------------------------------
def open_position(direction):
    global current_position, entry_price, breakeven_done, trail_active

    if current_position is not None:
        print("❌ Position exists. Anti-double-order activated.")
        return

    balance = get_balance()
    price = get_price()

    capital = balance * USE_CAPITAL
    qty = round((capital * LEVERAGE) / price, 3)
    if qty < 0.001:
        qty = 0.001

    p = {
        "access_id": API_KEY,
        "market": pair,
        "type": "market",
        "amount": qty,
        "side": direction,
        "leverage": LEVERAGE,
        "timestamp": int(time.time()*1000),
    }

    p["signature"] = sign(p)
    url = BASE + "/order/put_market"
    r = requests.post(url, data=p).json()

    print("REAL FUTURES ORDER SENT:", direction, qty, r)

    current_position = "LONG" if direction=="buy" else "SHORT"
    entry_price = price
    breakeven_done = False
    trail_active = False

# ----------------------------------------------------------
# CLOSE ALL
# ----------------------------------------------------------
def close_all():
    global current_position, trail_active, breakeven_done
    p = {
        "access_id": API_KEY,
        "market": pair,
        "timestamp": int(time.time()*1000),
    }
    p["signature"] = sign(p)
    url = BASE + "/position/close_market"
    r = requests.post(url, data=p).json()
    print("CLOSE ALL RESULT:", r)
    current_position = None
    trail_active = False
    breakeven_done = False

# ----------------------------------------------------------
# TP / SL / Trailing / Breakeven
# ----------------------------------------------------------
def risk_manager():
    global current_position, entry_price, trail_active, breakeven_done

    if current_position is None:
        return

    price = get_price()
    candles = get_ohlc()
    a = atr(candles)

    sl = entry_price - 1.5*a if current_position=="LONG" else entry_price + 1.5*a
    tp = entry_price + 3*a if current_position=="LONG" else entry_price - 3*a

    if not breakeven_done:
        if current_position=="LONG" and price >= entry_price + 1.2*a:
            entry_price = price
            breakeven_done = True
            print("BREAKEVEN ✔ moved entry")
        if current_position=="SHORT" and price <= entry_price - 1.2*a:
            entry_price = price
            breakeven_done = True
            print("BREAKEVEN ✔ moved entry")

    if not trail_active and breakeven_done:
        trail_active = True
        print("TRAILING ACTIVATED ✔")

    if trail_active:
        if current_position=="LONG":
            if price <= entry_price - 0.8*a:
                print("TRAIL HIT SL ✔")
                close_all()
        if current_position=="SHORT":
            if price >= entry_price + 0.8*a:
                print("TRAIL HIT SL ✔")
                close_all()

    if current_position=="LONG":
        if price <= sl:
            print("HIT HARD SL ❌")
            close_all()
        if price >= tp:
            print("TP SUCCESS ✔✔✔")
            close_all()

    if current_position=="SHORT":
        if price >= sl:
            print("HIT HARD SL ❌")
            close_all()
        if price <= tp:
            print("TP SUCCESS ✔✔✔")
            close_all()

# ----------------------------------------------------------
# SUPERSIGNAL V3
# ----------------------------------------------------------
def super_signal():
    candles = get_ohlc()
    price = get_price()

    ema20_ = ema([float(c[2]) for c in candles], 20)
    ema50_ = ema([float(c[2]) for c in candles], 50)
    macd_line, macd_signal, hist = macd(candles)
    r = rsi(candles)
    a = atr(candles)

    c0 = candles[-1]
    c1 = candles[-2]

    pump = abs(float(c0[2]) - float(c1[2]))
    if pump > 2*a:
        print("ANTI PUMP/DUMP ACTIVE ❌")
        return None

    if ema20_ > ema50_ and hist > 0 and 48 < r < 67:
        return "LONG"
    if ema20_ < ema50_ and hist < 0 and 33 < r < 52:
        return "SHORT"

    return None

# ----------------------------------------------------------
# BOT LOOP
# ----------------------------------------------------------
def bot_loop():
    global bot_running
    print("CONNECTED TO COINEX FUTURES ✔")
    print("Balance:", get_balance())

    while bot_running:
        try:
            print("Heartbeat ✔ Price:", get_price())

            risk_manager()

            if current_position is None:
                signal = super_signal()
                if signal == "LONG":
                    open_position("buy")
                elif signal == "SHORT":
                    open_position("sell")

            time.sleep(5)
        except Exception as e:
            print("ERROR:", e)
            time.sleep(2)

# ----------------------------------------------------------
# FLASK
# ----------------------------------------------------------
@app.route("/start")
def start():
    global bot_running
    if not bot_running:
        bot_running = True
        threading.Thread(target=bot_loop).start()
        return jsonify({"status": "Bot started"})
    return jsonify({"status": "Already running"})

@app.route("/kill")
def kill():
    global bot_running
    bot_running = False
    return jsonify({"status": "Bot stopped"})

@app.route("/status")
def status():
    return jsonify({
        "running": bot_running,
        "position": current_position,
        "entry_price": entry_price
    })

@app.route("/close")
def close():
    close_all()
    return jsonify({"status": "positions closed"})

@app.route("/positions")
def pos():
    return jsonify(get_positions())

# ----------------------------------------------------------
# MAIN
# ----------------------------------------------------------
if __name__ == "__main__":
    from waitress import serve
    port = int(os.environ.get("PORT", 10000))
    serve(app, host="0.0.0.0", port=port)

