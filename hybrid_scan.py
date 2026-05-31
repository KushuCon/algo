"""
hybrid_scan.py — Positional trade finder with intraday entry timing.
NO trades placed. Signal-only.

HOW IT WORKS (Top-Down):
  STEP 1 — Daily filter (run once at start + refresh every 30 min):
    Check each stock on 1Day bars:
    - Is it in an uptrend? (price > SMA50 > SMA200)
    - Does it have momentum? (price up >3% over last 10 days)
    - Is RSI healthy? (not overbought >75)
    → Only "qualified" stocks move to Step 2

  STEP 2 — 5-min entry scanner (runs every 5 min during market hours):
    For each qualified stock, watch 5-min bars for:
    - Pullback to EMA zone (price dips near EMA8/EMA21)
    - MACD histogram turning positive (momentum resuming)
    - Volume confirmation (1.5x average)
    → ENTRY SIGNAL: buy zone, stop loss, 2-5 day target, full reason

Usage:
    python hybrid_scan.py --symbols NVDA TSLA AMD QCOM MU ARM NOW STX MRVL GE
    python hybrid_scan.py --symbols NVDA TSLA AMD --interval 300

Hold target: 2-5 days (positional swing trade)
Entry method: intraday pullback/breakout on 5-min chart
"""

import argparse
import time
import schedule
from datetime import datetime

import pandas as pd

import config
from broker import AlpacaBroker
from utils.logger import get_logger
from utils.indicators import sma, ema, rsi, macd, atr, momentum
from utils.helpers import now_et

log = get_logger("hybrid_scan")

# ── ANSI colors ───────────────────────────────────────────────────────────────
G  = "\033[92m"   # green
R  = "\033[91m"   # red
Y  = "\033[93m"   # yellow
C  = "\033[96m"   # cyan
B  = "\033[94m"   # blue
BLD= "\033[1m"
DIM= "\033[2m"
X  = "\033[0m"    # reset
LN = "─" * 64


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1 — Daily trend filter
# ══════════════════════════════════════════════════════════════════════════════

def check_daily_trend(symbol: str, bars_1d: pd.DataFrame) -> dict:
    """
    Analyse 1Day bars and return a trend score + qualification status.
    Returns dict with: qualified (bool), trend_summary, reasons, levels
    """
    if bars_1d is None or len(bars_1d) < 55:
        return {"qualified": False, "reason": "Not enough daily data"}

    close  = bars_1d["close"]
    high   = bars_1d["high"]
    low    = bars_1d["low"]
    volume = bars_1d["volume"]

    price   = float(close.iloc[-1])
    sma20v  = float(sma(close, 20).iloc[-1])
    sma50v  = float(sma(close, 50).iloc[-1])
    sma200v = float(sma(close, 200).iloc[-1]) if len(close) >= 200 else None
    rsi14   = float(rsi(close, 14).iloc[-1])
    mom10   = float(momentum(close, 10).iloc[-1])   # 10-day price change %
    atr14   = float(atr(high, low, close, 14).iloc[-1])

    # Volume trend — is avg volume growing?
    vol_20  = float(volume.rolling(20).mean().iloc[-1])
    vol_5   = float(volume.rolling(5).mean().iloc[-1])
    vol_increasing = vol_5 > vol_20 * 1.1

    # Trend score (0-6 points)
    score = 0
    checks = []

    # 1. Price above SMA50
    if price > sma50v:
        score += 2
        checks.append((True,  f"Price ${price:.2f} above SMA50 ${sma50v:.2f}"))
    else:
        checks.append((False, f"Price ${price:.2f} BELOW SMA50 ${sma50v:.2f} — downtrend"))

    # 2. SMA20 above SMA50 (golden alignment)
    if sma20v > sma50v:
        score += 1
        checks.append((True,  f"SMA20 ${sma20v:.2f} > SMA50 (bullish alignment)"))
    else:
        checks.append((False, f"SMA20 ${sma20v:.2f} < SMA50 (bearish alignment)"))

    # 3. Price above SMA200 (long-term trend)
    if sma200v:
        if price > sma200v:
            score += 1
            checks.append((True,  f"Price above SMA200 ${sma200v:.2f} — long-term uptrend"))
        else:
            checks.append((False, f"Price below SMA200 ${sma200v:.2f} — long-term downtrend"))

    # 4. Momentum (10-day)
    if mom10 >= 0.03:
        score += 1
        checks.append((True,  f"10-day momentum +{mom10:.1%} — strong"))
    elif mom10 >= 0:
        checks.append((None,  f"10-day momentum +{mom10:.1%} — weak but positive"))
    else:
        checks.append((False, f"10-day momentum {mom10:.1%} — negative"))

    # 5. RSI not overbought
    if rsi14 <= 72:
        score += 1
        checks.append((True,  f"RSI {rsi14:.1f} — room to run (not overbought)"))
    elif rsi14 <= 80:
        checks.append((None,  f"RSI {rsi14:.1f} — slightly extended, be careful"))
    else:
        checks.append((False, f"RSI {rsi14:.1f} — overbought, avoid chasing"))

    # Qualify: need score >= 3 AND must be above SMA50
    qualified = score >= 3 and price > sma50v

    # Key price levels for the daily chart
    # Support zone: recent swing low (lowest low of last 10 days)
    recent_low  = float(low.iloc[-10:].min())
    recent_high = float(high.iloc[-10:].max())
    support     = round(max(sma50v, recent_low * 0.99), 2)   # SMA50 or recent low
    resistance  = round(recent_high, 2)

    # Daily ATR-based target (3-5 day hold)
    daily_target   = round(price + 3.0 * atr14, 2)   # ~3 ATR above = 3-5 day target
    daily_stop     = round(price - 1.5 * atr14, 2)   # daily stop basis

    return {
        "qualified":      qualified,
        "score":          score,
        "checks":         checks,
        "price":          round(price, 2),
        "sma20":          round(sma20v, 2),
        "sma50":          round(sma50v, 2),
        "sma200":         round(sma200v, 2) if sma200v else None,
        "rsi":            round(rsi14, 1),
        "momentum_10d":   round(mom10, 4),
        "atr_daily":      round(atr14, 2),
        "support":        support,
        "resistance":     resistance,
        "daily_target":   daily_target,
        "daily_stop":     daily_stop,
        "vol_increasing": vol_increasing,
    }


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2 — 5-min intraday entry finder
# ══════════════════════════════════════════════════════════════════════════════

