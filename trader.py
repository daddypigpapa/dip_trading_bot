import os
import json
import time
import logging
from config import KOSPI_50_TICKERS, SIMULATION_MODE
from strategy import evaluate_strategy_c_buy, evaluate_strategy_c_sell, extract_option_walls

logger = logging.getLogger("Trader")

PORTFOLIO_FILE = "portfolio.json"
TRADE_LOG_FILE = "trade_log.json"

class Trader:
    def __init__(self, client):
        self.client = client
        self.portfolio = self.load_portfolio()
        
    def load_portfolio(self):
        """Loads portfolio state from file, or creates new if missing."""
        if os.path.exists(PORTFOLIO_FILE):
            try:
                with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading portfolio.json: {e}")
                
        # Initialize default portfolio with 50,000,000 KRW
        default_portfolio = {
            "cash": 50000000.0,
            "holdings": {},  # Format: "symbol": {"qty": N, "entry_price": P, "entry_date": D}
            "last_updated": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        self.save_portfolio(default_portfolio)
        return default_portfolio

    def save_portfolio(self, portfolio):
        """Saves portfolio state to file."""
        try:
            portfolio["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
            with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
                json.dump(portfolio, f, indent=4, ensure_ascii=False)
            logger.info("Successfully updated portfolio.json")
        except Exception as e:
            logger.error(f"Error saving portfolio.json: {e}")

    def append_trade_log(self, log_entry):
        """Appends a new trade transaction to trade_log.json."""
        trade_logs = []
        if os.path.exists(TRADE_LOG_FILE):
            try:
                with open(TRADE_LOG_FILE, "r", encoding="utf-8") as f:
                    trade_logs = json.load(f)
            except Exception:
                # If file exists but is corrupted, overwrite with empty list
                pass
                
        trade_logs.append(log_entry)
        
        try:
            with open(TRADE_LOG_FILE, "w", encoding="utf-8") as f:
                json.dump(trade_logs, f, indent=4, ensure_ascii=False)
            logger.info(f"Trade successfully logged to trade_log.json: {log_entry['action']} {log_entry['symbol']}")
        except Exception as e:
            logger.error(f"Error writing to trade_log.json: {e}")

    def scan_and_trade(self):
        """Scans all 50 target tickers and executes buy/sell signals."""
        logger.info("Starting scan for top 50 KOSPI 200 stocks...")
        
        # Load fresh copy of portfolio
        portfolio = self.load_portfolio()
        holdings = portfolio["holdings"]
        cash = portfolio["cash"]
        
        # 1. Process existing holdings (Check SELL signals)
        logger.info(f"Checking sell signals for {len(holdings)} held positions...")
        symbols_to_sell = []
        
        for symbol, position in list(holdings.items()):
            name = KOSPI_50_TICKERS.get(symbol, f"종목 {symbol}")
            logger.info(f"Evaluating {name} ({symbol}) for sell signals...")
            
            # Fetch current stock price and option chain
            daily_prices = self.client.fetch_daily_prices(symbol, 5)
            if not daily_prices:
                logger.warning(f"Could not retrieve daily price for {symbol}. Skipping.")
                continue
                
            current_price = daily_prices[-1]["close"]
            option_chain = self.client.fetch_option_chain(symbol)
            
            should_sell, reason = evaluate_strategy_c_sell(
                symbol, 
                current_price, 
                position["entry_price"], 
                option_chain
            )
            
            if should_sell:
                # Sell execution
                qty = position["qty"]
                res = self.client.execute_order(symbol, "sell", current_price, qty)
                
                if res.get("status") == "success":
                    revenue = qty * current_price
                    # Deduct trading cost (0.2% tax & commissions)
                    trading_cost = revenue * 0.002
                    net_revenue = revenue - trading_cost
                    
                    cash += net_revenue
                    profit_loss = net_revenue - (qty * position["entry_price"])
                    profit_pct = (profit_loss / (qty * position["entry_price"])) * 100
                    
                    # Log the trade
                    log_entry = {
                        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "symbol": symbol,
                        "name": name,
                        "action": "SELL",
                        "price": current_price,
                        "quantity": qty,
                        "amount": round(revenue, 1),
                        "trading_cost": round(trading_cost, 1),
                        "net_revenue": round(net_revenue, 1),
                        "reason": reason,
                        "profit_loss": round(profit_loss, 1),
                        "profit_pct": round(profit_pct, 2)
                    }
                    self.append_trade_log(log_entry)
                    
                    # Remove from holdings list
                    symbols_to_sell.append(symbol)
                    logger.info(f"Sold {name} ({symbol}). Profit/Loss: {profit_pct:.2f}%")
                    
        # Update holdings dictionary
        for sym in symbols_to_sell:
            del holdings[sym]
            
        portfolio["cash"] = cash
        self.save_portfolio(portfolio)

        # 2. Process new entries (Check BUY signals)
        # Limit the maximum number of holdings (e.g. max 5 stocks) to manage risk
        MAX_HOLDINGS = 5
        active_holdings_count = len(holdings)
        
        if active_holdings_count >= MAX_HOLDINGS:
            logger.info(f"Active holdings ({active_holdings_count}) reached MAX_HOLDINGS ({MAX_HOLDINGS}). Skipping buy scan.")
            return

        # Calculate base allocation size per trade (7,500,000 KRW, or 12,000,000 KRW for STRONG_BUY)
        base_allocation = 7500000.0
        
        logger.info("Scanning for buy signals with short-selling filter...")
        for symbol, name in KOSPI_50_TICKERS.items():
            if symbol in holdings:
                continue # Already holding this stock
                
            if cash < base_allocation:
                logger.warning(f"Insufficient cash ({cash:.1f} KRW) to allocate minimum {base_allocation:.1f} KRW. Stopping buy scan.")
                break
                
            logger.info(f"Scanning {name} ({symbol})...")
            
            # Fetch required data
            daily_prices = self.client.fetch_daily_prices(symbol, 130) # 130 to cover 120-day MA
            intraday_bars = self.client.fetch_intraday_prices(symbol, '15', 40)
            option_chain = self.client.fetch_option_chain(symbol)
            short_selling_data = self.client.fetch_short_selling_data(symbol, 10)
            
            if not daily_prices or not intraday_bars or not option_chain or not short_selling_data:
                logger.warning(f"Missing data for {symbol}. Skipping.")
                continue
                
            should_buy, details = evaluate_strategy_c_buy(symbol, daily_prices, intraday_bars, option_chain, short_selling_data)
            
            if should_buy:
                current_price = daily_prices[-1]["close"]
                
                # Dynamic allocation based on signal strength
                strength = details.get("signal_strength", "NORMAL_BUY")
                trade_allocation = 12000000.0 if strength == "STRONG_BUY" else 7500000.0
                
                # If cash is insufficient for STRONG_BUY, scale down to remaining cash or standard base
                if cash < trade_allocation:
                    trade_allocation = cash
                
                # Calculate quantity to purchase
                qty = int(trade_allocation // current_price)
                if qty == 0:
                    continue
                    
                actual_cost = qty * current_price
                # Add trading cost (approx 0.15% fee)
                trading_fee = actual_cost * 0.0015
                total_deduction = actual_cost + trading_fee
                
                if cash >= total_deduction:
                    # Place order
                    res = self.client.execute_order(symbol, "buy", current_price, qty)
                    
                    if res.get("status") == "success":
                        cash -= total_deduction
                        
                        # Add to holdings
                        holdings[symbol] = {
                            "name": name,
                            "qty": qty,
                            "entry_price": current_price,
                            "entry_date": time.strftime("%Y%m%d"),
                            "put_wall": details["put_wall"],
                            "call_wall": details["call_wall"],
                            "signal_strength": strength
                        }
                        
                        # Log the trade
                        log_entry = {
                            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "symbol": symbol,
                            "name": name,
                            "action": "BUY",
                            "price": current_price,
                            "quantity": qty,
                            "amount": round(actual_cost, 1),
                            "trading_cost": round(trading_fee, 1),
                            "reason": details["reason"],
                            "signal_strength": strength,
                            "ma_120": details["ma_120"],
                            "fib_level": details["fib_level"],
                            "put_wall": details["put_wall"],
                            "call_wall": details["call_wall"],
                            "avg_short_ratio_3d": details["avg_short_ratio_3d"],
                            "short_balance_pct": details["short_balance_pct"]
                        }
                        self.append_trade_log(log_entry)
                        
                        logger.info(f"Bought {name} ({symbol}) - Qty: {qty}, Price: {current_price} KRW")
                        
                        # Update portfolio cash and holdings
                        portfolio["cash"] = cash
                        portfolio["holdings"] = holdings
                        self.save_portfolio(portfolio)
                        
                        active_holdings_count += 1
                        if active_holdings_count >= MAX_HOLDINGS:
                            logger.info("Maximum holdings count reached during scan. Ending buy loop.")
                            break
                            
            # Sleep slightly to respect API rate limits (e.g. 200ms)
            time.sleep(0.2)
            
        logger.info("Scan completed.")
