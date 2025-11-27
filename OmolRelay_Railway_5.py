import telebot
from flask import Flask, request
import json
import requests
import os

print("=== SERVICE STARTED ===")

# Load API CONFIG
try:
    with open("LBank_API_config.json", "r") as cfg:
        api_configs = json.load(cfg)
    LBANK_API_KEY = api_configs.get("apiKey")
    LBANK_API_SECRET = api_configs.get("apiSecret")
    TELEGRAM_TOKEN = api_configs.get("telegramBotToken")
    print("=== CONFIG LOADED OK ===")
except Exception as e:
    print("CONFIG LOAD ERROR:", e)

bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)


##########################################
# TEST SEND ORDER (FAKE ENDPOINT FOR NOW)
##########################################
def send_order(symbol, side, qty):
    print("=== send_order called ===")
    print("symbol:", symbol)
    print("side:", side)
    print("qty:", qty)

    url = "https://api.lbkex.com/u2/futures/order"
    payload = {
        "symbol": symbol,
        "side": side,
        "type": "market",
        "qty": qty,
        "reduceOnly": False
    }
    headers = {
        "Authorization": f"Bearer {LBANK_API_KEY}"
    }

    try:
        print("Sending request to LBank...")
        r = requests.post(url, json=payload, headers=headers)
        print("LBank RESPONSE:", r.text)
        return r.text
    except Exception as e:
        print("LBank ERROR:", e)
        return str(e)


##########################################
# TELEGRAM HANDLER
##########################################
@bot.message_handler(commands=['order'])
def handle_order(msg):
    print("=== /order handler triggered ===")
    print("Raw message:", msg.text)

    parts = msg.text.split()
    if len(parts) != 4:
        bot.reply_to(msg, "Usage:\n/order SYMBOL SIDE QTY")
        return

    _, symbol, side, qty = parts
    resp = send_order(symbol.upper(), side.upper(), qty)
    bot.reply_to(msg, resp)


##########################################
# WEBHOOK HANDLER
##########################################
@app.route('/telegram', methods=['POST'])
def webhook():
    print("\n==========================")
    print("=== UPDATE RECEIVED ===")
    print("==========================")

    try:
        raw = request.get_data().decode('utf-8')
        print("RAW UPDATE:", raw)

        update = telebot.types.Update.de_json(json.loads(raw))
        print("Parsed UPDATE OK")

        if update.message:
            print("Message text:", update.message.text)
            print("From user id:", update.message.chat.id)
        else:
            print("NO MESSAGE OBJECT FOUND")

        print("=== Before bot.process_new_updates ===")
        bot.process_new_updates([update])
        print("=== After bot.process_new_updates ===")

        return "", 200

    except Exception as e:
        print("WEBHOOK ERROR:", e)
        return "error", 200


@app.route('/')
def index():
    return "OmolRelay Service Running ✔️", 200


if __name__ == "__main__":
    print("=== Flask running on port 10000 ===")
    app.run(host="0.0.0.0", port=10000)
# end of file
