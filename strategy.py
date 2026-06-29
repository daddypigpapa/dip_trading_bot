import logging

logger = logging.getLogger("Strategy")

def calculate_ma(prices, period):
    """Calculates Simple Moving Average (SMA) for the given period."""
    if len(prices) < period:
        return None
    closes = [p["close"] for p in prices[-period:]]
    return sum(closes) / period

def check_ma_alignment(prices, period=120):
    """
    Checks if:
    1. Current price is above the MA.
    2. The MA is upward-sloping (last MA > MA from 5 days ago).
    """
    if len(prices) < period + 5:
        return False, None, None
        
    current_ma = calculate_ma(prices, period)
    prev_ma = calculate_ma(prices[:-5], period)
    current_close = prices[-1]["close"]
    
    if current_ma is None or prev_ma is None:
        return False, None, None
        
    ma_slope = current_ma - prev_ma
    is_aligned = (current_close > current_ma) and (ma_slope > 0)
    return is_aligned, current_ma, ma_slope

def calculate_fibonacci_levels(prices, lookback=60):
    """
    Calculates Fibonacci Retracement Levels based on the high/low of a recent swing.
    Returns a dict of levels: 0.382, 0.500, 0.618.
    """
    if len(prices) < lookback:
        lookback = len(prices)
        
    recent_prices = prices[-lookback:]
    high = max(p["high"] for p in recent_prices)
    low = min(p["low"] for p in recent_prices)
    diff = high - low
    
    return {
        "high": high,
        "low": low,
        "fib_382": high - (diff * 0.382),
        "fib_500": high - (diff * 0.500),
        "fib_618": high - (diff * 0.618)
    }

def detect_double_bottom(intraday_bars, tolerance=0.006):
    """
    Detects a double bottom pattern on 15-minute bars.
    Conditions:
    - Finds a local low (Bottom 1).
    - Finds a local high (Neckline) after Bottom 1.
    - Finds a second local low (Bottom 2) close in price to Bottom 1.
    - Recent price must be rising from Bottom 2, ideally breaking or heading toward the neckline.
    """
    if len(intraday_bars) < 25:
        return False, None, None
        
    lows = [b["low"] for b in intraday_bars]
    closes = [b["close"] for b in intraday_bars]
    
    # 1. Simple local minima scanner
    # A local minimum has lower low than 3 bars before and after
    local_minima = []
    for i in range(4, len(lows) - 4):
        val = lows[i]
        if val == min(lows[i-3:i+4]):
            local_minima.append((i, val))
            
    if len(local_minima) < 2:
        return False, None, None
        
    # Check pairs of local minima for double bottom characteristics
    # We look at the last two local minima
    b1_idx, b1_val = local_minima[-2]
    b2_idx, b2_val = local_minima[-1]
    
    # Bottoms must be separated by some distance (at least 6 bars, i.e., 1.5 hours)
    if b2_idx - b1_idx < 6:
        return False, None, None
        
    # Bottom prices must be close to each other (within tolerance)
    price_diff_pct = abs(b1_val - b2_val) / max(b1_val, b2_val)
    if price_diff_pct > tolerance:
        return False, None, None
        
    # Find the neckline (highest peak between Bottom 1 and Bottom 2)
    neckline_idx = b1_idx + lows[b1_idx:b2_idx].index(min(lows[b1_idx:b2_idx])) # placeholder index scan
    # Actually, scan for maximum high between the two bottoms
    between_highs = [b["high"] for b in intraday_bars[b1_idx:b2_idx]]
    if not between_highs:
        return False, None, None
    neckline_val = max(between_highs)
    
    # Current close price must be higher than the second bottom and heading up
    current_close = closes[-1]
    if current_close > b2_val and current_close >= b2_val * 1.003:
        # Pattern is valid: price bounced off second bottom
        return True, min(b1_val, b2_val), neckline_val
        
    return False, None, None

def extract_option_walls(option_chain):
    """
    Finds the Call Wall (highest Call Open Interest strike) 
    and Put Wall (highest Put Open Interest strike).
    """
    options = option_chain.get("options", [])
    if not options:
        return None, None
        
    max_call_oi = -1
    call_wall = None
    max_put_oi = -1
    put_wall = None
    
    for opt in options:
        c_oi = opt["call"]["open_interest"]
        p_oi = opt["put"]["open_interest"]
        strike = opt["strike_price"]
        
        if c_oi > max_call_oi:
            max_call_oi = c_oi
            call_wall = strike
            
        if p_oi > max_put_oi:
            max_put_oi = p_oi
            put_wall = strike
            
    return call_wall, put_wall

