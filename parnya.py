import sys
import os
import time
import hmac
import hashlib
import requests
import threading
from flask import Flask, request

app = Flask(__name__)
@app.route("/test")
def test():
    send_telegram("Test OK from Render")
    return "Telegram test sent"

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

current_position = None
entry_price = None
trailing_active = False

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        params = {"chat_id": CHAT_ID, "text": msg}
        r = requests.get(url, params=params)

        print("Telegram status:", r.status_code)
        print("Telegram response:", r.text)
        sys.stdout.flush()

    except Exception as e:
        print("Telegram send error:", str(e))
        sys.stdout.flush()

def coinex_sign(params):
    sorted_params = "".join([f"{k}{params[k]}" for k in sorted(params)])
    sign = hashlib.md5((sorted_params + API_SECRET).encode()).hexdigest()
    return sign

def coinex_request(path, params):
    base = "https://api.coinex.com/perpetual/v1"
    params["access_id"] = API_KEY
    params["timestamp"] = int(time.time() * 1000)
    sign = coinex_sign(params)
    headers = {"Content-Type": "application/json", "Authorization": sign}
    return requests.post(base + path, json=params, headers=headers).json()

def get_price():
    r = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT")
    return float(r.json()["price"])

def get_klines():
    url = "https://api.binance.com/api/v3/klines"
    r = requests.get(url, params={"symbol": SYMBOL, "interval": "5m", "limit": 120})
    closes = [float(k[4]) for k in r.json()]
    return closes

def calc_macd(prices):
    def ema(data, period):
        k = 2 / (period + 1)
        ema_val = data[0]
        for p in data[1:]:
            ema_val = p * k + ema_val * (1 - k)
        return ema_val

    macd_line = ema(prices, 12) - ema(prices, 26)
    signal = ema(prices, 9)
    return macd_line, signal

def calc_rsi(prices, period=14):
    gains = []
    losses = []
    for i in range(1, period + 1):
        diff = prices[-i] - prices[-i - 1]
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

def close_position():
    global current_position
    if not current_position:
        return

    side = "sell" if current_position == "LONG" else "buy"

    params = {
        "market": SYMBOL,
        "side": side,
        "type": "market",
        "amount": 0,
        "client_id": str(int(time.time()))
    }

    coinex_request("/order/put_market", params)
    send_telegram("پوزیشن قبلی بسته شد.")
    current_position = None

def open_position(direction, price):
    global current_position, entry_price, trailing_active

    balance = 100
    amount = (balance * POSITION_SIZE_PERCENT * LEVERAGE) / price

    side = "buy" if direction == "LONG" else "sell"

    params = {
        "market": SYMBOL,
        "side": side,
        "type": "market",
        "amount": round(amount, 3),
        "client_id": str(int(time.time()))
    }

    coinex_request("/order/put_market", params)

    current_position = direction
    entry_price = price
    trailing_active = False

    send_telegram(
        f"پوزیشن باز شد\n"
        f"نوع: {direction}\n"
        f"قیمت ورود: {price}\n"
        f"لوریج: {LEVERAGE}x\n"
        f"TP: {TP_PERCENT}%\n"
        f"SL: {SL_PERCENT}%\n"
        f"Trailing بعد از {TRIGGER_TRAIL}% فعال می‌شود"
    )

def check_tp_sl_trailing(current_price):
    global current_position, entry_price, trailing_active

    if not current_position:
        return

    if current_position == "LONG":
        profit_percent = ((current_price - entry_price) / entry_price) * 100
    else:
        profit_percent = ((entry_price - current_price) / entry_price) * 100

    if not trailing_active and profit_percent >= TRIGGER_TRAIL:
        trailing_active = True
        send_telegram("Trailing Stop فعال شد.")

    if profit_percent >= TP_PERCENT:
        close_position()
        send_telegram(f"پوزیشن در سود {TP_PERCENT}% بسته شد.")
        return

    if profit_percent <= -SL_PERCENT:
        close_position()
        send_telegram(f"پوزیشن در ضرر {SL_PERCENT}% بسته شد.")
        return

    if trailing_active and profit_percent <= (TRIGGER_TRAIL - TRAIL_DISTANCE):
        close_position()
        send_telegram("Trailing Stop پوزیشن را بست.")

def strategy():
    prices = get_klines()
    macd_line, macd_signal = calc_macd(prices)
    rsi = calc_rsi(prices)

    if macd_line > macd_signal and rsi > 45:
        return "BUY"

    if macd_line < macd_signal and rsi < 55:
        return "SELL"

    return "NONE"

def main_loop():
    while True:
        price = get_price()
        check_tp_sl_trailing(price)
        sig = strategy()

        if sig == "BUY" and current_position != "LONG":
            close_position()
            open_position("LONG", price)

        elif sig == "SELL" and current_position != "SHORT":
            close_position()
            open_position("SHORT", price)

        time.sleep(20)

def heartbeat():
    send_telegram("Heartbeat: ربات فعال است.")
    threading.Timer(300, heartbeat).start()
    
@app.route("/status")
def status():
    return "Bot is running"
    
@app.route("/telegram")
def telegram_route():
    text = request.args.get("text", "")
    if not text:
        return "Error: text parameter required", 400
    send_telegram(text)
    return "Message sent"

if __name__ == "__main__":
    threading.Thread(target=main_loop).start()
    heartbeat()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))


