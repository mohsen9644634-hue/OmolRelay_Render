import os
import time
import hmac
import hashlib
import httpx
from fastapi import FastAPI, Request

app = FastAPI()

# ----------------------------
# Environment
# ----------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
LBANK_API_KEY = os.getenv("LBANK_API_KEY")
LBANK_API_SECRET = os.getenv("LBANK_API_SECRET")

LBANK_BASE = "https://api.lbkex.com"


# ----------------------------
# Telegram Send Message
# ----------------------------
async def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    async with httpx.AsyncClient() as client:
        await client.post(url, data={"chat_id": chat_id, "text": text})


# ----------------------------
# LBank Signature (v2)
# ----------------------------
def lbank_sign(params: dict) -> dict:
    params["api_key"] = LBANK_API_KEY
    params["timestamp"] = int(time.time() * 1000)

    items = sorted(params.items())
    sign_string = "".join([f"{k}{v}" for k, v in items]) + LBANK_API_SECRET
    signature = hashlib.md5(sign_string.encode()).hexdigest()

    params["sign"] = signature
    return params


# ----------------------------
# Create Order (Open Position)
# ----------------------------
async def lbank_order(direction: str, amount: float):
    url = f"{LBANK_BASE}/v2/future/order/create"

    params = {
        "symbol": "BTCUSDT",
        "size": amount,
        "type": "market",
        "side": 1 if direction == "long" else 2,
        "leverage": 25,
        "open_type": "isolated"
    }

    signed = lbank_sign(params)

    async with httpx.AsyncClient() as client:
        r = await client.post(url, data=signed)
        return r.json()


# ----------------------------
# Close Position (Reduce-Only)
# ----------------------------
async def lbank_close():
    url = f"{LBANK_BASE}/v2/future/order/create"

    params = {
        "symbol": "BTCUSDT",
        "size": 9999,              # close ALL
        "type": "market",
        "side": 3,                 # reduce only
        "reduce_only": True
    }

    signed = lbank_sign(params)

    async with httpx.AsyncClient() as client:
        r = await client.post(url, data=signed)
        return r.json()


# ----------------------------
# Telegram Webhook
# ----------------------------
@app.post("/telegram")
async def telegram_webhook(request: Request):
    update = await request.json()
    print("RAW Telegram Update:", update)

    try:
        msg = update["message"]
        chat_id = msg["chat"]["id"]
        text = msg.get("text", "")
    except:
        return {"ok": True}

    # -----------------------------------------
    # /ping
    # -----------------------------------------
    if text == "/ping":
        await send_message(chat_id, "Pong! Relay working! ⚡️")
        return {"ok": True}

    # -----------------------------------------
    # /order long 10
    # /order short 10
    # /order close
    # -----------------------------------------
    if text.startswith("/order"):
        parts = text.split()

        # Long / Short with amount
        if len(parts) == 3:
            _, direction, amount = parts
            direction = direction.lower()

            if direction not in ["long", "short"]:
                await send_message(chat_id, "Direction must be: long | short")
                return {"ok": True}

            try:
                amount = float(amount)
            except:
                await send_message(chat_id, "Amount must be a number")
                return {"ok": True}

            await send_message(chat_id, f"Executing {direction.upper()} x{amount} ...")
            result = await lbank_order(direction, amount)
            await send_message(chat_id, f"LBank Response:\n{result}")
            return {"ok": True}

        # Close position
        if len(parts) == 2 and parts[1] == "close":
            await send_message(chat_id, "Closing position...")
            result = await lbank_close()
            await send_message(chat_id, f"LBank Response:\n{result}")
            return {"ok": True}

        await send_message(chat_id, "Format:\n/order long 10\n/order short 10\n/order close")
        return {"ok": True}

    return {"ok": True}
