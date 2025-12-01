from flask import Flask, jsonify
import requests
import hmac
import hashlib
import time
import base64
import math
from threading import Thread
import schedule

app = Flask(__name__)

# --- Bitget API Configuration ---
# You MUST replace these with your actual Bitget API credentials
API_KEY = "YOUR_BITGET_API_KEY"
SECRET_KEY = "YOUR_BITGET_SECRET_KEY"
PASSWORD = "YOUR_BITGET_PASSWORD" # Passphrase for Bitget

BASE_URL = "https://api.bitget.com"

# --- Trading Parameters ---
SYMBOL = "BTCUSDT_UMCBL"  # BTCUSDT Perpetual futures
LEVERAGE = 10
MARGIN_MODE = "isolated" # isolated or cross

# --- Strategy Parameters ---
EMA_SHORT_PERIOD = 50
EMA_LONG_PERIOD = 200
RSI_PERIOD = 14
SUPER_TREND_PERIOD = 10
SUPER_TREND_MULTIPLIER = 3

# Global variable to keep track of the current position
# Can be 'long', 'short', or 'none'
current_position = "none"

# --- Helper Functions for Bitget API ---
def generate_signature(timestamp, method, request_path, body=None):
    if body is None:
        body = ""
    message = str(timestamp) + method.upper() + request_path + str(body)
    hmac_key = base64.b64decode(SECRET_KEY)
    signature = hmac.new(hmac_key, message.encode('utf-8'), hashlib.sha256).digest()
    return base64.b64encode(signature).decode('utf-8')

def bitget_request(method, path, params=None, body=None):
    timestamp = str(int(time.time() * 1000))
    request_path = "/api/v2/mix/market" + path if "market" in path else "/api/v2/mix/account" + path if "account" in path else "/api/v2/mix/trade" + path
    
    headers = {
        "Content-Type": "application/json",
        "X-BG-API-KEY": API_KEY,
        "X-BG-API-TIMESTAMP": timestamp,
        "X-BG-API-PASSPHRASE": PASSWORD,
    }

    if body:
        body_str = jsonify(body).data.decode('utf-8')
        headers["X-BG-API-SIGN"] = generate_signature(timestamp, method, request_path, body_str)
    else:
        headers["X-BG-API-SIGN"] = generate_signature(timestamp, method, request_path)

    url = BASE_URL + request_path
    
    try:
        if method.upper() == "GET":
            response = requests.get(url, headers=headers, params=params)
        elif method.upper() == "POST":
            response = requests.post(url, headers=headers, json=body)
        else:
            return {"error": "Unsupported HTTP method"}

        response.raise_for_status() # Raise an HTTPError for bad responses (4xx or 5xx)
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Bitget API Request Error: {e}")
        return {"error": str(e)}

# --- Bitget Specific Operations ---
def get_balance(coin="USDT"):
    response = bitget_request("GET", f"/account/getAccountList?productType=UMCBL&coin={coin}")
    if response and response.get('code') == '00000' and response.get('data'):
        for account in response['data']:
            if account['marginCoin'] == coin:
                return float(account['available'])
    return 0.0

def get_market_price(symbol=SYMBOL):
    response = bitget_request("GET", f"/market/tickers?symbol={symbol}")
    if response and response.get('code') == '00000' and response.get('data'):
        return float(response['data'][0]['lastPr'])
    return 0.0

def get_klines(symbol=SYMBOL, interval="15m", limit=200):
    response = bitget_request("GET", f"/market/candles?symbol={symbol}&granularity={interval}&limit={limit}")
    if response and response.get('code') == '00000' and response.get('data'):
        # Bitget returns [timestamp, open, high, low, close, volume, ...]
        # We need [close] for calculations
        return [float(kline[4]) for kline in response['data']]
    return []

def set_leverage(symbol=SYMBOL, leverage=LEVERAGE, margin_type=MARGIN_MODE):
    body = {
        "symbol": symbol,
        "marginCoin": "USDT",
        "leverage": str(leverage),
        "holdSide": "long", # Set leverage for long
        "marginMode": margin_type
    }
    response_long = bitget_request("POST", "/trade/setLeverage", body=body)
    
    body["holdSide"] = "short" # Set leverage for short
    response_short = bitget_request("POST", "/trade/setLeverage", body=body)

    return response_long, response_short

def set_margin_mode(symbol=SYMBOL, margin_type=MARGIN_MODE):
    body = {
        "symbol": symbol,
        "marginCoin": "USDT",
        "marginMode": margin_type
    }
    return bitget_request("POST", "/trade/setMarginMode", body=body)