def find_5min_entry(symbol: str, bars_5m: pd.DataFrame, daily: dict) -> dict | None:
    """
    On 5-min bars, look for an intraday pullback entry into a daily-qualified stock.

    Entry patterns:
      A) Pullback to EMA zone — price dipped near EMA8/21, now bouncing back
      B) MACD histogram crossover up — momentum resuming after pause
      C) Both together — highest confidence signal

    Returns signal dict or None if no setup.
    """
    MIN_BARS = 50
    if bars_5m is None or len(bars_5m) < MIN_BARS:
        return None

    close  = bars_5m["close"]
    high   = bars_5m["high"]
    low    = bars_5m["low"]
    volume = bars_5m["volume"]

    price        = float(close.iloc[-1])
    ema8         = ema(close, 8)
    ema21        = ema(close, 21)
    cur_ema8     = float(ema8.iloc[-1])
    cur_ema21    = float(ema21.iloc[-1])
    _, _, hist   = macd(close, 12, 26, 9)
    atr5         = float(atr(high, low, close, 14).iloc[-1])
    avg_vol      = float(volume.rolling(20).mean().iloc[-1])
    cur_vol      = float(volume.iloc[-1])
    vol_ratio    = round(cur_vol / avg_vol, 2) if avg_vol > 0 else 1.0

    # Intraday RSI
    rsi_5m       = float(rsi(close, 14).iloc[-1])

    ribbon_up    = cur_ema8 > cur_ema21
    ribbon_gap   = abs(cur_ema8 - cur_ema21) / price if price > 0 else 0

    # MACD histogram — did it just flip positive?
    hist_crossed_up = (
        len(hist) >= 2
        and float(hist.iloc[-2]) < 0
        and float(hist.iloc[-1]) > 0
    )
    hist_positive = float(hist.iloc[-1]) > 0

    # Pullback check: price touched near EMA zone (within 0.5 ATR) in last 6 bars
    # and is now back above EMA8
    lows_last6   = low.iloc[-6:]
    ema8_last6   = ema8.iloc[-6:]
    touched_ema  = any(
        float(lows_last6.iloc[i]) <= float(ema8_last6.iloc[i]) * 1.003
        for i in range(len(lows_last6))
    )
    back_above   = price > cur_ema8

    # Volume confirmation
    vol_ok       = vol_ratio >= 1.5

    # Time window check (skip first 15 min and last 30 min)
    now          = now_et().time()
    from datetime import time as dtime
    in_window    = dtime(9, 45) <= now <= dtime(15, 30)

    # ── Determine signal type ────────────────────────────────────────────────
    pattern      = None
    confidence   = 0
    entry_reasons = []

    if ribbon_up and hist_crossed_up and vol_ok and in_window:
        pattern    = "MACD_CROSS"
        confidence = 3
        entry_reasons = [
            f"MACD histogram just flipped positive on 5-min — momentum resuming",
            f"EMA8 {cur_ema8:.2f} > EMA21 {cur_ema21:.2f} — ribbon bullish",
            f"Volume {vol_ratio:.1f}× average — confirms the move",
        ]

    elif ribbon_up and touched_ema and back_above and hist_positive and in_window:
        pattern    = "PULLBACK_TO_EMA"
        confidence = 2
        entry_reasons = [
            f"Price pulled back to EMA zone ({cur_ema8:.2f}–{cur_ema21:.2f}) and bounced",
            f"MACD histogram positive — upward momentum intact",
            f"Classic buy-the-dip setup in an uptrending stock",
        ]

    elif ribbon_up and hist_crossed_up and in_window:
        pattern    = "MACD_CROSS_LOW_VOL"
        confidence = 1
        entry_reasons = [
            f"MACD histogram flipped positive — momentum signal",
            f"Volume confirmation weak ({vol_ratio:.1f}× avg) — wait for volume",
            f"EMA ribbon bullish but low confidence entry",
        ]

    if pattern is None:
        return None

    # ── Calculate entry, SL, Target ─────────────────────────────────────────
    # Entry zone: current price to slightly above (don't chase more than 0.3 ATR)
    entry_low  = round(price - 0.3 * atr5, 2)
    entry_high = round(price + 0.3 * atr5, 2)

    # Stop loss: below EMA21 on 5-min (intraday structure break = exit)
    sl_ema     = round(cur_ema21 - 0.5 * atr5, 2)
    sl_pct     = round(price * (1 - config.STOP_LOSS_PCT), 2)
    sl         = round(max(sl_ema, sl_pct), 2)   # tighter of the two

    # Target: use daily ATR target (this is a 2-5 day hold)
    target     = daily["daily_target"]

    risk       = round(price - sl, 2)
    reward     = round(target - price, 2)
    rr         = round(reward / risk, 2) if risk > 0 else 0

    return {
        "symbol":       symbol,
        "pattern":      pattern,
        "confidence":   confidence,
        "price":        round(price, 2),
        "entry_low":    entry_low,
        "entry_high":   entry_high,
        "stop_loss":    sl,
        "target":       target,
        "risk":         risk,
        "reward":       reward,
        "rr":           rr,
        "entry_reasons":entry_reasons,
        "ema8":         round(cur_ema8, 2),
        "ema21":        round(cur_ema21, 2),
        "rsi_5m":       round(rsi_5m, 1),
        "vol_ratio":    vol_ratio,
        "atr_5m":       round(atr5, 2),
        "hold_target":  "2–5 days",
    }


