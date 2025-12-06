import time
import hmac
import hashlib
import requests
from flask import Flask

# ============================
# تنظیمات اصلی
# ============================
API_KEY = "YOUR_API_KEY"
API_SECRET = "YOUR_API_SECRET"
BASE = "https://api.coinex.com/perpetual/v1"
MARKET = "BTCUSDT"
LEVERAGE = 15
USE_BALANCE = 0.80   # 80% سرمایه

LIVE = True
TELEGRAM = True
BOT_TOKEN = "YOUR_TELEGRAM_TOKEN"
CHAT_ID = "7156028278"

app = Flask(__name__)

# ============================
# ارسال پیام تلگرام
# ============================
def send_telegram(text):
    try:
        if not TELEGRAM:
            return
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": text})
    except:
        pass

# ============================
# SIGNATURE (فیوچرز)
# ============================
def sign(params):
    raw = "&".join([f"{k}={params[k]}" for k in sorted(params)])
    return hmac.new(API_SECRET.encode(), raw.encode(), hashlib.sha256).hexdigest()

# ============================
# گرفتن موجودی فیوچرز
# ============================
def get_balance():
    try:
        ts = int(time.time() * 1000)
        params = {"access_id": API_KEY, "tonce": ts}
        params["sign"] = sign(params)

        r = requests.get(f"{BASE}/asset/query", params=params, timeout=5).json()

        if "data" not in r:
            return 0
        
        return float(r["data"]["USDT"]["available"])
    except:
        return 0

# ============================
# داده کندل فیوچرز — ERROR PROOF
# ============================
def get_klines():
    for attempt in range(5):
        try:
            r = requests.get(
                f"{BASE}/market/kline",
                params={"market": MARKET, "limit": 150, "period": 900},
                timeout=5
            ).json()

            if "data" not in r:
                print("KLINE ERROR: NO DATA", r)
                time.sleep(1)
                continue

            if "kline" not in r["data"]:
                print("KLINE ERROR: NO KLINE", r)
                time.sleep(1)
                continue

            k = r["data"]["kline"]
            if not k or len(k) < 50:
                print("KLINE ERROR: SHORT", r)
                time.sleep(1)
                continue

            high, low, close = [], [], []

            for c in k:
                high.append(float(c[0]))
                low.append(float(c[1]))
                close.append(float(c[2]))

            return high, low, close
        
        except Exception as e:
            print("KLINE FATAL:", e)
            time.sleep(1)

    print("KLINE FAILED x5 — returning safe zeros")
    return [0], [0], [0]

# ============================
# اندیکاتورها
# ============================
def ema(data, length):
    k = 2 / (length + 1)
    ema_val = data[0]
    for price in data[1:]:
        ema_val = price * k + ema_val * (1 - k)
    return ema_val

def macd(close):
    ema12 = ema(close[-60:], 12)
    ema26 = ema(close[-60:], 26)
    line = ema12 - ema26
    signal = ema(close[-60:], 9)
    return line, signal

def rsi(data, length=14):
    gains, losses = [], []
    for i in range(1, len(data)):
        diff = data[i] - data[i - 1]
        if diff >= 0:
            gains.append(diff)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(-diff)
    avg_gain = sum(gains[-length:]) / length
    avg_loss = sum(losses[-length:]) / length
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def atr(high, low, close, period=14):
    trs = []
    for i in range(1, len(close)):
        tr = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1])
        )
        trs.append(tr)
    return sum(trs[-period:]) / period

# ============================
# سفارش فیوچرز — MARKET
# ============================
def order(side, amount):
    if not LIVE:
        print("SIM", side, amount)
        send_telegram(f"[SIM] {side} {amount}")
        return

    ts = int(time.time() * 1000)
    params = {
        "access_id": API_KEY,
        "market": MARKET,
        "amount": str(amount),
        "side": side,          # buy_long / sell_long / buy_short / sell_short
        "tonce": ts
    }
    params["sign"] = sign(params)

    r = requests.post(f"{BASE}/order/put_market", data=params).json()
    send_telegram(str(r))
    return r

# ============================
# مدیریت پوزیشن
# ============================
POSITION = None
ENTRY = 0
SL = 0
TP = 0
BREAKEVEN = False

# ============================
# ENGINE
# ============================
def engine():
    global POSITION, ENTRY, SL, TP, BREAKEVEN

    high, low, close = get_klines()

    if close == [0]:
        return

    price = close[-1]

    macd_line, macd_sig = macd(close)
    ema50 = ema(close[-80:], 50)
    rsi_val = rsi(close)
    atr_val = atr(high, low, close)

    send_telegram(f"HB | C={price} | MACD={macd_line:.4f}/{macd_sig:.4f} | RSI={rsi_val:.1f}")

    # ----------------------------
    # ورود LONG
    # ----------------------------
    if POSITION is None:
        if macd_line > macd_sig and price > ema50 and rsi_val > 50:
            bal = get_balance()
            qty = round((bal * USE_BALANCE * LEVERAGE) / price, 4)

            order("buy_long", qty)

            POSITION = "LONG"
            ENTRY = price
            SL = ENTRY - 1.5 * atr_val
            TP = ENTRY + 3 * atr_val
            BREAKEVEN = False

            send_telegram(f"ENTER LONG | ENTRY={ENTRY} | SL={SL} | TP={TP}")

    # ----------------------------
    # مدیریت LONG
    # ----------------------------
    if POSITION == "LONG":
        if price <= SL:
            order("sell_long", 999)
            send_telegram("STOP LOSS HIT")
            POSITION = None

        if price >= TP:
            order("sell_long", 999)
            send_telegram("TAKE PROFIT HIT")
            POSITION = None

        if not BREAKEVEN and price >= ENTRY + atr_val:
            SL = ENTRY
            BREAKEVEN = True
            send_telegram("BREAKEVEN ACTIVATED")

# ============================
# ROUTES
# ============================
@app.route("/")
def home():
    return "BOT RUNNING (FUTURES)"

@app.route("/test")
def test():
    send_telegram("TEST OK")
    return "OK"

# ============================
# LOOP
# ============================
def loop():
    while True:
        try:
            engine()
        except Exception as e:
                print("ENGINE ERROR:", e)
                send_telegram(f"ENGINE ERROR: {e}")
        time.sleep(20)

if __name__ == "__main__":
    loop()