def open_position(symbol=SYMBOL, side="long", volume_usdt=0):
    price = get_market_price(symbol)
    if price == 0:
        print("Failed to get market price, cannot open position.")
        return {"error": "Failed to get market price"}

    if volume_usdt <= 0:
        print("Volume in USDT must be greater than 0 to open a position.")
        return {"error": "Invalid volume"}

    # Calculate actual size in base currency (e.g., BTC for BTCUSDT)
    # Using available balance for the order, divided by price
    order_size = (volume_usdt * LEVERAGE) / price
    
    # Bitget requires string for quantity, and sometimes specific precision
    # For BTCUSDT, a common precision is 3-5 decimal places for quantity
    order_size = math.floor(order_size * 100000) / 100000.0 # Example: 5 decimal places precision

    if order_size <= 0:
        print("Calculated order size is too small or zero.")
        return {"error": "Calculated order size too small"}

    body = {
        "symbol": symbol,
        "marginCoin": "USDT",
        "side": side.upper(), # 'BUY' for long, 'SELL' for short
        "orderType": "market",
        "price": str(price), # Market order does not strictly need price, but good to include
        "size": str(order_size),
        "tradeMode": "isolated", # Ensure consistent margin mode
        "posSide": side.upper(), # 'long' or 'short' position side
    }

    print(f"Attempting to open {side} position with body: {body}")
    response = bitget_request("POST", "/trade/placeOrder", body=body)
    print(f"Open position response: {response}")
    return response

def close_all_positions(symbol=SYMBOL):
    response = bitget_request("POST", "/trade/closeAllFills", body={"symbol": symbol})
    print(f"Close all positions response: {response}")
    return response

# --- Indicator Calculations ---
def calculate_ema(prices, period):
    ema = [0.0] * len(prices)
    if not prices:
        return ema
    ema[0] = prices[0]
    multiplier = 2 / (period + 1)
    for i in range(1, len(prices)):
        ema[i] = (prices[i] - ema[i-1]) * multiplier + ema[i-1]
    return ema

def calculate_rsi(prices, period):
    if len(prices) < period:
        return [0.0] * len(prices)

    gains = []
    losses = []
    for i in range(1, len(prices)):
        diff = prices[i] - prices[i-1]
        if diff > 0:
            gains.append(diff)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(diff))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    rs = avg_gain / avg_loss if avg_loss != 0 else 200 # Avoid division by zero, treat as very strong gain

    rsi = [0.0] * len(prices)
    rsi[period-1] = 100 - (100 / (1 + rs))

    for i in range(period, len(prices)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i-1]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i-1]) / period
        rs = avg_gain / avg_loss if avg_loss != 0 else 200
        rsi[i] = 100 - (100 / (1 + rs))
    return rsi

