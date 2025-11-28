import os
import time
import hmac
import hashlib
import httpx
from fastapi import FastAPI, Request

app = FastAPI()

# ---------------------------
# Environment Variables
# ---------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
LBANK_API_KEY = os.getenv("LBANK_API_KEY")
LBANK_API_SECRET = os.getenv("LBANK_API_SECRET")

BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
LBANK_BASE = "https://www.lbkex.net"
SYMBOL = "BTCUSDT"


# ---------------------------
# Telegram Sender
# ---------------------------
async def send_message(chat_id, text):
    url = f"{BASE_URL}/sendMessage"
    data = {"chat_id": chat_id, "text": text}
    async with httpx.AsyncClient() as client:
        r = await client.post(url, json=data)
        return r.text


# ---------------------------
# LBank Signature
# ---------------------------
def lbank_sign(params: dict):
    keys = sorted(params.keys())
    query = "&".join([f"{k}={params[k]}" for k in keys])
    sign = hmac.new(
        LBANK_API_SECRET.encode(),
        query.encode(),
        hashlib.sha256
    ).hexdigest()
    return sign


# ---------------------------
# Create Order (Market)
# ---------------------------
async def lbank_order(side: str, amount: float):
    endpoint = "/v2/upp/order/create"
    url = LBANK_BASE + endpoint

    ts = int(time.time() * 1000)

    body = {
        "api_key": LBANK_API_KEY,
        "symbol": SYMBOL,
        "type": "market",
        "side": side,
        "amount": str(amount),
        "timestamp": ts
    }

    body["sign"] = lbank_sign(body)

    async with httpx.AsyncClient() as client:
        r = await client.post(url, json=body)
        return r.json()


# ---------------------------
# Close Position
# ---------------------------
async def lbank_close():
    endpoint = "/v2/upp/order/close"
    url = LBANK_BASE + endpoint

    ts = int(time.time() * 1000)

    body = {
        "api_key": LBANK_API_KEY,
        "symbol": SYMBOL,
        "timestamp": ts
    }

    body["sign"] = lbank_sign(body)

    async with httpx.AsyncClient() as client:
        r = await client.post(url, json=body)
        return r.json()


# ---------------------------
# Telegram Webhook
# ---------------------------
@app.post("/telegram")
async def telegram_webhook(request: Request):
    update = await request.json()

    try:
        message = update.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        text = message.get("text", "")

        if not text:
            return {"ok": True}

        # ---- /ping ----
        if text == "/ping":
            await send_message(chat_id, "Pong! Relay working! ⚡️")
            return {"ok": True}

        # ---- /help ----
        if text == "/help":
            help_msg = (
                "/ping → تست ربات\n"
                "/order long 10 → ورود لانگ\n"
                "/order short 10 → ورود شورت\n"
                "/close → بستن پوزیشن\n"
            )
            await send_message(chat_id, help_msg)
            return {"ok": True}

        # ---- /order ----
        if text.startswith("/order"):
            parts = text.split()
            if len(parts) != 3:
                await send_message(chat_id, "فرمت صحیح: /order long 10")
                return {"ok": True}

            _, direction, amount_str = parts
            direction = direction.lower()

            if direction not in ["long", "short"]:
                await send_message(chat_id, "نوع باید long یا short باشد.")
                return {"ok": True}

            try:
                amount = float(amount_str)
            except:
                await send_message(chat_id, "عدد حجم معتبر نیست.")
                return {"ok": True}

            side = "buy" if direction == "long" else "sell"
            result = await lbank_order(side, amount)

            await send_message(chat_id, f"نتیجه سفارش:\n{result}")
            return {"ok": True}

        # ---- /close ----
        if text == "/close":
            result = await lbank_close()
            await send_message(chat_id, f"نتیجه بستن پوزیشن:\n{result}")
            return {"ok": True}

        return {"ok": True}

    except Exception as e:
        # جلوگیری از Crash خاموش
        return {"ok": True, "error": str(e)}
