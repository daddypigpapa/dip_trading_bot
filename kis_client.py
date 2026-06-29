import os
import time
import logging
import requests
import random
import math
from config import KIS_BASE_URL, KIS_APPKEY, KIS_APPSECRET, KIS_CANO, KIS_ACNT_PRDT_CD, KIS_MODE

logger = logging.getLogger("KISClient")
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class KISClient:
    def __init__(self):
        self.appkey = KIS_APPKEY
        self.appsecret = KIS_APPSECRET
        self.base_url = KIS_BASE_URL
        self.token = None
        self.token_expire = 0
        self.has_keys = bool(self.appkey and self.appsecret)
        
        if not self.has_keys:
            logger.warning("KIS API credentials (appkey/appsecret) are missing. Running client in MOCK data mode.")

    def get_access_token(self):
        """Retrieves and caches OAuth2 token."""
        if not self.has_keys:
            return None
            
        current_time = time.time()
        if self.token and current_time < self.token_expire:
            return self.token
            
        url = f"{self.base_url}/oauth2/tokenP"
        payload = {
            "grant_type": "client_credentials",
            "appkey": self.appkey,
            "secretkey": self.appsecret
        }
        
        try:
            res = requests.post(url, json=payload, timeout=5)
            if res.status_code == 200:
                data = res.json()
                self.token = data.get("access_token")
                # Expire token 60 seconds early for safety
                self.token_expire = current_time + float(data.get("expires_in", 7200)) - 60
                logger.info("Successfully refreshed KIS API Access Token.")
                return self.token
            else:
                logger.error(f"KIS Token Request failed ({res.status_code}): {res.text}")
        except Exception as e:
            logger.error(f"Exception during token retrieval: {e}")
            
        return None

    def fetch_daily_prices(self, symbol, count=120):
        """Fetches daily prices for a stock. Falls back to mock if keys are missing or API fails."""
        token = self.get_access_token()
        
        if token:
            try:
                # KIS UAPI: 국내주식 기간별시세(일/주/월/년)
                url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
                headers = {
                    "Content-Type": "application/json",
                    "authorization": f"Bearer {token}",
                    "appkey": self.appkey,
                    "appsecret": self.appsecret,
                    "tr_id": "FHKST03010100", # TR for daily chart price
                    "custtype": "P"
                }
                params = {
                    "FID_COND_MRKT_DIV_CODE": "J",
                    "FID_INPUT_ISCD": symbol,
                    "FID_PERIOD_DIV_CODE": "D",
                    "FID_ORG_ADPR_PRC": "0000000000",
                    "FID_INPUT_DATE_1": time.strftime("%Y%m%d", time.localtime(time.time() - count * 24 * 3600)),
                    "FID_INPUT_DATE_2": time.strftime("%Y%m%d"),
                }
                
                res = requests.get(url, headers=headers, params=params, timeout=5)
                if res.status_code == 200:
                    data = res.json()
                    output = data.get("output2", [])
                    if isinstance(output, list) and len(output) > 0:
                        # KIS returns data newest first. Format: close, open, high, low, volume
                        prices = []
                        for day in reversed(output[:count]):
                            prices.append({
                                "date": day.get("stck_bsop_date"),
                                "close": float(day.get("stck_clpr", 0)),
                                "open": float(day.get("stck_oprc", 0)),
                                "high": float(day.get("stck_hgpr", 0)),
                                "low": float(day.get("stck_lwpr", 0)),
                                "volume": int(day.get("acml_vol", 0))
                            })
                        return prices
                logger.warning(f"Failed to fetch daily prices from KIS for {symbol}. Falling back to mock.")
            except Exception as e:
                logger.error(f"Error fetching daily prices for {symbol}: {e}")

        # Fallback to Mock Daily prices
        return self._generate_mock_daily_prices(symbol, count)

    def fetch_intraday_prices(self, symbol, interval='15', count=40):
        """Fetches intraday price bars (15-min or 30-min). Falls back to mock if fails."""
        token = self.get_access_token()
        
        if token:
            try:
                # KIS UAPI: 주식 당일분봉조회
                url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
                headers = {
                    "Content-Type": "application/json",
                    "authorization": f"Bearer {token}",
                    "appkey": self.appkey,
                    "appsecret": self.appsecret,
                    "tr_id": "FHKST03010200",
                    "custtype": "P"
                }
                params = {
                    "FID_COND_MRKT_DIV_CODE": "J",
                    "FID_INPUT_ISCD": symbol,
                    "FID_HOUR_CLS_CODE": f"{interval}M", # e.g. "15M"
                    "FID_PW_DATA_INCU_YN": "N"
                }
                
                res = requests.get(url, headers=headers, params=params, timeout=5)
                if res.status_code == 200:
                    data = res.json()
                    output = data.get("output2", [])
                    if isinstance(output, list) and len(output) > 0:
                        bars = []
                        for bar in reversed(output[:count]):
                            bars.append({
                                "time": bar.get("stck_cntg_hour"),
                                "close": float(bar.get("stck_prpr", 0)),
                                "open": float(bar.get("stck_oprc", 0)),
                                "high": float(bar.get("stck_hgpr", 0)),
                                "low": float(bar.get("stck_lwpr", 0)),
                                "volume": int(bar.get("cntg_vol", 0))
                            })
                        return bars
                logger.warning(f"Failed to fetch intraday bars from KIS for {symbol}. Falling back to mock.")
            except Exception as e:
                logger.error(f"Error fetching intraday bars for {symbol}: {e}")
                
        return self._generate_mock_intraday_prices(symbol, interval, count)

    def fetch_option_chain(self, symbol):
        """Fetches Option board data. Falls back to mock if fails."""
        token = self.get_access_token()
        
        if token:
            try:
                # KIS UAPI: 국내옵션전광판_콜풋
                url = f"{self.base_url}/uapi/domestic-futureoption/v1/quotations/option-board-callput"
                headers = {
                    "Content-Type": "application/json",
                    "authorization": f"Bearer {token}",
                    "appkey": self.appkey,
                    "appsecret": self.appsecret,
                    "tr_id": "FNMN50200100"
                }
                params = {
                    "FID_COND_MRKT_DIV_CODE": "OP",
                    "FID_INPUT_ISCD": symbol
                }
                
                res = requests.get(url, headers=headers, params=params, timeout=5)
                if res.status_code == 200:
                    data = res.json()
                    output = data.get("output")
                    if isinstance(output, list) and len(output) > 0:
                        options = []
                        for item in output:
                            options.append({
                                "strike_price": int(float(item.get("acpr", 0))),
                                "call": {
                                    "premium": float(item.get("call_askp1", 0)),
                                    "open_interest": int(item.get("call_opnl_opst_elc_qty", 0)),
                                    "iv": float(item.get("call_ints_vltl", 0)),
                                    "delta": float(item.get("call_delt", 0))
                                },
                                "put": {
                                    "premium": float(item.get("put_askp1", 0)),
                                    "open_interest": int(item.get("put_opnl_opst_elc_qty", 0)),
                                    "iv": float(item.get("put_ints_vltl", 0)),
                                    "delta": float(item.get("put_delt", 0))
                                }
                            })
                        # Sort by strike
                        options.sort(key=lambda x: x["strike_price"])
                        return {
                            "spot_price": float(data.get("output2", {}).get("hts_acpr", 0)),
                            "options": options
                        }
                logger.warning(f"Failed to fetch option board from KIS for {symbol}. Falling back to mock.")
            except Exception as e:
                logger.error(f"Error fetching option board for {symbol}: {e}")

        # Fallback
        mock_spot = self._get_mock_base_price(symbol)
        mock_chain = self._generate_mock_option_chain(symbol, mock_spot)
        return {
            "spot_price": mock_spot,
            "options": mock_chain
        }

    def fetch_short_selling_data(self, symbol, count=10):
        """Fetches short selling daily statistics. Falls back to mock if fails."""
        token = self.get_access_token()
        
        if token:
            try:
                url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-short-daily"
                headers = {
                    "Content-Type": "application/json",
                    "authorization": f"Bearer {token}",
                    "appkey": self.appkey,
                    "appsecret": self.appsecret,
                    "tr_id": "FHKST03011200",
                    "custtype": "P"
                }
                params = {
                    "FID_COND_MRKT_DIV_CODE": "J",
                    "FID_INPUT_ISCD": symbol,
                }
                
                res = requests.get(url, headers=headers, params=params, timeout=5)
                if res.status_code == 200:
                    data = res.json()
                    output = data.get("output", [])
                    if isinstance(output, list) and len(output) > 0:
                        short_data = []
                        for day in reversed(output[:count]):
                            short_data.append({
                                "date": day.get("stck_bsop_date"),
                                "short_volume": int(day.get("shrt_msell_vol", 0)),
                                "short_ratio": float(day.get("shrt_msell_rto", 0)),
                                "short_balance_shares": int(day.get("ss_vol", 0)) if day.get("ss_vol") else 0
                            })
                        return short_data
                logger.warning(f"Failed to fetch short selling data from KIS for {symbol}. Falling back to mock.")
            except Exception as e:
                logger.error(f"Error fetching short selling data for {symbol}: {e}")
                
        return self._generate_mock_short_selling_data(symbol, count)

    def execute_order(self, symbol, order_type, price, quantity):
        """Executes a trade order (Buy or Sell). In SIMULATION_MODE, mock executes."""
        # Always check credentials for placing live orders
        token = self.get_access_token()
        
        # If we have no credentials, force simulation logging
        is_simulation = not token or bool(os.getenv("SIMULATION_MODE", "True").lower() == "true")
        
        if is_simulation:
            # Simulated transaction log
            logger.info(f"[SIMULATED ORDER] {order_type.upper()} {quantity} shares of {symbol} at {price} KRW.")
            return {
                "status": "success",
                "mode": "simulation",
                "order_no": f"SIM_{int(time.time())}_{random.randint(100, 999)}",
                "code": "0"
            }
            
        # Live/Mock actual execution via KIS API
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-cash"
        tr_id = "VTTC0802U" if KIS_MODE == "MOCK" else "TTTC0802U" # Buy
        if order_type.lower() == "sell":
            tr_id = "VTTC0801U" if KIS_MODE == "MOCK" else "TTTC0801U" # Sell
            
        headers = {
            "Content-Type": "application/json",
            "authorization": f"Bearer {token}",
            "appkey": self.appkey,
            "appsecret": self.appsecret,
            "tr_id": tr_id,
            "custtype": "P"
        }
        payload = {
            "CANO": KIS_CANO,
            "ACNT_PRDT_CD": KIS_ACNT_PRDT_CD,
            "PDNO": symbol,
            "ORD_DVSN": "00", # 00: Limit order, 01: Market order
            "ORD_QTY": str(quantity),
            "ORD_UNPR": str(int(price)) if price > 0 else "0", # 0 if Market order
        }
        
        try:
            res = requests.post(url, json=payload, headers=headers, timeout=5)
            if res.status_code == 200:
                data = res.json()
                if data.get("rt_cd") == "0":
                    logger.info(f"[LIVE ORDER SUCCESS] {order_type.upper()} {quantity} shares of {symbol} at {price} KRW.")
                    return {
                        "status": "success",
                        "mode": "live",
                        "order_no": data.get("output", {}).get("ODNO"),
                        "code": "0"
                    }
                else:
                    logger.error(f"[LIVE ORDER FAIL] Business Error: {data.get('msg1')}")
                    return {"status": "fail", "msg": data.get("msg1"), "code": data.get("rt_cd")}
            else:
                logger.error(f"[LIVE ORDER FAIL] HTTP Error {res.status_code}: {res.text}")
                return {"status": "fail", "msg": "HTTP Error", "code": str(res.status_code)}
        except Exception as e:
            logger.error(f"Exception during order execution: {e}")
            return {"status": "fail", "msg": str(e), "code": "-1"}

    # =====================================================================
    # Mock Data Generators
    # =====================================================================
    def _get_mock_base_price(self, symbol):
        """Generates static/repeatable seed base price based on symbol code."""
        # Generates deterministic price based on symbol digits
        seed = int(symbol) if symbol.isdigit() else 100000
        if seed % 3 == 0:
            return 72500.0 # Samsung Electronics scale
        elif seed % 3 == 1:
            return 185000.0 # SK Hynix scale
        else:
            return 120000.0 # Standard scale

    def _generate_mock_daily_prices(self, symbol, count):
        """Generates mock daily prices with a slight upward trend and normal noise."""
        base_price = self._get_mock_base_price(symbol)
        prices = []
        current_time = time.time()
        
        current_price = base_price * 0.9  # Start slightly lower
        for i in range(count):
            day_offset = count - i
            st_date = time.strftime("%Y%m%d", time.localtime(current_time - day_offset * 24 * 3600))
            
            # Simple random walk with positive drift (to simulate long-term uptrend)
            drift = base_price * 0.0003
            noise = base_price * 0.015 * (random.random() - 0.49)
            current_price += (drift + noise)
            
            # Daily volatility
            day_high = current_price * (1 + 0.02 * random.random())
            day_low = current_price * (1 - 0.02 * random.random())
            day_open = current_price * (1 + 0.005 * (random.random() - 0.5))
            
            # Ensure price bounds
            current_price = max(current_price, 1000.0)
            
            prices.append({
                "date": st_date,
                "close": round(current_price, 1),
                "open": round(day_open, 1),
                "high": round(day_high, 1),
                "low": round(day_low, 1),
                "volume": int(500000 + random.random() * 1000000)
            })
        return prices

    def _generate_mock_intraday_prices(self, symbol, interval, count):
        """Generates mock intraday 15-minute price bars simulating a pullback double bottom."""
        base_price = self._get_mock_base_price(symbol)
        bars = []
        
        # We will generate a sequence that has a double bottom shape
        # Double bottom shape: drop -> bottom 1 -> small bounce -> drop to bottom 2 -> bounce up
        for i in range(count):
            t_str = f"{9 + (i // 25):02d}{(i % 25) * 15 % 60:02d}00"
            
            # Double bottom logic
            # i from 0 to 40
            # Bottom 1 near index 15
            # Small bounce near index 22
            # Bottom 2 near index 28
            # Strong bounce after index 30
            if i < 15:
                # Drop phase
                ratio = 1.0 - (0.03 * (i / 15))
            elif i >= 15 and i < 22:
                # First bottom & small bounce
                ratio = 0.97 + (0.015 * ((i - 15) / 7))
            elif i >= 22 and i < 28:
                # Redrop to bottom 2
                ratio = 0.985 - (0.016 * ((i - 22) / 6))
            else:
                # Second bottom and upward breakout
                ratio = 0.969 + (0.04 * ((i - 28) / (count - 28)))
                
            # Add small random noise
            ratio += 0.002 * (random.random() - 0.5)
            
            bar_close = base_price * ratio
            bar_open = bar_close * (1 + 0.002 * (random.random() - 0.5))
            bar_high = max(bar_close, bar_open) * (1 + 0.003 * random.random())
            bar_low = min(bar_close, bar_open) * (1 - 0.003 * random.random())
            
            bars.append({
                "time": t_str,
                "close": round(bar_close, 1),
                "open": round(bar_open, 1),
                "high": round(bar_high, 1),
                "low": round(bar_low, 1),
                "volume": int(5000 + random.random() * 20000)
            })
        return bars

    def _generate_mock_option_chain(self, symbol, spot_price):
        """Generates mock option chain with Open Interest peaks for Put/Call Walls."""
        seed = int(symbol) if symbol.isdigit() else 100000
        strike_step = 1000 if spot_price < 100000 else 2500
        
        atm_strike = round(spot_price / strike_step) * strike_step
        strikes = [int(atm_strike + i * strike_step) for i in range(-5, 6)]
        
        # Expiry T = 14 days
        T = 14.0 / 365.0
        r = 0.035
        
        # We will deterministically place option walls to simulate consistent levels
        # Put Wall: ATM - 2 steps
        # Call Wall: ATM + 2 steps
        put_wall_strike = atm_strike - 2 * strike_step
        call_wall_strike = atm_strike + 2 * strike_step
        
        options = []
        for K in strikes:
            dist_pct = (K - spot_price) / spot_price
            sigma = 0.22 + 0.3 * (dist_pct ** 2)
            
            # Simple CDF math to mock Black-Scholes delta
            d1 = (math.log(spot_price / K) + (r + (sigma ** 2) / 2.0) * T) / (sigma * math.sqrt(T))
            delta_call = (1.0 + math.erf(d1 / math.sqrt(2.0))) / 2.0
            
            # Volatility smile premiums
            call_price = max(spot_price * delta_call - K * math.exp(-r * T) * delta_call * 0.9, 100.0)
            put_price = max(K * math.exp(-r * T) * (1.0 - delta_call) - spot_price * (1.0 - delta_call) * 0.9, 100.0)
            
            # Open Interest peaks at walls
            call_oi_base = 5000 * math.exp(-((K - call_wall_strike) / (1.5 * strike_step))**2)
            put_oi_base = 6000 * math.exp(-((K - put_wall_strike) / (1.5 * strike_step))**2)
            
            # Add small noise based on symbol/strike
            call_oi = int(call_oi_base + 300 + (hash(str(K) + symbol + "c") % 400))
            put_oi = int(put_oi_base + 350 + (hash(str(K) + symbol + "p") % 450))
            
            options.append({
                "strike_price": K,
                "call": {
                    "premium": round(call_price, 1),
                    "open_interest": call_oi,
                    "iv": round(sigma * 100, 2),
                    "delta": round(delta_call, 3)
                },
                "put": {
                    "premium": round(put_price, 1),
                    "open_interest": put_oi,
                    "iv": round(sigma * 100, 2),
                    "delta": round(delta_call - 1.0, 3)
                }
            })
            
        options.sort(key=lambda x: x["strike_price"])
        return options

    def _generate_mock_short_selling_data(self, symbol, count):
        """Generates realistic mock daily short selling data including balance."""
        base_price = self._get_mock_base_price(symbol)
        seed = int(symbol) if symbol.isdigit() else 100000
        
        short_data = []
        current_time = time.time()
        
        # Deterministically high or low short interest based on symbol seed
        # E.g., if seed % 5 == 0, it has very high accumulated short balance (simulating short squeeze target)
        is_high_si = (seed % 5 == 0)
        base_balance_ratio = 0.045 if is_high_si else 0.012 # 4.5% vs 1.2% of market cap
        
        for i in range(count):
            day_offset = count - i
            st_date = time.strftime("%Y%m%d", time.localtime(current_time - day_offset * 24 * 3600))
            
            # Daily short ratio: normally 2% to 8%, but some days spikes up to 18%
            # If high SI, we have occasional panic daily short spikes
            is_spike_day = (i == count - 2) and not is_high_si
            if is_spike_day:
                short_ratio = 18.5
            else:
                short_ratio = round(2.0 + (hash(str(i) + symbol) % 80) / 10.0, 2)
                
            # Short volume based on typical daily volume
            total_vol = 800000
            short_vol = int(total_vol * (short_ratio / 100.0))
            
            # Short balance shares (mocked out of 100M outstanding shares)
            outstanding_shares = 100000000
            short_balance = int(outstanding_shares * base_balance_ratio * (1.0 + 0.05 * (random.random() - 0.5)))
            
            short_data.append({
                "date": st_date,
                "short_volume": short_vol,
                "short_ratio": short_ratio,
                "short_balance_shares": short_balance
            })
            
        return short_data
