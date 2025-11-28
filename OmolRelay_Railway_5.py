import os
import json
import httpx
from fastapi import FastAPI, Request

app = FastAPI()

BOT_TOKEN = os.getenv("BOT_TOKEN")
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"


# -----------------------------
# SEND MESSAGE
# -----------------------------
async def send_message(chat_id, text):
    url = f"{TELEGRAM_API}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            r = await client.post(url, json=payload)
            print("📨 send_message response →", r.text)
        except Exception as e:
            print("❌ send_message error:", e)


# -----------------------------
# HANDLE /PING
# -----------------------------
async def handle_ping(chat_id):
    await send_message(chat_id, "Pong! Relay working!")


# -----------------------------
# HANDLE /ORDER
# -----------------------------
async def handle_order(chat_id, text):
    try:
        order = text.replace("/order", "").strip()
        if not order:
            await send_message(chat_id, "❌ Order is empty!")
            return

        await send_message(chat_id, f"✅ Order received:\n{order}")

    except Exception as e:
        print("❌ handle_order error:", e)
        await send_message(chat_id, "ERR\n" + str(e))


# -----------------------------
# TELEGRAM WEBHOOK HANDLER
# -----------------------------
@app.post("/telegram")
async def telegram_webhook(request: Request):
    data = await request.json()
    print("📩 Raw update:", data)

    # Extract message safely
    try:
        message = data["message"]
        chat_id = message["chat"]["id"]
        text = message.get("text", "")
    except Exception as e:
        print("❌ Cannot parse update:", e)
        return {"ok": True}

    print(f"👉 chat_id={chat_id} | text='{text}'")

    # Commands
    if text.startswith("/ping"):
        await handle_ping(chat_id)

    elif text.startswith("/order"):
        await handle_order(chat_id, text)

    else:
        await send_message(chat_id, "Unknown command")

    return {"ok": True}


# -----------------------------
# ROOT
# -----------------------------
@app.get("/")
async def home():
    return {"status": "OK", "relay": "running"}


# -----------------------------
# START
# -----------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=port)
