from flask import Flask, request, jsonify
import time
import hmac
import hashlib
import json
import requests
import threading

app = Flask(__name__)

API_KEY = "YOUR_BITGET_API_KEY"
SECRET_KEY = "YOUR_BITGET_SECRET_KEY"
PASSPHRASE = "YOUR_BITGET_PASSPHRASE"

BASE_URL = "https://api.bitget.com"
SYMBOL = "BTCUSDT"
MARGIN = "isolated"
LEVERAGE = "10"

# تابع امضای HMAC برای Bitget
def sign(params, secret):
    message = json.dumps(params)
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    #-------------------------------
#  SET LEVERAGE
#-------------------------------
def set_leverage():
    url = f"{BASE_URL}/api/mix/v1/position/setLeverage"
    data = {
        "symbol": SYMBOL,
        "productType": "USDT-FUTURES",
        "marginMode": MARGIN,
        "leverage": LEVERAGE,
    }
    sig = sign(data, SECRET_KEY)

    headers = {
        "Content-Type": "application/json",
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": sig,
        "ACCESS-PASSPHRASE": PASSPHRASE,
        "ACCESS-TIMESTAMP": str(int(time.time()*1000)),
    }

    r = requests.post(url, headers=headers, data=json.dumps(data))
    return r.text


#-------------------------------
#  PLACE MARKET ORDER (LONG/SHORT)
#-------------------------------
def place_order(side, size):
    url = f"{BASE_URL}/api/mix/v1/order/placeOrder"

    data = {
        "symbol": SYMBOL,
        "productType": "USDT-FUTURES",
        "marginMode": MARGIN,
        "side": side,            # open_long / open_short
        "orderType": "market",
        "size": str(size),
        "force": "gtc",
    }

    sig = sign(data, SECRET_KEY)

    headers = {
        "Content-Type": "application/json",
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": sig,
        "ACCESS-PASSPHRASE": PASSPHRASE,
        "ACCESS-TIMESTAMP": str(int(time.time()*1000)),
    }

    r = requests.post(url, headers=headers, data=json.dumps(data))
    try:
        return r.json()
    except:
        return {"error": r.text}


#-------------------------------
#  PLACE TP + SL
#-------------------------------
def place_tp_sl(side, entry_price):
    tp_pct = 0.008      # 0.8%
    sl_pct = 0.003      # 0.3%

    if side == "open_long":
        tp_price = entry_price * (1 + tp_pct)
        sl_price = entry_price * (1 - sl_pct)
        tp_side = "close_long"
        sl_side = "close_long"
    else:
        tp_price = entry_price * (1 - tp_pct)
        sl_price = entry_price * (1 + sl_pct)
        tp_side = "close_short"
        sl_side = "close_short"

    url = f"{BASE_URL}/api/mix/v1/order/placeOrder"

    # TP
    tp_data = {
        "symbol": SYMBOL,
        "productType": "USDT-FUTURES",
        "marginMode": MARGIN,
        "side": tp_side,
        "orderType": "limit",
        "price": str(round(tp_price, 2)),
        "size": "0.001",
        "force": "gtc"
    }
    tp_sig = sign(tp_data, SECRET_KEY)

    headers = {
        "Content-Type": "application/json",
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": tp_sig,
        "ACCESS-PASSPHRASE": PASSPHRASE,
        "ACCESS-TIMESTAMP": str(int(time.time()*1000)),
    }
    requests.post(url, headers=headers, data=json.dumps(tp_data))

    # SL
    sl_data = {
        "symbol": SYMBOL,
        "productType": "USDT-FUTURES",
        "marginMode": MARGIN,
        "side": sl_side,
        "orderType": "limit",
        "price": str(round(sl_price, 2)),
        "size": "0.001",
        "force": "gtc"
    }
    sl_sig = sign(sl_data, SECRET_KEY)
    headers["ACCESS-SIGN"] = sl_sig

    requests.post(url, headers=headers, data=json.dumps(sl_data))

    return {"tp": tp_price, "sl": sl_price}
#-------------------------------
#  GET PRICE
#-------------------------------
def get_price():
    url = f"{BASE_URL}/api/mix/v1/market/ticker?symbol={SYMBOL}&productType=USDT-FUTURES"
    r = requests.get(url)
    try:
        return float(r.json()["data"]["last"])
    except:
        return None


#-------------------------------
#  FLASK ROUTES
#-------------------------------
@app.route('/test', methods=['GET'])
def test():
    return jsonify({"status": "online", "exchange": "bitget"})


@app.route('/signal/long', methods=['POST'])
def long_signal():
    set_leverage()
    price = get_price()
    if not price:
        return jsonify({"error": "price error"})

    res = place_order("open_long", "0.001")
    tp_sl = place_tp_sl("open_long", price)

    return jsonify({
        "signal": "LONG",
        "entry_price": price,
        "tp": tp_sl["tp"],
        "sl": tp_sl["sl"],
        "order": res
    })


@app.route('/signal/short', methods=['POST'])
def short_signal():
    set_leverage()
    price = get_price()
    if not price:
        return jsonify({"error": "price error"})

    res = place_order("open_short", "0.001")
    tp_sl = place_tp_sl("open_short", price)

    return jsonify({
        "signal": "SHORT",
        "entry_price": price,
        "tp": tp_sl["tp"],
        "sl": tp_sl["sl"],
        "order": res
    })


#-------------------------------
# KEEP RENDER ALIVE
#-------------------------------
def keep_alive():
    while True:
        time.sleep(15)

t = threading.Thread(target=keep_alive)
t.daemon = True
t.start()


#-------------------------------
# RUN FLASK
#-------------------------------
if __name__ == '__main__':
    app.run(host="0.0.0.0", port=10000)