# ══════════════════════════════════════════════════════════════════════════════
# Print functions
# ══════════════════════════════════════════════════════════════════════════════

def print_daily_filter_report(daily_results: dict):
    """Print daily trend filter summary at startup."""
    qualified   = [s for s, d in daily_results.items() if d.get("qualified")]
    disqualified= [s for s, d in daily_results.items() if not d.get("qualified")]

    print(f"\n{'═'*64}")
    print(f"  {BLD}DAILY TREND FILTER — {datetime.now().strftime('%Y-%m-%d %H:%M')}{X}")
    print(f"{'═'*64}")
    print(f"  {G}{BLD}{len(qualified)} stocks qualified{X} for intraday entry scanning")
    print(f"  {DIM}{len(disqualified)} stocks filtered out{X}\n")

    for sym, d in daily_results.items():
        if not d.get("qualified") and "checks" not in d:
            print(f"  {R}✗ {sym:6s}{X}  {d.get('reason','')}")
            continue

        icon  = f"{G}✓{X}" if d["qualified"] else f"{R}✗{X}"
        score = d.get("score", 0)
        bars  = "▓" * score + "░" * (6 - score)
        print(f"  {icon} {BLD}{sym:6s}{X}  score {bars}  "
              f"RSI {d['rsi']:4.1f}  "
              f"mom {d['momentum_10d']:+.1%}  "
              f"${d['price']}")

    print()
    if qualified:
        print(f"  {C}Watching: {', '.join(qualified)}{X}")
        print(f"  {DIM}Scanning these every 5 min for intraday entry...{X}")
    else:
        print(f"  {Y}No stocks qualified today. Market may be weak or all stocks overbought.{X}")
    print(f"{'═'*64}\n")


