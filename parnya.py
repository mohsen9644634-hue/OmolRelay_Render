from flask import Flask, request, jsonify
import os, time, requests, hmac, hashlib
import pandas as pd
import numpy as np

app = Flask(__name__)

BASE_URL = "https://api.coinex.com/v1"
API_KEY = os.getenv("COINEX_KEY", "")
SECRET = os.getenv("COINEX_SECRET", "").encode()
TRADE_TOKEN = os.getenv("TRADE_TOKEN", "Mp0551977") # This is for /trade endpoint, not directly used in /scan for signal
SYMBOL = "BTCUSDT"
TIMEFRAME = "15min" # Changed to 15-minute timeframe

# Telegram Bot configuration - IMPORTANT: Set these as environment variables in Render
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# --- Helper Functions ---

# Signing function for CoinEx API
def sign(params):
    items = sorted(params.items())
    qs = '&'.join([f"{k}={v}" for k,v in items])
    return hmac.new(SECRET, qs.encode(), hashlib.sha256).hexdigest()

# CoinEx API request function
def ce_request(url, params=None):
    if params is None: params = {}
    params['access_id'] = API_KEY
    params['tonce'] = int(time.time()*1000)
    params['sign'] = sign(params)
    
    headers = {
        'Content-Type': 'application/json; charset=utf-8'
    }
    
    try:
        r = requests.get(BASE_URL + url, params=params, headers=headers, timeout=10)
        r.raise_for_status() # Raise an exception for HTTP errors
        return r.json()
    except requests.exceptions.RequestException as e:
        print(f"CoinEx API request failed: {e}")
        return {"code": -1, "message": str(e), "data": None}

# Function to send Telegram messages
def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram bot token or chat ID not set. Cannot send message.")
        return {"ok": False, "description": "Telegram config missing"}

    telegram_api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        response = requests.post(telegram_api_url, json=payload, timeout=5)
        response.raise_for_status()
        print(f"Telegram message sent: {message}")
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Failed to send Telegram message: {e}")
        return {"ok": False, "description": str(e)}

# --- Indicator Calculation Functions ---

def calculate_rsi(df, window=14):
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    return df

def calculate_macd(df, short_window=12, long_window=26, signal_window=9):
    df['ema_short'] = df['close'].ewm(span=short_window, adjust=False).mean()
    df['ema_long'] = df['close'].ewm(span=long_window, adjust=False).mean()
    df['macd'] = df['ema_short'] - df['ema_long']
    df['macd_signal'] = df['macd'].ewm(span=signal_window, adjust=False).mean()
    df['macd_hist'] = df['macd'] - df['macd_signal']
    return df

def calculate_atr(df, window=14):
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    tr = pd.DataFrame({'high_low': high_low, 'high_close': high_close, 'low_close': low_close}).max(axis=1)
    df['atr'] = tr.ewm(span=window, adjust=False).mean()
    return df

def calculate_ema(df, window=20):
    df[f'ema_{window}'] = df['close'].ewm(span=window, adjust=False).mean()
    return df

# --- Flask Routes ---

@app.route('/')
def home():
    return 'ربات سالم اجرا شد!'

@app.route('/status')
def status():
    return jsonify({"running": True, "symbol": SYMBOL, "timeframe": TIMEFRAME})

