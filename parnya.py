# -*- coding: utf-8 -*-
import os
import time
import hmac
import hashlib
import requests
import json
from datetime import datetime
from threading import Thread, Event

class CoinExAPI:
    def __init__(self, api_key, secret_key):
        self.api_key = api_key
        self.secret_key = secret_key
        self.base_url = "https://api.coinex.com/v1"

    def _sign(self, params):
        sorted_params = sorted(params.items(), key=lambda x: x[0])
        param_string = "&".join([f"{k}={v}" for k, v in sorted_params])
        sign_string = param_string + "&secret_key=" + self.secret_key
        return hashlib.md5(sign_string.encode()).hexdigest()

    def _request(self, method, path, params=None, headers=None):
        if params is None:
            params = {}
        
        timestamp = int(time.time() * 1000)
        
        if method in ["POST", "PUT", "DELETE"]:
            # For POST, PUT, DELETE, params are in the body
            auth_params = {
                'access_id': self.api_key,
                'tonce': timestamp,
                **params
            }
            sign = self._sign(auth_params)
            
            req_headers = {
                'User-Agent': 'CoinEx-API-Client/1.0.0',
                'Content-Type': 'application/json',
                'ACCESS-ID': self.api_key,
                'ACCESS-SIGN': sign,
                'ACCESS-TONCE': str(timestamp)
            }
            if headers:
                req_headers.update(headers)
            
            response = requests.request(method, self.base_url + path, json=params, headers=req_headers)
        else: # GET
            # For GET, params are in the query string
            auth_params = {
                'access_id': self.api_key,
                'tonce': timestamp,
                **params
            }
            sign = self._sign(auth_params)
            
            req_headers = {
                'User-Agent': 'CoinEx-API-Client/1.0.0',
                'ACCESS-ID': self.api_key,
                'ACCESS-SIGN': sign,
                'ACCESS-TONCE': str(timestamp)
            }
            if headers:
                req_headers.update(headers)
                
            response = requests.request(method, self.base_url + path, params=params, headers=req_headers)
            
        return response.json()

    def get_market_depth(self, market, limit=5, merge="0"):
        path = "/market/depth"
        params = {
            "market": market,
            "limit": limit,
            "merge": merge
        }
        return self._request("GET", path, params=params)

    def get_kline(self, market, type="15min", limit=100):
        path = "/market/kline"
        params = {
            "market": market,
            "type": type,
            "limit": limit
        }
        return self._request("GET", path, params=params)

    def get_account_info(self):
        path = "/balance_info"
        return self._request("GET", path)

    def get_position_info(self, market="BTCUSDT"):
        path = "/contract/position"
        params = {"market": market}
        return self._request("GET", path, params=params)

    def get_ticker(self, market="BTCUSDT"):
        path = "/market/ticker"
        params = {"market": market}
        return self._request("GET", path, params=params)

    def place_order(self, market, type, side, price, amount, leverage=10, client_id=""):
        path = "/order/limit"
        params = {
            "access_id": self.api_key,
            "market": market,
            "type": type, # "limit" or "market" (for spot, for contract it's usually limit)
            "side": side, # "buy" or "sell"
            "price": str(price),
            "amount": str(amount),
            "source_id": client_id,
            "leverage": leverage
        }
        return self._request("POST", path, params=params)

    def cancel_order(self, market, order_id):
        path = "/order/cancel"
        params = {
            "access_id": self.api_key,
            "market": market,
            "order_id": order_id
        }
        return self._request("POST", path, params=params)
    
    def get_open_orders(self, market="BTCUSDT", offset=0, limit=100):
        path = "/order/pending"
        params = {
            "market": market,
            "offset": offset,
            "limit": limit
        }
        return self._request("GET", path, params=params)

