from flask import Flask, jsonify
import os
import time
import hmac
import hashlib
import json
import requests

APP = Flask(__name__)

# ===============================
# ENV VARIABLES
# ===============================
BITGET_API_KEY = os.getenv("BITGET_API_KEY")
BITGET_API_SECRET = os.getenv("BITGET_API_SECRET")
BITGET_API_PASSPHRASE = os.getenv("BITGET_API_PASSPHRASE")


# ===============================
# BITGET SIGN
# ===============================
def bitget_sign(timestamp, method, path, body=""):
    msg = f"{timestamp}{method}{path}{body}"
    return hmac.new(
        BITGET_API_SECRET.encode(),
        msg.encode(),
        hashlib.sha256
    ).hexdigest()


# ===============================
# BITGET REQUEST
# ===============================
def bitget_request(method, path, body_dict=None):
    url = f"https://api.bitget.com{path}"
    timestamp = str(int(time.time() * 1000))
    body = "" if not body_dict else json.dumps(body_dict)

    headers = {
        "ACCESS-KEY": BITGET_API_KEY,
        "ACCESS-SIGN": bitget_sign(timestamp, method, path, body),
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": BITGET_API_PASSPHRASE,
        "Content-Type": "application/json"
    }

    try:
        if method == "POST":
            r = requests.post(url, headers=headers, data=body)
        else:
            r = requests.get(url, headers=headers)
        return r.json()
    except Exception as e:
        return {"error": str(e)}


# ===============================
# GET BALANCE
# ===============================
def get_balance():
    r = bitget_request(
        "GET",
        "/api/mix/v1/account/accounts?productType=USDT-FUTURES"
    )

    try:
        return float(r["data"][0]["available"])
    except:
        return 0


# ===============================
# OPEN POSITION
# ===============================
def open_position(side):
    balance = get_balance()
    if balance <= 0:
        return {"error": "no balance"}

    body = {
        "symbol": "BTCUSDT",
        "marginCoin": "USDT",
        "size": balance,       # full balance
        "side": side,          # buy_long OR sell_short
        "orderType": "market",
        "marginMode": "isolated",
        "leverage": "10"
    }

    return bitget_request(
        "POST",
        "/api/mix/v1/order/placeOrder",
        body
    )


# ===============================
# CLOSE ALL POSITIONS
# ===============================
def close_all():
    long_close = {
        "symbol": "BTCUSDT",
        "marginCoin": "USDT",
        "holdSide": "long"
    }
    short_close = {
        "symbol": "BTCUSDT",
        "marginCoin": "USDT",
        "holdSide": "short"
    }

    r1 = bitget_request(
        "POST",
        "/api/mix/v1/position/closePosition",
        long_close
    )

    r2 = bitget_request(
        "POST",
        "/api/mix/v1/position/closePosition",
        short_close
    )

    return {"long_close": r1, "short_close": r2}


# ===============================
# ROUTES
# ===============================
@APP.route("/")
def home():
    return "ربات Bitget REAL فعال است - بدون تلگرام."


@APP.route("/long")
def do_long():
    return jsonify(open_position("buy_long"))


@APP.route("/short")
def do_short():
    return jsonify(open_position("sell_short"))


@APP.route("/close")
def do_close():
    return jsonify(close_all())


app = APP
