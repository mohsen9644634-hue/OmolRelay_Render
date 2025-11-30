from flask import Flask, jsonify
import requests
import time
import hmac
import hashlib
import base64
import urllib.parse
import os

app = Flask(__name__)

LBANK_API_KEY = os.environ.get("LBANK_API_KEY")
LBANK_SECRET_KEY = os.environ.get("LBANK_SECRET_KEY")

# ---------- SIGN FUNCTION ----------
def sign_request(params, secret):
    sorted_params = sorted(params.items())
    encoded_params = urllib.parse.urlencode(sorted_params)
    message = encoded_params.encode("utf-8")
    mac = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).digest()
    return base64.b64encode(mac).decode()

# ---------- GET TICKER ----------
def get_price():
    try:
        url = "https://api.lbank.info/v2/ticker.do?symbol=btcusdt"
        r = requests.get(url, timeout=10).json()
        return float(r["data"]["ticker"]["latest"])
    except:
        return None

# ---------- STRATEGY ----------
def execute_trading_strategy():
    print("🔄 اجرای استراتژی 15m...")
    price = get_price()

    if price is None:
        print("⛔ قیمت دریافت نشد")
        return {"status": "error", "msg": "price fetch failed"}

    print(f"📊 قیمت فعلی BTCUSDT: {price}")
    # استراتژی نمایشی
    if price % 2 == 0:
        signal = "BUY"
    else:
        signal = "SELL"

    print(f"📌 سیگنال: {signal}")
    return {"status": "ok", "signal": signal, "price": price}

# ---------- TRIGGER ENDPOINT ----------
@app.route("/run-strategy", methods=["GET"])
def trigger():
    result = execute_trading_strategy()
    return jsonify(result)

# ---------- ROOT ----------
@app.route("/", methods=["GET"])
def home():
    return "OK", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