class Bot:
    def __init__(self, api_key, secret_key, market="BTCUSDT", leverage=10, timeframe="15min"):
        self.coinex = CoinExAPI(api_key, secret_key)
        self.market = market
        self.leverage = leverage
        self.timeframe = timeframe
        self.stop_event = Event()
        self.trade_thread = None
        self.min_btc_amount = 0.0001 # CoinEx BTCUSDT minimum order amount

    def get_candlestick_data(self):
        klines_data = self.coinex.get_kline(market=self.market, type=self.timeframe, limit=200)
        if klines_data and klines_data['code'] == 0:
            candles = []
            for kline in klines_data['data']:
                candles.append({
                    "timestamp": kline[0],
                    "open": float(kline[1]),
                    "close": float(kline[2]),
                    "high": float(kline[3]),
                    "low": float(kline[4]),
                    "volume": float(kline[5])
                })
            return candles
        return None

    def calculate_ema(self, prices, period):
        if not prices:
            return []
        ema_values = [sum(prices[:period]) / period]
        multiplier = 2 / (period + 1)
        for i in range(period, len(prices)):
            ema = (prices[i] - ema_values[-1]) * multiplier + ema_values[-1]
            ema_values.append(ema)
        return ema_values

    def calculate_rsi(self, prices, period=14):
        if len(prices) < period:
            return None

        gains = []
        losses = []
        for i in range(1, len(prices)):
            change = prices[i] - prices[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))

        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        rs_values = []
        rsi_values = []

        if avg_loss == 0:
            rsi_values.append(100)
        else:
            rs = avg_gain / avg_loss
            rsi_values.append(100 - (100 / (1 + rs)))

        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            
            if avg_loss == 0:
                rsi_values.append(100)
            else:
                rs = avg_gain / avg_loss
                rsi_values.append(100 - (100 / (1 + rs)))
        return rsi_values

    def calculate_atr(self, candles, period=14):
        if len(candles) < period:
            return None
        
        tr_values = []
        for i in range(1, len(candles)):
            high_low = candles[i]['high'] - candles[i]['low']
            high_prev_close = abs(candles[i]['high'] - candles[i-1]['close'])
            low_prev_close = abs(candles[i]['low'] - candles[i-1]['close'])
            tr = max(high_low, high_prev_close, low_prev_close)
            tr_values.append(tr)
            
        atr_values = []
        atr = sum(tr_values[:period]) / period
        atr_values.append(atr)
        
        for i in range(period, len(tr_values)):
            atr = ((atr * (period - 1)) + tr_values[i]) / period
            atr_values.append(atr)
            
        return atr_values

    def calculate_supertrend(self, candles, atr_period=10, multiplier=3):
        if len(candles) < atr_period:
            return None
        
        atr_values = self.calculate_atr(candles, atr_period)
        if not atr_values:
            return None
        
        basic_upper_band = []
        basic_lower_band = []
        
        for i in range(len(candles)):
            if i >= atr_period -1: # ATR values start from atr_period - 1 index of candles
                hl2 = (candles[i]['high'] + candles[i]['low']) / 2
                basic_upper = hl2 + (multiplier * atr_values[i - (atr_period - 1)])
                basic_lower = hl2 - (multiplier * atr_values[i - (atr_period - 1)])
                basic_upper_band.append(basic_upper)
                basic_lower_band.append(basic_lower)
            else:
                basic_upper_band.append(None)
                basic_lower_band.append(None)
        
        final_upper_band = [None] * len(candles)
        final_lower_band = [None] * len(candles)
        
        supertrend = [None] * len(candles)
        supertrend_direction = [0] * len(candles) # 1 for uptrend, -1 for downtrend
        
# -*- coding: utf-8 -*-
import os
import time
import hmac
import hashlib
import requests
import json
from datetime import datetime
from threading import Thread, Event

class CoinExAPI:
    def __init__(self, api_key, secret_key):
        self.api_key = api_key
        self.secret_key = secret_key
        self.base_url = "https://api.coinex.com/v1"

    def _sign(self, params):
        sorted_params = sorted(params.items(), key=lambda x: x[0])
        param_string = "&".join([f"{k}={v}" for k, v in sorted_params])
        sign_string = param_string + "&secret_key=" + self.secret_key
        return hashlib.md5(sign_string.encode()).hexdigest()

    def _request(self, method, path, params=None, headers=None):
        if params is None:
            params = {}
        
        timestamp = int(time.time() * 1000)
        
        if method in ["POST", "PUT", "DELETE"]:
            # For POST, PUT, DELETE, params are in the body
            auth_params = {
                'access_id': self.api_key,
                'tonce': timestamp,
                **params
            }
            sign = self._sign(auth_params)
            
            req_headers = {
                'User-Agent': 'CoinEx-API-Client/1.0.0',
                'Content-Type': 'application/json',
                'ACCESS-ID': self.api_key,
                'ACCESS-SIGN': sign,
                'ACCESS-TONCE': str(timestamp)
            }
            if headers:
                req_headers.update(headers)
            
            response = requests.request(method, self.base_url + path, json=params, headers=req_headers)
        else: # GET
            # For GET, params are in the query string
            auth_params = {
                'access_id': self.api_key,
                'tonce': timestamp,
                **params
            }
            sign = self._sign(auth_params)
            
            req_headers = {
                'User-Agent': 'CoinEx-API-Client/1.0.0',
                'ACCESS-ID': self.api_key,
                'ACCESS-SIGN': sign,
                'ACCESS-TONCE': str(timestamp)
            }
            if headers:
                req_headers.update(headers)
                
            response = requests.request(method, self.base_url + path, params=params, headers=req_headers)
            
        return response.json()

    def get_market_depth(self, market, limit=5, merge="0"):
        path = "/market/depth"
        params = {
            "market": market,
            "limit": limit,
            "merge": merge
        }
        return self._request("GET", path, params=params)

    def get_kline(self, market, type="15min", limit=100):
        path = "/market/kline"
        params = {
            "market": market,
            "type": type,
            "limit": limit
        }
        return self._request("GET", path, params=params)

    def get_account_info(self):
        path = "/balance_info"
        return self._request("GET", path)

    def get_position_info(self, market="BTCUSDT"):
        path = "/contract/position"
        params = {"market": market}
        return self._request("GET", path, params=params)

    def get_ticker(self, market="BTCUSDT"):
        path = "/market/ticker"
        params = {"market": market}
        return self._request("GET", path, params=params)

    def place_order(self, market, type, side, price, amount, leverage=10, client_id=""):
        path = "/order/limit"
        params = {
            "access_id": self.api_key,
            "market": market,
            "type": type, # "limit" or "market" (for spot, for contract it's usually limit)
            "side": side, # "buy" or "sell"
            "price": str(price),
            "amount": str(amount),
            "source_id": client_id,
            "leverage": leverage
        }
        return self._request("POST", path, params=params)

    def cancel_order(self, market, order_id):
        path = "/order/cancel"
        params = {
            "access_id": self.api_key,
            "market": market,
            "order_id": order_id
        }
        return self._request("POST", path, params=params)
    
    def get_open_orders(self, market="BTCUSDT", offset=0, limit=100):
        path = "/order/pending"
        params = {
            "market": market,
            "offset": offset,
            "limit": limit
        }
        return self._request("GET", path, params=params)

