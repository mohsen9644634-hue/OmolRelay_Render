import requests
import json
import time
import hmac
import hashlib
import pandas as pd
import numpy as np
import threading
from flask import Flask, jsonify

# ====================================================================
# 1. تنظیمات و متغیرهای حیاتی
# ====================================================================

# 🚨🚨🚨 این مقادیر را با کلیدهای واقعی خود جایگزین کنید 🚨🚨🚨
API_KEY = "9702A8DB3E074A45996BAC0E8D85F748"
SECRET_KEY = "4029D375ED5D17344BB175DF9FB0B36EBC497F5BA389C4C1"

# Base URL برای CoinEx V2
BASE_URL = "https://api.coinex.com/v2" 
# پارامترهای ترید
SYMBOL = "BTCUSDT"
TIMEFRAME = "15min" # تایم‌فریم تحلیل
LEVERAGE = 10 
TRADE_INTERVAL_SECONDS = 30 # هر 30 ثانیه یک بار اجرا شود
# پارامترهای اندیکاتور
EMA_SHORT_PERIOD = 12
EMA_LONG_PERIOD = 26
RSI_PERIOD = 14
RSI_OVERBOUGHT = 70  # بالای 70 برای LONG ریسک دارد
RSI_OVERSOLD = 30    # زیر 30 برای SHORT ریسک دارد
ST_PERIOD = 10
ST_MULTIPLIER = 3

# ====================================================================
# 2. مدیریت API CoinEx V2 (شامل ساخت Signature)
# ====================================================================

def generate_signature(method, path, params, body, timestamp, secret_key):
    """
    ساخت HMAC-SHA256 Signature برای CoinEx V2
    (قانون: timestamp + method + path + body_content)
    """
    body_content = json.dumps(body) if body else ""
    message = f"{timestamp}{method}{path}{body_content}"
    
    hashed = hmac.new(secret_key.encode('utf-8'), 
                       message.encode('utf-8'), 
                       hashlib.sha256)
    return hashed.hexdigest()

def make_request(method, path, params=None, body=None):
    """تابع اصلی برای ارسال درخواست‌های احراز هویت شده"""
    url = f"{BASE_URL}{path}"
    timestamp = str(int(time.time() * 1000))
    
    if API_KEY == "YOUR_API_KEY_HERE" or SECRET_KEY == "YOUR_SECRET_KEY_HERE":
        print("❌ CRITICAL: API Key or Secret Key not set.")
        return None
        
    signature = generate_signature(method, path, params, body, timestamp, SECRET_KEY)
    
    headers = {
        'Content-Type': 'application/json',
        'X-COINEX-KEY': API_KEY,
        'X-COINEX-SIGNATURE': signature,
        'X-COINEX-TIMESTAMP': timestamp,
        'X-COINEX-API-VERSION': 'v2',
    }
    
    try:
        response = requests.request(method, url, params=params, json=body, headers=headers, timeout=10)
        response.raise_for_status() 
        result = response.json()
        
        if result.get('code') != 0:
            print(f"❌ API Call Failed ({path}): Code {result.get('code')}, Message: {result.get('message')}")
            return None
        
        return result
        
    except requests.exceptions.RequestException as e:
        print(f"❌ CoinEx Network Error ({method} {path}): {e}")
        return None

# ====================================================================
# 3. توابع محاسبات اندیکاتور
# ====================================================================

