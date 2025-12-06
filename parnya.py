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

# Spot برای کندل
SPOT_BASE = "https://api.coinex.com/v1"

# Futures برای معامله
FUT_BASE = "https://api.coinex.com/perpetual/v1"

MARKET = "BTCUSDT"
LIVE = True

LEVERAGE = 15
USE_BALANCE = 0.80

TELEGRAM = True
BOT_TOKEN = "YOUR_TELEGRAM_TOKEN"
CHAT_ID = "7156028278"

app = Flask(__name__)

# ============================
# ارسال پیام تلگرام
# ============================
def send_telegram(text):
    if not TELEGRAM:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": text},
            timeout=5
        )
    except:
        pass

# ============================
# امضای فیوچرز CoinEx
# ============================
def sign(params):
    raw = "&".join([f"{k}={params[k]}" for k in sorted(params)])
    return hmac.new(API_SECRET.encode(), raw.encode(), hashlib.sha256).hexdigest()

# ============================
# موجودی فیوچرز
# ============================
def get_balance():
    try:
        ts = int(time.time() * 1000)
        params = {"access_id": API_KEY, "tonce": ts}
        params["sign"] = sign(params)

        r = requests.get(f"{FUT_BASE}/asset/query", params=params, timeout=5).json()

        return float(r["data"]["USDT"]["available"])
    except:
        return 0

# ============================
# KLINE اسپات (درست و رسمی)
# Error‑Proof + Retry
# ============================
def get_klines():
    url = f"{SPOT_BASE}/market/kline"

    for a in range(5):
        try:
            r = requests.get(
                url,
                params={"market": MARKET, "limit": 150, "period": 900},
                timeout=5
            ).json()

            if "data" not in r:
                time.sleep(1)
                continue

            if not isinstance(r["data"], list):
                time.sleep(1)
                continue

            high, low, close = [], [], []

            for c in r["data"]:
                high.append(float(c[3]))   # high
                low.append(float(c[4]))    # low
                close.append(float(c[2]))  # close

            return high, low, close

        except:
            time.sleep(1)

    return [0], [0], [0]

# ============================
# اندیکاتورها
# ============================
def ema(data, length):
    k = 2 / (length + 1)
    val = data[0]
    for p in data[1:]:
        val = p * k + val * (1 - k)
    return val

def macd(close):
    ema12 = ema(close[-80:], 12)
    ema26 = ema(close[-80:], 26)
    macd_line = ema12 - ema26
    signal = ema(close[-80:], 9)
    return macd_line, signal

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
# سفارش MARKET فیوچرز
# ============================
def fut_order(side, qty):
    if not LIVE:
        send_telegram(f"[SIM] {side} {qty}")
        return

    ts = int(time.time() * 1000)
    params = {
        "access_id": API_KEY,
        "market": MARKET,
        "side": side,
        "amount": str(qty),
        "tonce": ts
    }
    params["sign"] = sign(params)

    r = requests.post(f"{FUT_BASE}/order/put_market", data=params).json()
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
# ENGINE اصلی
# ============================
def engine():
    global POSITION, ENTRY, SL, TP, BREAKEVEN

    high, low, close = get_klines()
    if close == [0]:
        return

    price = close[-1]

    macd_line, macd_signal = macd(close)
    ema50 = ema(close[-80:], 50)
    rsi_val = rsi(close)
    atr_val = atr(high, low, close)

    send_telegram(f"HB | P={price} | MACD={macd_line:.4f}/{macd_signal:.4f} | RSI={rsi_val:.1f}")

    # ورود LONG
    if POSITION is None:
        if macd_line > macd_signal and price > ema50 and rsi_val > 50:
            bal = get_balance()
            qty = round((bal * USE_BALANCE * LEVERAGE) / price, 4)

            fut_order("buy_long", qty)

            POSITION = "LONG"
            ENTRY = price
            SL = ENTRY - 1.5 * atr_val
            TP = ENTRY + 3 * atr_val
            BREAKEVEN = False

            send_telegram(f"ENTER LONG | ENTRY={ENTRY} | SL={SL} | TP={TP}")

    # مدیریت LONG
    if POSITION == "LONG":
        # SL
        if price <= SL:
            fut_order("sell_long", 999)
            POSITION = None
            send_telegram("STOP LOSS HIT")

        # TP
        if price >= TP:
            fut_order("sell_long", 999)
            POSITION = None
            send_telegram("TAKE PROFIT HIT")

        # Breakeven
        if not BREAKEVEN and price >= ENTRY + atr_val:
            SL = ENTRY
            BREAKEVEN = True
            send_telegram("BREAKEVEN ACTIVE")

# ============================
# ROUTES
# ============================
@app.route("/")
def home():
    return "BOT RUNNING (FUTURES PRO+ REAL LIVE)"

@app.route("/test")
def test():
    send_telegram("Test: Bot Telegram Connection OK")
    return "Telegram test sent"

# ============================
# LOOP
# ============================
def loop():
    while True:
        try:
            engine()
        except Exception as e:
            send_telegram(f"ENGINE ERROR: {e}")
        time.sleep(20)

if __name__ == "__main__":
    loop()
