import os
import time
import hmac
import hashlib
import requests
import json
from flask import Flask, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
import logging

# تنظیمات لاگ‌گذاری
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)

# --- پیکربندی API صرافی LBank (کلیدها را از Environment Variables در Render.com تنظیم کنید) ---
LBANK_API_KEY = os.environ.get('LBANK_API_KEY')
LBANK_SECRET_KEY = os.environ.get('LBANK_SECRET_KEY')
# آدرس API فیوچرز LBank - این آدرس را از مستندات رسمی LBank تایید کنید.
LBANK_FUTURES_BASE_URL = "https://api.lbank.com/v2" 

if not LBANK_API_KEY or not LBANK_SECRET_KEY:
    logging.error("خطا: LBANK_API_KEY یا LBANK_SECRET_KEY تنظیم نشده است. ربات نمی‌تواند معامله کند.")

# --- توابع کمکی برای ارتباط با API LBank ---
def generate_signature(params: dict) -> str:
    """امضای HMAC SHA256 را برای درخواست‌های API LBank تولید می‌کند."""
    if not LBANK_SECRET_KEY:
        raise ValueError("LBANK_SECRET_KEY تنظیم نشده است.")

    # پارامترها را بر اساس کلید مرتب‌سازی کنید و رشته کوئری بسازید
    query_string = '&'.join([f"{k}={v}" for k, v in sorted(params.items())])
    
    signature = hmac.new(LBANK_SECRET_KEY.encode('utf-8'),
                         query_string.encode('utf-8'),
                         hashlib.sha256).hexdigest()
    return signature

def lbank_api_request(method: str, endpoint: str, params: dict = None, signed: bool = False) -> dict | None:
    """درخواستی به API فیوچرز LBank ارسال می‌کند."""
    if params is None:
        params = {}

    headers = {
        'Content-Type': 'application/json',
        'X-LBANK-APIKEY': LBANK_API_KEY # یا 'api_key' در پارامترها، بسته به LBank
    }
    
    if signed:
        params['timestamp'] = int(time.time() * 1000) # LBank ممکن است نیاز به timestamp داشته باشد
        params['signature'] = generate_signature(params)
        
    url = f"{LBANK_FUTURES_BASE_URL}{endpoint}"
    
    try:
        if method == 'GET':
            response = requests.get(url, params=params, headers=headers)
        elif method == 'POST':
            response = requests.post(url, json=params, headers=headers) 
        else:
            logging.error(f"متد HTTP پشتیبانی نشده: {method}")
            return None
        
        response.raise_for_status() # برای خطاهای HTTP (4xx یا 5xx)
        response_json = response.json()
        
        # بررسی کد خطای LBank (معمولاً 0 برای موفقیت)
        if response_json.get('error_code') is not None and response_json.get('error_code') != 0:
            logging.error(f"LBank API خطا برگرداند: {response_json.get('error_code')} - {response_json.get('msg')}")
            return None
        return response_json
    except requests.exceptions.RequestException as e:
        logging.error(f"خطا در درخواست API LBank: {e}")
        return None
    except json.JSONDecodeError as e:
        logging.error(f"خطا در دیکد کردن JSON از LBank: {e}, پاسخ: {response.text}")
        return None

