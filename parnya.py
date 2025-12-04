from flask import Flask, request, jsonify
import os, time, requests, hmac, hashlib
import pandas as pd

# --- 1. تنظیمات و متغیرهای محیطی ---
app = Flask(__name__)

BASE_URL = "https://api.coinex.com/v1"
API_KEY = os.getenv("9702A8DB3E074A45996BAC0E8D85F748") 
SECRET = os.getenv("4029D375ED5D17344BB175DF9FB0B36EBC497F5BA389C4C1").encode() 
TRADE_TOKEN = os.getenv("TRADE_TOKEN", "Mp0551977") 

# پارامترهای استراتژی
SYMBOL = "BTCUSDT"
TIMEFRAME = "1min" 
LIMIT = 25 
FAST_MA_PERIOD = 5  
SLOW_MA_PERIOD = 20 

# پارامترهای معاملاتی
FEE_DEDUCTION = 0.001 
# درصد موجودی قابل استفاده (مثلاً 99% برای اطمینان از پوشش کارمزد)
BALANCE_USAGE_PERCENT = 0.85 

# --- 2. توابع احراز هویت و درخواست ---

def sign(params):
    """تولید امضای HMAC-SHA256 بر اساس پارامترهای مرتب شده"""
    items = sorted(params.items())
    qs = '&'.join([f"{k}={v}" for k,v in items])
    return hmac.new(SECRET, qs.encode(), hashlib.sha256).hexdigest()

def ce_request(method, url, params=None):
    """ارسال درخواست به CoinEx API (GET یا POST)"""
    if params is None: params = {}
    params['access_id'] = API_KEY
    params['tonce'] = int(time.time()*1000)
    params['sign'] = sign(params)
    
    headers = {'Content-Type': 'application/json'}

    try:
        if method.upper() == 'GET':
            r = requests.get(BASE_URL + url, params=params, timeout=10)
        elif method.upper() == 'POST':
            # Note: CoinEx requires parameters for POST requests to be sent as JSON body
            r = requests.post(BASE_URL + url, json=params, headers=headers, timeout=10)
        else:
            raise ValueError("Unsupported HTTP method")

        r.raise_for_status() 
        return r.json()
    except requests.exceptions.RequestException as e:
        print(f"Error in ce_request ({method} {url}): {e}")
        return {"code": 10000, "message": f"Request Failed: {e}", "data": None}

# --- 3. تابع جدید: دریافت موجودی ---

def get_account_balance(currency):
    """دریافت موجودی یک ارز خاص (مثلاً 'USDT' یا 'BTC')"""
    response = ce_request("GET", "/balance/info")
    
    if response and response.get('code') == 0 and response.get('data'):
        # موجودی کل و موجودی قابل استفاده (available) را استخراج می‌کنیم
        balance_data = response['data'].get(currency, {})
        available_balance = balance_data.get('available', '0')
        return float(available_balance)
    return 0.0

# --- 4. توابع تحلیل تکنیکال (Signal Generation) ---

def get_candlestick_data():
    # ... (بدون تغییر) ...
    params = {
        'market': SYMBOL,
        'type': TIMEFRAME,
        'limit': LIMIT
    }
    response = ce_request("GET", "/market/kline", params=params)
    
    if response and response.get('code') == 0 and response.get('data'):
        columns = ['time', 'open', 'close', 'high', 'low', 'volume']
        df = pd.DataFrame(response['data'], columns=columns)
        df['close'] = pd.to_numeric(df['close'])
        return df
    return None

def calculate_ma_crossover(df):
    # ... (بدون تغییر) ...
    if df is None or len(df) < SLOW_MA_PERIOD:
        return "neutral", "Insufficient data"

    df['fast_ma'] = df['close'].rolling(window=FAST_MA_PERIOD).mean()
    df['slow_ma'] = df['close'].rolling(window=SLOW_MA_PERIOD).mean()
    
    if len(df) < 2:
        return "neutral", "Not enough data points for crossover comparison"

    fast_ma_current = df['fast_ma'].iloc[-1]
    slow_ma_current = df['slow_ma'].iloc[-1]
    
    fast_ma_previous = df['fast_ma'].iloc[-2]
    slow_ma_previous = df['slow_ma'].iloc[-2]

    if fast_ma_previous < slow_ma_previous and fast_ma_current > slow_ma_current:
        signal_type = "buy"
        reason = f"Fast MA({FAST_MA_PERIOD}) crossed above Slow MA({SLOW_MA_PERIOD}). Price: {df['close'].iloc[-1]}"
    
    elif fast_ma_previous > slow_ma_previous and fast_ma_current < slow_ma_current:
        signal_type = "sell"
        reason = f"Fast MA({FAST_MA_PERIOD}) crossed below Slow MA({SLOW_MA_PERIOD}). Price: {df['close'].iloc[-1]}"
        
    else:
        signal_type = "neutral"
        reason = "No crossover detected / Holding."
        
    return signal_type, reason