def evaluate_strategy_c_buy(symbol, daily_prices, intraday_bars, option_chain):
    """
    Evaluates Strategy C BUY signals:
    1. Daily 120 MA trend is UP and price is above MA.
    2. Daily price pulled back to Fibonacci retracement levels (38.2%, 50%, 61.8%).
    3. Intraday 15-min chart shows a Double Bottom pattern.
    4. Options Put Wall is nearby below the price, providing a margin of safety (floor).
    """
    current_price = daily_prices[-1]["close"]
    
    # 1. Check MA alignment
    ma_aligned, ma_val, ma_slope = check_ma_alignment(daily_prices, 120)
    if not ma_aligned:
        return False, "MA_NOT_ALIGNED"
        
    # 2. Check Fibonacci Retracement Levels
    fibs = calculate_fibonacci_levels(daily_prices, 60)
    # Check if price is within 1.5% of any key Fibonacci level
    near_fib = False
    matched_level = None
    
    for name in ["fib_382", "fib_500", "fib_618"]:
        level_val = fibs[name]
        dist_pct = abs(current_price - level_val) / level_val
        if dist_pct <= 0.015: # 1.5% closeness
            near_fib = True
            matched_level = name
            break
            
    if not near_fib:
        return False, "NOT_NEAR_FIB_LEVEL"
        
    # 3. Check Option Put Wall (Support Floor)
    call_wall, put_wall = extract_option_walls(option_chain)
    if not put_wall:
        return False, "NO_OPTION_DATA"
        
    # Put wall must be BELOW current price, and close enough (within 3%) to act as a floor
    # If Put Wall is higher than current price, the floor is broken!
    if put_wall > current_price:
        return False, "PUT_WALL_BROKEN"
        
    dist_to_put_wall = (current_price - put_wall) / current_price
    if dist_to_put_wall > 0.035: # Too far from the Put Wall (not protected)
        return False, "TOO_FAR_FROM_PUT_WALL"
        
    # 4. Detect Intraday Double Bottom
    double_bottom_detected, bottom_val, neckline_val = detect_double_bottom(intraday_bars)
    if not double_bottom_detected:
        return False, "NO_DOUBLE_BOTTOM"
        
    # All conditions met!
    return True, {
        "reason": "Strategy C buy criteria met",
        "spot_price": current_price,
        "ma_120": round(ma_val, 1),
        "fib_level": matched_level,
        "fib_value": round(fibs[matched_level], 1),
        "put_wall": put_wall,
        "call_wall": call_wall,
        "double_bottom_low": bottom_val,
        "neckline": neckline_val
    }

def evaluate_strategy_c_sell(symbol, current_price, entry_price, option_chain):
    """
    Evaluates Strategy C SELL/Exit signals:
    1. Take Profit: Price reaches the Option Call Wall (within 1%) OR hits targeted Fib extension.
    2. Stop Loss: Price closes below the Option Put Wall (support broken).
    """
    call_wall, put_wall = extract_option_walls(option_chain)
    if not call_wall or not put_wall:
        # Fallback to standard risk-reward exit
        if current_price >= entry_price * 1.05:
            return True, "STANDARD_TAKE_PROFIT"
        if current_price <= entry_price * 0.96:
            return True, "STANDARD_STOP_LOSS"
        return False, "HOLD"
        
    # 1. Stop Loss: Close below Put Wall by 1%
    if current_price < put_wall * 0.99:
        return True, f"STOP_LOSS_PUT_WALL_BREACHED (Put Wall: {put_wall})"
        
    # 2. Take Profit: Reaches Call Wall (within 1%) or above it
    if current_price >= call_wall * 0.99:
        return True, f"TAKE_PROFIT_CALL_WALL_REACHED (Call Wall: {call_wall})"
        
    # 3. Trailing Stop Loss if price drops below 4% of entry
    if current_price <= entry_price * 0.96:
        return True, "STOP_LOSS_FIXED_4_PERCENT"
        
    return False, "HOLD"
