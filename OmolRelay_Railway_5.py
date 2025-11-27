import telebot
from flask import Flask, request
import json
import requests
import os

print("=== SERVICE STARTED ===")


###########################################
# CONFIG LOAD (OPTIONAL) 
###########################################
# اگر فایل کانفیگ وجود نداشت، از مقادیر ثابت استفاده می‌کنیم

LBANK_API_KEY = None
LBANK_API_SECRET = None

try:
    with open("LBank_API_config.json", "r") as cfg:
        api_configs = json.load(cfg)
        LBANK_API_KEY = api_configs.get("apiKey")
        LBANK_API_SECRET = api_configs.get("apiSecret")
        TELEGRAM_TOKEN = api_configs.get("telegramBotToken")
        print("=== CONFIG LOADED OK ===")

except Exception as e:
    print("CONFIG LOAD ERROR:", e)

    # تنظیم دستی توکن ربات تلگرام
    TELEGRAM_TOKEN = "7565436021:AAHHzoXwyJ9piF3ik3nC5jRljvLaxPuCUuA"

    # تنظیم دستی کلیدهای LBank (اختیاری)
    LBANK_API_KEY = "44541d03-4c58-47be-9e4e-cd8d17f08419"
    LBANK_API_SECRET = "8DC478B35C5F6B07D6C7EA57745AE915"


###########################################
# TELEGRAM BOT INIT
###########################################
bot = telebot.TeleBot(TELEGRAM_TOKEN)

app = Flask(__name__)


###########################################
# TEST SEND ORDER (FAKE ENDPOINT FOR NOW)
###########################################
def send_order(symbol, side, qty):
    print("=== send_order called ===")
    print("symbol:", symbol)
    print("side:", side)
    print("qty:", qty)

    url = "https://api.lbkex.com/u2/futures/order"   # endpoint واقعی
    payload = {
        "symbol": symbol,
        "side": side,
        "type": "market",
        "qty": qty,
        "reduceOnly": False
    }
    headers = {
        "Content-Type": "application/json",
        "X-LB-APIKEY": LBANK_API_KEY if LBANK_API_KEY else "",
    }

    try:
        r = requests.post(url, json=payload, headers=headers)
        print("LBANK Response Status:", r.status_code)
        print("LBANK Response Body:", r.text)

    except Exception as e:
        print("LBANK REQUEST ERROR:", e)


###########################################
# ROOT ENDPOINT
###########################################
@app.route("/", methods=["GET"])
def home():
    return "OmolRelay is running.", 200


###########################################
# TELEGRAM WEBHOOK ENDPOINT
###########################################
@app.route("/telegram", methods=["POST"])
def telegram_webhook():
    print("=== UPDATE RECEIVED ===")

    try:
        update = request.get_json()
        print("JSON Update:", update)
    except:
        print("ERROR: Invalid Telegram update")
        return "Bad Request", 400

    if not update or "message" not in update:
        print("No message in update")
        return "OK", 200

    message = update["message"]
    chat_id = message["chat"]["id"]
    text = message.get("text", "")
    print("Message text:", text)

    # پاسخ ساده
    if text == "/ping":
        bot.send_message(chat_id, "Pong! Relay working!")
        return "OK", 200

    # ارسال سفارش تست
    if text == "/buy":
        send_order("BTCUSDT", "buy", "0.001")
        bot.send_message(chat_id, "Buy test order sent!")
        return "OK", 200

    if text == "/sell":
        send_order("BTCUSDT", "sell", "0.001")
        bot.send_message(chat_id, "Sell test order sent!")
        return "OK", 200

    bot.send_message(chat_id, f"Message received: {text}")
    return "OK", 200


###########################################
# RUN FLASK
###########################################
if __name__ == "__main__":
    print("=== FLASK STARTING ON PORT 10000 ===")
    app.run(host="0.0.0.0", port=10000)