# --- 5. تابع اجرای معامله (Order Execution) - بروزرسانی شده ---

def execute_trade_order(action, price):
    """ارسال سفارش Limit با استفاده از کل موجودی موجود"""
    
    # Base currency ( ارز پایه/برای خرید) = USDT
    # Trading currency ( ارز معاملاتی/برای فروش) = BTC
    
    if action == 'buy':
        # 1. گرفتن موجودی ارز پایه (USDT)
        base_currency = SYMBOL[3:]  # مثال: USDT
        available_balance = get_account_balance(base_currency)
        
        # 2. محاسبه حجم دلاری قابل استفاده
        trade_usdt_amount = available_balance * BALANCE_USAGE_PERCENT
        
        if trade_usdt_amount < 5: # حداقل حجم سفارش در CoinEx معمولا 5 USDT است
            return {"code": 10001, "message": f"Insufficient {base_currency} balance. Need > 5 USD/USDT.", "data": None}
            
        # 3. محاسبه مقدار (Amount) قابل خرید: حجم دلاری / قیمت
        amount = trade_usdt_amount / price
        
        # 4. تنظیم قیمت Limit کمی بالاتر (برای اجرای سریع)
        limit_price = round(price * (1 + FEE_DEDUCTION), 2) 
        order_type = 'buy'

    else: # sell
        # 1. گرفتن موجودی ارز معاملاتی (BTC)
        trading_currency = SYMBOL[:3] # مثال: BTC
        available_balance = get_account_balance(trading_currency)
        
        # 2. محاسبه مقدار (Amount) قابل فروش
        amount = available_balance * BALANCE_USAGE_PERCENT
        
        if amount * price < 5: # بررسی حداقل معادل دلاری (مثلاً 5 USDT)
             return {"code": 10001, "message": f"Insufficient {trading_currency} balance. Need > 5 USDT equivalent.", "data": None}
            
        # 3. تنظیم قیمت Limit کمی پایین‌تر (برای اجرای سریع)
        limit_price = round(price * (1 - FEE_DEDUCTION), 2)
        order_type = 'sell'
        
    # گرد کردن مقدار و قیمت برای دقت صرافی
    amount = round(amount, 6) 
        
    # پارامترهای سفارش CoinEx
    params = {
        'market': SYMBOL,
        'type': order_type,
        'amount': str(amount),
        'price': str(limit_price),
        'source_id': 'MyTradingBot'
    }
    
    print(f"Submitting {order_type.upper()} order: {amount} {SYMBOL[:3]} at {limit_price} (using full balance)")
    
    # ارسال درخواست POST برای ثبت سفارش
    response = ce_request("POST", "/order/put_limit", params=params)
    
    return response

# --- 6. نقاط دسترسی Flask (API Endpoints) ---

@app.route('/')
def home():
    return f'🚀 ربات معاملاتی CoinEx برای {SYMBOL} فعال است و از کل موجودی حساب استفاده می‌کند.'

# ... (سایر توابع status و signal بدون تغییر) ...

@app.route('/status')
def status():
    return jsonify({
        "running": True, 
        "symbol": SYMBOL,
        "strategy": "MAC Crossover",
        "fast_period": FAST_MA_PERIOD,
        "slow_period": SLOW_MA_PERIOD,
        "balance_usage": f"{BALANCE_USAGE_PERCENT*100}% of available balance"
    })

@app.route('/signal')
def signal():
    """دریافت سیگنال معاملاتی"""
    df = get_candlestick_data()
    signal_type, reason = calculate_ma_crossover(df)
    
    if df is None:
        current_price = "N/A"
    else:
        current_price = df['close'].iloc[-1]
        
    return jsonify({
        "signal": signal_type, 
        "timestamp": time.time(),
        "reason": reason,
        "current_price": current_price
    })


@app.route('/trade')
def trade():
    """اجرای فرمان معامله (Buy/Sell)"""
    token = request.args.get('token', '')
    action = request.args.get('action', '').lower() # buy or sell
    
    if token != TRADE_TOKEN:
        return jsonify({"error": "Invalid trade token"}), 403
    
    if action not in ['buy', 'sell']:
        return jsonify({"error": "Action parameter (buy/sell) required"}), 400

    df = get_candlestick_data()
    if df is None:
        return jsonify({"error": "Could not fetch current market data for trade execution"}), 500
        
    current_price = df['close'].iloc[-1]
    
    # اجرای سفارش با موجودی کل
    trade_response = execute_trade_order(action, current_price)

    if trade_response.get('code') == 0:
        return jsonify({
            "executed": True,
            "action": action,
            "price_used": current_price,
            "order_details": trade_response['data'],
            "message": "Order placed successfully using full available balance"
        })
    else:
        return jsonify({
            "executed": False,
            "action": action,
            "error": trade_response.get('message', 'Unknown API Error'),
            "api_code": trade_response.get('code'),
        }), 500

if __name__=='__main__':
    port = int(os.environ.get("PORT", 8000))
    app.run(host='0.0.0.0', port=port)
