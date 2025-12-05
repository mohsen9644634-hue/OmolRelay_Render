import sys
import os
import time
import json
import hashlib
import requests
import threading
from flask import Flask, request, jsonify # Added jsonify

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
        print(f"Telegram message sent: {msg}") # Added print for debugging
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
    if len(data) < period: # Added check for sufficient data
        return data[-1] # or handle error
    k = 2 / (period + 1)
    # Ensure starting average is based on 'period' data points
    val = sum(data[:period]) / period
    for p in data[period:]:
        val = p * k + val * (1 - k)
    return val


def macd(data):
    if len(data) < 26: # Need at least 26 data points for EMA26
        return 0, 0 # Or handle error appropriately
    ema12 = ema(data, 12)
    ema26 = ema(data, 26)
    macd_line = ema12 - ema26

    # Signal line = EMA9 of historical MACD
    macd_history = []
    # Generate MACD values for a sufficient history to calculate EMA9
    # This part was already reasonably implemented in your code
    for i in range(len(data) - 26, len(data)): # Iterate from earliest point that allows EMA26 to latest
        if i >= 25: # Ensure there's enough data for both EMAs
            current_ema12 = ema(data[:i+1], 12)
            current_ema26 = ema(data[:i+1], 26)
            macd_history.append(current_ema12 - current_ema26)
    
    # Take the last 9 MACD values if fewer than 9 are generated
    if len(macd_history) < 9:
        signal_line = 0 # Not enough history for signal line, or handle differently
    else:
        signal_line = ema(macd_history[-9:], 9) # EMA of last 9 MACD values

    return macd_line, signal_line


def rsi(data, period=14):
    if len(data) < period + 1: # Need at least period + 1 data points
        return 50 # Default to 50 if not enough data
    
    # Your current RSI calculation (simple average)
    gains, losses = [], []
    for i in range(1, period + 1):
        diff = data[-i] - data[-i - 1]
        if diff >= 0:
            gains.append(diff)
        else:
            losses.append(abs(diff))

    avg_gain = sum(gains) / period if gains else 0
    avg_loss = sum(losses) / period if losses else 0
    
    if avg_loss == 0:
        return 100 if avg_gain > 0 else 50 # If no losses, RSI is 100 (or 50 if no gains either)
    
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

# Note: For accurate Wilder's RSI, the calculation needs to track previous avg_gain and avg_loss
# and apply smoothing: new_avg_gain = (prev_avg_gain * (period - 1) + current_gain) / period
# This current implementation is a simple SMA-based RSI.


############################################################
# TRADING ACTIONS
############################################################

def close_position():
    global current_position, entry_amount
    if current_position is None:
        print("[CLOSE] No position to close.") # Added print
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
    entry_amount = None # Reset entry amount

def open_position(direction, price):
    global current_position, entry_price, trailing_active, entry_amount

    if current_position is not None:
        print(f"[OPEN] Already in a {current_position} position.") # Added print
        return # Prevent opening a new position if one is already open

    # TODO: Fetch actual balance from CoinEx API for LIVE trading
    balance = 100  # <<< WARNING: This is a fixed backtest baseline, not live balance!
    amount = (balance * POSITION_SIZE_PERCENT * LEVERAGE) / price
    entry_amount = round(amount, 3) # Make sure this is within CoinEx's min/max limits

    side = "buy" if direction == "LONG" else "sell"

    params = {
        "market": SYMBOL,
        "side": side,
        "type": "market",
        "amount": entry_amount,
        "client_id": str(int(time.time()))
    }

    response = coinex_request("/order/put_market", params)
    
    # Only update position if order was successful
    if response and response.get('code') == 0: # Assuming 'code': 0 means success
        current_position = direction
        entry_price = price
        trailing_active = False

        send_telegram(
            f"NEW {direction}\nEntry: {price}\nLeverage: {LEVERAGE}x\nTP: {TP_PERCENT}%\nSL: {SL_PERCENT}%"
        )
    else:
        print(f"Failed to open {direction} position: {response}")


