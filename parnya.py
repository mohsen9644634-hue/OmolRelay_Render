import os
import requests
from flask import Flask, request, jsonify

# ------------------------------------------------------
# Initialization
# ------------------------------------------------------

APP = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

# ------------------------------------------------------
# Send Message Function (MUST be above telegram route!)
# ------------------------------------------------------

def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text
    }
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print("ERROR sending message:", str(e))


# ------------------------------------------------------
# Safe Routes for Render / Health Check
# ------------------------------------------------------

@APP.route("/")
def home2():
    return "GapGPT Trading Automation is LIVE! ✔️", 200


@APP.route("/test")
def test2():
    return "200 OK", 200


# ------------------------------------------------------
# Telegram Webhook Receiver
# ------------------------------------------------------

@APP.route("/telegram", methods=["POST"])
def telegram_check2():
    try:
        data = request.get_json(force=True, silent=True) or {}
        print("Telegram Message:", data)

        message = data.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        text = message.get("text", "").strip().lower()

        if not chat_id or not text:
            return jsonify({"status": "ignored"}), 200

        # --------------------------------------------------
        # Combined Commands (English + Persian)
        # --------------------------------------------------

        # LONG
        if text in ["long", "لانگ", "buy", "خرید"]:
            reply = "فرمان لانگ دریافت شد ✔️\n(فعلاً تست - معامله اجرا نشد)"
            send_message(chat_id, reply)
            return jsonify({"status": "long"}), 200

        # SHORT
        if text in ["short", "شورت", "sell", "فروش"]:
            reply = "فرمان شورت دریافت شد ✔️\n(فعلاً تست - معامله اجرا نشد)"
            send_message(chat_id, reply)
            return jsonify({"status": "short"}), 200

        # CLOSE POSITION
        if text in ["close", "ببند", "بستن", "خروج", "close all"]:
            reply = "فرمان بستن پوزیشن دریافت شد ✔️\n(فعلاً تست - معامله بسته نشد)"
            send_message(chat_id, reply)
            return jsonify({"status": "close"}), 200

        # DEFAULT
        reply = f"پیام شما دریافت شد: {text}\n(دستور معتبر نبود)"
        send_message(chat_id, reply)
        return jsonify({"status": "ok"}), 200

    except Exception as e:
        print("ERROR in /telegram:", str(e))
        return jsonify({"error": "server error"}), 200


# ------------------------------------------------------
# Gunicorn Entry Point
# ------------------------------------------------------

app = APP
