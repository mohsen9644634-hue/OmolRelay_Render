import os
import json
import hashlib
import hmac
import base64
import time
import requests
from flask import Flask, request, jsonify

# --- Bitget API Configuration ---
# این کلیدها باید از طریق متغیرهای محیطی Render تنظیم شده باشند.
API_KEY = os.environ.get('BG_API_KEY')
SECRET_KEY = os.environ.get('BG_SECRET_KEY')
PASSPHRASE = os.environ.get('BG_PASSPHRASE')
BASE_URL = "https://api.bitget.com"

# --- Helper Functions for Bitget API ---
def get_server_time():
    """Get Bitget server time."""
    url = f"{BASE_URL}/api/v2/mix/market/time"
    response = requests.get(url)
    response.raise_for_status() # Raise an exception for HTTP errors (4xx or 5xx)
    return response.json()['data']['t']

def make_request(method, endpoint, params=None, body=None):
    """
    Makes a signed request to the Bitget API.
import os
import json
import hashlib
import hmac
import base64
import time
import requests
from flask import Flask, request, jsonify

# --- Bitget API Configuration ---
# این کلیدها باید از طریق متغیرهای محیطی Render تنظیم شده باشند.
API_KEY = os.environ.get('BG_API_KEY')
SECRET_KEY = os.environ.get('BG_SECRET_KEY')
PASSPHRASE = os.environ.get('BG_PASSPHRASE')
BASE_URL = "https://api.bitget.com"

# --- Helper Functions for Bitget API ---
def get_server_time():
    """Get Bitget server time."""
    url = f"{BASE_URL}/api/v2/mix/market/time"
    response = requests.get(url)
    response.raise_for_status() # Raise an exception for HTTP errors (4xx or 5xx)
    return response.json()['data']['t']

def make_request(method, endpoint, params=None, body=None):
    """
    Makes a signed request to the Bitget API.
    Handles authentication and error responses.
    """
    timestamp = str(get_server_time())
    
    # Pre-process parameters for GET requests
    if params:
        query_string = '&'.join(f"{k}={v}" for k, v in sorted(params.items()))
        full_endpoint = f"{endpoint}?{query_string}"
    else:
        full_endpoint = endpoint
    
    # Construct the message for signing
    if body:
        body_str = json.dumps(body)
        message = timestamp + method.upper() + full_endpoint + body_str
    else:
        message = timestamp + method.upper() + full_endpoint

    # Sign the message
    mac = hmac.new(SECRET_KEY.encode('utf-8'), message.encode('utf-8'), hashlib.sha256)
    signature = base64.b64encode(mac.digest())

    headers = {
        "Content-Type": "application/json",
        "X-BG-APIKEY": API_KEY,
        "X-BG-SIGN": signature.decode('utf-8'),
        "X-BG-TIMESTAMP": timestamp,
        "X-BG-PASSPHRASE": PASSPHRASE,
        "X-BG-RETRY-TIMES": "1" # مهم برای جلوگیری از سفارشات تکراری در صورت بروز مشکل شبکه
    }

    url = f"{BASE_URL}{full_endpoint}"

    try:
        if method == "GET":
            response = requests.get(url, headers=headers)
        elif method == "POST":
            response = requests.post(url, headers=headers, json=body)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

        response.raise_for_status() # در صورت خطای HTTP (4xx یا 5xx) یک استثنا ایجاد می‌کند
        resp_json = response.json()
        if resp_json.get('code') != '00000':
            print(f"Bitget API Error: {resp_json.get('msg', 'Unknown error')}, Code: {resp_json.get('code')}")
            return {'status': 'error', 'msg': resp_json.get('msg', 'Unknown error'), 'code': resp_json.get('code')}
        return {'status': 'success', 'data': resp_json['data']}
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return {'status': 'error', 'msg': str(e)}

# --- Bitget Trading Functions ---

def set_leverage(symbol, margin_coin, leverage, margin_mode="isolated", pos_side="both"):
    """
    Sets the leverage for a given symbol.
    pos_side can be "long", "short", or "both".
    """
    endpoint = "/api/v2/mix/account/set-leverage"
    body = {
        "symbol": symbol,
        "marginCoin": margin_coin,
        "leverage": str(leverage), # باید string باشد
        "marginMode": margin_mode,
        "posSide": pos_side
    }
    return make_request("POST", endpoint, body=body)

def place_order(symbol, side, quantity, order_type="market"):
    """
    Places a market order and attempts to get its average fill price.
    Returns the order details including avg_fill_price.
    """
    endpoint = "/api/v2/mix/order/place-order"
    body = {
        "symbol": symbol,
        "marginCoin": "USDT",
        "side": side, # 'buy' برای long, 'sell' برای short
        "orderType": order_type,
        "size": str(quantity), # باید string باشد
        "forceFollow": "false", # استاندارد
        "presetTakeProfitPrice": "0", # از TP/SL پیش فرض در زمان ثبت سفارش استفاده نمی‌کنیم
        "presetStopLossPrice": "0",
        "timeInForce": "GTC",
        "marginMode": "isolated",
        "tradeAccount": "UMCBL", # Unified Margin Account
        "posSide": "long" if side == "buy" else "short" # تعیین صریح جهت پوزیشن
    }

    # مرحله اول: ثبت سفارش
    order_response = make_request("POST", endpoint, body=body)
    if order_response['status'] == 'success':
        order_id = order_response['data']['orderId']
        print(f"Order placed successfully: {order_id}")
        
        # بعد از ثبت سفارش مارکت، برای دریافت قیمت میانگین اجرا شده (avg_price) نیاز به کوئری داریم
        # این یک ساده‌سازی است؛ در یک ربات واقعی، از وب‌سوکت‌ها استفاده می‌شود.
        max_retries = 5
        for i in range(max_retries):
            time.sleep(1) # کمی صبر می‌کنیم تا سفارش پر شود
            query_endpoint = "/api/v2/mix/order/detail"
            query_params = {
                "symbol": symbol,
                "orderId": order_id
            }
            order_detail_response = make_request("GET", query_endpoint, params=query_params)
            
            if order_detail_response['status'] == 'success' and order_detail_response['data']:
                details = order_detail_response['data'][0] # فرض بر این است که یک سفارش برگردانده می‌شود
                if details.get('status') == 'filled':
                    return {'status': 'success', 'order_id': order_id, 'avg_price': float(details['tradeAvgPrice']), 'details': details}
                elif details.get('status') == 'new' or details.get('status') == 'partial_fill':
                    print(f"Order {order_id} not fully filled yet. Retrying...")
                    continue
                else:
                    print(f"Order {order_id} status: {details.get('status')}. No avg_price available.")
                    return {'status': 'error', 'msg': f"Order {order_id} not filled or failed.", 'details': details}
            else:
                print(f"Could not retrieve order details for {order_id}. Retrying...")

        return {'status': 'error', 'msg': f"Order {order_id} did not fill after {max_retries} retries."}
    else:
        return order_response

def place_tp_sl(symbol, pos_side, trigger_price_tp, order_price_tp, trigger_price_sl, order_price_sl, quantity):
    """
    Places Take Profit and Stop Loss orders for an existing position.
    pos_side: 'long' or 'short'
    """
    endpoint = "/api/v2/mix/order/place-plan-order"
    
    # ثبت سفارش Take Profit
    tp_body = {
        "symbol": symbol,
        "marginCoin": "USDT",
        "posSide": pos_side,
        "planType": "profit_plan", # Take Profit
        "triggerPrice": str(trigger_price_tp),
        "triggerType": "market_price", # زمانی که قیمت مارکت به این قیمت رسید، فعال شود
        "orderType": "limit", # خود سفارش TP یک سفارش لیمیت است
        "price": str(order_price_tp), # قیمت واقعی لیمیت برای TP
        "size": str(quantity),
        "tradeAccount": "UMCBL",
        "timeInForce": "GTC",
        "rangeRate": "0",
    }
    tp_response = make_request("POST", endpoint, body=tp_body)
    
    # ثبت سفارش Stop Loss
    sl_body = {
        "symbol": symbol,
        "marginCoin": "USDT",
        "posSide": pos_side,
        "planType": "loss_plan", # Stop Loss
        "triggerPrice": str(trigger_price_sl),
        "triggerType": "market_price", # زمانی که قیمت مارکت به این قیمت رسید، فعال شود
        "orderType": "limit", # خود سفارش SL یک سفارش لیمیت است
        "price": str(order_price_sl), # قیمت واقعی لیمیت برای SL
        "size": str(quantity),
        "tradeAccount": "UMCBL",
        "timeInForce": "GTC",
        "rangeRate": "0",
    }
    sl_response = make_request("POST", endpoint, body=sl_body)

    return {
        'tp_status': tp_response['status'],
        'tp_msg': tp_response.get('msg'),
        'tp_data': tp_response.get('data'),
        'sl_status': sl_response['status'],
        'sl_msg': sl_response.get('msg'),
        'sl_data': sl_response.get('data')
    }

# --- Flask App ---
app = Flask(__name__)

# --- Routes ---

@app.route('/')
def index():
    return jsonify({"message": "Bitget Signal Bot is running. Use /test or /signal/long /signal/short."})

@app.route('/test', methods=['GET'])
def test_bitget_connection():
    """Tests the connection to Bitget by getting server time."""
    try:
        server_time = get_server_time()
        return jsonify({"status": "online", "exchange": "bitget", "server_time": server_time})
    except Exception as e:
        return jsonify({"status": "error", "exchange": "bitget", "message": str(e)}), 500

@app.route('/signal/long', methods=['POST'])
def handle_long_signal():
    """Handles an incoming LONG signal from TradingView/Telegram."""
    print("Received LONG signal.")
    symbol = "BTCUSDT_UMCBL"
    leverage = 10
    quantity = 0.001 # حجم ثابت 0.001 BTC مطابق با خواست شما. 
                     # توجه: برای سرمایه ثابت (مثلاً 10 USDT)، حجم باید بر اساس قیمت فعلی محاسبه شود.
                     # فعلاً از 0.001 به عنوان مقدار ثابت استفاده می‌شود.

    # 1. تنظیم لوریج
    leverage_response = set_leverage(symbol, "USDT", leverage, "isolated", "both")
    if leverage_response['status'] == 'error':
        return jsonify({"status": "error", "message": f"Failed to set leverage: {leverage_response['msg']}"}), 500
    print(f"Leverage set to {leverage}x for {symbol}")

    # 2. ثبت سفارش LONG مارکت
    order_response = place_order(symbol, "buy", quantity, "market")
    if order_response['status'] == 'error':
        return jsonify({"status": "error", "message": f"Failed to place LONG order: {order_response['msg']}"}), 500
    
    avg_entry_price = order_response.get('avg_price')
    if not avg_entry_price:
        return jsonify({"status": "error", "message": "LONG order placed, but could not get average entry price for TP/SL."}), 500

    print(f"LONG order placed. Avg entry price: {avg_entry_price}")

    # 3. محاسبه و ثبت TP/SL برای LONG
    # SL: 0.3%, TP: 0.8%
    sl_trigger_price = round(avg_entry_price * (1 - 0.003), 4) # گرد کردن برای دقت قیمت
    tp_trigger_price = round(avg_entry_price * (1 + 0.008), 4) # گرد کردن برای دقت قیمت

    # برای TP/SL لیمیت، قیمت سفارش معمولاً همان قیمت تریگر یا کمی تهاجمی‌تر است.
    # برای سادگی و بر اساس رویه رایج، از قیمت تریگر به عنوان قیمت لیمیت استفاده می‌کنیم.
    sl_order_price = sl_trigger_price
    tp_order_price = tp_trigger_price

    tp_sl_response = place_tp_sl(
        symbol,
        "long", # جهت پوزیشن Long است
        tp_trigger_price, tp_order_price,
        sl_trigger_price, sl_order_price,
        quantity
    )

    if tp_sl_response['tp_status'] == 'error' or tp_sl_response['sl_status'] == 'error':
        return jsonify({"status": "error", "message": "Failed to place TP/SL orders.", "tp_response": tp_sl_response.get('tp_msg'), "sl_response": tp_sl_response.get('sl_msg')}), 500

    print(f"TP/SL placed for LONG. TP: {tp_trigger_price}, SL: {sl_trigger_price}")
    
    return jsonify({
        "status": "success",
        "message": "LONG trade executed with TP/SL.",
        "order_id": order_response['order_id'],
        "avg_entry_price": avg_entry_price,
        "tp_trigger": tp_trigger_price,
        "sl_trigger": sl_trigger_price,
        "tp_order_id": tp_sl_response.get('tp_data', {}).get('orderId'),
        "sl_order_id": tp_sl_response.get('sl_data', {}).get('orderId')
    })

@app.route('/signal/short', methods=['POST'])
def handle_short_signal():
    """Handles an incoming SHORT signal from TradingView/Telegram."""
    print("Received SHORT signal.")
    symbol = "BTCUSDT_UMCBL"
    leverage = 10
    quantity = 0.001 # حجم ثابت 0.001 BTC

    # 1. تنظیم لوریج
    leverage_response = set_leverage(symbol, "USDT", leverage, "isolated", "both")
    if leverage_response['status'] == 'error':
        return jsonify({"status": "error", "message": f"Failed to set leverage: {leverage_response['msg']}"}), 500
    print(f"Leverage set to {leverage}x for {symbol}")

    # 2. ثبت سفارش SHORT مارکت
    order_response = place_order(symbol, "sell", quantity, "market")
    if order_response['status'] == 'error':
        return jsonify({"status": "error", "message": f"Failed to place SHORT order: {order_response['msg']}"}), 500

    avg_entry_price = order_response.get('avg_price')
    if not avg_entry_price:
        return jsonify({"status": "error", "message": "SHORT order placed, but could not get average entry price for TP/SL."}), 500

    print(f"SHORT order placed. Avg entry price: {avg_entry_price}")

    # 3. محاسبه و ثبت TP/SL برای SHORT
    # SL: 0.3%, TP: 0.8%
    sl_trigger_price = round(avg_entry_price * (1 + 0.003), 4) # گرد کردن برای دقت قیمت
    tp_trigger_price = round(avg_entry_price * (1 - 0.008), 4) # گرد کردن برای دقت قیمت

    # برای TP/SL لیمیت، قیمت سفارش معمولاً همان قیمت تریگر یا کمی تهاجمی‌تر است.
    sl_order_price = sl_trigger_price
    tp_order_price = tp_trigger_price

    tp_sl_response = place_tp_sl(
        symbol,
        "short", # جهت پوزیشن Short است
        tp_trigger_price, tp_order_price,
        sl_trigger_price, sl_order_price,
        quantity
    )

    if tp_sl_response['tp_status'] == 'error' or tp_sl_response['sl_status'] == 'error':
        return jsonify({"status": "error", "message": "Failed to place TP/SL orders.", "tp_response": tp_sl_response.get('tp_msg'), "sl_response": tp_sl_response.get('sl_msg')}), 500

    print(f"TP/SL placed for SHORT. TP: {tp_trigger_price}, SL: {sl_trigger_price}")

    return jsonify({
        "status": "success",
        "message": "SHORT trade executed with TP/SL.",
        "order_id": order_response['order_id'],
        "avg_entry_price": avg_entry_price,
        "tp_trigger": tp_trigger_price,
        "sl_trigger": sl_trigger_price,
        "tp_order_id": tp_sl_response.get('tp_data', {}).get('orderId'),
        "sl_order_id": tp_sl_response.get('sl_data', {}).get('orderId')
    })

# --- Main entry point for Flask app ---
if __name__ == '__main__':
    # برای Render، ضروری است که به '0.0.0.0' متصل شوید و از متغیر محیطی PORT استفاده کنید.
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
￼Enter    Handles authentication and error responses.
    """
    timestamp = str(get_server_time())
    
    # Pre-process parameters for GET requests
    if params:
        query_string = '&'.join(f"{k}={v}" for k, v in sorted(params.items()))
        full_endpoint = f"{endpoint}?{query_string}"
    else:
        full_endpoint = endpoint
    
    # Construct the message for signing
    if body:
        body_str = json.dumps(body)
        message = timestamp + method.upper() + full_endpoint + body_str
    else:
        message = timestamp + method.upper() + full_endpoint

    # Sign the message
    mac = hmac.new(SECRET_KEY.encode('utf-8'), message.encode('utf-8'), hashlib.sha256)
    signature = base64.b64encode(mac.digest())

    headers = {
        "Content-Type": "application/json",
        "X-BG-APIKEY": API_KEY,
        "X-BG-SIGN": signature.decode('utf-8'),
        "X-BG-TIMESTAMP": timestamp,
        "X-BG-PASSPHRASE": PASSPHRASE,
        "X-BG-RETRY-TIMES": "1" # مهم برای جلوگیری از سفارشات تکراری در صورت بروز مشکل شبکه
    }

    url = f"{BASE_URL}{full_endpoint}"

    try:
        if method == "GET":
            response = requests.get(url, headers=headers)
        elif method == "POST":
            response = requests.post(url, headers=headers, json=body)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

        response.raise_for_status() # در صورت خطای HTTP (4xx یا 5xx) یک استثنا ایجاد می‌کند
        resp_json = response.json()
        if resp_json.get('code') != '00000':
            print(f"Bitget API Error: {resp_json.get('msg', 'Unknown error')}, Code: {resp_json.get('code')}")
            return {'status': 'error', 'msg': resp_json.get('msg', 'Unknown error'), 'code': resp_json.get('code')}
        return {'status': 'success', 'data': resp_json['data']}
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return {'status': 'error', 'msg': str(e)}

