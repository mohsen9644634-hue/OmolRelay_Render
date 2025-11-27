import os
import time
import hmac
import hashlib
import requests
from fastapi import FastAPI, Request
import uvicorn

app = FastAPI()

# ---------------------------
#  CONFIG (SAFE)
# ---------------------------

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
LBANK_API_KEY = os.getenv("LBANK_API_KEY", "")
LBANK_API_SECRET = os.getenv("LBANK_API_SECRET", "")

TG_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"


# ---------------------------
#  SEND MESSAGE
# ---------------------------

async def send_message(chat_id, text):
    try:
        requests.post(TG_URL, json={"chat_id": chat_id, "text": text})
    except:
        pass


# ---------------------------
#  /ping
# ---------------------------

async def handle_ping(chat_id):
    await send_message(chat_id, "Pong! Relay working!")


# ---------------------------
#  /order (SAFE)
# ---------------------------

async def handle_order(chat_id, text):
    try:
        parts = text.split()
        _, symbol, side, qty = parts
        symbol = symbol.upper()
        side = side.upper()
        qty = float(qty)

        endpoint = "/v2/futures/createOrder"
        url = "https://www.lbkex.net" + endpoint
        ts = str(int(time.time()*1000))

        payload = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "positionMode": "ISOLATED",
            "leverage": 25,
            "quantity": qty,
            "timestamp": ts
        }

        query = "&".join(f"{k}={payload[k]}" for k in sorted(payload))
        sig = hmac.new(LBANK_API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
        payload["signature"] = sig

        r = requests.post(url, data=payload, headers={"X-LBAPI-KEY": LBANK_API_KEY})
        res = r.json()

        if str(res.get("code")) == "0":
            await send_message(chat_id, "OK\n" + str(res))
        else:
            await send_message(chat_id, "ERR\n" + str(res))

    except Exception as e:
        await send_message(chat_id, "ERR\n" + str(e))


# ---------------------------
#  TELEGRAM WEBHOOK HANDLER
# ---------------------------

@app.post("/telegram")
async def telegram_webhook(request: Request):
    data = await request.json()

    try:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"].get("text", "")
    except:
        return {"ok": True}

    if text.startswith("/ping"):
        await handle_ping(chat_id)

    elif text.startswith("/order"):
        await handle_order(chat_id, text)

    return {"ok": True}


# ---------------------------
#  ROOT
# ---------------------------

@app.get("/")
async def home():
    return {"status": "OK", "relay": "running"}


# ---------------------------
#  START (LOCAL ONLY)
# ---------------------------

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

