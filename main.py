import sys
import os
import json
import logging
from config import KIS_MODE, SIMULATION_MODE
from kis_client import KISClient
from trader import Trader, PORTFOLIO_FILE, TRADE_LOG_FILE

# Set logging level for console output
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s [%(name)s]: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("Main")

def print_banner():
    banner = """
========================================================================
     KOSPI 50 OPTION-FILTERED PULLBACK TRADING SYSTEM (STRATEGY C)
========================================================================
    """
    print(banner)
    logger.info(f"System Mode: KIS_MODE={KIS_MODE} | SIMULATION_MODE={SIMULATION_MODE}")
    logger.info(f"Configured Stock Count: 50 Tickers")

def print_summary():
    """Prints a neat terminal summary of the portfolio and trade logs."""
    print("\n" + "="*72)
    print("                      TRADING RUN SUMMARY")
    print("="*72)
    
    # Read Portfolio
    if os.path.exists(PORTFOLIO_FILE):
        try:
            with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
                port = json.load(f)
            cash = port.get("cash", 0)
            holdings = port.get("holdings", {})
            
            print(f"  * Current Cash: {cash:,.1f} KRW")
            print(f"  * Active Positions ({len(holdings)}):")
            for sym, pos in holdings.items():
                print(f"    - [{sym}] {pos['name']}: {pos['qty']} shares @ {pos['entry_price']:,} KRW (Put Wall: {pos.get('put_wall')}, Call Wall: {pos.get('call_wall')})")
        except Exception as e:
            print(f"  * Error reading portfolio: {e}")
    else:
        print("  * No portfolio file found yet.")
        
    # Read Trade Log
    if os.path.exists(TRADE_LOG_FILE):
        try:
            with open(TRADE_LOG_FILE, "r", encoding="utf-8") as f:
                logs = json.load(f)
            print(f"  * Total Historical Trades Logged: {len(logs)}")
            if logs:
                print("  * Recent Transactions (Last 3):")
                for log in logs[-3:]:
                    pnl_str = f" | PnL: {log['profit_pct']}%" if "profit_pct" in log else ""
                    print(f"    - {log['timestamp']} | {log['action']} | {log['symbol']} ({log['name']}) | Price: {log['price']:,} KRW | Qty: {log['quantity']}{pnl_str} ({log['reason']})")
        except Exception as e:
            print(f"  * Error reading trade log: {e}")
    else:
        print("  * No trades logged yet.")
    print("="*72 + "\n")

def main():
    print_banner()
    
    # Initialize components
    client = KISClient()
    trader = Trader(client)
    
    # Execute scan loop
    try:
        trader.scan_and_trade()
    except KeyboardInterrupt:
        logger.info("Bot execution cancelled by user.")
    except Exception as e:
        logger.error(f"Critical error during execution: {e}", exc_info=True)
        
    # Output final summary
    print_summary()
    logger.info("Bot execution finished.")

if __name__ == "__main__":
    main()