# --- Bitget Trading Functions ---

def set_leverage(symbol, margin_coin, leverage, margin_mode="isolated", pos_side="both"):
    """
    Sets the leverage for a given symbol.
    pos_side can be "long", "short", or "both".
    """
    endpoint = "/api/v2/mix/account/set-leverage"
    body = {
        "symbol": symbol,
        "marginCoin": margin_coin,
        "leverage": str(leverage), # باید string باشد
        "marginMode": margin_mode,
        "posSide": pos_side
    }
    return make_request("POST", endpoint, body=body)

def place_order(symbol, side, quantity, order_type="market"):
    """
    Places a market order and attempts to get its average fill price.
    Returns the order details including avg_fill_price.
    """
    endpoint = "/api/v2/mix/order/place-order"
    body = {
        "symbol": symbol,
        "marginCoin": "USDT",
        "side": side, # 'buy' برای long, 'sell' برای short
        "orderType": order_type,
        "size": str(quantity), # باید string باشد
        "forceFollow": "false", # استاندارد
        "presetTakeProfitPrice": "0", # از TP/SL پیش فرض در زمان ثبت سفارش استفاده نمی‌کنیم
        "presetStopLossPrice": "0",
        "timeInForce": "GTC",
        "marginMode": "isolated",
        "tradeAccount": "UMCBL", # Unified Margin Account
        "posSide": "long" if side == "buy" else "short" # تعیین صریح جهت پوزیشن
    }

    # مرحله اول: ثبت سفارش
    order_response = make_request("POST", endpoint, body=body)
    if order_response['status'] == 'success':
        order_id = order_response['data']['orderId']
        print(f"Order placed successfully: {order_id}")
        
        # بعد از ثبت سفارش مارکت، برای دریافت قیمت میانگین اجرا شده (avg_price) نیاز به کوئری داریم
        # این یک ساده‌سازی است؛ در یک ربات واقعی، از وب‌سوکت‌ها استفاده می‌شود.
        max_retries = 5
        for i in range(max_retries):
            time.sleep(1) # کمی صبر می‌کنیم تا سفارش پر شود
            query_endpoint = "/api/v2/mix/order/detail"
            query_params = {
                "symbol": symbol,
                "orderId": order_id
            }
      order_detail_response = make_request("GET", query_endpoint, params=query_params)
            
            if order_detail_response['status'] == 'success' and order_detail_response['data']:
                details = order_detail_response['data'][0] # فرض بر این است که یک سفارش برگردانده می‌شود
                if details.get('status') == 'filled':
                    return {'status': 'success', 'order_id': order_id, 'avg_price': float(details['tradeAvgPrice']), 'details': details}
                elif details.get('status') == 'new' or details.get('status') == 'partial_fill':
                    print(f"Order {order_id} not fully filled yet. Retrying...")
                    continue
                else:
                    print(f"Order {order_id} status: {details.get('status')}. No avg_price available.")
                    return {'status': 'error', 'msg': f"Order {order_id} not filled or failed.", 'details': details}
            else:
                print(f"Could not retrieve order details for {order_id}. Retrying...")

        return {'status': 'error', 'msg': f"Order {order_id} did not fill after {max_retries} retries."}
    else:
        return order_response

