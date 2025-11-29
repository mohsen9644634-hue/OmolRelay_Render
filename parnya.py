import os
import time
import hmac
import hashlib
import requests
import json
from flask import Flask, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
import logging

# تنظیم لاگ
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)

# --- API KEYS ---
LBANK_API_KEY = os.environ.get('LBANK_API_KEY')
LBANK_SECRET_KEY = os.environ.get('LBANK_SECRET_KEY')

if not LBANK_API_KEY or not LBANK_SECRET_KEY:
    logging.error("⚠️ LBANK_API_KEY یا LBANK_SECRET_KEY تنظیم نشده است!")

LBANK_FUTURES_BASE_URL = "https://api.lbank.com/v2"


# --- Signature ---
def generate_signature(params: dict) -> str:
    query_string = '&'.join([f"{k}={v}" for k, v in sorted(params.items())])
    signature = hmac.new(
        LBANK_SECRET_KEY.encode('utf-8'),
        query_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return signature


# --- API Request ---
def lbank_api_request(method: str, endpoint: str, params: dict = None, signed: bool = False):
    if params is None:
        params = {}

    headers = {
        'Content-Type': 'application/json',
        'X-LBANK-APIKEY': LBANK_API_KEY
    }

    if signed:
        params['timestamp'] = int(time.time() * 1000)
        params['signature'] = generate_signature(params)

    url = f"{LBANK_FUTURES_BASE_URL}{endpoint}"

    try:
        if method == 'GET':
            response = requests.get(url, params=params, headers=headers)
        else:
            response = requests.post(url, json=params, headers=headers)

        response.raise_for_status()
        response_json = response.json()

        if response_json.get('error_code') not in [None, 0]:
            logging.error(f"LBank Error: {response_json}")
            return None

        return response_json

    except Exception as e:
        logging.error(f"API Request Error: {e}")
        return None


# --- Trading Strategy ---
def execute_trading_strategy():
    logging.info("🔄 اجرای استراتژی فیوچرز BTCUSDT (15m)...")

    if not LBANK_API_KEY or not LBANK_SECRET_KEY:
        logging.warning("کلیدهای API تنظیم نشده‌اند.")
        return

    try:
        # دریافت آخرین کندل
        params = {
            "symbol": "BTCUSDT",
            "interval": "15min",
            "size": 1
        }
        resp = lbank_api_request('GET', '/futures/kline', params=params)

        if not resp or not resp.get('data'):
            logging.error("❌ دریافت کندل ناموفق")
            return

        kline = resp['data'][0]
        current_price = float(kline[4])
        logging.info(f"📈 قیمت فعلی: {current_price}")

        # مثال ساده برای تست
        if current_price < 65000:
            logging.info("📗 سیگنال لانگ شناسایی شد.")
        elif current_price > 68000:
            logging.info("📕 سیگنال شورت شناسایی شد.")
        else:
            logging.info("📘 سیگنالی وجود ندارد.")

    except Exception as e:
        logging.error(f"❌ خطا در استراتژی: {e}")


# --- Flask Routes ---
@app.route('/')
def home():
    return "ربات معامله‌گر فیوچرز BTCUSDT در حال اجراست ✔️"


@app.route('/health')
def health_check():
    return jsonify({"status": "healthy", "message": "Bot is active and scheduler is running."})


# --- Scheduler (GLOBAL START) ---
scheduler = BackgroundScheduler()
scheduler.add_job(func=execute_trading_strategy, trigger="interval", minutes=15)
scheduler.start()
logging.info("⏳ Scheduler started (GLOBAL).")
