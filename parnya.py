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

    # ===========================
    #   BUY LOGIC – PRO MODE
    # ===========================
    buy = (
        trend_up and
        macd > macd_signal and
        macd_hist > 0 and
        45 < rsi14 < 70
    )

    # ===========================
    #   SELL LOGIC – PRO MODE
    # ===========================
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
#   Auto Position + Trailing TP
# ===========================

API_KEY = os.getenv("API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

BASE_URL = "https://api.coinex.com/perpetual/v1"

current_position = None     # "LONG" or "SHORT" or None
entry_price = None
position_size = 0
trailing_active = False
trailing_price = None       # آخرین قیمت دنبال‌کننده سود
last_signal_time = 0        # جلوگیری از اسپم

# ===========================
#   SEND TELEGRAM MESSAGE
# ===========================
def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = {"chat_id": CHAT_ID, "text": msg}
        requests.post(url, data=data, timeout=5)
    except:
        pass

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
#   PLACE ORDER (REAL MODE)
# ===========================
def place_order(side, amount):
    url = f"{BASE_URL}/order/put_market"

    params = {
        "access_id": API_KEY,
        "market": PAIR,
        "side": side,         # buy یا sell
        "amount": amount,
        "timestamp": int(time.time()*1000)
    }
    params["sign"] = sign_request(params)

    try:
        r = requests.post(url, data=params, timeout=5).json()
        return r
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
        send_telegram("❗ بالانس کافی نیست")
        return

    # 80% موجودی
    position_size = round(balance * 0.8 / price * 15, 3)

    # اجرای سفارش
    if direction == "BUY":
        place_order("buy", position_size)
        current_position = "LONG"

    elif direction == "SELL":
        place_order("sell", position_size)
        current_position = "SHORT"

    entry_price = price
    trailing_active = True

    # فاصله شروع Trailing
    trailing_price = entry_price + atr if current_position == "LONG" else entry_price - atr

    send_telegram(f"""
🚀 پوزیشن جدید باز شد

نوع: {current_position}
ورود: {price}
ATR: {atr}
اندازه: {position_size}
Leverage: 15x
Trailing SL فعال شد
""")

# ===========================
#   TRAILING STOP SYSTEM
# ===========================
def trailing_system(current_price, atr):
    global trailing_price, trailing_active

    if not trailing_active:
        return False

    # LONG
    if current_position == "LONG":
        # اگر قیمت بالاتر رفت، تریلینگ هم بالا بیاید
        if current_price - atr > trailing_price:
            trailing_price = current_price - atr

        # اگر قیمت برگشت و SL فعال شد
        if current_price < trailing_price:
            send_telegram("🟡 Trailing SL (LONG) فعال شد")
            return True

    # SHORT
    if current_position == "SHORT":
        if current_price + atr < trailing_price:
            trailing_price = current_price + atr

        if current_price > trailing_price:
            send_telegram("🟡 Trailing SL (SHORT) فعال شد")
            return True

    return False

# ===========================
#   MASTER TRADE HANDLER
# ===========================
def execute_trade(signal):
    global current_position, entry_price, last_signal_time

    if signal is None:
        return

    action = signal["signal"]
    price = signal["price"]
    atr = signal["atr"]

    # ضد اسپم
    if time.time() - last_signal_time < 30:
        return
    last_signal_time = time.time()

    # اگر پوزیشن باز داریم → Trailing SL چک شود
    if current_position is not None:
        hit = trailing_system(price, atr)
        if hit:
            close_position()
            send_telegram("🔻 پوزیشن بسته شد (Trailing)")
            return

    # اگر BUY آمد ولی SHORT بودیم → معکوس کن
    if action == "BUY":
        if current_position == "SHORT":
            close_position()
            send_telegram("🔄 معکوس SHORT → LONG")
            open_position("BUY", price, atr)
            return

        if current_position is None:
            open_position("BUY", price, atr)
            return

    # اگر SELL آمد ولی LONG بودیم → معکوس کن
    if action == "SELL":
        if current_position == "LONG":
            close_position()
            send_telegram("🔄 معکوس LONG → SHORT")
            open_position("SELL", price, atr)
            return

        if current_position is None:
            open_position("SELL", price, atr)
            return
# ===========================
#   FUTURES PRO+ BOT (PART 3)
#   Flask Server + Threading
#   Main Bot Loop + Render Deploy
# ===========================

from flask import Flask, jsonify, request
import threading
import sys
import time
import os
import requests
from datetime import datetime

# ===========================
#   GLOBAL BOT CONTROL
# ===========================
bot_running = True
last_heartbeat_time = 0
HEARTBEAT_INTERVAL = 60 * 10 # 10 minutes

# ===========================
#   FLASK APP SETUP
# ===========================
app = Flask(__name__)

# ===========================
#   BOT MAIN LOOP
# ===========================
def bot_loop():
    global bot_running, last_heartbeat_time
    print("Bot loop started.")
    send_telegram("🚀 ربات Ultra PRO++ Futures شروع به کار کرد (M15 - Trailing TP)!")

    while bot_running:
        try:
            current_time = time.time()
            if current_time - last_heartbeat_time > HEARTBEAT_INTERVAL:
                closes, _, _ = get_klines()
                if closes is not None:
                    send_telegram(f"❤️ ربات فعال است. آخرین قیمت: {closes[-1]}")
                last_heartbeat_time = current_time

            signal = generate_signal()
            if signal:
                execute_trade(signal)
            
            time.sleep(30) # هر 30 ثانیه یکبار چک می کند

        except Exception as e:
            send_telegram(f"❌ خطای بحرانی در Bot Loop: {str(e)}")
            print(f"Error in bot_loop: {e}")
            time.sleep(60) # در صورت خطا یک دقیقه صبر کن

    send_telegram("⛔️ ربات متوقف شد.")
    print("Bot loop stopped.")

# ===========================
#   FLASK ROUTES
# ===========================
@app.route("/")
def home():
    status = "Running" if bot_running else "Stopped"
    return f"Ultra PRO++ Render-STABLE Bot Running. Status: {status}"

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
    send_telegram("🚨 دستور توقف دریافت شد. ربات متوقف می‌شود.")
    return "Bot stopping..."

@app.route("/start")
def start_bot():
    global bot_running
    if not bot_running:
        bot_running = True
        threading.Thread(target=bot_loop).start()
        send_telegram("✅ دستور شروع مجدد دریافت شد. ربات شروع به کار کرد.")
        return "Bot starting..."
    return "Bot already running."

@app.route("/telegram", methods=["POST"])
def telegram_webhook():
    try:
        data = request.json
        print("Telegram update:", data)

        # تشخیص نوع پیام
        if "message" in data:
            message = data["message"]
        elif "edited_message" in data:
            message = data["edited_message"]
        else:
            return jsonify({"status": "ignored"})

        chat_id = message["chat"]["id"]
        text = message.get("text", "").strip()

        # تبدیل به lowercase و حذف @botname
        text = text.split("@")[0].lower()

        # ارسال دستور /status
        if text == "/status":
            status_data = status().json
            send_telegram(
                f"وضعیت ربات:\n"
                f"Uptime: {status_data['uptime']}\n"
                f"پوزیشن فعلی: {status_data['current_position']}\n"
                f"ورود: {status_data['entry_price']}\n"
                f"سایز: {status_data['position_size']}\n"
                f"تریلینگ: {status_data['trailing_active']}\n"
                f"قیمت تریلینگ: {status_data['trailing_price']}"
            )

        elif text == "/kill":
            kill_bot()
            send_telegram("ربات متوقف شد.")

        elif text == "/start":
            start_bot()
            send_telegram("ربات شروع به کار کرد.")

        else:
            send_telegram(f"دستور ناشناس دریافت شد: {text}")

        return jsonify({"status": "ok"})

    except Exception as e:
        print("Telegram error:", str(e))
        send_telegram(f"❌ خطای تلگرام: {str(e)}")
        return jsonify({"status": "error", "message": str(e)})

@app.route("/test")
def test_telegram():
    send_telegram("تست تلگرام موفق بود! ربات پاسخ می‌دهد.")
    return "Telegram test message sent."

# ===========================
#   MAIN ENTRY POINT
# ===========================
if __name__ == "__main__":
    start_time = datetime.now()
    
    # Start the bot loop in a separate thread
    bot_thread = threading.Thread(target=bot_loop)
    bot_thread.daemon = True # Allow main program to exit even if thread is running
    bot_thread.start()

    # Get port from environment variable provided by Render
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