def print_entry_signal(sig: dict, daily: dict):
    """Print a full intraday entry signal."""
    sym  = sig["symbol"]
    conf = sig["confidence"]
    conf_str = {3: f"{G}HIGH{X}", 2: f"{Y}MEDIUM{X}", 1: f"{DIM}LOW{X}"}[conf]
    pat  = sig["pattern"].replace("_", " ")
    ts   = now_et().strftime("%H:%M:%S ET")

    print(f"\n{LN}")
    print(f"  {BLD}{G}▲ ENTRY SIGNAL{X}  {BLD}{sym}{X}  "
          f"{DIM}@ {ts}{X}  confidence: {conf_str}")
    print(f"  {DIM}Pattern: {pat}  |  Hold: {sig['hold_target']}{X}")
    print(LN)

    # Daily context
    print(f"  {BLD}{C}── Daily Trend (why this stock){X}")
    for ok, txt in daily["checks"]:
        icon = f"{G}✓{X}" if ok is True else (f"{Y}~{X}" if ok is None else f"{R}✗{X}")
        print(f"  {icon} {txt}")
    print()

    # Entry details
    print(f"  {BLD}── Intraday Entry Setup (5-min chart){X}")
    for r in sig["entry_reasons"]:
        print(f"  {C}→{X} {r}")
    print()

    # Price levels box
    print(f"  {BLD}── Price Levels ────────────────────────────────────{X}")
    print(f"  Current price   : {BLD}${sig['price']}{X}")
    print(f"  {G}Buy zone        : ${sig['entry_low']} – ${sig['entry_high']}{X}"
          f"  ← enter here on next 5-min bar")
    print(f"  {G}Target (2-5d)   : ${sig['target']}{X}"
          f"  (+{sig['reward']:.2f} pts / +{sig['reward']/sig['price']*100:.1f}%)")
    print(f"  {R}Stop loss       : ${sig['stop_loss']}{X}"
          f"  (-{sig['risk']:.2f} pts / -{sig['risk']/sig['price']*100:.1f}%)")
    print(f"  Risk : Reward    : 1 : {sig['rr']}")
    print()

    # Technical snapshot
    print(f"  {BLD}── 5-Min Technicals ────────────────────────────────{X}")
    print(f"  EMA8 / EMA21    : ${sig['ema8']} / ${sig['ema21']}"
          f"  {'✓ bullish ribbon' if sig['ema8'] > sig['ema21'] else '✗ bearish ribbon'}")
    rsi_note = "healthy" if 40 < sig["rsi_5m"] < 65 else ("overbought — careful" if sig["rsi_5m"] >= 65 else "oversold — bounce zone")
    rsi_col  = G if sig["rsi_5m"] < 65 else R
    print(f"  RSI (5-min)     : {rsi_col}{sig['rsi_5m']}{X}  {rsi_note}")
    print(f"  Volume ratio    : {sig['vol_ratio']}× average")
    print(f"  ATR (5-min)     : ${sig['atr_5m']}  (expected move per 5-min bar)")
    print()

    # Daily levels for reference
    print(f"  {BLD}── Daily Chart Levels (for reference){X}")
    print(f"  Daily support   : ${daily['support']}   (SMA50 / recent low)")
    print(f"  Daily resistance: ${daily['resistance']}   (10-day high)")
    print(f"  Daily SMA50     : ${daily['sma50']}")
    if daily["sma200"]:
        print(f"  Daily SMA200    : ${daily['sma200']}")
    print(LN)


def print_no_setup(sym: str, reason: str):
    print(f"  {DIM}  {sym:6s}  no setup — {reason}{X}")