def calculate_indicators(df):
    """محاسبه EMA، RSI و Supertrend"""
    
    # 1. EMA (میانگین متحرک نمایی)
    df['EMA_Short'] = df['close'].ewm(span=EMA_SHORT_PERIOD, adjust=False).mean()
    df['EMA_Long'] = df['close'].ewm(span=EMA_LONG_PERIOD, adjust=False).mean()

    # 2. RSI (شاخص قدرت نسبی)
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).fillna(0)
    loss = (-delta.where(delta < 0, 0)).fillna(0)
    
    # محاسبات EWM برای RSI دقیق
    avg_gain = gain.ewm(com=RSI_PERIOD - 1, min_periods=RSI_PERIOD, adjust=False).mean()
    avg_loss = loss.ewm(com=RSI_PERIOD - 1, min_periods=RSI_PERIOD, adjust=False).mean()
    
    rs = avg_gain / avg_loss
    df['RSI'] = 100 - (100 / (1 + rs))

    # 3. Supertrend (نیازمند ATR)
    # True Range (TR)
    df['TR'] = np.maximum.reduce([
        df['high'] - df['low'], 
        np.abs(df['high'] - df['close'].shift(1)), 
        np.abs(df['low'] - df['close'].shift(1))
    ])
    # Average True Range (ATR)
    df['ATR'] = df['TR'].ewm(span=ST_PERIOD, adjust=False).mean()

    # خطوط بیسیک Supertrend
    df['Basic_Upper'] = (df['high'] + df['low']) / 2 + ST_MULTIPLIER * df['ATR']
    df['Basic_Lower'] = (df['high'] + df['low']) / 2 - ST_MULTIPLIER * df['ATR']

    # منطق اصلی Supertrend (با رویکرد تکراری برای دقت)
    df['Supertrend'] = np.nan
    df['ST_Direction'] = np.nan # 1: Long, -1: Short

    for i in range(1, len(df)):
        # پیگیری جهت قبلی
        prev_st_direction = df['ST_Direction'].iloc[i-1]
        prev_supertrend = df['Supertrend'].iloc[i-1]
        
        # تعیین مقدار Supertrend فعلی
        if df['close'].iloc[i] > prev_supertrend and prev_st_direction == 1:
            # روند صعودی ادامه دارد، خط از Basic_Lower پیروی می‌کند
            df.loc[df.index[i], 'Supertrend'] = max(df['Basic_Lower'].iloc[i], prev_supertrend)
            df.loc[df.index[i], 'ST_Direction'] = 1
        elif df['close'].iloc[i] < prev_supertrend and prev_st_direction == -1:
            # روند نزولی ادامه دارد، خط از Basic_Upper پیروی می‌کند
            df.loc[df.index[i], 'Supertrend'] = min(df['Basic_Upper'].iloc[i], prev_supertrend)
            df.loc[df.index[i], 'ST_Direction'] = -1
        elif df['close'].iloc[i] > prev_supertrend and prev_st_direction == -1:
            # سیگنال برگشت به LONG
            df.loc[df.index[i], 'Supertrend'] = df['Basic_Lower'].iloc[i]
            df.loc[df.index[i], 'ST_Direction'] = 1
        elif df['close'].iloc[i] < prev_supertrend and prev_st_direction == 1:
            # سیگنال برگشت به SHORT
            df.loc[df.index[i], 'Supertrend'] = df['Basic_Upper'].iloc[i]
            df.loc[df.index[i], 'ST_Direction'] = -1
        else:
             # اگر جهت قبلی نامشخص باشد یا در محدوده خنثی
             if np.isnan(prev_st_direction):
                 df.loc[df.index[i], 'Supertrend'] = df['Basic_Lower'].iloc[i] # شروع با صعودی
                 df.loc[df.index[i], 'ST_Direction'] = 1
             else:
                 # اگر نه صعودی و نه نزولی باشد (در محدوده Supertrend قبلی)
                 df.loc[df.index[i], 'Supertrend'] = prev_supertrend
                 df.loc[df.index[i], 'ST_Direction'] = prev_st_direction

    # برای ورودی جدید (ناقص بودن داده‌های اولیه)
    df.iloc[0:ST_PERIOD, df.columns.get_loc('ST_Direction')] = 1 
    
    return df.iloc[ST_PERIOD:] # داده‌های معتبر بعد از دوره ATR

# ====================================================================
# 4. منطق سیگنال‌گیری نهایی
import requests
import json
import time
import hmac
import hashlib
import pandas as pd
import numpy as np
import threading
from flask import Flask, jsonify

# ====================================================================
# 1. تنظیمات و متغیرهای حیاتی
# ====================================================================

# 🚨🚨🚨 این مقادیر را با کلیدهای واقعی خود جایگزین کنید 🚨🚨🚨
API_KEY = "YOUR_API_KEY_HERE"
SECRET_KEY = "YOUR_SECRET_KEY_HERE"

# Base URL برای CoinEx V2
BASE_URL = "https://api.coinex.com/v2" 
# پارامترهای ترید
SYMBOL = "BTCUSDT"
TIMEFRAME = "15min" # تایم‌فریم تحلیل
LEVERAGE = 10 
TRADE_INTERVAL_SECONDS = 30 # هر 30 ثانیه یک بار اجرا شود
# پارامترهای اندیکاتور
EMA_SHORT_PERIOD = 12
EMA_LONG_PERIOD = 26
RSI_PERIOD = 14
RSI_OVERBOUGHT = 70  # بالای 70 برای LONG ریسک دارد
RSI_OVERSOLD = 30    # زیر 30 برای SHORT ریسک دارد
ST_PERIOD = 10
ST_MULTIPLIER = 3

