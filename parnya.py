import os
import threading
import time
import hmac
import hashlib
import json
import requests
from flask import Flask, request

# --- Configuration ---
API_KEY = os.getenv('API_KEY', '') # Ensure this variable is set in Render
SECRET_KEY = os.getenv('SECRET_KEY', '') # Ensure this variable is set in Render
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '') # <--- YOU MUST SET THIS IN RENDER ENVIRONMENT VARIABLES!
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '7156028278') # <--- This is your chat ID
SYMBOL = "BTCUSDT"
LEVERAGE = 10
TRADE_AMOUNT_USDT = 10 # For demo, trade a small amount
INTERVAL = "5min" # KLINE interval

# --- Global Variables for Bot State ---
app = Flask(__name__)
bot_running = False
trade_loop_thread = None
last_run_time = time.time()
position_info = None
start_time = time.time() # To track uptime

# --- Coinex API Endpoints ---
BASE_URL_SPOT = "https://api.coinex.com/v1"
BASE_URL_PERPETUAL = "https://api.coinex.com/perpetual/v1"

# --- Telegram Functions ---
def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN:
        print("Telegram bot token is not set. Cannot send message.")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }
        response = requests.post(url, json=payload)
        response.raise_for_status()
        print(f"Telegram message sent: {message}")
    except requests.exceptions.RequestException as e:
        print(f"Error sending Telegram message: {e}")

# --- Coinex API Utilities ---
def generate_sign(params, secret_key):
    sorted_params = sorted(params.items())
    param_string = "&".join([f"{k}={v}" for k, v in sorted_params])
    sign_string = param_string + "&secret_key=" + secret_key
    return hashlib.md5(sign_string.encode()).hexdigest().upper()

def make_request(method, url, params=None, headers=None, sign_required=False):
    if params is None:
        params = {}
    if headers is None:
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

    if sign_required:
        nonce = str(int(time.time() * 1000))
        params['access_id'] = API_KEY
        params['tonce'] = nonce
        headers['authorization'] = generate_sign(params, SECRET_KEY)

    try:
        if method == 'GET':
            response = requests.get(url, params=params, headers=headers)
        elif method == 'POST':
            response = requests.post(url, json=params, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"API request failed: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Response content: {e.response.text}")
        return None

# --- Coinex Specific Functions ---
def get_spot_kline(symbol, interval, limit=100):
    url = f"{BASE_URL_SPOT}/market/kline"
    params = {
        "market": symbol,
        "type": interval,
        "limit": limit
    }
    response = make_request('GET', url, params=params)
    if response and response.get('code') == 0:
        return response.get('data')
    print(f"Failed to get SPOT kline for {symbol}: {response}")
    return None

def get_perpetual_position(symbol):
    url = f"{BASE_URL_PERPETUAL}/position/list"
    params = {"market": symbol}
    response = make_request('GET', url, params=params, sign_required=True)
    if response and response.get('code') == 0:
        # Check if 'records' key exists and is not empty before accessing index 0
        if response['data'] and response['data'].get('records'):
            return response['data']['records'][0]
        return None # No open positions
    print(f"Failed to get perpetual position for {symbol}: {response}")
    return None


def place_perpetual_order(symbol, side, amount, price=None, type="LIMIT"):
    url = f"{BASE_URL_PERPETUAL}/order/put_limit" if type == "LIMIT" else f"{BASE_URL_PERPETUAL}/order/put_market"
    params = {
        "market": symbol,
        "side": side,
        "amount": amount,
        "type": type,
        "source_id": "CoinexBot",
        "price": price if type == "LIMIT" else None # Price is only for LIMIT orders
    }
    if type == "LIMIT" and price is None:
        print("Limit order requires a price.")
        return None

    response = make_request('POST', url, params=params, sign_required=True)
    if response and response.get('code') == 0:
        print(f"Order placed: {response['data']}")
        send_telegram_message(f"🚨 **ORDER PLACED:**\nSymbol: {symbol}\nSide: {side}\nAmount: {amount}\nPrice: {price if type == 'LIMIT' else 'Market'}")
        return response['data']
    print(f"Failed to place order: {response}")
    send_telegram_message(f"❌ **ORDER FAILED:**\nSymbol: {symbol}\nSide: {side}\nAmount: {amount}\nError: {response}")
    return None

def set_leverage(symbol, leverage):
    url = f"{BASE_URL_PERPETUAL}/market/adjust_leverage"
    params = {
        "market": symbol,
        "leverage": leverage
    }
    response = make_request('POST', url, params=params, sign_required=True)
    if response and response.get('code') == 0:
        print(f"Leverage set to {leverage} for {symbol}")
        return True
    print(f"Failed to set leverage: {response}")
    return False

# --- Trading Logic (Simplified for demonstration) ---
def calculate_indicators(kline_data):
    # Dummy indicators for now, replace with actual calculations
    closes = [float(k[2]) for k in kline_data]
    if len(closes) < 20: # Example minimum data for EMA
        return {"ema50": None, "rsi": None, "macd": None, "atr": None}

    # Basic EMA (replace with proper EMA calculation)
    ema50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else None

    # Dummy RSI, MACD, ATR
    rsi = 50.0 # Placeholder
    macd = {"histogram": 0.0} # Placeholder
    atr = 20.0 # Placeholder

    return {"ema50": ema50, "rsi": rsi, "macd": macd, "atr": atr}