def calculate_supertrend(candles, period, multiplier):
    # candles: list of [timestamp, open, high, low, close, volume]
    if len(candles) < period:
        return [0.0] * len(candles), ["none"] * len(candles)

    highs = [float(c[2]) for c in candles]
    lows = [float(c[3]) for c in candles]
    closes = [float(c[4]) for c in cands]

    atr_values = [0.0] * len(candles)
    supertrend = [0.0] * len(candles)
    trend_direction = ["none"] * len(candles) # 'up' or 'down'

    # Calculate ATR
    for i in range(1, len(candles)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        if i == period:
            atr_values[i] = sum(atr_values[1:period+1]) / period
        elif i > period:
            atr_values[i] = (atr_values[i-1] * (period - 1) + tr) / period

    # Calculate Supertrend
    for i in range(period, len(candles)):
        upper_band = ((highs[i] + lows[i]) / 2) + (multiplier * atr_values[i])
        lower_band = ((highs[i] + lows[i]) / 2) - (multiplier * atr_values[i])

        if i == period:
            supertrend[i] = upper_band # Initial value, assuming downtrend
            trend_direction[i] = "down"
        else:
            if closes[i] > supertrend[i-1]:
                trend_direction[i] = "up"
            elif closes[i] < supertrend[i-1]:
                trend_direction[i] = "down"
            else: # No change in trend
                trend_direction[i] = trend_direction[i-1]
            
            # Adjust bands based on previous trend
            if trend_direction[i] == "up":
                supertrend[i] = max(lower_band, supertrend[i-1])
            else: # trend_direction[i] == "down"
                supertrend[i] = min(upper_band, supertrend[i-1])
    
    return supertrend, trend_direction


# --- Automated Trading Strategy ---
def execute_trading_strategy():
    global current_position

    print(f"--- Running Automated Strategy at {time.ctime()} ---")
    
    # 1. Get Klines for indicators (e.g., 1-hour interval, enough data)
    # Bitget klines returns [timestamp, open, high, low, close, volume]
    cands = bitget_request("GET", f"/market/candles?symbol={SYMBOL}&granularity=1h&limit=200")
    if not cands or not cands.get('data'):
        print("Failed to get klines data.")
        return

    closes = [float(c[4]) for c in cands['data']]
    
    if len(closes) < max(EMA_LONG_PERIOD, RSI_PERIOD, SUPER_TREND_PERIOD):
        print("Not enough klines data to calculate indicators.")
        return

    # 2. Calculate Indicators
    ema_short = calculate_ema(closes, EMA_SHORT_PERIOD)
    ema_long = calculate_ema(closes, EMA_LONG_PERIOD)
    rsi = calculate_rsi(closes, RSI_PERIOD)
    super_trend_values, super_trend_dirs = calculate_supertrend(cands['data'], SUPER_TREND_PERIOD, SUPER_TREND_MULTIPLIER)

    # Get the latest indicator values
    latest_ema_short = ema_short[-1]
    latest_ema_long = ema_long[-1]
    latest_rsi = rsi[-1]
    latest_close_price = closes[-1]
    latest_super_trend_value = super_trend_values[-1]
    latest_super_trend_dir = super_trend_dirs[-1]

    print(f"Latest Close: {latest_close_price}")
    print(f"EMA {EMA_SHORT_PERIOD}: {latest_ema_short}, EMA {EMA_LONG_PERIOD}: {latest_ema_long}")
    print(f"RSI {RSI_PERIOD}: {latest_rsi}")
    print(f"Supertrend ({SUPER_TREND_PERIOD}, {SUPER_TREND_MULTIPLIER}): {latest_super_trend_value}, Dir: {latest_super_trend_dir}")
    print(f"Current Position: {current_position}")


    # 3. Strategy Logic
    # Trend Filter (EMA Cross)
    ema_trend_up = latest_ema_short > latest_ema_long
    ema_trend_down = latest_ema_short < latest_ema_long

    # Get available balance for position sizing
    available_usdt = get_balance("USDT")
    if available_usdt < 5: # Minimum trade amount e.g. 5 USDT
        print(f"Insufficient balance for trading. Available: {available_usdt} USDT")
        return

    # --- Long Entry Condition ---
    if (ema_trend_up and
        latest_rsi < 40 and # Slightly lower RSI for potential bounce/entry
        latest_close_price > latest_super_trend_value and latest_super_trend_dir == "up"): # Price above ST and ST is up
        
        if current_position != "long":
            print("--- LONG Signal Detected ---")
            # Close existing short position if any
            if current_position == "short":
                print("Closing existing SHORT position before opening LONG.")
                close_all_positions(SYMBOL)
                time.sleep(2) # Wait for close to process

            response = open_position(SYMBOL, "long", available_usdt)
            if response and response.get('code') == '00000':
                current_position = "long"
                print("Successfully opened LONG position.")
            else:
                print(f"Failed to open LONG position: {response}")
        else:
            print("Already in a LONG position, doing nothing.")

    # --- Short Entry Condition ---
    elif (ema_trend_down and
          latest_rsi > 60 and # Slightly higher RSI for potential pullback/entry
          latest_close_price < latest_super_trend_value and latest_super_trend_dir == "down"): # Price below ST and ST is down
        
        if current_position != "short":
            print("--- SHORT Signal Detected ---")
            # Close existing long position if any
            if current_position == "long":
                print("Closing existing LONG position before opening SHORT.")
                close_all_positions(SYMBOL)
                time.sleep(2) # Wait for close to process

            response = open_position(SYMBOL, "short", available_usdt)
            if response and response.get('code') == '00000':
                current_position = "short"
                print("Successfully opened SHORT position.")
            else:
                print(f"Failed to open SHORT position: {response}")
        else:
            print("Already in a SHORT position, doing nothing.")

    # --- Exit/Reverse Condition (Supertrend crossover acts as exit) ---
    # If we are long and Supertrend flips to down
    elif current_position == "long" and latest_super_trend_dir == "down":
        print("--- LONG Exit Signal (Supertrend Down) ---")
        response = close_all_positions(SYMBOL)
        if response and response.get('code') == '00000':
            current_position = "none"
            print("Successfully closed LONG position.")
        else:
            print(f"Failed to close LONG position: {response}")

    # If we are short and Supertrend flips to up
    elif current_position == "short" and latest_super_trend_dir == "up":
        print("--- SHORT Exit Signal (Supertrend Up) ---")
        response = close_all_positions(SYMBOL)
        if response and response.get('code') == '00000':
            current_position = "none"
            print("Successfully closed SHORT position.")
        else:
            print(f"Failed to close SHORT position: {response}")

    else:
        print("No strong signal or current position maintained.")
    print("--------------------------------------------------")

# --- Scheduler Setup ---
def run_scheduler():
    # Set initial leverage and margin mode once at startup
    print("Setting initial leverage and margin mode...")
    set_leverage(SYMBOL, LEVERAGE, MARGIN_MODE)
    set_margin_mode(SYMBOL, MARGIN_MODE)
    print("Initial setup complete.")

    # Schedule the strategy to run every 30 seconds
    schedule.every(30).seconds.do(execute_trading_strategy)
    
    while True:
        schedule.run_pending()
        time.sleep(1) # Sleep to avoid busy-waiting

# Start the scheduler in a separate thread
scheduler_thread = Thread(target=run_scheduler)
scheduler_thread.daemon = True # Allow main program to exit even if thread is running
scheduler_thread.start()


# --- Flask Routes ---
@app.route('/')
def home():
    return "ربات Bitget REAL فعال است - کاملا اتوماتیک."

@app.route('/status')
def status():
    return jsonify({
        "status": "running",
        "current_position": current_position,
        "symbol": SYMBOL,
        "leverage": LEVERAGE,
        "margin_mode": MARGIN_MODE
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