# ====================================================================
# 2. مدیریت API CoinEx V2 (شامل ساخت Signature)
# ====================================================================

def generate_signature(method, path, params, body, timestamp, secret_key):
    """
    ساخت HMAC-SHA256 Signature برای CoinEx V2
    (قانون: timestamp + method + path + body_content)
    """
    body_content = json.dumps(body) if body else ""
    message = f"{timestamp}{method}{path}{body_content}"
    
    hashed = hmac.new(secret_key.encode('utf-8'), 
                       message.encode('utf-8'), 
                       hashlib.sha256)
    return hashed.hexdigest()

def make_request(method, path, params=None, body=None):
    """تابع اصلی برای ارسال درخواست‌های احراز هویت شده"""
    url = f"{BASE_URL}{path}"
    timestamp = str(int(time.time() * 1000))
    
    if API_KEY == "YOUR_API_KEY_HERE" or SECRET_KEY == "YOUR_SECRET_KEY_HERE":
        print("❌ CRITICAL: API Key or Secret Key not set.")
        return None
        
    signature = generate_signature(method, path, params, body, timestamp, SECRET_KEY)
    
    headers = {
        'Content-Type': 'application/json',
        'X-COINEX-KEY': API_KEY,
        'X-COINEX-SIGNATURE': signature,
        'X-COINEX-TIMESTAMP': timestamp,
        'X-COINEX-API-VERSION': 'v2',
    }
    
    try:
        response = requests.request(method, url, params=params, json=body, headers=headers, timeout=10)
        response.raise_for_status() 
        result = response.json()
        
        if result.get('code') != 0:
            print(f"❌ API Call Failed ({path}): Code {result.get('code')}, Message: {result.get('message')}")
            return None
        
        return result
        
    except requests.exceptions.RequestException as e:
        print(f"❌ CoinEx Network Error ({method} {path}): {e}")
        return None

# ====================================================================
# 3. توابع محاسبات اندیکاتور
# ====================================================================

def calculate_indicators(df):
    """محاسبه EMA، RSI و Supertrend"""
    
    # 1. EMA (میانگین متحرک نمایی)
    df['EMA_Short'] = df['close'].ewm(span=EMA_SHORT_PERIOD, adjust=False).mean()
    df['EMA_Long'] = df['close'].ewm(span=EMA_LONG_PERIOD, adjust=False).mean()

    # 2. RSI (شاخص قدرت نسبی)
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).fillna(0)
    loss = (-delta.where(delta < 0, 0)).fillna(0)
    
    # محاسبات EWM برای RSI دقیق
    avg_gain = gain.ewm(com=RSI_PERIOD - 1, min_periods=RSI_PERIOD, adjust=False).mean()
    avg_loss = loss.ewm(com=RSI_PERIOD - 1, min_periods=RSI_PERIOD, adjust=False).mean()
    
    rs = avg_gain / avg_loss
    df['RSI'] = 100 - (100 / (1 + rs))

    # 3. Supertrend (نیازمند ATR)
    # True Range (TR)
    df['TR'] = np.maximum.reduce([
        df['high'] - df['low'], 
        np.abs(df['high'] - df['close'].shift(1)), 
        np.abs(df['low'] - df['close'].shift(1))
    ])
    # Average True Range (ATR)
    df['ATR'] = df['TR'].ewm(span=ST_PERIOD, adjust=False).mean()

    # خطوط بیسیک Supertrend
    df['Basic_Upper'] = (df['high'] + df['low']) / 2 + ST_MULTIPLIER * df['ATR']
    df['Basic_Lower'] = (df['high'] + df['low']) / 2 - ST_MULTIPLIER * df['ATR']

    # منطق اصلی Supertrend (با رویکرد تکراری برای دقت)
    df['Supertrend'] = np.nan
    df['ST_Direction'] = np.nan # 1: Long, -1: Short

    for i in range(1, len(df)):
        # پیگیری جهت قبلی
        prev_st_direction = df['ST_Direction'].iloc[i-1]
        prev_supertrend = df['Supertrend'].iloc[i-1]
        
        # تعیین مقدار Supertrend فعلی
        if df['close'].iloc[i] > prev_supertrend and prev_st_direction == 1:
            # روند صعودی ادامه دارد، خط از Basic_Lower پیروی می‌کند
            df.loc[df.index[i], 'Supertrend'] = max(df['Basic_Lower'].iloc[i], prev_supertrend)
            df.loc[df.index[i], 'ST_Direction'] = 1
        elif df['close'].iloc[i] < prev_supertrend and prev_st_direction == -1:
            # روند نزولی ادامه دارد، خط از Basic_Upper پیروی می‌کند
            df.loc[df.index[i], 'Supertrend'] = min(df['Basic_Upper'].iloc[i], prev_supertrend)
            df.loc[df.index[i], 'ST_Direction'] = -1
        elif df['close'].iloc[i] > prev_supertrend and prev_st_direction == -1:
            # سیگنال برگشت به LONG
            df.loc[df.index[i], 'Supertrend'] = df['Basic_Lower'].iloc[i]
            df.loc[df.index[i], 'ST_Direction'] = 1
        elif df['close'].iloc[i] < prev_supertrend and prev_st_direction == 1:
            # سیگنال برگشت به SHORT
            df.loc[df.index[i], 'Supertrend'] = df['Basic_Upper'].iloc[i]
            df.loc[df.index[i], 'ST_Direction'] = -1
        else:
             # اگر جهت قبلی نامشخص باشد یا در محدوده خنثی
             if np.isnan(prev_st_direction):
                 df.loc[df.index[i], 'Supertrend'] = df['Basic_Lower'].iloc[i] # شروع با صعودی
                 df.loc[df.index[i], 'ST_Direction'] = 1
             else:
                 # اگر نه صعودی و نه نزولی باشد (در محدوده Supertrend قبلی)
                 df.loc[df.index[i], 'Supertrend'] = prev_supertrend
                 df.loc[df.index[i], 'ST_Direction'] = prev_st_direction

    # برای ورودی جدید (ناقص بودن داده‌های اولیه)
    df.iloc[0:ST_PERIOD, df.columns.get_loc('ST_Direction')] = 1 
    
    return df.iloc[ST_PERIOD:] # داده‌های معتبر بعد از دوره ATR