class Bot:
    def __init__(self, api_key, secret_key, market="BTCUSDT", leverage=10, timeframe="15min"):
        self.coinex = CoinExAPI(api_key, secret_key)
        self.market = market
        self.leverage = leverage
        self.timeframe = timeframe
        self.stop_event = Event()
        self.trade_thread = None
        self.min_btc_amount = 0.0001 # CoinEx BTCUSDT minimum order amount

    def get_candlestick_data(self):
        klines_data = self.coinex.get_kline(market=self.market, type=self.timeframe, limit=200)
        if klines_data and klines_data['code'] == 0:
            candles = []
            for kline in klines_data['data']:
                candles.append({
                    "timestamp": kline[0],
                    "open": float(kline[1]),
                    "close": float(kline[2]),
                    "high": float(kline[3]),
                    "low": float(kline[4]),
                    "volume": float(kline[5])
                })
            return candles
        return None

    def calculate_ema(self, prices, period):
        if not prices:
            return []
        ema_values = [sum(prices[:period]) / period]
        multiplier = 2 / (period + 1)
        for i in range(period, len(prices)):
            ema = (prices[i] - ema_values[-1]) * multiplier + ema_values[-1]
            ema_values.append(ema)
        return ema_values

    def calculate_rsi(self, prices, period=14):
        if len(prices) < period:
            return None

        gains = []
        losses = []
        for i in range(1, len(prices)):
            change = prices[i] - prices[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))

        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        rs_values = []
        rsi_values = []

        if avg_loss == 0:
            rsi_values.append(100)
        else:
            rs = avg_gain / avg_loss
            rsi_values.append(100 - (100 / (1 + rs)))

        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            
            if avg_loss == 0:
                rsi_values.append(100)
            else:
                rs = avg_gain / avg_loss
                rsi_values.append(100 - (100 / (1 + rs)))
        return rsi_values

    def calculate_atr(self, candles, period=14):
        if len(candles) < period:
            return None
        
        tr_values = []
        for i in range(1, len(candles)):
            high_low = candles[i]['high'] - candles[i]['low']
            high_prev_close = abs(candles[i]['high'] - candles[i-1]['close'])
            low_prev_close = abs(candles[i]['low'] - candles[i-1]['close'])
            tr = max(high_low, high_prev_close, low_prev_close)
            tr_values.append(tr)
            
        atr_values = []
        atr = sum(tr_values[:period]) / period
        atr_values.append(atr)
        
        for i in range(period, len(tr_values)):
            atr = ((atr * (period - 1)) + tr_values[i]) / period
            atr_values.append(atr)
            
        return atr_values

    def calculate_supertrend(self, candles, atr_period=10, multiplier=3):
        if len(candles) < atr_period:
            return None
        
        atr_values = self.calculate_atr(candles, atr_period)
        if not atr_values:
            return None
        
        basic_upper_band = []
        basic_lower_band = []
        
        for i in range(len(candles)):
            if i >= atr_period -1: # ATR values start from atr_period - 1 index of candles
                hl2 = (candles[i]['high'] + candles[i]['low']) / 2
                basic_upper = hl2 + (multiplier * atr_values[i - (atr_period - 1)])
                basic_lower = hl2 - (multiplier * atr_values[i - (atr_period - 1)])
                basic_upper_band.append(basic_upper)
                basic_lower_band.append(basic_lower)
            else:
                basic_upper_band.append(None)
                basic_lower_band.append(None)
        
        final_upper_band = [None] * len(candles)
        final_lower_band = [None] * len(candles)
        
        supertrend = [None] * len(candles)
        supertrend_direction = [0] * len(candles) # 1 for uptrend, -1 for downtrend
        
        for i in range(len(candles)):
            if basic_upper_band[i] is None:
                continue

            # Calculate Final Upper Band
            if i == 0 or final_upper_band[i-1] is None:
                final_upper_band[i] = basic_upper_band[i]
            elif basic_upper_band[i] < final_upper_band[i-1] or candles[i-1]['close'] > final_upper_band[i-1]:
                final_upper_band[i] = basic_upper_band[i]
            else:
                final_upper_band[i] = final_upper_band[i-1]
            
            # Calculate Final Lower Band
            if i == 0 or final_lower_band[i-1] is None:
                final_lower_band[i] = basic_lower_band[i]
            elif basic_lower_band[i] > final_lower_band[i-1] or candles[i-1]['close'] < final_lower_band[i-1]:
                final_lower_band[i] = basic_lower_band[i]
            else:
                final_lower_band[i] = final_lower_band[i-1]

            # Calculate Supertrend
            if supertrend_direction[i-1] == 1 and candles[i]['close'] < final_lower_band[i]:
                supertrend_direction[i] = -1
            elif supertrend_direction[i-1] == -1 and candles[i]['close'] > final_upper_band[i]:
                supertrend_direction[i] = 1
            else:
                supertrend_direction[i] = supertrend_direction[i-1]
            
            if supertrend_direction[i] == 1:
                supertrend[i] = final_lower_band[i]
            else:
                supertrend[i] = final_upper_band[i]
        
        return supertrend, supertrend_direction


    def analyze_strategy_c(self, candles):
        closes = [c['close'] for c in candles]

        # EMA
        ema10 = self.calculate_ema(closes, 10)
        ema20 = self.calculate_ema(closes, 20)
        ema50 = self.calculate_ema(closes, 50)
        
        if len(ema10) < 1 or len(ema20) < 1 or len(ema50) < 1:
            return None, "Not enough data for EMA"

        latest_ema10 = ema10[-1]
        latest_ema20 = ema20[-1]
        latest_ema50 = ema50[-1]

        # RSI
        rsi_values = self.calculate_rsi(closes, 14)
        if rsi_values is None:
            return None, "Not enough data for RSI"
        latest_rsi = rsi_values[-1]

        # Supertrend
        supertrend_line, supertrend_dir = self.calculate_supertrend(candles, atr_period=10, multiplier=3)
        if supertrend_line is None or len(supertrend_line) < 1:
            return None, "Not enough data for Supertrend"
        latest_supertrend_line = supertrend_line[-1]
        latest_supertrend_dir = supertrend_dir[-1]

        latest_close = closes[-1]

        # Buy/Long Signal
        # EMA crossover: EMA10 > EMA20 > EMA50
        # RSI: > 50 (indicating bullish momentum)
        # Supertrend: Currently in uptrend (green)
        if (latest_ema10 > latest_ema20 and latest_ema20 > latest_ema50 and
            latest_rsi > 50 and latest_supertrend_dir == 1 and
            latest_close > latest_supertrend_line):
            return "BUY", "Strategy C: All bullish conditions met"

        # Sell/Short Signal
        # EMA crossover: EMA10 < EMA20 < EMA50
        # RSI: < 50 (indicating bearish momentum)
        # Supertrend: Currently in downtrend (red)
        if (latest_ema10 < latest_ema20 and latest_ema20 < latest_ema50 and
            latest_rsi < 50 and latest_supertrend_dir == -1 and
            latest_close < latest_supertrend_line):
            return "SELL", "Strategy C: All bearish conditions met"

        return "HOLD", "No clear signal from Strategy C"

    def get_available_balance(self, asset="USDT"):
        account_info = self.coinex.get_account_info()
        if account_info and account_info['code'] == 0:
            for currency, balance_data in account_info['data']['balance'].items():
                if currency == asset:
                    return float(balance_data['available'])
        return 0.0

    def get_position_quantity(self, market="BTCUSDT"):
        position_info = self.coinex.get_position_info(market)
        if position_info and position_info['code'] == 0:
            if 'data' in position_info and position_info['data']:
                # The data structure might be a list of positions or a single position object
                # Assuming 'data' is a list and we want the first one, or it's a dict.
                if isinstance(position_info['data'], list) and position_info['data']:
                    for pos in position_info['data']:
                        if pos['market'] == market:
                            return float(pos['amount']), pos['type'] # type: 'long' or 'short'
                elif isinstance(position_info['data'], dict) and position_info['data'].get('market') == market:
                     return float(position_info['data']['amount']), position_info['data']['type']
        return 0.0, None

    def calculate_order_amount(self, current_price, usdt_balance, is_long):
        # Calculate max orderable amount considering leverage and minimum trade size
        # Coinex minimum BTCUSDT order amount is 0.0001 BTC
        
        # Total value we can trade with leverage
        trade_value_usdt = usdt_balance * self.leverage
        
        # Amount in BTC
        amount_btc = trade_value_usdt / current_price
        
        # Ensure it meets minimum
        if amount_btc < self.min_btc_amount:
            print(f"Calculated amount {amount_btc:.8f} is less than minimum {self.min_btc_amount}, adjusting to minimum.")
            amount_btc = self.min_btc_amount
            
            # Check if even minimum is affordable with current balance
            cost_for_min_btc = (self.min_btc_amount * current_price) / self.leverage
            if cost_for_min_btc > usdt_balance:
                print(f"Not enough balance ({usdt_balance:.2f} USDT) to open minimum position ({self.min_btc_amount} BTC) at current price ({current_price:.2f}). Required: {cost_for_min_btc:.2f} USDT.")
                return 0.0

        return amount_btc

    def trade_loop(self):
        print("Bot started trading loop.")
        while not self.stop_event.is_set():
            try:
                candles = self.get_candlestick_data()
                if not candles:
                    print("Failed to get candlestick data. Retrying in 60 seconds.")
                    time.sleep(60)
                    continue

                signal, reason = self.analyze_strategy_c(candles)
                current_price = candles[-1]['close'] # Use the latest close price for decisions

                print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Market: {self.market}, Signal: {signal}, Reason: {reason}, Current Price: {current_price:.2f}")

                position_quantity, position_type = self.get_position_quantity(self.market)
                open_orders = self.coinex.get_open_orders(self.market)
                
                # Cancel any pending orders before making new decisions
                if open_orders and open_orders['code'] == 0 and open_orders['data']['data']:
                    print(f"Found {len(open_orders['data']['data'])} open orders. Cancelling them.")
                    for order in open_orders['data']['data']:
                        self.coinex.cancel_order(self.market, order['id'])
                    # Give some time for orders to be cancelled
                    time.sleep(5)
                    # Recheck position after cancellation
                    position_quantity, position_type = self.get_position_quantity(self.market)


                if signal == "BUY":
                    if position_type == "short":
                        print(f"Closing existing SHORT position ({position_quantity:.8f} {self.market.replace('USDT', '')}) before going LONG.")
                        # Close short position by buying
                        self.coinex.place_order(self.market, "limit", "buy", current_price, position_quantity, self.leverage)
                        time.sleep(5) # Wait for order to fill
                        position_quantity, position_type = self.get_position_quantity(self.market)
                        if position_quantity > 0: # If position still exists, something went wrong
                            print("Failed to fully close short position.")
                            continue # Try again next cycle
                        print("Short position closed.")

                    if position_type != "long" or position_quantity == 0:
                        usdt_balance = self.get_available_balance("USDT")
                        amount_to_buy = self.calculate_order_amount(current_price, usdt_balance, True)
                        
                        if amount_to_buy > 0:
                            print(f"Placing LONG order: {amount_to_buy:.8f} {self.market.replace('USDT', '')} at {current_price:.2f} USDT.")
                            order = self.coinex.place_order(self.market, "limit", "buy", current_price, amount_to_buy, self.leverage)
                            if order and order['code'] == 0:
                                print(f"LONG order placed successfully: {order['data']['id']}")
                            else:
                                print(f"Failed to place LONG order: {order}")
                        else:
                            print("Cannot place LONG order: Not enough balance or amount too small.")
                    else:
                        print("Already in a LONG position. Holding.")

                elif signal == "SELL":
                    if position_type == "long":
                        print(f"Closing existing LONG position ({position_quantity:.8f} {self.market.replace('USDT', '')}) before going SHORT.")
                        # Close long position by selling
                        self.coinex.place_order(self.market, "limit", "sell", current_price, position_quantity, self.leverage)
                        time.sleep(5) # Wait for order to fill
                        position_quantity, position_type = self.get_position_quantity(self.market)
                        if position_quantity > 0: # If position still exists
                            print("Failed to fully close long position.")
                            continue # Try again next cycle
                        print("Long position closed.")

                    if position_type != "short" or position_quantity == 0:
                        usdt_balance = self.get_available_balance("USDT")
                        amount_to_sell = self.calculate_order_amount(current_price, usdt_balance, False) # Using same logic for amount
                        
                        if amount_to_sell > 0:
                            print(f"Placing SHORT order: {amount_to_sell:.8f} {self.market.replace('USDT', '')} at {current_price:.2f} USDT.")
                            order = self.coinex.place_order(self.market, "limit", "sell", current_price, amount_to_sell, self.leverage)
                            if order and order['code'] == 0:
                                print(f"SHORT order placed successfully: {order['data']['id']}")
                            else:
                                print(f"Failed to place SHORT order: {order}")
                        else:
                            print("Cannot place SHORT order: Not enough balance or amount too small.")
                    else:
                        print("Already in a SHORT position. Holding.")
                else: # HOLD
                    print("No strong signal, holding current position or staying out of market.")
                    # If there's an open position, we'll just keep it based on HOLD signal
                    # If there are open orders (e.g., from a failed close), they should have been cancelled already.

                # Sleep until the next candlestick closes (15 minutes for 15min timeframe)
                # This assumes we want to analyze data at the start of each new candle
                # For 15min, 900 seconds. Add a buffer for API calls.
                time.sleep(15 * 60) 

            except Exception as e:
                print(f"An error occurred in trade loop: {e}")
                time.sleep(60) # Wait before retrying

    def start_bot(self):
        if self.trade_thread and self.trade_thread.is_alive():
            print("Bot is already running.")
            return "Bot is already running."
        
        self.stop_event.clear()
        self.trade_thread = Thread(target=self.trade_loop)
        self.trade_thread.start()
        print("Bot started.")
        return "Bot started."

    def stop_bot(self):
        if self.trade_thread and self.trade_thread.is_alive():
            self.stop_event.set()
            self.trade_thread.join()
            print("Bot stopped.")
            return "Bot stopped."
        else:
            print("Bot is not running.")
            return "Bot is not running."

