import time
import hmac
import hashlib
import requests
from flask import Flask, jsonify
import os

API_KEY = os.getenv("BITGET_API_KEY")
API_SECRET = os.getenv("BITGET_API_SECRET")
API_PASSPHRASE = os.getenv("BITGET_API_PASS")
BASE_URL = "https://api.bitget.com"
SYMBOL = "BTCUSDT_UMCBL"
MARGIN_MODE = "isolated"
LEVERAGE = "10"
APP = Flask(__name__)


class BitgetAPI:
    def __init__(self):
        self.api_key = API_KEY
        self.secret = API_SECRET
        self.passphrase = API_PASSPHRASE

    def _sign(self, timestamp, method, path, body=""):
        to_sign = str(timestamp) + method + path + body
        return hmac.new(
            self.secret.encode(), to_sign.encode(), hashlib.sha256
        ).hexdigest()

    def _headers(self, timestamp, sign):
        return {
            "ACCESS-KEY": self.api_key,
            "ACCESS-SIGN": sign,
            "ACCESS-PASSPHRASE": self.passphrase,
            "ACCESS-TIMESTAMP": str(timestamp),
            "Content-Type": "application/json",
        }

    def make_request(self, method, path, data=None):
        body = "" if data is None else json.dumps(data)
        timestamp = int(time.time() * 1000)
        sign = self._sign(timestamp, method, path, body)
        url = BASE_URL + path
        headers = self._headers(timestamp, sign)

        if method == "GET":
            r = requests.get(url, headers=headers)
        else:
            r = requests.post(url, headers=headers, data=body)

        return r.json()

    def set_leverage(self):
        data = {
            "symbol": SYMBOL,
            "marginCoin": "USDT",
            "leverage": LEVERAGE,
        }
        return self.make_request("POST", "/api/v2/mix/account/set-leverage", data)

    def place_order(self, side):
        data = {
            "symbol": SYMBOL,
            "marginCoin": "USDT",
            "size": "0.001",
            "side": side,
            "orderType": "market",
            "marginMode": MARGIN_MODE,
        }
        return self.make_request("POST", "/api/v2/mix/order/place-order", data)

    def set_tp_sl(self, order_id, entry_price, side):
        tp = entry_price * 1.008 if side == "open_long" else entry_price * 0.992
        sl = entry_price * 0.997 if side == "open_long" else entry_price * 1.003

        data = {
            "symbol": SYMBOL,
            "orderId": order_id,
            "presetTakeProfitPrice": f"{tp:.2f}",
            "presetStopLossPrice": f"{sl:.2f}",
        }
        return self.make_request("POST", "/api/v2/mix/order/set-tpsl", data)


import json
bitget = BitgetAPI()


@APP.route("/test")
def test():
    return jsonify({"status": "running"})


def execute_signal(position_side):
    lev = bitget.set_leverage()
    order = bitget.place_order(position_side)

    if order.get("data") is None:
        return {"error": "order failed", "details": order}

    order_id = order["data"]["orderId"]

    time.sleep(1)
    entry = bitget.make_request(
        "GET",
        f"/api/v2/mix/order/detail?symbol={SYMBOL}&orderId={order_id}",
    )

    try:
        entry_price = float(entry["data"]["priceAvg"])
    except:
        return {"error": "cannot read entry", "details": entry}

    tp_sl = bitget.set_tp_sl(order_id, entry_price, position_side)

    return {
        "leverage": lev,
        "order": order,
        "entry_price": entry_price,
        "tp_sl": tp_sl,
    }


@APP.route("/signal/long")
def long_signal():
    out = execute_signal("open_long")
    return jsonify(out)


@APP.route("/signal/short")
def short_signal():
    out = execute_signal("open_short")
    return jsonify(out)


if __name__ == "__main__":
    APP.run(host="0.0.0.0", port=5000)
app = APP