# ====================================================================
# 4. منطق سیگنال‌گیری نهایی
# ====================================================================

def get_final_signal(df):
    """ترکیب سیگنال‌های EMA Cross، Supertrend و فیلتر RSI"""
    latest = df.iloc[-1]
    
    # 1. سیگنال EMA
    ema_signal = 0
    if latest['EMA_Short'] > latest['EMA_Long']:
        ema_signal = 1 # Long
    elif latest['EMA_Short'] < latest['EMA_Long']:
        ema_signal = -1 # Short
        
    # 2. سیگنال Supertrend
    st_signal = latest['ST_Direction']
    
    # 3. ترکیب و فیلتر RSI
    
    final_signal = "HOLD"
    
    if ema_signal == 1 and st_signal == 1:
        # کاندید LONG: اگر RSI بیش از حد بالا نباشد (Overbought)
        if latest['RSI'] <= RSI_OVERBOUGHT:
            final_signal = "LONG"
        else:
            # فیلتر RSI فعال شد
            final_signal = "HOLD" 
            
    elif ema_signal == -1 and st_signal == -1:
        # کاندید SHORT: اگر RSI بیش از حد پایین نباشد (Oversold)
        if latest['RSI'] >= RSI_OVERSOLD:
            final_signal = "SHORT"
        else:
            # فیلتر RSI فعال شد
            final_signal = "HOLD"
            
    # اگر سیگنال‌های اصلی ضد و نقیض باشند، HOLD می‌کنیم
    
    return final_signal

# ====================================================================
# 5. توابع اجرایی ترید
# ====================================================================