# Flask App for web interface to control the bot
from flask import Flask, request, jsonify

app = Flask(__name__)

# Replace with your actual API Key and Secret
API_KEY = os.getenv("COINEX_API_KEY")
SECRET_KEY = os.getenv("COINEX_SECRET_KEY")

if not API_KEY or not SECRET_KEY:
    print("WARNING: COINEX_API_KEY or COINEX_SECRET_KEY environment variables are not set.")
    print("Please set them before deploying to Render. Bot functionality will be limited.")
    # For local testing without environment variables, you can uncomment these and fill them:
    # API_KEY = "YOUR_API_KEY"
    # SECRET_KEY = "YOUR_SECRET_KEY"

# Initialize the bot globally
trading_bot = None
if API_KEY and SECRET_KEY:
    trading_bot = Bot(API_KEY, SECRET_KEY, market="BTCUSDT", leverage=10, timeframe="15min")
else:
    print("Bot not initialized due to missing API keys.")


@app.route("/")
def home():
    return "CoinEx Trading Bot is running. Use /start_bot or /stop_bot."

@app.route("/status")
def status():
    if trading_bot:
        if trading_bot.trade_thread and trading_bot.trade_thread.is_alive():
            return jsonify({"status": "running", "message": "Trading bot is active."})
        else:
            return jsonify({"status": "stopped", "message": "Trading bot is currently stopped."})
    else:
        return jsonify({"status": "error", "message": "Trading bot not initialized (API keys missing?)."})