def place_tp_sl(symbol, pos_side, trigger_price_tp, order_price_tp, trigger_price_sl, order_price_sl, quantity):
    """
    Places Take Profit and Stop Loss orders for an existing position.
    pos_side: 'long' or 'short'
    """
    endpoint = "/api/v2/mix/order/place-plan-order"
    
    # ثبت سفارش Take Profit
    tp_body = {
        "symbol": symbol,
        "marginCoin": "USDT",
        "posSide": pos_side,
        "planType": "profit_plan", # Take Profit
        "triggerPrice": str(trigger_price_tp),
        "triggerType": "market_price", # زمانی که قیمت مارکت به این قیمت رسید، فعال شود
        "orderType": "limit", # خود سفارش TP یک سفارش لیمیت است
        "price": str(order_price_tp), # قیمت واقعی لیمیت برای TP
        "size": str(quantity),
        "tradeAccount": "UMCBL",
        "timeInForce": "GTC",
        "rangeRate": "0",
    }
    tp_response = make_request("POST", endpoint, body=tp_body)
    
    # ثبت سفارش Stop Loss
    sl_body = {
        "symbol": symbol,
        "marginCoin": "USDT",
        "posSide": pos_side,
        "planType": "loss_plan", # Stop Loss
        "triggerPrice": str(trigger_price_sl),
        "triggerType": "market_price", # زمانی که قیمت مارکت به این قیمت رسید، فعال شود
        "orderType": "limit", # خود سفارش SL یک سفارش لیمیت است
        "price": str(order_price_sl), # قیمت واقعی لیمیت برای SL
        "size": str(quantity),
        "tradeAccount": "UMCBL",
        "timeInForce": "GTC",
        "rangeRate": "0",
    }
    sl_response = make_request("POST", endpoint, body=sl_body)

    return {
        'tp_status': tp_response['status'],
        'tp_msg': tp_response.get('msg'),
        'tp_data': tp_response.get('data'),
        'sl_status': sl_response['status'],
        'sl_msg': sl_response.get('msg'),
        'sl_data': sl_response.get('data')
    }