def get_coinex_data():
    """دریافت داده‌های کندل (K-Line) از CoinEx"""
    path = f"/market/kline"
    params = {
        'market': SYMBOL,
        'time_type': TIMEFRAME,
        'limit': 100 
    }
    
    result = make_request('GET', path, params=params)
    
    if result and result.get('code') == 0:
        data = result['data']['kline']
        df = pd.DataFrame(data, columns=['ts', 'open', 'close', 'high', 'low', 'amount', 'volume'])
        # اطمینان از نوع داده عددی
        for col in ['open', 'close', 'high', 'low', 'amount', 'volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
            
        df['datetime'] = pd.to_datetime(df['ts'], unit='ms')
        df = df.set_index('datetime')
        return df
    return None

def get_current_balance(ccy="USDT"):
    """دریافت موجودی قابل استفاده (Available) در حساب Perpetual"""
    path = "/asset/margin/balance"
    # برای معاملات Perpetual (فیوچرز) باید موجودی حساب Perpetual را چک کنیم.
    # در CoinEx V2، این endpoint موجودی‌ها را برمی‌گرداند.
    
    result = make_request('GET', path, params={'ccy': ccy})
    
    if result and result.get('code') == 0:
        for asset in result['data']:
            if asset['ccy'] == ccy:
                # استفاده از 'available'
                return float(asset['available'])
    return 0.0

def get_open_positions():
    """دریافت لیست پوزیشن‌های باز برای بازار مشخص"""
    path = "/perpetual/position"
    params = {'market': SYMBOL}
    result = make_request('GET', path, params=params)
    
    if result and result.get('code') == 0:
        # فیلتر کردن پوزیشن‌هایی که اندازه آن‌ها واقعاً > 0 است
        positions = [p for p in result['data'] if float(p['position_size']) > 0]
        return positions
    return []

def calculate_amount(balance_usdt, current_price):
    """محاسبه حجم پوزیشن در واحد BTC بر اساس موجودی کل و لوریج"""
    
    if current_price <= 0:
        return 0.0
        
    # محاسبه کل ارزش دلاری که وارد معامله می‌شود
    total_usdt_value = balance_usdt * LEVERAGE
    # تبدیل به حجم BTC
    amount_btc = total_usdt_value / current_price
    
    # CoinEx برای BTCUSDT حداقل اندازه 0.0001 دارد.
    min_btc_amount = 0.0001
    
    if amount_btc < min_btc_amount:
        print(f"⚠️ موجودی کافی برای حداقل حجم معامله {min_btc_amount} BTC وجود ندارد. (Calculated: {amount_btc:.4f})")
        return 0.0
        
    # بازگرداندن با دقت بالا
    return float(f"{amount_btc:.4f}") 

def close_all_positions(positions):
    """بستن تمام پوزیشن‌های باز برای SYMBOL مشخص"""
    
    # اطمینان از تنظیم لوریج و Isolated قبل از ترید (برای بار اول)
    set_leverage(LEVERAGE, position_type=1) 
    
    closed_count = 0
    for pos in positions:
        if float(pos['position_size']) > 0:
            path = "/perpetual/close_position"
            body = {
                'market': SYMBOL,
                'position_id': pos['position_id'], 
                'close_type': 'MARKET' # بستن فوری در قیمت بازار
            }
            
            close_result = make_request('POST', path, body=body)
            if close_result:
                print(f"✅ پوزیشن {pos['side']} با شناسه {pos['position_id']} بسته شد.")
                closed_count += 1
            else:
                print(f"❌ خطای بستن پوزیشن {pos['position_id']}.")
                # بهتر است ادامه دهیم تا بقیه هم بسته شوند
                
    return closed_count == len(positions)

def set_leverage(leverage, position_type=1):
    """تنظیم لوریج و نوع پوزیشن (1: Isolated)"""
    path_leverage = "/perpetual/position/adjust_leverage"
    leverage_body = {
        'market': SYMBOL,
        'leverage': leverage,
        'position_type': position_type 
    }
    leverage_result = make_request('POST', path_leverage, body=leverage_body)
    
    if leverage_result and leverage_result.get('code') == 0:
        return True
    return False

def open_new_position(side, amount_btc):
    """باز کردن پوزیشن جدید (BUY برای LONG، SELL برای SHORT)"""
    
    # 1. مطمئن شدن از تنظیم لوریج (10x Isolated)
    set_leverage(LEVERAGE, position_type=1) 
    
    # 2. ارسال دستور مارکت
    path_order = "/perpetual/submit_order"
    body = {
        'market': SYMBOL,
        'side': side, 
        'type': 'MARKET',
        'amount': str(amount_btc) # مقدار در واحد BTC
    }
    
    open_result = make_request('POST', path_order, body=body)
    
    if open_result:
        print(f"🚀 موفق: پوزیشن {side} با حجم {amount_btc} BTC باز شد.")
        return True
    else:
        print(f"❌ شکست: نتوانست پوزیشن {side} را باز کند.")
        return False

# ====================================================================
# 6. حلقه اصلی ربات
# ====================================================================

def run_trading_bot():
    """تابع اصلی منطق ربات که هر 30 ثانیه اجرا می‌شود."""
    
    print(f"\n--- ParnyaBot V3.0 (CoinEx Perpetual) - Run Start: {time.ctime()} ---")
    
    # 1. دریافت و تحلیل داده‌ها
    df = get_coinex_data()
    if df is None or len(df) < 50:
        print("🛑 داده‌های کافی برای تحلیل (K-Line) در دسترس نیست.")
        return "ERROR: DATA"
        
    df = calculate_indicators(df)
    
    # 2. بررسی سیگنال
    signal = get_final_signal(df)
    current_price = df['close'].iloc[-1]
    
    print(f"📈 قیمت لحظه‌ای: {current_price:.2f} USDT")
    print(f"📊 وضعیت RSI: {df['RSI'].iloc[-1]:.2f}, ST Direction: {df['ST_Direction'].iloc[-1]}")
    print(f"🔥 سیگنال نهایی: {signal}")
    
    # 3. مدیریت پوزیشن‌های فعلی
    positions = get_open_positions()
    has_long = any(p['side'] == 'LONG' for p in positions)
    has_short = any(p['side'] == 'SHORT' for p in positions)
    
    # 4. اجرای ترید
    
    if signal == "LONG":
        if has_long:
            print("➡️ سیگنال LONG است، پوزیشن LONG باز است. نگهداری.")
        elif has_short:
            print("🔄 سیگنال LONG است، ابتدا پوزیشن SHORT موجود بسته می‌شود.")
            if close_all_positions(positions):
                balance = get_current_balance("USDT")
                amount_btc = calculate_amount(balance, current_price)
                if amount_btc > 0:
                    open_new_position('BUY', amount_btc)
        else:
            print("🚀 سیگنال LONG است، پوزیشن جدید باز می‌شود.")
            balance = get_current_balance("USDT")
            amount_btc = calculate_amount(balance, current_price)
            if amount_btc > 0:
                open_new_position('BUY', amount_btc)
                
    elif signal == "SHORT":
        if has_short:
            print("➡️ سیگنال SHORT است، پوزیشن SHORT باز است. نگهداری.")
        elif has_long:
            print("🔄 سیگنال SHORT است، ابتدا پوزیشن LONG موجود بسته می‌شود.")
            if close_all_positions(positions):
                balance = get_current_balance("USDT")
                amount_btc = calculate_amount(balance, current_price)
                if amount_btc > 0:
                    open_new_position('SELL', amount_btc)
        else:
            print("🚀 سیگنال SHORT است، پوزیشن جدید باز می‌شود.")
            balance = get_current_balance("USDT")
            amount_btc = calculate_amount(balance, current_price)
            if amount_btc > 0:
                open_new_position('SELL', amount_btc)
                
    elif signal == "HOLD":
        print("⏸️ سیگنال HOLD است. هیچ اقدامی انجام نمی‌شود.")
        
    return "SUCCESS"
    
# ====================================================================
# 7. پیکربندی Flask (برای اجرای در Render)
# ====================================================================

app = Flask(__name__)
# فلگ کنترل برای حلقهٔ ترید
bot_running = False

def bot_loop():
    """حلقه‌ای که وظیفهٔ اجرای متناوب ربات را بر عهده دارد."""
    global bot_running
    
    # چک اولیه امنیتی
    if API_KEY == "YOUR_API_KEY_HERE" or SECRET_KEY == "YOUR_SECRET_KEY_HERE":
        print("CRITICAL: API_KEY/SECRET_KEY placeholder detected. Bot loop cannot run.")
        bot_running = False
        return

    while bot_running:
        try:
            run_trading_bot()
        except Exception as e:
            print(f"CRITICAL ERROR in main bot loop: {e}")
            
        # صبر برای اجرای بعدی
        time.sleep(TRADE_INTERVAL_SECONDS)
        
    print("Bot loop stopped successfully.")

@app.route('/')
def home():
    """روت اصلی برای چک کردن وضعیت سرویس"""
    global bot_running
    status = "RUNNING" if bot_running else "STOPPED"
    return jsonify({
        "status": status,
        "message": f"Parnya Trading Bot status: {status}. Access /start_bot to begin trading.",
        "config": f"Market: {SYMBOL} @ {TIMEFRAME}, Leverage: {LEVERAGE}x, Interval: {TRADE_INTERVAL_SECONDS}s"
    })

@app.route('/start_bot')
def start_bot_route():
    """روت برای شروع حلقه ترید در پس‌زمینه"""
    global bot_running
    if not bot_running:
        bot_running = True
        # اجرای حلقه ربات در یک Thread جداگانه
        thread = threading.Thread(target=bot_loop)
        thread.daemon = True 
        thread.start()
        print("Bot started successfully in background thread.")
        return jsonify({"status": "started", "message": "Parnya Bot has started its trading loop."})
    else:
        return jsonify({"status": "already_running", "message": "Parnya Bot is already running."})

@app.route('/stop_bot')
def stop_bot_route():
    """روت برای توقف حلقه ترید"""
    global bot_running
    if bot_running:
        bot_running = False
        print("Bot requested to stop.")
        return jsonify({"status": "stopping", "message": "Parnya Bot will stop after the current 30s cycle finishes."})
    else:
        return jsonify({"status": "already_stopped", "message": "Parnya Bot is already stopped."})
# ====================================================================

def get_final_signal(df):
    """ترکیب سیگنال‌های EMA Cross، Supertrend و فیلتر RSI"""
    latest = df.iloc[-1]
    
    # 1. سیگنال EMA
    ema_signal = 0
    if latest['EMA_Short'] > latest['EMA_Long']:
        ema_signal = 1 # Long
    elif latest['EMA_Short'] < latest['EMA_Long']:
        ema_signal = -1 # Short
        
    # 2. سیگنال Supertrend
    st_signal = latest['ST_Direction']
    
    # 3. ترکیب و فیلتر RSI
    
    final_signal = "HOLD"
    
    if ema_signal == 1 and st_signal == 1:
        # کاندید LONG: اگر RSI بیش از حد بالا نباشد (Overbought)
        if latest['RSI'] <= RSI_OVERBOUGHT:
            final_signal = "LONG"
        else:
            # فیلتر RSI فعال شد
            final_signal = "HOLD" 
            
    elif ema_signal == -1 and st_signal == -1:
        # کاندید SHORT: اگر RSI بیش از حد پایین نباشد (Oversold)
        if latest['RSI'] >= RSI_OVERSOLD:
            final_signal = "SHORT"
        else:
            # فیلتر RSI فعال شد
            final_signal = "HOLD"
            
    # اگر سیگنال‌های اصلی ضد و نقیض باشند، HOLD می‌کنیم
    
    return final_signal

# ====================================================================
# 5. توابع اجرایی ترید
# ====================================================================

def get_coinex_data():
    """دریافت داده‌های کندل (K-Line) از CoinEx"""
    path = f"/market/kline"
    params = {
        'market': SYMBOL,
        'time_type': TIMEFRAME,
        'limit': 100 
    }
    
    result = make_request('GET', path, params=params)
    
    if result and result.get('code') == 0:
        data = result['data']['kline']
        df = pd.DataFrame(data, columns=['ts', 'open', 'close', 'high', 'low', 'amount', 'volume'])
        # اطمینان از نوع داده عددی
        for col in ['open', 'close', 'high', 'low', 'amount', 'volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
            
        df['datetime'] = pd.to_datetime(df['ts'], unit='ms')
        df = df.set_index('datetime')
        return df
    return None

def get_current_balance(ccy="USDT"):
    """دریافت موجودی قابل استفاده (Available) در حساب Perpetual"""
    path = "/asset/margin/balance"
    # برای معاملات Perpetual (فیوچرز) باید موجودی حساب Perpetual را چک کنیم.
    # در CoinEx V2، این endpoint موجودی‌ها را برمی‌گرداند.
    
    result = make_request('GET', path, params={'ccy': ccy})
    
    if result and result.get('code') == 0:
        for asset in result['data']:
            if asset['ccy'] == ccy:
                # استفاده از 'available'
                return float(asset['available'])
    return 0.0

def get_open_positions():
    """دریافت لیست پوزیشن‌های باز برای بازار مشخص"""
    path = "/perpetual/position"
    params = {'market': SYMBOL}
    result = make_request('GET', path, params=params)
    
    if result and result.get('code') == 0:
        # فیلتر کردن پوزیشن‌هایی که اندازه آن‌ها واقعاً > 0 است
        positions = [p for p in result['data'] if float(p['position_size']) > 0]
        return positions
    return []

def calculate_amount(balance_usdt, current_price):
    """محاسبه حجم پوزیشن در واحد BTC بر اساس موجودی کل و لوریج"""
    
    if current_price <= 0:
        return 0.0
        
    # محاسبه کل ارزش دلاری که وارد معامله می‌شود
    total_usdt_value = balance_usdt * LEVERAGE
    # تبدیل به حجم BTC
    amount_btc = total_usdt_value / current_price
    
CoinEx برای BTCUSDT حداقل اندازه 0.0001 دارد.
    min_btc_amount = 0.0001
    
    if amount_btc < min_btc_amount:
        print(f"⚠️ موجودی کافی برای حداقل حجم معامله {min_btc_amount} BTC وجود ندارد. (Calculated: {amount_btc:.4f})")
        return 0.0
        
    # بازگرداندن با دقت بالا
    return float(f"{amount_btc:.4f}") 

def close_all_positions(positions):
    """بستن تمام پوزیشن‌های باز برای SYMBOL مشخص"""
    
    # اطمینان از تنظیم لوریج و Isolated قبل از ترید (برای بار اول)
    set_leverage(LEVERAGE, position_type=1) 
    
    closed_count = 0
    for pos in positions:
        if float(pos['position_size']) > 0:
            path = "/perpetual/close_position"
            body = {
                'market': SYMBOL,
                'position_id': pos['position_id'], 
                'close_type': 'MARKET' # بستن فوری در قیمت بازار
            }
            
            close_result = make_request('POST', path, body=body)
            if close_result:
                print(f"✅ پوزیشن {pos['side']} با شناسه {pos['position_id']} بسته شد.")
                closed_count += 1
            else:
                print(f"❌ خطای بستن پوزیشن {pos['position_id']}.")
                # بهتر است ادامه دهیم تا بقیه هم بسته شوند
                
    return closed_count == len(positions)

def set_leverage(leverage, position_type=1):
    """تنظیم لوریج و نوع پوزیشن (1: Isolated)"""
    path_leverage = "/perpetual/position/adjust_leverage"
    leverage_body = {
        'market': SYMBOL,
        'leverage': leverage,
        'position_type': position_type 
    }
    leverage_result = make_request('POST', path_leverage, body=leverage_body)
    
    if leverage_result and leverage_result.get('code') == 0:
        return True
    return False

def open_new_position(side, amount_btc):
    """باز کردن پوزیشن جدید (BUY برای LONG، SELL برای SHORT)"""
    
    # 1. مطمئن شدن از تنظیم لوریج (10x Isolated)
    set_leverage(LEVERAGE, position_type=1) 
    
    # 2. ارسال دستور مارکت
    path_order = "/perpetual/submit_order"
    body = {
        'market': SYMBOL,
        'side': side, 
        'type': 'MARKET',
        'amount': str(amount_btc) # مقدار در واحد BTC
    }
    
    open_result = make_request('POST', path_order, body=body)
    
    if open_result:
        print(f"🚀 موفق: پوزیشن {side} با حجم {amount_btc} BTC باز شد.")
        return True
    else:
        print(f"❌ شکست: نتوانست پوزیشن {side} را باز کند.")
        return False

# ====================================================================
# 6. حلقه اصلی ربات
# ====================================================================

def run_trading_bot():
    """تابع اصلی منطق ربات که هر 30 ثانیه اجرا می‌شود."""
    
    print(f"\n--- ParnyaBot V3.0 (CoinEx Perpetual) - Run Start: {time.ctime()} ---")
    
    # 1. دریافت و تحلیل داده‌ها
    df = get_coinex_data()
    if df is None or len(df) < 50:
        print("🛑 داده‌های کافی برای تحلیل (K-Line) در دسترس نیست.")
        return "ERROR: DATA"
        
    df = calculate_indicators(df)
    
    # 2. بررسی سیگنال
    signal = get_final_signal(df)
    current_price = df['close'].iloc[-1]
    
    print(f"📈 قیمت لحظه‌ای: {current_price:.2f} USDT")
    print(f"📊 وضعیت RSI: {df['RSI'].iloc[-1]:.2f}, ST Direction: {df['ST_Direction'].iloc[-1]}")
    print(f"🔥 سیگنال نهایی: {signal}")
    
    # 3. مدیریت پوزیشن‌های فعلی
    positions = get_open_positions()
    has_long = any(p['side'] == 'LONG' for p in positions)
    has_short = any(p['side'] == 'SHORT' for p in positions)
    
    # 4. اجرای ترید