############################################################
# TP / SL / TRAILING
############################################################

def check_tp_sl_trailing(current_price):
    global current_position, entry_price, trailing_active

    if current_position is None or entry_price is None: # Added check for entry_price
        return

    if current_position == "LONG":
        profit = ((current_price - entry_price) / entry_price) * 100
    else: # current_position == "SHORT"
        profit = ((entry_price - current_price) / entry_price) * 100

    if not trailing_active and profit >= TRIGGER_TRAIL:
        trailing_active = True
        send_telegram("Trailing Activated")

    if profit >= TP_PERCENT:
        send_telegram("TP HIT") # Send message BEFORE closing
        close_position()
        return

    if profit <= -SL_PERCENT:
        send_telegram("SL HIT") # Send message BEFORE closing
        close_position()
        return

    if trailing_active and profit <= (TRIGGER_TRAIL - TRAIL_DISTANCE):
        send_telegram("TRAILING STOP HIT") # Send message BEFORE closing
        close_position()
        return


############################################################
# STRATEGY — VERY STRONG MODEL
############################################################

def strategy():
    prices = get_klines()
    if not prices: # Handle case where klines is empty
        print("Strategy Error: No klines data available.")
        return "NONE"

    last = prices[-1]

    macd_line, signal_line = macd(prices)
    ema50 = ema(prices, 50)
    rsi_value = rsi(prices)

    print("MACD:", macd_line, "Signal:", signal_line, "RSI:", rsi_value, "Last Price:", last) # Added last price for debug

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
                close_position() # Close any existing position first
                open_position("LONG", price)

            # OPEN SHORT
            elif sig == "SELL" and current_position != "SHORT":
                close_position() # Close any existing position first
                open_position("SHORT", price)

        except Exception as e:
            print("Main Loop Error:", e)
            sys.stdout.flush() # Flush print statements immediately

        time.sleep(20)


############################################################
# PERIODIC HEARTBEAT (New name to avoid conflict)
############################################################

def periodic_heartbeat(): # Renamed to avoid conflict
    send_telegram("Heartbeat: Bot is alive and well!")
    # Reschedule itself
    threading.Timer(300, periodic_heartbeat).start()


############################################################
# ROUTES
############################################################

# Renamed the main "/" route for clarity and removed the duplicate
@app.route("/")
def home_status():
    return "Bot is running — Model: M15 — Status: OK"

@app.route("/status")
def status():
    return f"Position: {current_position}, LIVE={LIVE}"

@app.route("/test")
def test():
    send_telegram("Test OK")
    return "OK"

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
        # Corrected get_klines call (no args)
        k = get_klines()
        if not k:
            return jsonify({"error": "No klines data available for debug."})
            
        macd_line, signal_line = macd(k)
        rsi_value = rsi(k)
        ema50_value = ema(k, 50)

        return jsonify({
            "last_price": k[-1], # Corrected access to last price (it's a float)
            "ema50": ema50_value,
            "macd": macd_line,
            "signal": signal_line,
            "rsi": rsi_value,
            "current_position": current_position, # Added current position
            "entry_price": entry_price # Added entry price
        })
    except Exception as e:
        print("Debug Route Error:", e) # Print error for server logs
        return jsonify({"error": str(e)}), 500 # Return 500 for server errors

# Renamed the heartbeat route function to avoid conflict with the periodic_heartbeat function
@app.route("/heartbeat")
def send_heartbeat_response(): 
    send_telegram("Heartbeat route triggered: Bot is alive.")
    return "Heartbeat sent via route"


############################################################
# STARTUP
############################################################

if __name__ == "__main__":
    threading.Thread(target=main_loop, daemon=True).start() # daemon=True ensures thread exits with main app
    periodic_heartbeat() # Call the correctly named periodic heartbeat
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