@app.route('/scan')
def scan():
    # Fetch kline data for the specified symbol and timeframe
    kline_params = {
        'market': SYMBOL,
        'type': TIMEFRAME,
        'limit': 100 # Fetch enough data for indicators
    }
    kline_response = ce_request("/market/kline", params=kline_params)

    if kline_response.get("code") != 0 or not kline_response.get("data"):
        error_msg = f"Failed to fetch kline data: {kline_response.get('message', 'Unknown error')}"
        send_telegram_message(f"🚨 Error fetching kline for {SYMBOL}: {error_msg}")
        return jsonify({"status": "error", "message": error_msg}), 500

    kline_data = kline_response['data']
    if not kline_data:
        msg = f"No kline data received for {SYMBOL} on {TIMEFRAME}."
        send_telegram_message(f"⚠️ {msg}")
        return jsonify({"status": "warning", "message": msg})

    # Convert kline data to DataFrame for indicator calculation
    # Each kline entry is [timestamp, open, close, high, low, volume, amount]
    df = pd.DataFrame(kline_data, columns=['time', 'open', 'close', 'high', 'low', 'volume', 'amount'])
    df[['open', 'close', 'high', 'low', 'volume', 'amount']] = df[['open', 'close', 'high', 'low', 'volume', 'amount']].astype(float)
    df['time'] = pd.to_datetime(df['time'], unit='s')

    # Calculate indicators
    df = calculate_rsi(df)
    df = calculate_macd(df)
    df = calculate_atr(df)
    df = calculate_ema(df, window=20) # Add 20-period EMA

    # Get the latest candle
    latest_candle = df.iloc[-1]
    previous_candle = df.iloc[-2] # For MACD crossover confirmation

    # --- Signal Logic (More Robust) ---
    signal = "neutral"
    signal_strength = "Weak"
    message = ""
    
    # Check for strong BUY signal
    # MACD crossover (MACD line crosses above signal line)
    macd_buy_cross = (previous_candle['macd'] < previous_candle['macd_signal']) and (latest_candle['macd'] > latest_candle['macd_signal'])
    # RSI confirming buy (RSI below 50 and rising or just crossed above 30)
    rsi_buy_confirm = (latest_candle['rsi'] > previous_candle['rsi']) and (latest_candle['rsi'] < 50)
    # Price above EMA20 for trend confirmation
    price_above_ema = latest_candle['close'] > latest_candle['ema_20']
    
    if macd_buy_cross and rsi_buy_confirm and price_above_ema:
        signal = "BUY"
        signal_strength = "Strong"
        message = (f"🟢 **STRONG BUY SIGNAL** for {SYMBOL} ({TIMEFRAME})!\n\n"
                   f"📊 Price: ${latest_candle['close']:.2f}\n"
                   f"📈 RSI: {latest_candle['rsi']:.2f} (Rising, <50)\n"
                   f"🚀 MACD: {latest_candle['macd']:.2f} (Crossed Signal Line Up)\n"
                   f"ATR (Volatility): {latest_candle['atr']:.2f}\n"
                   f"EMA20: {latest_candle['ema_20']:.2f} (Price above EMA)\n\n"
                   f"👉 Execute a BUY order with caution."
                  )
        send_telegram_message(message)
        
    # Check for strong SELL signal
    # MACD crossover (MACD line crosses below signal line)
    macd_sell_cross = (previous_candle['macd'] > previous_candle['macd_signal']) and (latest_candle['macd'] < latest_candle['macd_signal'])
    # RSI confirming sell (RSI above 50 and falling or just crossed below 70)
    rsi_sell_confirm = (latest_candle['rsi'] < previous_candle['rsi']) and (latest_candle['rsi'] > 50)
    # Price below EMA20 for trend confirmation
    price_below_ema = latest_candle['close'] < latest_candle['ema_20']
    
    if macd_sell_cross and rsi_sell_confirm and price_below_ema:
        signal = "SELL"
        signal_strength = "Strong"
        message = (f"🔴 **STRONG SELL SIGNAL** for {SYMBOL} ({TIMEFRAME})!\n\n"
                   f"📊 Price: ${latest_candle['close']:.2f}\n"
                   f"📉 RSI: {latest_candle['rsi']:.2f} (Falling, >50)\n"
                   f" سقوط MACD: {latest_candle['macd']:.2f} (Crossed Signal Line Down)\n"
                   f"ATR (Volatility): {latest_candle['atr']:.2f}\n"
                   f"EMA20: {latest_candle['ema_20']:.2f} (Price below EMA)\n\n"
                   f"👉 Execute a SELL order with caution."
                  )
        send_telegram_message(message)

    if signal == "neutral":
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] No strong signal for {SYMBOL} on {TIMEFRAME}. Current Close: {latest_candle['close']:.2f}, RSI: {latest_candle['rsi']:.2f}, MACD: {latest_candle['macd']:.2f}")
        return jsonify({
            "status": "ok",
            "symbol": SYMBOL,
            "timeframe": TIMEFRAME,
            "signal": "neutral",
            "message": "No strong signal detected based on current strategy."
        })
    else:
        return jsonify({
            "status": "ok",
            "symbol": SYMBOL,
            "timeframe": TIMEFRAME,
            "signal": signal,
            "strength": signal_strength,
            "current_price": f"{latest_candle['close']:.2f}",
            "rsi": f"{latest_candle['rsi']:.2f}",
            "macd": f"{latest_candle['macd']:.2f}",
            "macd_signal_line": f"{latest_candle['macd_signal']:.2f}",
            "atr": f"{latest_candle['atr']:.2f}",
            "ema20": f"{latest_candle['ema_20']:.2f}",
            "telegram_message_status": "sent" if message else "not_applicable"
        })

@app.route('/trade', methods=['GET']) # Only GET method for simplicity, adjust if needed
def trade():
    token = request.args.get('token','')
    if token != TRADE_TOKEN:
        return jsonify({"error": "invalid token"}), 403
    # This endpoint is kept as a dummy.
    # In a real scenario, you would execute a market order here.
    return jsonify({"executed": True, "note": "Market order execution logic is currently disabled for safety."})

# Example telegram webhook receiver (if you want to receive messages)
@app.route('/telegram', methods=['POST'])
def telegram_webhook():
    # This route is optional and for receiving messages from Telegram.
    # For sending signals, we use the send_telegram_message function.
    return jsonify({"status": "ok", "message": "Telegram webhook received but not processed."})


if __name__=='__main__':
    # When running locally, ensure you have these environment variables set or mock them.
    # Example:
    # os.environ["COINEX_KEY"] = "YOUR_COINEX_API_KEY"
    # os.environ["COINEX_SECRET"] = "YOUR_COINEX_SECRET_KEY"
    # os.environ["TELEGRAM_BOT_TOKEN"] = "YOUR_TELEGRAM_BOT_TOKEN"
    # os.environ["TELEGRAM_CHAT_ID"] = "YOUR_TELEGRAM_CHAT_ID"
    app.run(host='0.0.0.0', port=8000)
