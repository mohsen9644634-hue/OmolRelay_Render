###########################################################
#  PARNYA FUTURES AUTOTRADE BOT — FINAL LIVE STABLE        #
#  Render-Optimized Version (No 404, No Dev Server)        #
###########################################################

import time, hmac, hashlib, requests, os, json
from flask import Flask, jsonify

BASE_URL = "https://api.coinex.com/perpetual/v1"
SYMBOL = "BTCUSDT"
LEVERAGE = 10

API_KEY = os.getenv("COINEX_KEY")
API_SECRET = os.getenv("COINEX_SECRET").encode()

position = None
entry_price = None

############################################################
#                 API REQUEST HANDLER                      
############################################################
def sign_request(params):
    sorted_params = sorted(params.items())
    query = "&".join([f"{k}={v}" for k, v in sorted_params])
    signature = hmac.new(API_SECRET, query.encode(), hashlib.sha256).hexdigest()
    return signature

def private_request(method, endpoint, params=None):
    if params is None:
        params = {}
    params["access_id"] = API_KEY
    params["timestamp"] = int(time.time() * 1000)
    params["tonce"] = int(time.time() * 1000)
    params["signature"] = sign_request(params)
    headers = {"User-Agent": "Mozilla/5.0"}
    url = f"{BASE_URL}{endpoint}"
    try:
        if method == "GET":
            r = requests.get(url, params=params, headers=headers, timeout=10)
        else:
            r = requests.post(url, data=params, headers=headers, timeout=10)
        if r.status_code != 200:
            print(f"⚠️ API ERROR {r.status_code}: {r.text[:100]}")
            return {}
        data = r.json()
        return data
    except Exception as e:
        print(f"❌ [private_request] {endpoint} failed:", e)
        return {}

############################################################
#                 INDICATOR FUNCTIONS                      
############################################################
def ema(values, period):
    k = 2 / (period + 1)
    ema_ = values[0]
    for v in values[1:]:
        ema_ = v * k + ema_ * (1 - k)
    return ema_

def atr(candles, period=14):
    if len(candles) < period: return 0
    trs = [abs(float(c[2]) - float(c[3])) for c in candles[-period:]]
    return sum(trs) / len(trs)

def rsi(candles, period=14):
    closes = [float(c[2]) for c in candles]
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [d for d in deltas if d > 0]
    losses = [-d for d in deltas if d < 0]
    avg_gain = sum(gains[-period:]) / period if gains else 0
    avg_loss = sum(losses[-period:]) / period if losses else 0
    rs = avg_gain / avg_loss if avg_loss != 0 else 100
    return 100 - (100 / (1 + rs))

def macd(candles):
    closes = [float(c[2]) for c in candles]
    ema12 = ema(closes, 12)
    ema26 = ema(closes, 26)
    macd_line = ema12 - ema26
    signal = ema([macd_line], 9)
    hist = macd_line - signal
    return macd_line, signal, [hist]

############################################################
#                 MARKET FUNCTIONS                         
############################################################
def get_candles(symbol, period=900, limit=160):
    url = f"https://api.coinex.com/perpetual/v1/market/kline?market={symbol}&period={period}&limit={limit}"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            print(f"⚠️ HTTP Error {r.status_code}: {r.text[:150]}")
            return []
        data = r.json()
        return data.get("data", [])
    except Exception as e:
        print("❌ get_candles() request failed:", e)
        return []

def get_current_price(symbol):
    url = f"https://api.coinex.com/perpetual/v1/market/ticker?market={symbol}"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            print(f"⚠️ Ticker Error {r.status_code}: {r.text[:100]}")
            return None
        data = r.json()
        return float(data["data"]["ticker"]["last"])
    except Exception as e:
        print("❌ get_current_price() failed:", e)
        return None

############################################################
#                 ORDER MANAGEMENT                         
############################################################
def create_order(symbol, side, price, sl, tp):
    direction = "buy" if side == "LONG" else "sell"
    params = {
        "market": symbol,
        "side": direction,
        "amount": 0.01,
        "type": "market",
        "leverage": LEVERAGE
    }
    r = private_request("POST", "/order/put_market", params)
    print(f"✅ [LIVE ORDER] {side} | Entry={price:.2f} | SL={sl:.2f} | TP={tp:.2f} | Result={r}")

def update_stop_loss(symbol, new_sl):
    print(f"🔧 [LIVE UPDATE SL] {symbol} -> {new_sl:.2f}")

def close_position(symbol):
    params = {"market": symbol, "side": "close", "amount": 0.01}
    r = private_request("POST", "/position/close", params)
    print(f"❌ [LIVE CLOSE] {symbol} | Result={r}")

############################################################
#                 SIGNAL ENGINE                            
############################################################
def super_signal(candles):
    close_prices = [float(c[2]) for c in candles]
    ema20_ = ema(close_prices, 20)
    ema50_ = ema(close_prices, 50)
    ema20_prev = ema(close_prices[:-1], 20)
    ema50_prev = ema(close_prices[:-1], 50)

    macd_line, macd_signal, hist_values = macd(candles)
    hist = sum(hist_values) / len(hist_values)

    r = rsi(candles)
    a = atr(candles)
    last_close = close_prices[-1]
    last_open = float(candles[-1][1])

    if abs(last_close - last_open) > 2 * a:
        return None

    volatility = a / last_close

    if volatility < 0.002:
        if ema20_prev < ema50_prev and ema20_ > ema50_ and hist > 0 and 48 < r < 67:
            return "LONG"
        if ema20_prev > ema50_prev and ema20_ < ema50_ and hist < 0 and 33 < r < 52:
            return "SHORT"
    else:
        if ema20_ > ema50_ and hist >= 0 and 45 < r < 70:
            return "LONG"
        if ema20_ < ema50_ and hist <= 0 and 30 < r < 55:
            return "SHORT"

    return None

############################################################
#                 POSITION MANAGER                         
############################################################
def manage_positions(signal):
    global position, entry_price
    candles = get_candles(SYMBOL)
    if not candles:
        print("⚠️ No candle data. Skipping this cycle.")
        return

    atr_val = atr(candles)

    if position is None and signal in ["LONG", "SHORT"]:
        last_price = float(candles[-1][2])
        position = signal
        entry_price = last_price

        if signal == "LONG":
            sl = entry_price - 1.5 * atr_val
            tp = entry_price + 2.5 * atr_val
        else:
            sl = entry_price + 1.5 * atr_val
            tp = entry_price - 2.5 * atr_val

        create_order(SYMBOL, signal, entry_price, sl, tp)

    elif position is not None:
        current_price = get_current_price(SYMBOL)
        if current_price is None:
            print("⚠️ Price unavailable, skipping update.")
            return

        macd_line, macd_signal, hist_values = macd(candles)
        hist_avg = sum(hist_values) / len(hist_values)

        if position == "LONG":
            if current_price >= entry_price + 1.2 * atr_val:
                update_stop_loss(SYMBOL, entry_price)
            if hist_avg < 0:
                close_position(SYMBOL)
                position = None

        elif position == "SHORT":
            if current_price <= entry_price - 1.2 * atr_val:
                update_stop_loss(SYMBOL, entry_price)
            if hist_avg > 0:
                close_position(SYMBOL)
                position = None

############################################################
#                        WEB SERVER                        
############################################################
app = Flask(__name__)

@app.route("/")
def home():
    return "OK"

@app.route("/status")
def status():
    return jsonify({
        "running": True,
        "position": position,
        "entry_price": entry_price,
        "connection": test_coinex_connection()
    })

def test_coinex_connection():
    try:
        data = requests.get(f"https://api.coinex.com/perpetual/v1/market/ticker?market={SYMBOL}", timeout=10).json()
        price = float(data["data"]["ticker"]["last"])
        return {"connected": True, "market": SYMBOL, "price": price}
    except Exception as e:
        return {"connected": False, "error": str(e)}

############################################################
#                        MAIN LOOP                         
############################################################
if __name__ == "__main__":
    print("🚀 Starting PARNYA Auto Futures BOT [LIVE STABLE MODE]")

    from threading import Thread

    def trade_loop():
        while True:
            candles = get_candles(SYMBOL)
            signal = super_signal(candles) if candles else None
            manage_positions(signal)
            time.sleep(15)

    Thread(target=trade_loop).start()

    from waitress import serve
    serve(app, host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