@app.route("/start_bot", methods=["POST"])
def start_bot_route():
    if not trading_bot:
        return jsonify({"status": "error", "message": "Cannot start bot, API keys are missing or bot not initialized."}), 400
    
    message = trading_bot.start_bot()
    return jsonify({"status": "success", "message": message})

@app.route("/stop_bot", methods=["POST"])
def stop_bot_route():
    if not trading_bot:
        return jsonify({"status": "error", "message": "Cannot stop bot, API keys are missing or bot not initialized."}), 400

    message = trading_bot.stop_bot()
    return jsonify({"status": "success", "message": message})

if __name__ == "__main__":
    # This block is mainly for local development.
    # On Render, Gunicorn will typically handle running the app.
    if API_KEY and SECRET_KEY:
        print("Bot initialized with API keys. Starting Flask app...")
        app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
    else:
        print("Bot not initialized. Please set COINEX_API_KEY and COINEX_SECRET_KEY environment variables.")
        print("Running Flask app without bot functionality for status checks only.")
        app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
        for i in range(len(candles)):
            if basic_upper_band[i] is None:
                continue

            # Calculate Final Upper Band
            if i == 0 or final_upper_band[i-1] is None:
                final_upper_band[i] = basic_upper_band[i]
            elif basic_upper_band[i] < final_upper_band[i-1] or candles[i-1]['close'] > final_upper_band[i-1]:
                final_upper_band[i] = basic_upper_band[i]
            else:
                final_upper_band[i] = final_upper_band[i-1]
            
            # Calculate Final Lower Band
            if i == 0 or final_lower_band[i-1] is None:
                final_lower_band[i] = basic_lower_band[i]
            elif basic_lower_band[i] > final_lower_band[i-1] or candles[i-1]['close'] < final_lower_band[i-1]:
                final_lower_band[i] = basic_lower_band[i]
            else:
                final_lower_band[i] = final_lower_band[i-1]

            # Calculate Supertrend
            if supertrend_direction[i-1] == 1 and candles[i]['close'] < final_lower_band[i]:
                supertrend_direction[i] = -1
            elif supertrend_direction[i-1] == -1 and candles[i]['close'] > final_upper_band[i]:
                supertrend_direction[i] = 1
            else:
                supertrend_direction[i] = supertrend_direction[i-1]
            
            if supertrend_direction[i] == 1:
                supertrend[i] = final_lower_band[i]
            else:
                supertrend[i] = final_upper_band[i]
        
        return supertrend, supertrend_direction


    def analyze_strategy_c(self, candles):
        closes = [c['close'] for c in candles]

        # EMA
        ema10 = self.calculate_ema(closes, 10)
        ema20 = self.calculate_ema(closes, 20)
        ema50 = self.calculate_ema(closes, 50)
        
        if len(ema10) < 1 or len(ema20) < 1 or len(ema50) < 1:
            return None, "Not enough data for EMA"

        latest_ema10 = ema10[-1]
        latest_ema20 = ema20[-1]
        latest_ema50 = ema50[-1]

        # RSI
        rsi_values = self.calculate_rsi(closes, 14)
        if rsi_values is None:
            return None, "Not enough data for RSI"
        latest_rsi = rsi_values[-1]

        # Supertrend
        supertrend_line, supertrend_dir = self.calculate_supertrend(candles, atr_period=10, multiplier=3)
        if supertrend_line is None or len(supertrend_line) < 1:
            return None, "Not enough data for Supertrend"
        latest_supertrend_line = supertrend_line[-1]
        latest_supertrend_dir = supertrend_dir[-1]

        latest_close = closes[-1]

        # Buy/Long Signal
        # EMA crossover: EMA10 > EMA20 > EMA50
        # RSI: > 50 (indicating bullish momentum)
        # Supertrend: Currently in uptrend (green)
        if (latest_ema10 > latest_ema20 and latest_ema20 > latest_ema50 and
            latest_rsi > 50 and latest_supertrend_dir == 1 and
            latest_close > latest_supertrend_line):
            return "BUY", "Strategy C: All bullish conditions met"

        # Sell/Short Signal
        # EMA crossover: EMA10 < EMA20 < EMA50
        # RSI: < 50 (indicating bearish momentum)
        # Supertrend: Currently in downtrend (red)
        if (latest_ema10 < latest_ema20 and latest_ema20 < latest_ema50 and
            latest_rsi < 50 and latest_supertrend_dir == -1 and
            latest_close < latest_supertrend_line):
            return "SELL", "Strategy C: All bearish conditions met"

        return "HOLD", "No clear signal from Strategy C"

    def get_available_balance(self, asset="USDT"):
        account_info = self.coinex.get_account_info()
        if account_info and account_info['code'] == 0:
            for currency, balance_data in account_info['data']['balance'].items():
                if currency == asset:
                    return float(balance_data['available'])
        return 0.0

    def get_position_quantity(self, market="BTCUSDT"):
        position_info = self.coinex.get_position_info(market)
        if position_info and position_info['code'] == 0:
            if 'data' in position_info and position_info['data']:
                # The data structure might be a list of positions or a single position object
                # Assuming 'data' is a list and we want the first one, or it's a dict.
                if isinstance(position_info['data'], list) and position_info['data']:
                    for pos in position_info['data']:
                        if pos['market'] == market:
                            return float(pos['amount']), pos['type'] # type: 'long' or 'short'
                elif isinstance(position_info['data'], dict) and position_info['data'].get('market') == market:
               return float(position_info['data']['amount']), position_info['data']['type']
        return 0.0, None

    def calculate_order_amount(self, current_price, usdt_balance, is_long):
        # Calculate max orderable amount considering leverage and minimum trade size
        # Coinex minimum BTCUSDT order amount is 0.0001 BTC
        
        # Total value we can trade with leverage
        trade_value_usdt = usdt_balance * self.leverage
        
        # Amount in BTC
        amount_btc = trade_value_usdt / current_price
        
        # Ensure it meets minimum
        if amount_btc < self.min_btc_amount:
            print(f"Calculated amount {amount_btc:.8f} is less than minimum {self.min_btc_amount}, adjusting to minimum.")
            amount_btc = self.min_btc_amount
            
            # Check if even minimum is affordable with current balance
            cost_for_min_btc = (self.min_btc_amount * current_price) / self.leverage
            if cost_for_min_btc > usdt_balance:
                print(f"Not enough balance ({usdt_balance:.2f} USDT) to open minimum position ({self.min_btc_amount} BTC) at current price ({current_price:.2f}). Required: {cost_for_min_btc:.2f} USDT.")
                return 0.0

        return amount_btc

    def trade_loop(self):
        print("Bot started trading loop.")
        while not self.stop_event.is_set():
            try:
                candles = self.get_candlestick_data()
                if not candles:
                    print("Failed to get candlestick data. Retrying in 60 seconds.")
                    time.sleep(60)
                    continue

                signal, reason = self.analyze_strategy_c(candles)
                current_price = candles[-1]['close'] # Use the latest close price for decisions

                print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Market: {self.market}, Signal: {signal}, Reason: {reason}, Current Price: {current_price:.2f}")

                position_quantity, position_type = self.get_position_quantity(self.market)
                open_orders = self.coinex.get_open_orders(self.market)
                
                # Cancel any pending orders before making new decisions
                if open_orders and open_orders['code'] == 0 and open_orders['data']['data']:
                    print(f"Found {len(open_orders['data']['data'])} open orders. Cancelling them.")
                    for order in open_orders['data']['data']:
                        self.coinex.cancel_order(self.market, order['id'])
                    # Give some time for orders to be cancelled
                    time.sleep(5)
                    # Recheck position after cancellation
                    position_quantity, position_type = self.get_position_quantity(self.market)


                if signal == "BUY":
                    if position_type == "short":
                        print(f"Closing existing SHORT position ({position_quantity:.8f} {self.market.replace('USDT', '')}) before going LONG.")
                        # Close short position by buying
                        self.coinex.place_order(self.market, "limit", "buy", current_price, position_quantity, self.leverage)
                        time.sleep(5) # Wait for order to fill
                        position_quantity, position_type = self.get_position_quantity(self.market)
                        if position_quantity > 0: # If position still exists, something went wrong
                            print("Failed to fully close short position.")
                            continue # Try again next cycle
                        print("Short position closed.")

                    if position_type != "long" or position_quantity == 0:
                        usdt_balance = self.get_available_balance("USDT")
                        amount_to_buy = self.calculate_order_amount(current_price, usdt_balance, True)
                        
                        if amount_to_buy > 0:
                            print(f"Placing LONG order: {amount_to_buy:.8f} {self.market.replace('USDT', '')} at {current_price:.2f} USDT.")
                            order = self.coinex.place_order(self.market, "limit", "buy", current_price, amount_to_buy, self.leverage)
                            if order and order['code'] == 0:
                                print(f"LONG order placed successfully: {order['data']['id']}")
                            else:
                                print(f"Failed to place LONG order: {order}")
                        else:
                            print("Cannot place LONG order: Not enough balance or amount too small.")
                    else:
                        print("Already in a LONG position. Holding.")

                elif signal == "SELL":
                    if position_type == "long":
                        print(f"Closing existing LONG position ({position_quantity:.8f} {self.market.replace('USDT', '')}) before going SHORT.")
                        # Close long position by selling
                        self.coinex.place_order(self.market, "limit", "sell", current_price, position_quantity, self.leverage)
                        time.sleep(5) # Wait for order to fill
                        position_quantity, position_type = self.get_position_quantity(self.market)
                        if position_quantity > 0: # If position still exists
                            print("Failed to fully close long position.")
                            continue # Try again next cycle
                        print("Long position closed.")

                    if position_type != "short" or position_quantity == 0:
                        usdt_balance = self.get_available_balance("USDT")
                        amount_to_sell = self.calculate_order_amount(current_price, usdt_balance, False) # Using same logic for amount
                        
                        if amount_to_sell > 0:
                            print(f"Placing SHORT order: {amount_to_sell:.8f} {self.market.replace('USDT', '')} at {current_price:.2f} USDT.")
                            order = self.coinex.place_order(self.market, "limit", "sell", current_price, amount_to_sell, self.leverage)
                            if order and order['code'] == 0:
                                print(f"SHORT order placed successfully: {order['data']['id']}")
                            else:
