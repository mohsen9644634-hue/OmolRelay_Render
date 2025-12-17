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
    SL_CORE = 0.006  # 0.6%
    TP_TARGETS = [
        {"p": 0.004, "c": 0.4},  # پله اول: 0.4% سود، فروش 40% حجم
        {"p": 0.008, "c": 0.3},  # پله دوم: 0.8% سود
        {"p": 0.012, "c": 0.3}   # پله سوم: 1.2% سود
    ]
    BASE_URL = "https://api.coinex.com/v2"
    SIGNAL_HISTORY_DAYS = 5

# =================================================
# GLOBAL STATE & LOGGING
# =================================================
signal_history = deque()
state = {
    "loop_running": False,
    "confidence": 0.0,
    "tp_index": 0,
    "sl_set": False,
    "entry_lock": False
}

def log_signal(signal_type, side=None, price=None, confidence=None):
    signal_history.append({
        "time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "signal": signal_type,
        "side": side,
        "price": price,
        "confidence": confidence
    })
    cutoff = datetime.utcnow() - timedelta(days=Config.SIGNAL_HISTORY_DAYS)
    while signal_history and datetime.strptime(signal_history[0]["time"], "%Y-%m-%d %H:%M:%S") < cutoff:
        signal_history.popleft()

# =================================================
# BOT CORE CLASS
# =================================================
class CoinexBot:
    def __init__(self):
        self.session = requests.Session()

    def get_auth_headers(self, method, path):
        timestamp = str(int(time.time() * 1000))
        prepared_str = f"{method}{path}{timestamp}"
        signature = hmac.new(Config.API_SECRET.encode(), prepared_str.encode(), hashlib.sha256).hexdigest().lower()
        return {
            "X-COINEX-KEY": Config.API_KEY,
            "X-COINEX-SIGN": signature,
            "X-COINEX-TIMESTAMP": timestamp,
            "Content-Type": "application/json"
        }

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
            print(f"❌ API Error: {e}")
            return None

    # --- Indicators ---
    def ema(self, data, n):
        if len(data) < n: return None
        k = 2 / (n + 1)
        e = sum(data[:n]) / n
        for v in data[n:]: e = v * k + e * (1 - k)
        return e

    def rsi(self, data, n=14):
        if len(data) < n + 1: return 50
        deltas = [data[i] - data[i-1] for i in range(1, len(data))]
        gains = [d if d > 0 else 0 for d in deltas]
        losses = [abs(d) if d < 0 else 0 for d in deltas]
        avg_gain = sum(gains[:n]) / n
        avg_loss = sum(losses[:n]) / n
        for i in range(n, len(gains)):
            avg_gain = (avg_gain * (n - 1) + gains[i]) / n
            avg_loss = (avg_loss * (n - 1) + losses[i]) / n
        return 100 - (100 / (1 + (avg_gain/avg_loss))) if avg_loss != 0 else 100

    # --- Trading Logic ---
    def check_strategy(self):
        m15_data = self.request("GET", "/futures/market/kline", {"market": Config.SYMBOL, "period": "15min", "limit": "100"})
        h1_data = self.request("GET", "/futures/market/kline", {"market": Config.SYMBOL, "period": "1hour", "limit": "250"})
        
        if not m15_data or 'data' not in m15_data: return None, 0.0
        
        m15_closes = [float(c[2]) for c in m15_data['data']]
        h1_closes = [float(c[2]) for c in h1_data['data']]
        
        last_price = m15_closes[-1]
        ema50 = self.ema(m15_closes, 50)
        ema200 = self.ema(h1_closes, 200)
        rsi_val = self.rsi(m15_closes)

        # DEBUG OUTPUT
        print(f"DEBUG | Price: {last_price} | EMA50: {round(ema50,1)} | EMA200: {round(ema200,1)} | RSI: {round(rsi_val,1)}")

        if not ema50 or not ema200: return None, 0.0

        if last_price > ema50 and h1_closes[-1] > ema200 and rsi_val < 70:
            return "long", 0.8
        if last_price < ema50 and h1_closes[-1] < ema200 and rsi_val > 30:
            return "short", 0.8
        return None, 0.0

    def trading_loop(self):
        print("🤖 BOT STARTED")
        state["loop_running"] = True
        
        while True:
            try:
                # 1. داده‌های پایه
                ticker = self.request("GET", "/futures/market/ticker", {"market": Config.SYMBOL})
                price = float(ticker['data']['last'])
                
                pos_resp = self.request("GET", "/futures/pending-position", {"market": Config.SYMBOL}, auth=True)
                pos = pos_resp['data'][0] if (pos_resp and pos_resp.get('data')) else None

                # 2. اگر پوزیشن باز نداریم
                if not pos or float(pos['amount']) == 0:
                    state["tp_index"] = 0
                    state["sl_set"] = False
                    
                    side, conf = self.check_strategy()
                    state["confidence"] = conf
                    
                    if side and not state["entry_lock"]:
                        # محاسبه حجم
                        balance_resp = self.request("GET", "/assets/futures/balance", auth=True)
                        balance = float(balance_resp['data'][0]['available']) if balance_resp else 0
                        amount = (balance * Config.POSITION_SIZE_PCT * Config.LEVERAGE) / price
                        
                        print(f"🚀 Opening {side}...")
                        self.request("POST", "/futures/order", {
                            "market": Config.SYMBOL, "side": "buy" if side == "long" else "sell",
                            "type": "market", "amount": str(round(amount, 4))
                        }, auth=True)
                        log_signal("ENTRY", side.upper(), price, conf)
                        state["entry_lock"] = True
                
                # 3. اگر پوزیشن باز داریم
                else:
                    state["entry_lock"] = False
                    entry = float(pos['avg_entry_price'])
                    
                    # ست کردن SL
                    if not state["sl_set"]:
                        sl_price = entry * (1 - Config.SL_CORE) if pos['side'] == 'buy' else entry * (1 + Config.SL_CORE)
                        self.request("POST", "/futures/edit-position-stop-loss", {
                            "market": Config.SYMBOL, "stop_loss_price": str(round(sl_price, 2))
                        }, auth=True)
                        state["sl_set"] = True

                    # مدیریت TP (پله‌ای)
                    idx = state["tp_index"]
                    if idx < len(Config.TP_TARGETS):
                        target = Config.TP_TARGETS[idx]
                        tp_price = entry * (1 + target['p']) if pos['side'] == 'buy' else entry * (1 - target['p'])
                        
                        hit = (price >= tp_price) if pos['side'] == 'buy' else (price <= tp_price)
                        if hit:
                            close_amt = float(pos['amount']) * target['c']
                            self.request("POST", "/futures/order", {
                                "market": Config.SYMBOL, "side": "sell" if pos['side'] == 'buy' else "buy",
                                "type": "market", "amount": str(round(close_amt, 4)), "reduce_only": True
                            }, auth=True)
                            if idx == 0: # انتقال استاپ به نقطه ورود در پله اول
                                self.request("POST", "/futures/edit-position-stop-loss", {
                                    "market": Config.SYMBOL, "stop_loss_price": str(round(entry, 2))
                                }, auth=True)
                            state["tp_index"] += 1

                time.sleep(5)
            except Exception as e:
                print(f"❗ Error: {e}")
                time.sleep(10)

# =================================================
# FLASK INTERFACE
# =================================================
bot = CoinexBot()
app = Flask(__name__)

@app.get("/status")
def status():
    return jsonify({
        "running": state["loop_running"], "confidence": state["confidence"],
        "cpu": psutil.cpu_percent(), "signals_count": len(signal_history)
    })

@app.get("/signals")
def get_signals():
    return jsonify(list(signal_history))

if __name__ == "__main__":
    threading.Thread(target=bot.trading_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=5000)