# --- منطق ربات معامله‌گر (استراتژی شما اینجا پیاده‌سازی می‌شود) ---
def execute_trading_strategy():
    """
    *** بسیار مهم: این بخش فقط یک چارچوب و جایگزینی برای استراتژی واقعی شماست. ***
    *** هر 15 دقیقه یک بار اجرا خواهد شد. ***
    """
    logging.info("در حال اجرای استراتژی معاملاتی فیوچرز برای BTCUSDT (15m)...")

    if not LBANK_API_KEY or not LBANK_SECRET_KEY:
        logging.warning("کلیدهای API LBank تنظیم نشده‌اند. استراتژی اجرا نمی‌شود.")
        return

    try:
        # 1. دریافت داده‌های بازار (مثلاً کندل‌های 15 دقیقه‌ای BTCUSDT)
        # EndPoint: /futures/kline (نام دقیق EndPoint LBank را بررسی کنید)
        klines_params = {
            "symbol": "BTCUSDT",
            "interval": "15min", # یا '15m' - فرمت دقیق LBank را بررسی کنید
            "size": 1 # فقط آخرین کندل را می‌خواهیم
        }
        klines_response = lbank_api_request('GET', '/futures/kline', params=klines_params)
        
        if klines_response and klines_response.get('data'):
            klines = klines_response['data']
            latest_kline = klines[0] if klines else None # آخرین کندل
            if latest_kline:
                # فرض می‌کنیم فرمت کندل [timestamp, open, high, low, close, volume] باشد.
                # (این را با مستندات LBank تایید کنید)
                current_price = float(latest_kline[4]) 
                logging.info(f"قیمت فعلی BTCUSDT: {current_price}")
                
                # --- اینجا استراتژی معاملاتی واقعی خود را پیاده‌سازی کنید ---
                # مثال ساختگی: اگر قیمت زیر 65000 بود، یک پوزیشن لانگ (خرید) باز کن.
                # و اگر بالای 68000 بود، پوزیشن شورت (فروش) باز کن.
                # اینها فقط مثال هستند و نباید برای معامله واقعی استفاده شوند.
                
                # حجم معامله: 0.001 BTC (این را بر اساس مدیریت سرمایه خود تنظیم کنید)
                # برای لوریج 25x و ریسک/ریوارد 1:2
                trade_volume = "0.001" 
                
                # شما باید منطق پیچیده‌تری برای ورود، خروج، مدیریت پوزیشن، SL/TP داشته باشید.
                # همچنین باید قبل از باز کردن پوزیشن جدید، بررسی کنید که آیا پوزیشنی باز دارید یا خیر.

                if current_price < 65000:
                    logging.info(f"سیگنال لانگ تشخیص داده شد در قیمت {current_price}. در حال تلاش برای ثبت سفارش.")
                    order_params = {
                        "symbol": "BTCUSDT",
                        "direction": "buy",
                        "type": "limit", # یا 'market'
                        "price": str(round(current_price * 0.999, 2)), # مثال: کمی زیر قیمت فعلی برای لیمیت
                        "volume": trade_volume,
                        "lever": "25",
                        "open_type": "isolated",
                        "client_order_id": f"bot_long_{int(time.time())}"
                    }
                    # Uncomment خطوط زیر برای فعال کردن ثبت سفارش:
                    # response_order = lbank_api_request('POST', '/futures/trade', params=order_params, signed=True)
                    # if response_order:
                    #     logging.info(f"سفارش لانگ با موفقیت ثبت شد: {response_order}")
                    #     # بلافاصله پس از ورود، باید SL و TP را بر اساس RR=1:2 تنظیم کنید.
                    #     # SL_price = entry_price - (RiskAmount / trade_volume) / leverage
                    #     # TP_price = entry_price + (2 * RiskAmount / trade_volume) / leverage
                    # else:
                    #     logging.error("شکست در ثبت سفارش لانگ.")

                elif current_price > 68000:
                    logging.info(f"سیگنال شورت تشخیص داده شد در قیمت {current_price}. در حال تلاش برای ثبت سفارش.")
                    order_params = {
                        "symbol": "BTCUSDT",
                        "direction": "sell",
                        "type": "limit",
                        "price": str(round(current_price * 1.001, 2)), # مثال: کمی بالای قیمت فعلی برای لیمیت
                        "volume": trade_volume,
                        "lever": "25",
                        "open_type": "isolated",
                        "client_order_id": f"bot_short_{int(time.time())}"
                    }
                    # Uncomment خطوط زیر برای فعال کردن ثبت سفارش:
                    # response_order = lbank_api_request('POST', '/futures/trade', params=order_params, signed=True)
                    # if response_order:
                    #     logging.info(f"سفارش شورت با موفقیت ثبت شد: {response_order}")
                    #     # بلافاصله پس از ورود، باید SL و TP را بر اساس RR=1:2 تنظیم کنید.
                    # else:
                    #     logging.error("شکست در ثبت سفارش شورت.")
                else:
                    logging.info("در این لحظه سیگنال معاملاتی بر اساس منطق ساختگی وجود ندارد.")
            else:
                logging.warning("داده‌های کندل از LBank دریافت نشد یا خالی است.")
        else:
            logging.error("شکست در دریافت داده‌های کندل از API LBank.")

    except Exception as e:
        logging.exception("خطایی در طول اجرای استراتژی رخ داد.")

# --- مسیرهای Flask (برای دسترسی Render.com و نمایش وضعیت) ---
@app.route('/')
def home():
    return "ربات معامله‌گر فیوچرز BTCUSDT در حال اجرا است."

@app.route('/health')
def health_check():
    """EndPoint برای بررسی سلامت سرویس توسط Render.com."""
    return jsonify({"status": "healthy", "message": "Bot is active and scheduler is running."})

# --- راه‌اندازی زمان‌بندی (Scheduler) ---
scheduler = BackgroundScheduler()
# هر 15 دقیقه یک بار execute_trading_strategy() را اجرا کن
scheduler.add_job(func=execute_trading_strategy, trigger="interval", minutes=15)

# --- نقطه شروع اصلی برنامه ---
if __name__ == '__main__':
    logging.info("در حال راه‌اندازی ربات معامله‌گر فیوچرز LBank...")
    
    scheduler.start()
    logging.info("زمان‌بند شروع شد. استراتژی معاملاتی هر 15 دقیقه یک بار اجرا خواهد شد.")

    port = int(os.environ.get('PORT', 5000))
    logging.info(f"اپلیکیشن Flask در هاست=0.0.0.0، پورت={port} در حال اجرا است.")
    app.run(host='0.0.0.0', port=port)

    try:
        while True:
            time.sleep(2)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        logging.info("زمان‌بند خاموش شد.")

