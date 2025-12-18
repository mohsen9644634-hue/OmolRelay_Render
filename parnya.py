import time, hmac, hashlib, threading, requests, psutil, os
from flask import Flask, jsonify
from collections import deque
from datetime import datetime, timedelta

# =================================================
# CONFIGURATION
# =================================================
class Config:
    API_KEY = os.getenv("COINEX_API_KEY", "YOUR_KEY")
    API_SECRET = os.getenv("COINEX_API_SECRET", "YOUR_SECRET")
    SYMBOL = "BTCUSDT"
    LEVERAGE = 10
    POSITION_SIZE_PCT = 0.25
    SL_CORE = 0.012  
    TP_TARGETS = [
        {"p": 0.010, "c": 0.4},  
        {"p": 0.020, "c": 0.6}   
    ]
    BASE_URL = "https://api.coinex.com/v2"
    SIGNAL_HISTORY_DAYS = 5

# =================================================
# GLOBAL STATE
# =================================================
signal_history = deque()
state = {
    "loop_running": False,
    "confidence": 0.0,
    "tp_index": 0,
    "sl_set": False,
    "entry_lock": False,
    "thought": "در حال آماده‌سازی مغز ربات..."
}

def log_signal(signal_type, side=None, price=None, confidence=None):
    signal_history.append({
        "time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "signal": signal_type,
        "side": side,
        "price": price,
        "confidence": confidence
    })

# =================================================
# BOT CORE
# =================================================
class CoinexBot:
    def __init__(self):
        self.session = requests.Session()

    def get_auth_headers(self, method, path):
        timestamp = str(int(time.time() * 1000))
        prepared_str = f"{method}{path}{timestamp}"
        signature = hmac.new(Config.API_SECRET.encode(), prepared_str.encode(), hashlib.sha256).hexdigest().lower()
        return {"X-COINEX-KEY": Config.API_KEY, "X-COINEX-SIGN": signature, "X-COINEX-TIMESTAMP": timestamp, "Content-Type": "application/json"}

    def request(self, method, endpoint, params=None, auth=False):
        url = f"{Config.BASE_URL}{endpoint}"
        headers = self.get_auth_headers(method, endpoint) if auth else {}
        try:
            if method == "GET":
                resp = self.session.get(url, params=params, headers=headers, timeout=10)
            else:
                resp = self.session.post(url, json=params, headers=headers, timeout=10)
            return resp.json()
        except Exception as e:
            state["thought"] = f"خطای شبکه: {e}"
            return None

    def get_indicators(self):
        m15 = self.request("GET", "/futures/market/kline", {"market": Config.SYMBOL, "period": "15min", "limit": "100"})
        h1 = self.request("GET", "/futures/market/kline", {"market": Config.SYMBOL, "period": "1hour", "limit": "200"})
        
        if not m15 or 'data' not in m15 or not h1 or 'data' not in h1: return None
        
        closes_15 = [float(c[2]) for c in m15['data']]
        vols_15 = [float(c[5]) for c in m15['data']]
        closes_h1 = [float(c[2]) for c in h1['data']]
        
        ema200_h1 = sum(closes_h1[-200:]) / 200 
        ema10_15 = sum(closes_15[-10:]) / 10
        ema20_15 = sum(closes_15[-20:]) / 20
        vol_avg = sum(vols_15[-20:]) / 20 
        
        return {
            "last_price": closes_15[-1],
            "ema200": ema200_h1,
            "ema10": ema10_15,
            "ema20": ema20_15,
            "last_vol": vols_15[-1],
            "vol_avg": vol_avg,
            "rsi": self.calculate_rsi(closes_15)
        }

    def calculate_rsi(self, data, n=14):
        if len(data) < n+1: return 50
        deltas = [data[i] - data[i-1] for i in range(1, len(data))]
        gains = [max(d, 0) for d in deltas]
        losses = [abs(min(d, 0)) for d in deltas]
        avg_gain = sum(gains[-n:]) / n
        avg_loss = sum(losses[-n:]) / n
        return 100 - (100 / (1 + (avg_gain/avg_loss))) if avg_loss != 0 else 100

    def check_strategy(self):
        ind = self.get_indicators()
        if not ind: return None, 0.0

        is_uptrend = ind["last_price"] > ind["ema200"]
        is_downtrend = ind["last_price"] < ind["ema200"]
        volume_confirmed = ind["last_vol"] > (ind["vol_avg"] * 1.5)
        
        state["thought"] = f"قیمت: {ind['last_price']} | روند: {'صعبودی' if is_uptrend else 'نزولی'} | حجم: {'تایید' if volume_confirmed else 'ضعیف'}"

        if is_uptrend and ind["ema10"] > ind["ema20"] and ind["rsi"] > 53 and volume_confirmed:
            return "long", 0.95
        if is_downtrend and ind["ema10"] < ind["ema20"] and ind["rsi"] < 47 and volume_confirmed:
            return "short", 0.95
        return None, 0.1

    def trading_loop(self):
        state["loop_running"] = True
        print("🚀 BOT STARTED")
        while True:
            try:
                side, conf = self.check_strategy()
                state["confidence"] = conf
                # در اینجا منطق ثبت سفارش شما قرار می‌گیرد
                time.sleep(15)
            except Exception as e:
                time.sleep(20)

# =================================================
# WEB INTERFACE (FIXED ORDER)
# =================================================
# ابتدا آبجکت ربات را می‌سازیم
my_bot = CoinexBot() 
app = Flask(__name__)

@app.route("/status")
def status():
    return jsonify({
        "bot_running": state["loop_running"],
        "thought": state["thought"],
        "confidence": state["confidence"],
        "system": psutil.cpu_percent()
    })

if __name__ == "__main__":
    # حالا ترد را با استفاده از شیء ساخته شده شروع می‌کنیم
    threading.Thread(target=my_bot.trading_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
