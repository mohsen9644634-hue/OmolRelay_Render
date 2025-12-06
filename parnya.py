import os
import time
import threading
from flask import Flask, request, jsonify
import requests
import hmac
import hashlib
import json
import base64
from datetime import datetime

# --- Global Variables ---
app = Flask(__name__)
bot_running = True
start_time = datetime.now()

# --- Utility Functions ---
def get_signature(payload, secret_key):
    """Generates a CoinEx API signature."""
    sha256 = hmac.new(secret_key.encode(), payload.encode(), hashlib.sha256).digest()
    return base64.b64encode(sha256).decode().strip()

def send_telegram(message, chat_id=None):
    """Sends a message to Telegram."""
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    if chat_id is None:
        TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
    else:
        TELEGRAM_CHAT_ID = chat_id # Use provided chat_id if available

    if not TELEGRAM_BOT_TOKEN:
        print("Telegram BOT_TOKEN not set in environment variables. Cannot send message.")
        return False
    if not TELEGRAM_CHAT_ID:
        print("Telegram CHAT_ID not set in environment variables (or not provided). Cannot send message.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML" # Optional: for rich text formatting
    }
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        print(f"Telegram message sent to {TELEGRAM_CHAT_ID}: {message}")
        return True
    except requests.exceptions.RequestException as e:
        print(f"Error sending Telegram message: {e}")
        return False

# --- CoinEx API Interaction (simplified for example) ---
def get_spot_kline(market="BTCUSDT", type="1min", limit=1):
    """Fetches KLine data from CoinEx Spot API."""
    url = f"https://api.coinex.com/v1/market/kline?market={market}&type={type}&limit={limit}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        if data and data['code'] == 0 and data['data']:
            # Assuming the latest kline is the last element
            kline = data['data'][-1]
            # KLine structure: [timestamp, open, close, high, low, volume, amount]
            return {
                "timestamp": kline[0],
                "open": float(kline[1]),
                "close": float(kline[2]),
                "high": float(kline[3]),
                "low": float(kline[4]),
                "volume": float(kline[5]),
                "amount": float(kline[6])
            }
        else:
            print(f"Error or empty data fetching spot kline: {data}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"Network error fetching spot kline: {e}")
        return None
    except Exception as e:
        print(f"Error processing spot kline data: {e}")
        return None

def fetch_futures_balance():
    """Fetches CoinEx Futures account balance."""
    API_KEY = os.getenv("API_KEY")
    SECRET_KEY = os.getenv("SECRET_KEY")
    if not API_KEY or not SECRET_KEY:
        print("CoinEx API_KEY or SECRET_KEY not set in environment variables. Cannot fetch balance.")
        return None

    url = "https://api.coinex.com/perpetual/v1/account/assets"
    timestamp = int(time.time() * 1000)
    params = {
        "access_id": API_KEY,
        "timestamp": timestamp,
    }
    sorted_params = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
    signature = get_signature(sorted_params, SECRET_KEY)

    headers = {
        "Authorization": f"HMAC-SHA256 ApiKey={API_KEY},Signature={signature},Timestamp={timestamp}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        if data and data['code'] == 0:
            # Simplified balance extraction
            usdt_asset = next((asset for asset in data['data']['assets'] if asset['asset'] == 'USDT'), None)
            if usdt_asset:
                return float(usdt_asset['available_balance'])
            else:
                print("USDT asset not found in futures balance.")
                return 0.0
        else:
            print(f"Error fetching futures balance: {data}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"Network error fetching futures balance: {e}")
        return None
    except Exception as e:
        print(f"Error processing futures balance data: {e}")
        return None

# --- Bot Logic Loop ---
def bot_loop():
    """Main trading bot logic."""
    global bot_running
    while bot_running:
        print("Bot loop running...")
        kline_data = get_spot_kline()
        if kline_data:
            print(f"Latest KLine (Spot): {kline_data}")
            # Here you would implement your MACD/EMA50/RSI/ATR strategy
            # For demonstration, let's just log and sleep
            send_telegram(f"Bot active. Latest close: {kline_data['close']}")
        else:
            print("Failed to get KLine data.")
            send_telegram("Bot warning: Failed to get KLine data.")

        futures_balance = fetch_futures_balance()
        if futures_balance is not None:
            print(f"Futures USDT Available Balance: {futures_balance}")
        else:
            print("Failed to get futures balance.")

        time.sleep(60) # Run every minute

# --- Flask Routes ---
@app.route('/')
def home():
    """Root endpoint."""
    return "Ultra PRO++ Render-STABLE Bot Running"

@app.route('/status')
def status():
    """Returns bot status and uptime."""
    uptime = datetime.now() - start_time
    status_message = {
        "status": "Running" if bot_running else "Stopped",
        "uptime": str(uptime),
        "version": "Ultra PRO++ Render-STABLE",
        "message": "Bot is operational. Check logs for strategy execution details."
    }
    return jsonify(status_message)

@app.route('/kill')
def kill_bot():
    """Stops the bot loop."""
    global bot_running
    if bot_running:
        bot_running = False
        send_telegram("Bot has been commanded to stop.")
        return "Bot stopping..."
    return "Bot already stopped."

@app.route('/start')
def start_bot():
    """Starts the bot loop."""
    global bot_running
    if not bot_running:
        bot_running = True
        threading.Thread(target=bot_loop).start()
        send_telegram("Bot has been commanded to start.")
        return "Bot starting..."
    return "Bot already running."

@app.route('/test')
def test_telegram_connection():
    """Tests Telegram message sending."""
    message = "Test OK from Render"
    if send_telegram(message):
        return "Telegram test sent"
    else:
        return "Failed to send Telegram test message. Check logs."

@app.route('/telegram', methods=['POST'])
def telegram_webhook():
    """Handles incoming Telegram webhook updates."""
    try:
        update = request.get_json()
        if update:
            print(f"Received Telegram update: {json.dumps(update, indent=2)}")
            # --- You can add your logic here to process incoming Telegram messages ---
            if 'message' in update and 'text' in update['message']:
                user_message = update['message']['text']
                chat_id = update['message']['chat']['id']
                print(f"Message from {chat_id}: {user_message}")
                # Example: send a simple echo reply back to the user
                # send_telegram(f"Echo: {user_message}", chat_id=chat_id)
            # ---------------------------------------------------------------------
            return jsonify({"status": "ok", "message": "Update received"}), 200
        else:
            print("Received empty or invalid Telegram update.")
            return jsonify({"status": "error", "message": "Invalid update"}), 400
    except Exception as e:
        print(f"Error processing Telegram webhook: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# --- Main execution ---
if __name__ == '__main__':
    # Start the bot logic in a separate thread
    threading.Thread(target=bot_loop).start()
    # Run the Flask app
    app.run(host='0.0.0.0', port=os.getenv("PORT", 10000))
