import sys
import os
import time
import hashlib
import requests
import threading
from flask import Flask, request

############################################################
# CONFIG
############################################################

# Toggle switch for real trading
LIVE = False   # Set to True to enable real orders

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
BINANCE_LIMIT = 120

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
# COINEX AUTH
############################################################

def coinex_sign(params: dict):
    sorted_params = "".join([f"{k}{params[k]}" for k in sorted(params)])
    return hashlib.md5((sorted_params + API_SECRET).encode()).hexdigest()

def coinex_request(path, params):
    if not LIVE:
        print("LIVE = False → Order blocked (simulation mode).")
        return {"code": 0, "message": "Simulated - LIVE=False"}

    base = "https://api.coinex.com/perpetual/v1"
    params["access_id"] = API_KEY
    params["timestamp"] = int(time.time() * 1000)
    sign = coinex_sign(params)
    headers = {"Content-Type": "application/json", "Authorization": sign}
    r = requests.post(base + path, json=params, headers=headers).json()
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
    return [float(k[4]) for k in r.json()]


############################################################
# INDICATORS
############################################################

def ema(data, period):
    k = 2 / (period + 1)
    val = data[0]
    for p in data[1:]:
        val = p * k + val * (1 - k)
    return val

def calculate_macd(data):
    fast = ema(data, 12)
    slow = ema(data, 26)
    macd_line = fast - slow
    signal_line = ema(data, 9)
    return macd_line, signal_line

def calculate_rsi(data, period=14):
    gains = []
    losses = []
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
# TRADING FUNCTIONS
############################################################

def close_position():
    global current_position, entry_amount
    if current_position is None:
        return

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

    balance = 100
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
        f"NEW {direction}\n"
        f"Entry: {price}\n"
        f"Leverage: {LEVERAGE}x\n"
        f"TP: {TP_PERCENT}%\n"
        f"SL: {SL_PERCENT}%\n"
        f"Trailing @ {TRIGGER_TRAIL}%"
    )


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
        send_telegram("Trailing activated.")

    if profit >= TP_PERCENT:
        close_position()
        send_telegram("TP hit.")
        return

    if profit <= -SL_PERCENT:
        close_position()
        send_telegram("SL hit.")
        return

    if trailing_active and profit <= (TRIGGER_TRAIL - TRAIL_DISTANCE):
        close_position()
        send_telegram("Trailing stop triggered.")
        return


############################################################
# STRATEGY
############################################################

def strategy():
    prices = get_klines()

    macd_line, macd_signal = calculate_macd(prices)
    rsi = calculate_rsi(prices)
    ema50 = ema(prices, 50)
    last = prices[-1]

    if macd_line > macd_signal and last > ema50 and rsi > 48:
        return "BUY"

    if macd_line < macd_signal and last < ema50 and rsi < 52:
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

            if sig == "BUY" and current_position != "LONG":
                close_position()
                open_position("LONG", price)

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
    send_telegram("Heartbeat: Running.")
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
    send_telegram("Test OK.")
    return "OK"


############################################################
# STARTUP
############################################################

if __name__ == "__main__":
    threading.Thread(target=main_loop).start()
    heartbeat()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))