def trading_strategy():
    global position_info
    print("Running trading strategy...")
    kline_data = get_spot_kline(SYMBOL, INTERVAL, limit=200) # Get enough data for indicators
    if not kline_data:
        print("Failed to get kline data. Skipping strategy run.")
        return

    indicators = calculate_indicators(kline_data)
    current_price = float(kline_data[-1][2]) # Last close price

    print(f"Current Price: {current_price}, Indicators: {indicators}")

    position = get_perpetual_position(SYMBOL)
    if position:
        position_info = position
        print(f"Current Position: {position_info}")
        if float(position['value']) > 0: # Check if there is an open position
            # Add logic to close position based on strategy
            print("Position open, checking for close signals...")
            # For demo: Close position if profit/loss reaches a certain threshold or indicator changes
            # Example: Close if price moves significantly against position (replace with real logic)
            # if float(position['realized_pnl']) > 10 or float(position['unrealized_pnl']) < -5:
            #     close_perpetual_order(SYMBOL, position['side'], position['amount'])
            pass
        else:
            position_info = None # No open position
    else:
        position_info = None

    if not position_info:
        # No open position, look for new entry signals
        print("No open position, looking for entry signals...")
        # Placeholder for actual strategy:
        # Example: if EMA50 crosses up, go long
        # if indicators['ema50'] and current_price > indicators['ema50']:
        #     send_telegram_message(f"📈 **LONG SIGNAL!** Current Price: {current_price}")
        #     # Calculate actual amount based on TRADE_AMOUNT_USDT and leverage
        #     amount = TRADE_AMOUNT_USDT * LEVERAGE / current_price # Simplified for market order
        #     place_perpetual_order(SYMBOL, "buy", amount, type="MARKET")
        # elif indicators['ema50'] and current_price < indicators['ema50']:
        #     send_telegram_message(f"📉 **SHORT SIGNAL!** Current Price: {current_price}")
        #     amount = TRADE_AMOUNT_USDT * LEVERAGE / current_price # Simplified for market order
        #     place_perpetual_order(SYMBOL, "sell", amount, type="MARKET")
        send_telegram_message(f"🧡 Heartbeat: Bot is running. Price: {current_price}")


    print("Trading strategy finished.")

def trade_loop():
    global bot_running, last_run_time
    # Set initial leverage
    set_leverage(SYMBOL, LEVERAGE)
    while bot_running:
        try:
            trading_strategy()
            last_run_time = time.time()
        except Exception as e:
            print(f"Error in trade_loop: {e}")
            send_telegram_message(f"‼️ **CRITICAL ERROR in Trade Loop:** {e}")
        finally:
            time.sleep(60) # Run every 60 seconds

# --- Flask Routes ---
@app.route('/')
def home():
    return "CoinEx Futures Bot is running. Access /status for details."

@app.route('/status')
def status():
    uptime = time.time() - start_time
    hours, remainder = divmod(uptime, 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{int(hours)}h {int(minutes)}m {int(seconds)}s"

    last_run_ago = time.time() - last_run_time if last_run_time else "N/A"
    if last_run_ago != "N/A":
        last_run_ago_str = f"{int(last_run_ago)}s ago"
    else:
        last_run_ago_str = "Never run yet"

    status_message = (
        f"Bot Status: {'Running' if bot_running else 'Stopped'}\n"
        f"Uptime: {uptime_str}\n"
        f"Last Run: {last_run_ago_str}\n"
        f"Current Position: {json.dumps(position_info, indent=2) if position_info else 'None'}\n"
        f"Thread Active: {trade_loop_thread.is_alive() if trade_loop_thread else 'False'}"
    )
    return status_message, 200, {'Content-Type': 'text/plain; charset=utf-8'}


@app.route('/start')
def start_bot():
    global bot_running, trade_loop_thread, start_time
    if not bot_running:
        bot_running = True
        start_time = time.time() # Reset uptime on start
        trade_loop_thread = threading.Thread(target=trade_loop)
        trade_loop_thread.start()
        message = "CoinEx bot started!"
        send_telegram_message("✅ **Bot Started!**")
        return message, 200, {'Content-Type': 'text/plain; charset=utf-8'}
    return "CoinEx bot is already running.", 200, {'Content-Type': 'text/plain; charset=utf-8'}

@app.route('/kill')
def kill_bot():
    global bot_running, trade_loop_thread
    if bot_running:
        bot_running = False
        if trade_loop_thread and trade_loop_thread.is_alive():
            trade_loop_thread.join(timeout=5) # Wait for thread to finish gracefully
        message = "CoinEx bot stopped."
        send_telegram_message("🛑 **Bot Stopped!**")
        return message, 200, {'Content-Type': 'text/plain; charset=utf-8'}
    return "CoinEx bot is not running.", 200, {'Content-Type': 'text/plain; charset=utf-8'}

@app.route('/test')
def test_telegram():
    send_telegram_message("✅ **Test Message from Bot!** If you see this, Telegram connection is working.")
    return "Telegram test message sent!", 200, {'Content-Type': 'text/plain; charset=utf-8'}

# --- Main execution ---
if __name__ == '__main__':
    # Start the bot automatically when the Flask app starts
    start_bot()
    # Render uses the PORT environment variable
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