# --- Flask App ---
app = Flask(__name__)

# --- Routes ---

@app.route('/')
def index():
    return jsonify({"message": "Bitget Signal Bot is running. Use /test or /signal/long /signal/short."})

@app.route('/test', methods=['GET'])
def test_bitget_connection():
    """Tests the connection to Bitget by getting server time."""
    try:
        server_time = get_server_time()
        return jsonify({"status": "online", "exchange": "bitget", "server_time": server_time})
    except Exception as e:
        return jsonify({"status": "error", "exchange": "bitget", "message": str(e)}), 500

@app.route('/signal/long', methods=['POST'])
def handle_long_signal():
    """Handles an incoming LONG signal from TradingView/Telegram."""
    print("Received LONG signal.")
    symbol = "BTCUSDT_UMCBL"
    leverage = 10
    quantity = 0.001 # حجم ثابت 0.001 BTC مطابق با خواست شما. 
                     # توجه: برای سرمایه ثابت (مثلاً 10 USDT)، حجم باید بر اساس قیمت فعلی محاسبه شود.
                     # فعلاً از 0.001 به عنوان مقدار ثابت استفاده می‌شود.

    # 1. تنظیم لوریج
    leverage_response = set_leverage(symbol, "USDT", leverage, "isolated", "both")
    if leverage_response['status'] == 'error':
        return jsonify({"status": "error", "message": f"Failed to set leverage: {leverage_response['msg']}"}), 500
    print(f"Leverage set to {leverage}x for {symbol}")

    # 2. ثبت سفارش LONG مارکت
    order_response = place_order(symbol, "buy", quantity, "market")
