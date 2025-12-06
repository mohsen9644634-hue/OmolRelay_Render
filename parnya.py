import time
import hmac
import hashlib
import requests
import threading
import os
from flask import Flask

API_KEY = "YOUR_API_KEY"
API_SECRET = "YOUR_API_SECRET"

SPOT_BASE = "https://api.coinex.com/v1"
FUT_BASE  = "https://api.coinex.com/perpetual/v1"

MARKET = "BTCUSDT"
LIVE = True

LEVERAGE = 15
USE_BALANCE = 0.80

TELEGRAM = True
BOT_TOKEN = "YOUR_TELEGRAM_TOKEN"
CHAT_ID = "7156028278"

app = Flask(__name__)

# GLOBALS
POSITION = None
ENTRY = 0
SL = 0
TP = 0
BREAKEVEN = False
LOOP_ACTIVE = True
LAST_RUN = 0
START_TIME = time.time()
LAST_PRICE = 0


def uptime():
    t = int(time.time() - START_TIME)
    h = t // 3600
    m = (t % 3600) // 60
    s = t % 60
    return f"{h}h {m}m {s}s"


def send_telegram(msg):
    if not TELEGRAM:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg},
            timeout=5
        )
    except:
        pass


def sign(params):
    raw = "&".join([f"{k}={params[k]}" for k in sorted(params)])
    return hmac.new(API_SECRET.encode(), raw.encode(), hashlib.sha256).hexdigest()


def get_balance():
    try:
        ts = int(time.time()*1000)
        params = {"access_id": API_KEY, "tonce": ts}
        params["sign"] = sign(params)
        r = requests.get(f"{FUT_BASE}/asset/query", params=params, timeout=5).json()
        return float(r["data"]["USDT"]["available"])
    except:
        return 0


def get_klines():
    for _ in range(5):
        try:
            r = requests.get(
                f"{SPOT_BASE}/market/kline",
                params={"market": MARKET, "limit":150, "period":900},
                timeout=5
            ).json()

            if "data" not in r or not isinstance(r["data"], list):
                time.sleep(1)
                continue

            high, low, close = [], [], []
            for c in r["data"]:
                high.append(float(c[3]))
                low.append(float(c[4]))
                close.append(float(c[2]))

            return high, low, close
        except:
            time.sleep(1)
    return [0], [0], [0]


def ema(data, length):
    k = 2/(length+1)
    v = data[0]
    for p in data[1:]:
        v = p*k + v*(1-k)
    return v


def macd(close):
    ema12 = ema(close[-80:], 12)
    ema26 = ema(close[-80:], 26)
    line = ema12 - ema26
    sig = ema(close[-80:], 9)
    return line, sig


def rsi(data, length=14):
    gains, losses = [], []
    for i in range(1, len(data)):
        diff = data[i] - data[i-1]
        if diff >= 0:
            gains.append(diff); losses.append(0)
        else:
            gains.append(0); losses.append(-diff)
    avg_gain = sum(gains[-length:]) / length
    avg_loss = sum(losses[-length:]) / length
    if avg_loss == 0:
        return 100
    rs = avg_gain/avg_loss
    return 100 - (100/(1+rs))


def atr(high, low, close, period=14):
    trs = []
    for i in range(1, len(close)):
        tr = max(
            high[i]-low[i],
            abs(high[i] - close[i-1]),
            abs(low[i]  - close[i-1])
        )
        trs.append(tr)
    return sum(trs[-period:]) / period


def fut_order(side, qty):
    if not LIVE:
        send_telegram(f"[SIM] {side} {qty}")
        return

    ts = int(time.time()*1000)
    params = {
        "access_id": API_KEY,
        "market": MARKET,
        "side": side,
        "amount": str(qty),
        "tonce": ts
    }
    params["sign"] = sign(params)

    try:
        r = requests.post(f"{FUT_BASE}/order/put_market", data=params).json()
        send_telegram(str(r))
    except Exception as e:
        send_telegram(f"ORDER ERROR: {e}")


def engine():
    global POSITION, ENTRY, SL, TP, BREAKEVEN, LOOP_ACTIVE, LAST_RUN, LAST_PRICE

    LAST_RUN = time.time()

    high, low, close = get_klines()
    if close == [0]:
        send_telegram("CRITICAL ERROR: KLINE FAILED, BOT PAUSED")
        LOOP_ACTIVE = False
        return

    price = close[-1]
    LAST_PRICE = price

    macd_line, macd_sig = macd(close)
    ema50 = ema(close[-80:], 50)
    rsi_val = rsi(close)
    atr_val = atr(high, low, close)

    # HEARTBEAT
    send_telegram(
        f"HB | price={price} | pos={POSITION} | uptime={uptime()}"
    )

    if POSITION is None:
        if macd_line > macd_sig and price > ema50 and rsi_val > 50:
            bal = get_balance()
            qty = round((bal * USE_BALANCE * LEVERAGE) / price, 4)

            fut_order("buy_long", qty)

            POSITION = "LONG"
            ENTRY = price
            SL = ENTRY - 1.5 * atr_val
            TP = ENTRY + 3 * atr_val
            BREAKEVEN = False

            send_telegram(f"ENTER LONG | entry={ENTRY} | SL={SL} | TP={TP}")
            return

    if POSITION == "LONG":
        if price <= SL:
            fut_order("sell_long", 999)
            POSITION = None
            send_telegram("STOP LOSS HIT")
            return

        if price >= TP:
            fut_order("sell_long", 999)
            POSITION = None
            send_telegram("TAKE PROFIT HIT")
            return

        if not BREAKEVEN and price >= ENTRY + atr_val:
            SL = ENTRY
            BREAKEVEN = True
            send_telegram("BREAKEVEN ACTIVATED")


def loop_thread():
    global LOOP_ACTIVE, LAST_RUN

    while True:
        if LOOP_ACTIVE:
            try:
                engine()
            except Exception as e:
                send_telegram(f"ENGINE ERROR: {e}")
                LOOP_ACTIVE = False
        else:
            if time.time() - LAST_RUN > 60:
                LOOP_ACTIVE = True
                send_telegram("AUTO-RECOVERY: BOT RESUMED")

        time.sleep(20)


@app.route("/")
def home():
    return "Ultra PRO++ Render-STABLE Bot Running"


@app.route("/status")
def status():
    return (
        f"Position: {POSITION}\n"
        f"Entry: {ENTRY}\n"
        f"SL: {SL}\n"
        f"TP: {TP}\n"
        f"Breakeven: {BREAKEVEN}\n"
        f"Last Price: {LAST_PRICE}\n"
        f"Last Run: {int(time.time()-LAST_RUN)}s ago\n"
        f"UPTIME: {uptime()}\n"
        f"Version: Ultra PRO++ Render-STABLE"
    )


@app.route("/kill")
def kill():
    global LOOP_ACTIVE
    LOOP_ACTIVE = False
    return "BOT PAUSED"


@app.route("/start")
def start():
    global LOOP_ACTIVE
    LOOP_ACTIVE = True
    return "BOT RESUMED"


if __name__ == "__main__":
    threading.Thread(target=loop_thread, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
