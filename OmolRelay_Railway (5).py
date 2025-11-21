import os
import json
import requests
import telebot
from flask import Flask, request

# Load API config
with open("LBank_API_Config.json", "r") as cfg:
    api_config = json.load(cfg)

LBANK_API_KEY = api_config["apiKey"]
LBANK_API_SECRET = api_config["apiSecret"]
TELEGRAM_TOKEN = api_config["telegramBotToken"]

bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)

# Simple order sender to LBank Futures
def send_order(symbol, side, quantity):
    url = "https://www.lbank.com/api/v2/futures/order"
    payload = {
        "symbol": symbol,
        "side": side,  # BUY or SELL
        "type": "market",
        "quantity": quantity,
        "reduceOnly": False
    }
    headers = {
        "Authorization": f"Bearer {LBANK_API_KEY}"
    }
    r = requests.post(url, json=payload, headers=headers)
    return r.json()

# Telegram handler
@bot.message_handler(commands=['order'])
def handle_order(msg):
    parts = msg.text.split()
    if len(parts) != 4:
        bot.reply_to(msg, "فرمت صحیح: /order SYMBOL SIDE QTY")
        return
    _, symbol, side, qty = parts
    resp = send_order(symbol, side.upper(), float(qty))
    bot.reply_to(msg, str(resp))

# Webhook for Render
@app.route("/" + TELEGRAM_TOKEN, methods=['POST'])
def webhook():
    json_str = request.get_data().decode('UTF-8')
    update = telebot.types.Update.de_json(json.loads(json_str))
    bot.process_new_updates([update])
    return "OK", 200

@app.route("/")
def index():
    return "OmolRelay Service Running ⚡", 200

if __name__ == "__main__":
    bot.remove_webhook()
    bot.polling(none_stop=True)