# ══════════════════════════════════════════════════════════════════════════════
# Main scan loop
# ══════════════════════════════════════════════════════════════════════════════

_daily_cache: dict = {}        # symbol → daily trend dict
_last_daily_refresh = [None]   # mutable for closure


def refresh_daily_filter(broker: AlpacaBroker, symbols: list):
    """Fetch 1Day bars and run daily trend filter. Cache results."""
    global _daily_cache
    log.info("Refreshing daily trend filter...")
    for sym in symbols:
        bars = broker.get_bars(sym, timeframe="1Day", limit=220)
        _daily_cache[sym] = check_daily_trend(sym, bars)
    _last_daily_refresh[0] = datetime.now()
    print_daily_filter_report(_daily_cache)


def run_5min_scan(broker: AlpacaBroker, symbols: list):
    """Fetch 5-min bars for qualified stocks and look for entry signals."""
    if not broker.is_market_open():
        nxt = broker.next_market_open()
        print(f"  {DIM}[{now_et().strftime('%H:%M:%S')}] Market closed. "
              f"Next open: {nxt}{X}")
        return

    # Refresh daily filter every 30 min during trading
    last = _last_daily_refresh[0]
    if last is None or (datetime.now() - last).seconds > 1800:
        refresh_daily_filter(broker, symbols)

    qualified = [s for s in symbols if _daily_cache.get(s, {}).get("qualified")]

    if not qualified:
        print(f"  {DIM}[{now_et().strftime('%H:%M:%S')}] No qualified stocks — skipping 5-min scan{X}")
        return

    ts = now_et().strftime("%H:%M:%S")
    print(f"\n{DIM}  [{ts}] 5-min scan → {', '.join(qualified)}{X}")

    signals_found = 0
    for sym in qualified:
        bars_5m = broker.get_bars(sym, timeframe="5Min", limit=200)
        sig = find_5min_entry(sym, bars_5m, _daily_cache[sym])

        if sig:
            print_entry_signal(sig, _daily_cache[sym])
            signals_found += 1
        else:
            # Minimal "no setup" line so you know it was scanned
            daily = _daily_cache.get(sym, {})
            reason = f"RSI {daily.get('rsi','?')}  mom {daily.get('momentum_10d',0):+.1%}  waiting for 5-min trigger"
            print_no_setup(sym, reason)

    if signals_found == 0:
        print(f"  {DIM}  No entry setups yet. Waiting...{X}")
    else:
        print(f"\n  {G}{BLD}{signals_found} signal(s) found{X} — no orders placed, indication only\n")


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def parse_args():
    p = argparse.ArgumentParser(
        description="Hybrid scanner: daily trend filter + 5-min intraday entry"
    )
    p.add_argument("--symbols", nargs="+", default=config.SYMBOLS,
                   help="Stocks to watch (5–15 recommended)")
    p.add_argument("--interval", type=int, default=300,
                   help="5-min scan interval in seconds (default 300 = 5 min)")
    return p.parse_args()


def main():
    args = parse_args()

    print(f"\n{BLD}{'='*64}{X}")
    print(f"  {BLD}HYBRID POSITIONAL SCANNER{X}  {DIM}(signals only — no trades){X}")
    print(f"  Stocks   : {', '.join(args.symbols)}")
    print(f"  Scanning : every {args.interval}s during market hours")
    print(f"  Strategy : Daily trend filter → 5-min intraday entry")
    print(f"  Hold     : 2–5 days (positional swing)")
    print(f"  SL/TP    : -{config.STOP_LOSS_PCT*100:.0f}% stop / "
          f"+{config.TAKE_PROFIT_PCT*100:.0f}% base target")
    print(f"{'='*64}\n")

    broker = AlpacaBroker()

    # Load daily filter immediately (even if market closed — uses historical bars)
    refresh_daily_filter(broker, args.symbols)

    # Then start 5-min scan loop
    run_5min_scan(broker, args.symbols)

    schedule.every(args.interval).seconds.do(run_5min_scan, broker, args.symbols)
    # Refresh daily filter every 30 min
    schedule.every(30).minutes.do(refresh_daily_filter, broker, args.symbols)

    print(f"{DIM}  Scanning every {args.interval}s. Press Ctrl+C to stop.{X}\n")
    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        print(f"\n{DIM}  Scanner stopped.{X}\n")


if __name__ == "__main__":
    main()