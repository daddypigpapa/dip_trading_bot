import os
import json
import time
import math
import logging
from config import KOSPI_50_TICKERS, PUT_WALL_DISTANCE_LIMIT
from kis_client import KISClient
from strategy import check_ma_alignment, calculate_fibonacci_levels, extract_option_walls

logger = logging.getLogger("Backtester")
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')

BACKTEST_RESULTS_FILE = "backtest_results.json"

class Backtester:
    def __init__(self, client, initial_capital=50000000.0, fee_rate=0.002):
        self.client = client
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.fee_rate = fee_rate # 0.2% commission + tax
        self.holdings = {} # symbol -> {"qty": Q, "entry_price": P, "entry_day_idx": idx, "put_wall": PW, "call_wall": CW}
        self.trades = []
        self.equity_curve = []

    def run_backtest(self, simulation_days=60):
        """
        Runs the backtest simulation over the last N days.
        If KIS API key is active, it fetches actual historical daily charts and current option walls.
        If KIS API key is missing, it falls back to mock 1-year historical data.
        """
        logger.info("Initializing Backtester...")
        
        # Check if we can use live KIS API data
        token = self.client.get_access_token()
        is_live_data = token is not None
        
        if is_live_data:
            logger.info("Live KIS API Key detected. Fetching actual historical data for top 50 stocks...")
        else:
            logger.warning("No KIS API key detected or auth failed. Running backtest on simulated historical data.")
            
        # 1. Gather historical data for all 50 stocks
        historical_database = {}
        
        for symbol, name in KOSPI_50_TICKERS.items():
            logger.info(f"Loading data for {name} ({symbol})...")
            
            # Fetch daily prices
            # We need 120 (for MA) + simulation_days
            required_days = 120 + simulation_days
            daily_prices = self.client.fetch_daily_prices(symbol, required_days)
            
            # Fetch option chain (to get Put/Call walls)
            option_chain = self.client.fetch_option_chain(symbol)
            call_wall, put_wall = extract_option_walls(option_chain)
            
            if not daily_prices or not put_wall or not call_wall:
                logger.warning(f"Skipping {symbol} due to insufficient data.")
                continue
                
            historical_database[symbol] = {
                "name": name,
                "daily_prices": daily_prices,
                "put_wall": put_wall,
                "call_wall": call_wall
            }
            
        if not historical_database:
            logger.error("No valid historical data loaded. Backtest aborted.")
            return
            
        # Find the actual number of simulation steps we can perform
        # Typically the length of daily prices minus 120 (MA lookback)
        min_available_days = min(len(data["daily_prices"]) for data in historical_database.values())
        steps = min_available_days - 120
        
        if steps <= 0:
            logger.error("Insufficient historical price length for MA 120 calculation. Backtest aborted.")
            return
            
        logger.info(f"Starting historical simulation loop over {steps} trading days...")
        
        # 2. Historical Simulation Loop (Day by Day)
        # i represents the current day index in the simulation window (from index 120 to min_available_days)
        for i in range(120, min_available_days):
            current_date = historical_database[list(historical_database.keys())[0]]["daily_prices"][i]["date"]
            
            # A. Process exits (SELL signals)
            symbols_to_sell = []
            for symbol, pos in self.holdings.items():
                stock_data = historical_database[symbol]
                day_price = stock_data["daily_prices"][i]
                current_price = day_price["close"]
                
                # Check option wall breach
                # Stop Loss: Close below Put Wall (or 4% trailing stop)
                # Take Profit: Close reaches Call Wall (or standard 5% target)
                should_sell = False
                sell_reason = ""
                
                if current_price < pos["put_wall"] * 0.99:
                    should_sell = True
                    sell_reason = "STOP_LOSS_PUT_WALL_BREACHED"
                elif current_price >= pos["call_wall"] * 0.99:
                    should_sell = True
                    sell_reason = "TAKE_PROFIT_CALL_WALL_REACHED"
                elif current_price <= pos["entry_price"] * 0.96:
                    should_sell = True
                    sell_reason = "STOP_LOSS_FIXED_4_PERCENT"
                elif i - pos["entry_day_idx"] >= 10:
                    # Time stop: held for more than 10 trading days (approx 2 weeks)
                    should_sell = True
                    sell_reason = "TIME_STOP_10_DAYS"
                    
                if should_sell:
                    qty = pos["qty"]
                    revenue = qty * current_price
                    trading_fee = revenue * self.fee_rate
                    net_revenue = revenue - trading_fee
                    
                    self.cash += net_revenue
                    profit_loss = net_revenue - (qty * pos["entry_price"])
                    profit_pct = (profit_loss / (qty * pos["entry_price"])) * 100
                    
                    self.trades.append({
                        "date": current_date,
                        "symbol": symbol,
                        "name": stock_data["name"],
                        "action": "SELL",
                        "price": current_price,
                        "quantity": qty,
                        "net_revenue": round(net_revenue, 1),
                        "reason": sell_reason,
                        "profit_loss": round(profit_loss, 1),
                        "profit_pct": round(profit_pct, 2)
                    })
                    symbols_to_sell.append(symbol)
                    
            for sym in symbols_to_sell:
                del self.holdings[sym]
                
            # B. Process entries (BUY signals)
            # Max 5 positions
            MAX_HOLDINGS = 5
            trade_allocation = 7500000.0 # 7.5M KRW per trade
            
            if len(self.holdings) < MAX_HOLDINGS and self.cash >= trade_allocation:
                for symbol, stock_data in historical_database.items():
                    if symbol in self.holdings:
                        continue
                        
                    if self.cash < trade_allocation:
                        break
                        
                    # Slice daily prices up to current day 'i'
                    prices_slice = stock_data["daily_prices"][:i+1]
                    current_price = prices_slice[-1]["close"]
                    
                    # 1. Check MA alignment (120 MA trend is UP and price is above MA)
                    ma_aligned, ma_val, ma_slope = check_ma_alignment(prices_slice, 120)
                    if not ma_aligned:
                        continue
                        
                    # 2. Check Fibonacci Retracement Levels
                    fibs = calculate_fibonacci_levels(prices_slice, 60)
                    near_fib = False
                    matched_level = None
                    for name in ["fib_382", "fib_500", "fib_618"]:
                        level_val = fibs[name]
                        dist_pct = abs(current_price - level_val) / level_val
                        if dist_pct <= 0.015:
                            near_fib = True
                            matched_level = name
                            break
                            
                    if not near_fib:
                        continue
                        
                    # 3. Check Option Put Wall Floor
                    put_wall = stock_data["put_wall"]
                    call_wall = stock_data["call_wall"]
                    
                    # Floor check: Put Wall must be below current price and within 3% range
                    if put_wall > current_price:
                        continue
                        
                    dist_to_put_wall = (current_price - put_wall) / current_price
                    if dist_to_put_wall > 0.035:
                        continue
                        
                    # 4. Intraday Double Bottom Simulation (Approximated for historical days)
                    # Since historical intraday bars are not available in UAPI,
                    # we simulate that a double bottom was successfully formed and triggered
                    # if the daily candle low touched near the Fib level and closed in the upper half.
                    day_candle = prices_slice[-1]
                    bounced_from_low = (day_close := day_candle["close"]) > (day_low := day_candle["low"])
                    upper_half_close = (day_close - day_low) >= (day_candle["high"] - day_low) * 0.4
                    
                    if not bounced_from_low or not upper_half_close:
                        continue
                        
                    # Buy execution
                    qty = int(trade_allocation // current_price)
                    if qty == 0:
                        continue
                        
                    actual_cost = qty * current_price
                    trading_fee = actual_cost * 0.0015
                    total_cost = actual_cost + trading_fee
                    
                    if self.cash >= total_cost:
                        self.cash -= total_cost
                        self.holdings[symbol] = {
                            "qty": qty,
                            "entry_price": current_price,
                            "entry_day_idx": i,
                            "put_wall": put_wall,
                            "call_wall": call_wall
                        }
                        
                        self.trades.append({
                            "date": current_date,
                            "symbol": symbol,
                            "name": stock_data["name"],
                            "action": "BUY",
                            "price": current_price,
                            "quantity": qty,
                            "amount": round(actual_cost, 1),
                            "reason": f"Strategy C buy triggered at {matched_level}",
                            "ma_120": round(ma_val, 1),
                            "fib_level": matched_level,
                            "put_wall": put_wall,
                            "call_wall": call_wall
                        })
                        
                        if len(self.holdings) >= MAX_HOLDINGS:
                            break
                            
            # C. Track Daily Equity Value
            holdings_value = 0.0
            for symbol, pos in self.holdings.items():
                current_price = historical_database[symbol]["daily_prices"][i]["close"]
                holdings_value += pos["qty"] * current_price
                
            total_equity = self.cash + holdings_value
            self.equity_curve.append({
                "date": current_date,
                "equity": total_equity,
                "cash": self.cash,
                "holdings_val": holdings_value
            })
            
        # 3. Calculate Performance Metrics
        self.calculate_metrics(is_live_data, steps)

    def calculate_metrics(self, is_live_data, steps):
        """Calculates portfolio metrics and writes to json."""
        if not self.equity_curve:
            logger.error("No equity curve to evaluate.")
            return
            
        final_equity = self.equity_curve[-1]["equity"]
        total_return_pct = ((final_equity - self.initial_capital) / self.initial_capital) * 100
        
        # Calculate CAGR (Assuming 252 trading days = 1 year)
        years = steps / 252.0
        if years > 0:
            cagr = ((final_equity / self.initial_capital) ** (1.0 / years) - 1.0) * 100
        else:
            cagr = total_return_pct
            
        # Calculate Drawdown and Max Drawdown (MDD)
        peak = self.initial_capital
        max_dd = 0.0
        for eq in self.equity_curve:
            val = eq["equity"]
            if val > peak:
                peak = val
            dd = (peak - val) / peak
            if dd > max_dd:
                max_dd = dd
                
        max_dd_pct = max_dd * 100
        
        # Win Rate calculation
        completed_trades = []
        # Match BUY/SELL to get completed trade PnL
        buys = {}
        for t in self.trades:
            sym = t["symbol"]
            if t["action"] == "BUY":
                buys[sym] = t
            elif t["action"] == "SELL" and sym in buys:
                buy_trade = buys[sym]
                profit_loss = t["profit_loss"]
                profit_pct = t["profit_pct"]
                completed_trades.append({
                    "symbol": sym,
                    "name": t["name"],
                    "buy_date": buy_trade["date"],
                    "sell_date": t["date"],
                    "buy_price": buy_trade["price"],
                    "sell_price": t["price"],
                    "profit_loss": profit_loss,
                    "profit_pct": profit_pct,
                    "reason": t["reason"]
                })
                
        wins = [t for t in completed_trades if t["profit_loss"] > 0]
        win_rate = (len(wins) / len(completed_trades) * 100) if completed_trades else 0.0
        
        results = {
            "metadata": {
                "backtest_date": time.strftime("%Y-%m-%d %H:%M:%S"),
                "is_live_data": is_live_data,
                "initial_capital": self.initial_capital,
                "final_equity": round(final_equity, 1),
                "total_return_pct": round(total_return_pct, 2),
                "cagr_pct": round(cagr, 2),
                "max_drawdown_pct": round(max_dd_pct, 2),
                "total_trades_count": len(self.trades),
                "completed_trades_count": len(completed_trades),
                "win_rate_pct": round(win_rate, 2)
            },
            "completed_trades": completed_trades,
            "equity_curve": self.equity_curve
        }
        
        # Save to JSON
        try:
            with open(BACKTEST_RESULTS_FILE, "w", encoding="utf-8") as f:
                json.dump(results, f, indent=4, ensure_ascii=False)
            logger.info("Successfully updated backtest_results.json")
        except Exception as e:
            logger.error(f"Error saving backtest_results.json: {e}")
            
        self.print_terminal_report(results)

    def print_terminal_report(self, results):
        """Prints a clean ASCII performance report."""
        meta = results["metadata"]
        print("\n" + "="*72)
        print("                 STRATEGY C BACKTEST PERFORMANCE REPORT")
        print("="*72)
        print(f"  * Backtest Period: {len(self.equity_curve)} trading days")
        print(f"  * Data Source: {'Live KIS UAPI Data' if meta['is_live_data'] else 'Simulated Historical Database'}")
        print(f"  * Initial Capital: {meta['initial_capital']:,.0f} KRW")
        print(f"  * Final Portfolio Equity: {meta['final_equity']:,.0f} KRW")
        print(f"  * Total Cumulative Return: {meta['total_return_pct']}%")
        print(f"  * CAGR (Annualized Return): {meta['cagr_pct']}%")
        print(f"  * Maximum Drawdown (MDD): {meta['max_drawdown_pct']}%")
        print(f"  * Win Rate: {meta['win_rate_pct']}% ({meta['completed_trades_count']} completed trades)")
        
        print("\n  * Completed Trade History:")
        for t in results["completed_trades"]:
            pnl_color = "\033[92m" if t['profit_loss'] > 0 else "\033[91m"
            reset_color = "\033[0m"
            print(f"    - [{t['symbol']}] {t['name']}: {t['buy_date']} ~ {t['sell_date']} | Buy: {t['buy_price']:,} -> Sell: {t['sell_price']:,} | PnL: {pnl_color}{t['profit_pct']}%{reset_color} ({t['reason']})")
        print("="*72 + "\n")

if __name__ == "__main__":
    client = KISClient()
    backtester = Backtester(client)
    # Default 60 simulation days
    backtester.run_backtest(60)
