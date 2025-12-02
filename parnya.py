from flask import Flask, request, jsonify
import requests
import time
import hmac
import hashlib
import threading
import math
app = Flask(__name__)

# ============================
#   COINEX API CONFIG
# ============================

API_KEY = "9702A8DB3E074A45996BAC0E8D85F748"
SECRET_KEY = "4029D375ED5D17344BB175DF9FB0B36EBC497F5BA389C4C1"

BASE_URL = "https://api.coinex.com/v1"

# ============================
#   TRADING SETTINGS
# ============================

SYMBOL = "BTCUSDT"
LEVERAGE = 10
POSITION_SIZE = 5        # اندازه پوزیشن = 5 دلار

current_position = "none"

# ============================
#   STRATEGY SETTINGS
# ============================

EMA_SHORT = 50
EMA_LONG = 200
RSI_PERIOD = 14

# ============================
#   COINEX SIGNATURE
# ============================

def generate_signature(params):
    sorted_params = sorted(params.items())
    query = "&".join([f"{k}={v}" for k, v in sorted_params])
    return hmac.new(SECRET_KEY.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()

# ============================
#   API REQUESTS
# ============================

def coinex_request(method, path, params=None):
    if params is None:
        params = {}

    params["access_id"] = API_KEY
    params["tonce"] = int(time.time() * 1000)
    params["signature"] = generate_signature(params)

    url = BASE_URL + path

    if method == "GET":
        res = requests.get(url, params=params)
    else:
        res = requests.post(url, data=params)

    return res.json()

# ============================
#   ORDER FUNCTIONS
# ============================

def set_leverage():
    params = {
        "market": SYMBOL,
        "leverage": LEVERAGE,
        "position_type": 1
    }
    return coinex_request("POST", "/futures/adjust_leverage", params)

def place_order(side):
    params = {
        "market": SYMBOL,
        "type": "market",
        "amount": POSITION_SIZE,
        "side": side
    }
    return coinex_request("POST", "/futures/order/put_market", params)

def close_order():
    global current_position

    if current_position == "none":
        return {"msg": "NO POSITION"}

    opposite = "sell" if current_position == "long" else "buy"

    params = {
        "market": SYMBOL,
        "type": "market",
        "amount": POSITION_SIZE,
        "side": opposite
    }

    current_position = "none"
    return coinex_request("POST", "/futures/order/put_market", params)

# ============================
#   INDICATORS
# ============================

def get_kline():
    url = f"https://api.coinex.com/v1/market/kline?market={SYMBOL}&type=15min&limit=200"
    return requests.get(url).json()

def calculate_ema(data, period):
    multiplier = 2 / (period + 1)
    ema = data[0]
    for price in data[1:]:
        ema = (price - ema) * multiplier + ema
    return ema

def calculate_rsi(data, period=14):
    gains = []
    losses = []
    for i in range(1, len(data)):
        change = data[i] - data[i - 1]
        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(data)):
        change = data[i] - data[i - 1]
        gain = max(change, 0)
        loss = abs(min(change, 0))

        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

# ============================
#   STRATEGY LOOP
# ============================

def strategy_loop():
    global current_position

    while True:
        try:
            klines = get_kline()
            prices = [float(c[2]) for c in klines["data"]]

            ema_short = calculate_ema(prices, EMA_SHORT)
            ema_long = calculate_ema(prices, EMA_LONG)
            rsi = calculate_rsi(prices, RSI_PERIOD)

            # LONG SIGNAL
            if ema_short > ema_long and rsi < 70 and current_position != "long":
                close_order()
                set_leverage()
                place_order("buy")
                current_position = "long"

            # SHORT SIGNAL
            if ema_short < ema_long and rsi > 30 and current_position != "short":
                close_order()
                set_leverage()
                place_order("sell")
                current_position = "short"

        except Exception as e:
            print("ERROR:", e)

        time.sleep(30)

# ============================
#   THREAD START
# ============================

bot_thread = threading.Thread(target=strategy_loop)
bot_thread.daemon = True
bot_thread.start()

# ============================
#   FLASK API
# ============================

@app.route("/")
def home():
    return "CoinEx Auto-Trader Running!"

@app.route("/long", methods=["POST"])
def long_manual():
    close_order()
    set_leverage()
    place_order("buy")
    return "LONG ORDER SENT"

@app.route("/short", methods=["POST"])
def short_manual():
    close_order()
    set_leverage()
    place_order("sell")
    return "SHORT ORDER SENT"

@app.route("/close", methods=["POST"])
def close_manual():
    close_order()
    return "CLOSED"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
￼Enterfrom flask import Flask, request, jsonify
import requests
import time
import hmac
import hashlib
import threading
import math

app = Flask(__name__)

# ============================
#   COINEX API CONFIG
========================

API_KEY = "9702A8DB3E074A45996BAC0E8D85F748"         
SECRET_KEY = "4029D375ED5D17344BB175DF9FB0B36EBC497F5BA389C4C1"

BASE_URL = "https://api.coinex.com/v1"

# ============================
#   TRADING SETTINGS
# ============================

SYMBOL = "BTCUSDT"
LEVERAGE = 10
POSITION_SIZE = 5        # اندازه پوزیشن = 5 دلار

current_position = "none"

# ============================
#   STRATEGY SETTINGS
# ============================

EMA_SHORT = 50
EMA_LONG = 200
RSI_PERIOD = 14

# ============================
#   COINEX SIGNATURE
# ============================

def generate_signature(params):
    sorted_params = sorted(params.items())
    query = "&".join([f"{k}={v}" for k, v in sorted_params])
    return hmac.new(SECRET_KEY.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()

# ============================
#   API REQUESTS
# ============================

def coinex_request(method, path, params=None):
    if params is None:
        params = {}

    params["access_id"] = API_KEY
    params["tonce"] = int(time.time() * 1000)
    params["signature"] = generate_signature(params)

    url = BASE_URL + path

    if method == "GET":
        res = requests.get(url, params=params)
    else:
        res = requests.post(url, data=params)

    return res.json()

# ============================
#   ORDER FUNCTIONS
# ============================

def set_leverage():
    params = {
        "market": SYMBOL,
        "leverage": LEVERAGE,
        "position_type": 1
    }
    return coinex_request("POST", "/futures/adjust_leverage", params)

def place_order(side):
    params = {
        "market": SYMBOL,
        "type": "market",
        "amount": POSITION_SIZE,
        "side": side
    }
    return coinex_request("POST", "/futures/order/put_market", params)

def close_order():
    global current_position

    if current_position == "none":
        return {"msg": "NO POSITION"}

    opposite = "sell" if current_position == "long" else "buy"

    params = {
        "market": SYMBOL,
        "type": "market",
        "amount": POSITION_SIZE,
        "side": opposite
    }

    current_position = "none"
    return coinex_request("POST", "/futures/order/put_market", params)

# ============================
#   INDICATORS
# ============================

def get_kline():
    url = f"https://api.coinex.com/v1/market/kline?market={SYMBOL}&type=15min&limit=200"
    return requests.get(url).json()

def calculate_ema(data, period):
    multiplier = 2 / (period + 1)
    ema = data[0]
