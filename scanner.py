# # """
# # hybrid_scan.py — Positional trade finder with intraday entry timing.
# # NO trades placed. Signal-only.

# # HOW IT WORKS (Top-Down):
# #   STEP 1 — Daily filter (run once at start + refresh every 30 min):
# #     Check each stock on 1Day bars:
# #     - Is it in an uptrend? (price > SMA50 > SMA200)
# #     - Does it have momentum? (price up >3% over last 10 days)
# #     - Is RSI healthy? (not overbought >75)
# #     → Only "qualified" stocks move to Step 2

# #   STEP 2 — 5-min entry scanner (runs every 5 min during market hours):
# #     For each qualified stock, watch 5-min bars for:
# #     - Pullback to EMA zone (price dips near EMA8/EMA21)
# #     - MACD histogram turning positive (momentum resuming)
# #     - Volume confirmation (1.5x average)
# #     → ENTRY SIGNAL: buy zone, stop loss, 2-5 day target, full reason

# # Usage:
# #     python hybrid_scan.py --symbols NVDA TSLA AMD QCOM MU ARM NOW STX MRVL GE
# #     python hybrid_scan.py --symbols NVDA TSLA AMD --interval 300

# # Hold target: 2-5 days (positional swing trade)
# # Entry method: intraday pullback/breakout on 5-min chart
# # """

# # import argparse
# # import time
# # import schedule
# # from datetime import datetime

# # import pandas as pd

# # import config
# # from broker import AlpacaBroker
# # from utils.logger import get_logger
# # from utils.indicators import sma, ema, rsi, macd, atr, momentum
# # from utils.helpers import now_et

# # log = get_logger("hybrid_scan")

# # # ── ANSI colors ───────────────────────────────────────────────────────────────
# # G  = "\033[92m"   # green
# # R  = "\033[91m"   # red
# # Y  = "\033[93m"   # yellow
# # C  = "\033[96m"   # cyan
# # B  = "\033[94m"   # blue
# # BLD= "\033[1m"
# # DIM= "\033[2m"
# # X  = "\033[0m"    # reset
# # LN = "─" * 64


# # # ══════════════════════════════════════════════════════════════════════════════
# # # STEP 1 — Daily trend filter
# # # ══════════════════════════════════════════════════════════════════════════════

# # def check_daily_trend(symbol: str, bars_1d: pd.DataFrame) -> dict:
# #     """
# #     Analyse 1Day bars and return a trend score + qualification status.
# #     Returns dict with: qualified (bool), trend_summary, reasons, levels
# #     """
# #     if bars_1d is None or len(bars_1d) < 55:
# #         return {"qualified": False, "reason": "Not enough daily data"}

# #     close  = bars_1d["close"]
# #     high   = bars_1d["high"]
# #     low    = bars_1d["low"]
# #     volume = bars_1d["volume"]

# #     price   = float(close.iloc[-1])
# #     sma20v  = float(sma(close, 20).iloc[-1])
# #     sma50v  = float(sma(close, 50).iloc[-1])
# #     sma200v = float(sma(close, 200).iloc[-1]) if len(close) >= 200 else None
# #     rsi14   = float(rsi(close, 14).iloc[-1])
# #     mom10   = float(momentum(close, 10).iloc[-1])   # 10-day price change %
# #     atr14   = float(atr(high, low, close, 14).iloc[-1])

# #     # Volume trend — is avg volume growing?
# #     vol_20  = float(volume.rolling(20).mean().iloc[-1])
# #     vol_5   = float(volume.rolling(5).mean().iloc[-1])
# #     vol_increasing = vol_5 > vol_20 * 1.1

# #     # Trend score (0-6 points)
# #     score = 0
# #     checks = []

# #     # 1. Price above SMA50
# #     if price > sma50v:
# #         score += 2
# #         checks.append((True,  f"Price ${price:.2f} above SMA50 ${sma50v:.2f}"))
# #     else:
# #         checks.append((False, f"Price ${price:.2f} BELOW SMA50 ${sma50v:.2f} — downtrend"))

# #     # 2. SMA20 above SMA50 (golden alignment)
# #     if sma20v > sma50v:
# #         score += 1
# #         checks.append((True,  f"SMA20 ${sma20v:.2f} > SMA50 (bullish alignment)"))
# #     else:
# #         checks.append((False, f"SMA20 ${sma20v:.2f} < SMA50 (bearish alignment)"))

# #     # 3. Price above SMA200 (long-term trend)
# #     if sma200v:
# #         if price > sma200v:
# #             score += 1
# #             checks.append((True,  f"Price above SMA200 ${sma200v:.2f} — long-term uptrend"))
# #         else:
# #             checks.append((False, f"Price below SMA200 ${sma200v:.2f} — long-term downtrend"))

# #     # 4. Momentum (10-day)
# #     if mom10 >= 0.03:
# #         score += 1
# #         checks.append((True,  f"10-day momentum +{mom10:.1%} — strong"))
# #     elif mom10 >= 0:
# #         checks.append((None,  f"10-day momentum +{mom10:.1%} — weak but positive"))
# #     else:
# #         checks.append((False, f"10-day momentum {mom10:.1%} — negative"))

# #     # 5. RSI not overbought
# #     if rsi14 <= 72:
# #         score += 1
# #         checks.append((True,  f"RSI {rsi14:.1f} — room to run (not overbought)"))
# #     elif rsi14 <= 80:
# #         checks.append((None,  f"RSI {rsi14:.1f} — slightly extended, be careful"))
# #     else:
# #         checks.append((False, f"RSI {rsi14:.1f} — overbought, avoid chasing"))

# #     # Qualify: need score >= 3 AND must be above SMA50
# #     qualified = score >= 3 and price > sma50v

# #     # Key price levels for the daily chart
# #     # Support zone: recent swing low (lowest low of last 10 days)
# #     recent_low  = float(low.iloc[-10:].min())
# #     recent_high = float(high.iloc[-10:].max())
# #     support     = round(max(sma50v, recent_low * 0.99), 2)   # SMA50 or recent low
# #     resistance  = round(recent_high, 2)

# #     # Daily ATR-based target (3-5 day hold)
# #     daily_target   = round(price + 3.0 * atr14, 2)   # ~3 ATR above = 3-5 day target
# #     daily_stop     = round(price - 1.5 * atr14, 2)   # daily stop basis

# #     return {
# #         "qualified":      qualified,
# #         "score":          score,
# #         "checks":         checks,
# #         "price":          round(price, 2),
# #         "sma20":          round(sma20v, 2),
# #         "sma50":          round(sma50v, 2),
# #         "sma200":         round(sma200v, 2) if sma200v else None,
# #         "rsi":            round(rsi14, 1),
# #         "momentum_10d":   round(mom10, 4),
# #         "atr_daily":      round(atr14, 2),
# #         "support":        support,
# #         "resistance":     resistance,
# #         "daily_target":   daily_target,
# #         "daily_stop":     daily_stop,
# #         "vol_increasing": vol_increasing,
# #     }


# # # ══════════════════════════════════════════════════════════════════════════════
# # # STEP 2 — 5-min intraday entry finder
# # # ══════════════════════════════════════════════════════════════════════════════

# # def find_5min_entry(symbol: str, bars_5m: pd.DataFrame, daily: dict) -> dict | None:
# #     """
# #     On 5-min bars, look for an intraday pullback entry into a daily-qualified stock.

# #     Entry patterns:
# #       A) Pullback to EMA zone — price dipped near EMA8/21, now bouncing back
# #       B) MACD histogram crossover up — momentum resuming after pause
# #       C) Both together — highest confidence signal

# #     Returns signal dict or None if no setup.
# #     """
# #     MIN_BARS = 50
# #     if bars_5m is None or len(bars_5m) < MIN_BARS:
# #         return None

# #     close  = bars_5m["close"]
# #     high   = bars_5m["high"]
# #     low    = bars_5m["low"]
# #     volume = bars_5m["volume"]

# #     price        = float(close.iloc[-1])
# #     ema8         = ema(close, 8)
# #     ema21        = ema(close, 21)
# #     cur_ema8     = float(ema8.iloc[-1])
# #     cur_ema21    = float(ema21.iloc[-1])
# #     _, _, hist   = macd(close, 12, 26, 9)
# #     atr5         = float(atr(high, low, close, 14).iloc[-1])
# #     avg_vol      = float(volume.rolling(20).mean().iloc[-1])
# #     cur_vol      = float(volume.iloc[-1])
# #     vol_ratio    = round(cur_vol / avg_vol, 2) if avg_vol > 0 else 1.0

# #     # Intraday RSI
# #     rsi_5m       = float(rsi(close, 14).iloc[-1])

# #     ribbon_up    = cur_ema8 > cur_ema21
# #     ribbon_gap   = abs(cur_ema8 - cur_ema21) / price if price > 0 else 0

# #     # MACD histogram — did it just flip positive?
# #     hist_crossed_up = (
# #         len(hist) >= 2
# #         and float(hist.iloc[-2]) < 0
# #         and float(hist.iloc[-1]) > 0
# #     )
# #     hist_positive = float(hist.iloc[-1]) > 0

# #     # Pullback check: price touched near EMA zone (within 0.5 ATR) in last 6 bars
# #     # and is now back above EMA8
# #     lows_last6   = low.iloc[-6:]
# #     ema8_last6   = ema8.iloc[-6:]
# #     touched_ema  = any(
# #         float(lows_last6.iloc[i]) <= float(ema8_last6.iloc[i]) * 1.003
# #         for i in range(len(lows_last6))
# #     )
# #     back_above   = price > cur_ema8

# #     # Volume confirmation
# #     vol_ok       = vol_ratio >= 1.5

# #     # Time window check (skip first 15 min and last 30 min)
# #     now          = now_et().time()
# #     from datetime import time as dtime
# #     in_window    = dtime(9, 45) <= now <= dtime(15, 30)

# #     # ── Determine signal type ────────────────────────────────────────────────
# #     pattern      = None
# #     confidence   = 0
# #     entry_reasons = []

# #     if ribbon_up and hist_crossed_up and vol_ok and in_window:
# #         pattern    = "MACD_CROSS"
# #         confidence = 3
# #         entry_reasons = [
# #             f"MACD histogram just flipped positive on 5-min — momentum resuming",
# #             f"EMA8 {cur_ema8:.2f} > EMA21 {cur_ema21:.2f} — ribbon bullish",
# #             f"Volume {vol_ratio:.1f}× average — confirms the move",
# #         ]

# #     elif ribbon_up and touched_ema and back_above and hist_positive and in_window:
# #         pattern    = "PULLBACK_TO_EMA"
# #         confidence = 2
# #         entry_reasons = [
# #             f"Price pulled back to EMA zone ({cur_ema8:.2f}–{cur_ema21:.2f}) and bounced",
# #             f"MACD histogram positive — upward momentum intact",
# #             f"Classic buy-the-dip setup in an uptrending stock",
# #         ]

# #     elif ribbon_up and hist_crossed_up and in_window:
# #         pattern    = "MACD_CROSS_LOW_VOL"
# #         confidence = 1
# #         entry_reasons = [
# #             f"MACD histogram flipped positive — momentum signal",
# #             f"Volume confirmation weak ({vol_ratio:.1f}× avg) — wait for volume",
# #             f"EMA ribbon bullish but low confidence entry",
# #         ]

# #     if pattern is None:
# #         return None

# #     # ── Calculate entry, SL, Target ─────────────────────────────────────────
# #     # Entry zone: current price to slightly above (don't chase more than 0.3 ATR)
# #     entry_low  = round(price - 0.3 * atr5, 2)
# #     entry_high = round(price + 0.3 * atr5, 2)

# #     # Stop loss: below EMA21 on 5-min (intraday structure break = exit)
# #     sl_ema     = round(cur_ema21 - 0.5 * atr5, 2)
# #     sl_pct     = round(price * (1 - config.STOP_LOSS_PCT), 2)
# #     sl         = round(max(sl_ema, sl_pct), 2)   # tighter of the two

# #     # Target: use daily ATR target (this is a 2-5 day hold)
# #     target     = daily["daily_target"]

# #     risk       = round(price - sl, 2)
# #     reward     = round(target - price, 2)
# #     rr         = round(reward / risk, 2) if risk > 0 else 0

# #     return {
# #         "symbol":       symbol,
# #         "pattern":      pattern,
# #         "confidence":   confidence,
# #         "price":        round(price, 2),
# #         "entry_low":    entry_low,
# #         "entry_high":   entry_high,
# #         "stop_loss":    sl,
# #         "target":       target,
# #         "risk":         risk,
# #         "reward":       reward,
# #         "rr":           rr,
# #         "entry_reasons":entry_reasons,
# #         "ema8":         round(cur_ema8, 2),
# #         "ema21":        round(cur_ema21, 2),
# #         "rsi_5m":       round(rsi_5m, 1),
# #         "vol_ratio":    vol_ratio,
# #         "atr_5m":       round(atr5, 2),
# #         "hold_target":  "2–5 days",
# #     }


# # # ══════════════════════════════════════════════════════════════════════════════
# # # Print functions
# # # ══════════════════════════════════════════════════════════════════════════════

# # def print_daily_filter_report(daily_results: dict):
# #     """Print daily trend filter summary at startup."""
# #     qualified   = [s for s, d in daily_results.items() if d.get("qualified")]
# #     disqualified= [s for s, d in daily_results.items() if not d.get("qualified")]

# #     print(f"\n{'═'*64}")
# #     print(f"  {BLD}DAILY TREND FILTER — {datetime.now().strftime('%Y-%m-%d %H:%M')}{X}")
# #     print(f"{'═'*64}")
# #     print(f"  {G}{BLD}{len(qualified)} stocks qualified{X} for intraday entry scanning")
# #     print(f"  {DIM}{len(disqualified)} stocks filtered out{X}\n")

# #     for sym, d in daily_results.items():
# #         if not d.get("qualified") and "checks" not in d:
# #             print(f"  {R}✗ {sym:6s}{X}  {d.get('reason','')}")
# #             continue

# #         icon  = f"{G}✓{X}" if d["qualified"] else f"{R}✗{X}"
# #         score = d.get("score", 0)
# #         bars  = "▓" * score + "░" * (6 - score)
# #         print(f"  {icon} {BLD}{sym:6s}{X}  score {bars}  "
# #               f"RSI {d['rsi']:4.1f}  "
# #               f"mom {d['momentum_10d']:+.1%}  "
# #               f"${d['price']}")

# #     print()
# #     if qualified:
# #         print(f"  {C}Watching: {', '.join(qualified)}{X}")
# #         print(f"  {DIM}Scanning these every 5 min for intraday entry...{X}")
# #     else:
# #         print(f"  {Y}No stocks qualified today. Market may be weak or all stocks overbought.{X}")
# #     print(f"{'═'*64}\n")


# # def print_entry_signal(sig: dict, daily: dict):
# #     """Print a full intraday entry signal."""
# #     sym  = sig["symbol"]
# #     conf = sig["confidence"]
# #     conf_str = {3: f"{G}HIGH{X}", 2: f"{Y}MEDIUM{X}", 1: f"{DIM}LOW{X}"}[conf]
# #     pat  = sig["pattern"].replace("_", " ")
# #     ts   = now_et().strftime("%H:%M:%S ET")

# #     print(f"\n{LN}")
# #     print(f"  {BLD}{G}▲ ENTRY SIGNAL{X}  {BLD}{sym}{X}  "
# #           f"{DIM}@ {ts}{X}  confidence: {conf_str}")
# #     print(f"  {DIM}Pattern: {pat}  |  Hold: {sig['hold_target']}{X}")
# #     print(LN)

# #     # Daily context
# #     print(f"  {BLD}{C}── Daily Trend (why this stock){X}")
# #     for ok, txt in daily["checks"]:
# #         icon = f"{G}✓{X}" if ok is True else (f"{Y}~{X}" if ok is None else f"{R}✗{X}")
# #         print(f"  {icon} {txt}")
# #     print()

# #     # Entry details
# #     print(f"  {BLD}── Intraday Entry Setup (5-min chart){X}")
# #     for r in sig["entry_reasons"]:
# #         print(f"  {C}→{X} {r}")
# #     print()

# #     # Price levels box
# #     print(f"  {BLD}── Price Levels ────────────────────────────────────{X}")
# #     print(f"  Current price   : {BLD}${sig['price']}{X}")
# #     print(f"  {G}Buy zone        : ${sig['entry_low']} – ${sig['entry_high']}{X}"
# #           f"  ← enter here on next 5-min bar")
# #     print(f"  {G}Target (2-5d)   : ${sig['target']}{X}"
# #           f"  (+{sig['reward']:.2f} pts / +{sig['reward']/sig['price']*100:.1f}%)")
# #     print(f"  {R}Stop loss       : ${sig['stop_loss']}{X}"
# #           f"  (-{sig['risk']:.2f} pts / -{sig['risk']/sig['price']*100:.1f}%)")
# #     print(f"  Risk : Reward    : 1 : {sig['rr']}")
# #     print()

# #     # Technical snapshot
# #     print(f"  {BLD}── 5-Min Technicals ────────────────────────────────{X}")
# #     print(f"  EMA8 / EMA21    : ${sig['ema8']} / ${sig['ema21']}"
# #           f"  {'✓ bullish ribbon' if sig['ema8'] > sig['ema21'] else '✗ bearish ribbon'}")
# #     rsi_note = "healthy" if 40 < sig["rsi_5m"] < 65 else ("overbought — careful" if sig["rsi_5m"] >= 65 else "oversold — bounce zone")
# #     rsi_col  = G if sig["rsi_5m"] < 65 else R
# #     print(f"  RSI (5-min)     : {rsi_col}{sig['rsi_5m']}{X}  {rsi_note}")
# #     print(f"  Volume ratio    : {sig['vol_ratio']}× average")
# #     print(f"  ATR (5-min)     : ${sig['atr_5m']}  (expected move per 5-min bar)")
# #     print()

# #     # Daily levels for reference
# #     print(f"  {BLD}── Daily Chart Levels (for reference){X}")
# #     print(f"  Daily support   : ${daily['support']}   (SMA50 / recent low)")
# #     print(f"  Daily resistance: ${daily['resistance']}   (10-day high)")
# #     print(f"  Daily SMA50     : ${daily['sma50']}")
# #     if daily["sma200"]:
# #         print(f"  Daily SMA200    : ${daily['sma200']}")
# #     print(LN)


# # def print_no_setup(sym: str, reason: str):
# #     print(f"  {DIM}  {sym:6s}  no setup — {reason}{X}")


# # # ══════════════════════════════════════════════════════════════════════════════
# # # Main scan loop
# # # ══════════════════════════════════════════════════════════════════════════════

# # _daily_cache: dict = {}        # symbol → daily trend dict
# # _last_daily_refresh = [None]   # mutable for closure


# # def refresh_daily_filter(broker: AlpacaBroker, symbols: list):
# #     """Fetch 1Day bars and run daily trend filter. Cache results."""
# #     global _daily_cache
# #     log.info("Refreshing daily trend filter...")
# #     for sym in symbols:
# #         bars = broker.get_bars(sym, timeframe="1Day", limit=220)
# #         _daily_cache[sym] = check_daily_trend(sym, bars)
# #     _last_daily_refresh[0] = datetime.now()
# #     print_daily_filter_report(_daily_cache)


# # def run_5min_scan(broker: AlpacaBroker, symbols: list):
# #     """Fetch 5-min bars for qualified stocks and look for entry signals."""
# #     if not broker.is_market_open():
# #         nxt = broker.next_market_open()
# #         print(f"  {DIM}[{now_et().strftime('%H:%M:%S')}] Market closed. "
# #               f"Next open: {nxt}{X}")
# #         return

# #     # Refresh daily filter every 30 min during trading
# #     last = _last_daily_refresh[0]
# #     if last is None or (datetime.now() - last).seconds > 1800:
# #         refresh_daily_filter(broker, symbols)

# #     qualified = [s for s in symbols if _daily_cache.get(s, {}).get("qualified")]

# #     if not qualified:
# #         print(f"  {DIM}[{now_et().strftime('%H:%M:%S')}] No qualified stocks — skipping 5-min scan{X}")
# #         return

# #     ts = now_et().strftime("%H:%M:%S")
# #     print(f"\n{DIM}  [{ts}] 5-min scan → {', '.join(qualified)}{X}")

# #     signals_found = 0
# #     for sym in qualified:
# #         bars_5m = broker.get_bars(sym, timeframe="5Min", limit=200)
# #         sig = find_5min_entry(sym, bars_5m, _daily_cache[sym])

# #         if sig:
# #             print_entry_signal(sig, _daily_cache[sym])
# #             signals_found += 1
# #         else:
# #             # Minimal "no setup" line so you know it was scanned
# #             daily = _daily_cache.get(sym, {})
# #             reason = f"RSI {daily.get('rsi','?')}  mom {daily.get('momentum_10d',0):+.1%}  waiting for 5-min trigger"
# #             print_no_setup(sym, reason)

# #     if signals_found == 0:
# #         print(f"  {DIM}  No entry setups yet. Waiting...{X}")
# #     else:
# #         print(f"\n  {G}{BLD}{signals_found} signal(s) found{X} — no orders placed, indication only\n")


# # # ══════════════════════════════════════════════════════════════════════════════
# # # CLI
# # # ══════════════════════════════════════════════════════════════════════════════

# # def parse_args():
# #     p = argparse.ArgumentParser(
# #         description="Hybrid scanner: daily trend filter + 5-min intraday entry"
# #     )
# #     p.add_argument("--symbols", nargs="+", default=config.SYMBOLS,
# #                    help="Stocks to watch (5–15 recommended)")
# #     p.add_argument("--interval", type=int, default=300,
# #                    help="5-min scan interval in seconds (default 300 = 5 min)")
# #     return p.parse_args()


# # def main():
# #     args = parse_args()

# #     print(f"\n{BLD}{'='*64}{X}")
# #     print(f"  {BLD}HYBRID POSITIONAL SCANNER{X}  {DIM}(signals only — no trades){X}")
# #     print(f"  Stocks   : {', '.join(args.symbols)}")
# #     print(f"  Scanning : every {args.interval}s during market hours")
# #     print(f"  Strategy : Daily trend filter → 5-min intraday entry")
# #     print(f"  Hold     : 2–5 days (positional swing)")
# #     print(f"  SL/TP    : -{config.STOP_LOSS_PCT*100:.0f}% stop / "
# #           f"+{config.TAKE_PROFIT_PCT*100:.0f}% base target")
# #     print(f"{'='*64}\n")

# #     broker = AlpacaBroker()

# #     # Load daily filter immediately (even if market closed — uses historical bars)
# #     refresh_daily_filter(broker, args.symbols)

# #     # Then start 5-min scan loop
# #     run_5min_scan(broker, args.symbols)

# #     schedule.every(args.interval).seconds.do(run_5min_scan, broker, args.symbols)
# #     # Refresh daily filter every 30 min
# #     schedule.every(30).minutes.do(refresh_daily_filter, broker, args.symbols)

# #     print(f"{DIM}  Scanning every {args.interval}s. Press Ctrl+C to stop.{X}\n")
# #     try:
# #         while True:
# #             schedule.run_pending()
# #             time.sleep(1)
# #     except KeyboardInterrupt:
# #         print(f"\n{DIM}  Scanner stopped.{X}\n")


# # if __name__ == "__main__":
# #     main()

"""
hybrid_scan.py — Flexible signal scanner (swing + intraday entry).
NO trades placed. Signal-only.

TOP-DOWN LOGIC:
  STEP 1 — Daily bars (momentum.py exact conditions):
      ✓ 10-day momentum >= 5%          (same as momentum.py THRESHOLD)
      ✓ Price above SMA50 (daily)      (same as momentum.py)
      ✓ Daily volume spike >= 1.5x     (same as momentum.py MOM_VOL_MULT)
      ✓ RSI not overbought (< 72)
      → Stock qualifies for entry watching

  STEP 2 — 5-min bars (intraday entry timing):
      Pattern A: PULLBACK_BOUNCE  → price dipped to EMA zone, now bouncing
      Pattern B: MACD_CROSS       → MACD histogram just flipped positive
      Pattern C: VWAP_RECLAIM     → price reclaimed VWAP after dip
      → Each pattern gets a hold recommendation: "Today" / "1-2d" / "3-5d"

  SIGNAL OUTPUT per stock:
      - Daily momentum conditions (all checks shown)
      - 5-min entry pattern found (or "waiting")
      - Entry zone, stop loss, target
      - Why this trade might work (technicals in plain language)

Usage:
    python hybrid_scan.py --symbols NVDA TSLA AMD QCOM MU ARM NOW STX MRVL GE
    python hybrid_scan.py --symbols NVDA TSLA AMD --interval 300
"""

import argparse
import time
import schedule
from datetime import datetime, time as dtime

import pandas as pd

import config
from broker import AlpacaBroker
from utils.logger import get_logger
from utils.indicators import sma, ema, rsi, macd, atr, momentum, vwap_session
from utils.helpers import now_et

log = get_logger("hybrid_scan")

# ── Momentum.py exact thresholds (keep in sync with momentum.py) ──────────────
MOM_LOOKBACK  = getattr(config, "MOMENTUM_LOOKBACK",  10)
MOM_THRESHOLD = getattr(config, "MOMENTUM_THRESHOLD", 0.05)
MOM_VOL_MULT  = getattr(config, "MOMENTUM_VOL_MULT",  1.5)

# ── ANSI colors ───────────────────────────────────────────────────────────────
G   = "\033[92m"
R   = "\033[91m"
Y   = "\033[93m"
C   = "\033[96m"
BLD = "\033[1m"
DIM = "\033[2m"
X   = "\033[0m"
LN  = "─" * 66


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1 — Daily momentum filter (momentum.py exact logic)
# ══════════════════════════════════════════════════════════════════════════════

def check_daily_momentum(symbol: str, bars_1d: pd.DataFrame) -> dict:
    """
    Run momentum.py conditions on daily bars.
    Returns qualification status + all indicator values.
    """
    if bars_1d is None or len(bars_1d) < 55:
        return {"qualified": False, "reason": "Not enough daily history"}

    close  = bars_1d["close"]
    high   = bars_1d["high"]
    low    = bars_1d["low"]
    volume = bars_1d["volume"]

    price     = float(close.iloc[-1])
    sma50v    = float(sma(close, 50).iloc[-1])
    sma20v    = float(sma(close, 20).iloc[-1])
    sma200v   = float(sma(close, 200).iloc[-1]) if len(close) >= 200 else None
    rsi14     = float(rsi(close, 14).iloc[-1])
    mom_val   = float(momentum(close, MOM_LOOKBACK).iloc[-1])
    atr14     = float(atr(high, low, close, 14).iloc[-1])

    avg_vol   = float(volume.rolling(20).mean().iloc[-1])
    # Use 5-day avg volume instead of last bar — avoids weekend/holiday 0 volume
    last_vol  = float(volume.iloc[-5:].mean())
    vol_ratio = round(last_vol / avg_vol, 2) if avg_vol > 0 else 0

    # ── Exact momentum.py conditions ─────────────────────────────────────────
    above_sma50 = price > sma50v
    mom_ok      = mom_val >= MOM_THRESHOLD
    vol_spike   = vol_ratio >= MOM_VOL_MULT
    rsi_ok      = rsi14 < 72

    checks = [
        (mom_ok,      f"10d momentum {mom_val:+.1%}"
                      f" {'≥' if mom_ok else '<'} threshold {MOM_THRESHOLD:.0%}"),
        (above_sma50, f"Price ${price:.2f} {'above' if above_sma50 else 'BELOW'}"
                      f" SMA50 ${sma50v:.2f}"),
        (vol_spike,   f"Daily volume {vol_ratio:.1f}× avg"
                      f" {'✓ spike' if vol_spike else '(no spike yet)'}"),
        (rsi_ok,      f"RSI {rsi14:.1f}"
                      f" {'— room to run' if rsi_ok else '— OVERBOUGHT, avoid'}"),
    ]

    # Must pass momentum + SMA50 at minimum (same as momentum.py buy condition)
    qualified = mom_ok and above_sma50

    # ── PULLBACK-IN-UPTREND detection ─────────────────────────────────────────
    # Catches: stock was strong → profit booking 5-15% → buyers coming back
    # This fires even when qualified=False (stock below SMA50 after pullback)
    pullback_setup = False
    pullback_info  = {}

    if sma200v and len(close) >= 200:
        above_sma200    = price > sma200v

        # Was there a significant high in last 20 days?
        high_20d        = float(high.iloc[-20:].max())
        pullback_pct    = (high_20d - price) / high_20d   # how far off the high

        # Was it actually up strongly before the dip? (high_20d at least 5% above SMA50)
        was_in_uptrend  = high_20d > sma50v * 1.05

        # Pullback size: 5% to 18% = healthy profit booking
        healthy_pullback = 0.05 <= pullback_pct <= 0.18

        # RSI getting oversold — between 30 and 52 = buyers starting to appear
        rsi_pullback_zone = 30 <= rsi14 <= 52

        # Volume declining during pullback (last 5 days volume < 20-day avg)
        # = sellers losing conviction = profit booking, not panic exit
        vol_5d_avg      = float(volume.iloc[-5:].mean())
        vol_declining   = vol_5d_avg < avg_vol * 0.95

        # SMA50 is still sloping UP (20d ago SMA50 was lower than today's)
        sma50_20d_ago   = float(sma(close, 50).iloc[-21]) if len(close) > 70 else sma50v
        sma50_rising    = sma50v > sma50_20d_ago

        pullback_setup = (
            above_sma200        # long-term trend intact
            and was_in_uptrend  # it was genuinely strong before
            and healthy_pullback# 5-18% off high = profit booking zone
            and rsi_pullback_zone # buyers starting to appear
            and sma50_rising    # underlying trend still up
        )

        pullback_info = {
            "high_20d":        round(high_20d, 2),
            "pullback_pct":    round(pullback_pct, 4),
            "vol_declining":   vol_declining,
            "rsi_in_zone":     rsi_pullback_zone,
            "sma50_rising":    sma50_rising,
            "above_sma200":    above_sma200,
            "was_in_uptrend":  was_in_uptrend,
        }

        if pullback_setup:
            checks.append((True,
                f"PULLBACK SETUP: {pullback_pct:.1%} off 20d-high ${high_20d:.2f} "
                f"| SMA200 intact | RSI {rsi14:.0f} — discount zone"))

    # Qualify either way: normal uptrend OR pullback-in-uptrend
    qualified = qualified or pullback_setup

    # Support / resistance levels
    recent_low  = float(low.iloc[-10:].min())
    recent_high = float(high.iloc[-10:].max())
    daily_atr   = atr14

    return {
        "qualified":      qualified,
        "pullback_setup": pullback_setup,
        "pullback_info":  pullback_info,
        "checks":         checks,
        "price":          round(price, 2),
        "sma20":          round(sma20v, 2),
        "sma50":          round(sma50v, 2),
        "sma200":         round(sma200v, 2) if sma200v else None,
        "rsi":            round(rsi14, 1),
        "momentum":       round(mom_val, 4),
        "vol_ratio":      vol_ratio,
        "vol_spike":      vol_spike,
        "daily_atr":      round(daily_atr, 2),
        "recent_low":     round(recent_low, 2),
        "recent_high":    round(recent_high, 2),
    }


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2 — 5-min intraday entry patterns
# ══════════════════════════════════════════════════════════════════════════════

def find_entry_pattern(symbol: str, bars_5m: pd.DataFrame, daily: dict) -> dict | None:
    """
    Look for intraday entry patterns on 5-min bars.
    Returns signal dict with pattern, confidence, hold recommendation, levels.
    """
    if bars_5m is None or len(bars_5m) < 40:
        return None

    close  = bars_5m["close"]
    high   = bars_5m["high"]
    low    = bars_5m["low"]
    volume = bars_5m["volume"]

    price        = float(close.iloc[-1])
    ema8v        = float(ema(close, 8).iloc[-1])
    ema21v       = float(ema(close, 21).iloc[-1])
    _, _, hist   = macd(close, 12, 26, 9)
    atr5v        = float(atr(high, low, close, 14).iloc[-1])
    avg_vol      = float(volume.rolling(20).mean().iloc[-1])
    vol_ratio    = float(volume.iloc[-1]) / avg_vol if avg_vol > 0 else 1.0
    rsi5v        = float(rsi(close, 14).iloc[-1])

    # VWAP for today's session
    try:
        vwap_vals = vwap_session(high, low, close, volume, bars_5m.index)
        cur_vwap  = float(vwap_vals.iloc[-1])
        prev_vwap = float(vwap_vals.iloc[-2]) if len(vwap_vals) > 1 else cur_vwap
    except Exception:
        cur_vwap = price
        prev_vwap = price

    ribbon_up   = ema8v > ema21v
    hist_now    = float(hist.iloc[-1])
    hist_prev   = float(hist.iloc[-2]) if len(hist) > 1 else 0

    # Time window: skip first 15 min and last 30 min
    now = now_et().time()
    in_window = dtime(9, 45) <= now <= dtime(15, 30)

    # ── Pattern A: PULLBACK BOUNCE ────────────────────────────────────────────
    # Price dipped near EMA8/21 in last 6 bars and is now back above EMA8
    lows_6  = [float(low.iloc[-(i+1)]) for i in range(6)]
    ema8s_6 = [float(ema(close, 8).iloc[-(i+1)]) for i in range(6)]
    touched_ema = any(lows_6[i] <= ema8s_6[i] * 1.004 for i in range(6))
    bounced     = price > ema8v and hist_now > hist_prev  # histogram improving

    # ── Pattern B: MACD CROSS UP ──────────────────────────────────────────────
    macd_crossed_up = hist_prev < 0 and hist_now > 0

    # ── Pattern C: VWAP RECLAIM ───────────────────────────────────────────────
    # Price crossed back above VWAP after being below it
    vwap_reclaimed = prev_vwap > price * 0.999 and price > cur_vwap

    # ── Determine best pattern ────────────────────────────────────────────────
    pattern    = None
    confidence = 0
    reasons    = []
    hold_rec   = "3-5 days"   # default for momentum swing

    if not in_window:
        return None  # outside trading window

    if ribbon_up and macd_crossed_up and vol_ratio >= 1.5:
        pattern    = "MACD_CROSS"
        confidence = 3
        hold_rec   = "1-3 days"
        reasons = [
            f"MACD histogram flipped positive (was {hist_prev:.3f} → now {hist_now:.3f})",
            f"EMA8 {ema8v:.2f} > EMA21 {ema21v:.2f} — 5-min ribbon bullish",
            f"Volume {vol_ratio:.1f}× average — confirms momentum",
            f"Daily momentum {daily['momentum']:+.1%} already strong — swing candidate",
        ]

    elif ribbon_up and touched_ema and bounced and hist_now > 0:
        pattern    = "PULLBACK_BOUNCE"
        confidence = 3
        hold_rec   = "3-5 days"
        reasons = [
            f"Price pulled back to EMA zone ({ema8v:.2f}–{ema21v:.2f}) then bounced",
            f"MACD histogram positive and rising — uptrend resuming",
            f"Classic momentum continuation setup — dip into EMA = low-risk entry",
            f"Daily SMA50 ${daily['sma50']} — big picture uptrend intact",
        ]

    elif ribbon_up and vwap_reclaimed and hist_now > 0:
        pattern    = "VWAP_RECLAIM"
        confidence = 2
        hold_rec   = "Today – 1 day"
        reasons = [
            f"Price reclaimed VWAP ${cur_vwap:.2f} — intraday sentiment flipped bullish",
            f"EMA ribbon bullish on 5-min",
            f"MACD positive — short-term momentum up",
        ]

    elif ribbon_up and macd_crossed_up:
        pattern    = "MACD_CROSS_WEAK"
        confidence = 1
        hold_rec   = "1-2 days"
        reasons = [
            f"MACD histogram crossed up but volume weak ({vol_ratio:.1f}× avg)",
            f"EMA8 > EMA21 ribbon bullish — trend OK",
            f"Low confidence — wait for volume confirmation before entering",
        ]

    if pattern is None:
        return None

    # ── Price levels ──────────────────────────────────────────────────────────
    entry_low  = round(price - 0.3 * atr5v, 2)
    entry_high = round(price + 0.2 * atr5v, 2)
    sl         = round(max(ema21v - atr5v * 0.5,
                           price * (1 - config.STOP_LOSS_PCT)), 2)
    target     = round(daily["recent_high"]
                       if daily["recent_high"] > price
                       else price + 3 * daily["daily_atr"], 2)

    risk   = round(price - sl, 2)
    reward = round(target - price, 2)
    rr     = round(reward / risk, 2) if risk > 0 else 0

    return {
        "symbol":     symbol,
        "pattern":    pattern,
        "confidence": confidence,
        "hold_rec":   hold_rec,
        "price":      round(price, 2),
        "entry_low":  entry_low,
        "entry_high": entry_high,
        "stop_loss":  sl,
        "target":     target,
        "risk":       risk,
        "reward":     reward,
        "rr":         rr,
        "reasons":    reasons,
        "ema8":       round(ema8v, 2),
        "ema21":      round(ema21v, 2),
        "vwap":       round(cur_vwap, 2),
        "rsi_5m":     round(rsi5v, 1),
        "vol_ratio":  round(vol_ratio, 2),
        "atr_5m":     round(atr5v, 2),
        "hist_now":   round(hist_now, 4),
    }


# ══════════════════════════════════════════════════════════════════════════════
# Print helpers
# ══════════════════════════════════════════════════════════════════════════════

def print_daily_report(daily_results: dict):
    qual = [s for s, d in daily_results.items() if d.get("qualified")]
    disq = [s for s, d in daily_results.items() if not d.get("qualified")]
    print(f"\n{'═'*66}")
    print(f"  {BLD}DAILY MOMENTUM FILTER  {datetime.now().strftime('%Y-%m-%d %H:%M')}{X}")
    print(f"  Same conditions as momentum.py: "
          f"mom≥{MOM_THRESHOLD:.0%} + above SMA50 + vol≥{MOM_VOL_MULT}×")
    print(f"{'═'*66}")

    for sym, d in daily_results.items():
        if "checks" not in d:
            print(f"  {R}x {sym:6s}{X}  {d.get('reason','')}")
            continue
        is_pullback = d.get("pullback_setup", False)
        if is_pullback and d["qualified"]:
            icon  = f"{Y}{BLD}PB{X}"
            label = f"{Y}PULLBACK DISCOUNT{X}"
            pb    = d.get("pullback_info", {})
            extra = (f"     {DIM}off high ${pb.get('high_20d','?')} by "
                     f"{pb.get('pullback_pct',0):.1%} | "
                     f"RSI {d['rsi']:.0f} in zone | "
                     f"SMA200 {'intact' if pb.get('above_sma200') else 'broken'}{X}")
        elif d["qualified"]:
            icon  = f"{G}{BLD}OK{X}"
            label = f"{G}QUALIFIED{X}"
            extra = ""
        else:
            icon  = f"{R}--{X}"
            label = f"{DIM}skip{X}"
            extra = ""
        print(f"  {icon} {BLD}{sym:6s}{X}  "
              f"mom {d['momentum']:+.1%}  "
              f"RSI {d['rsi']:4.1f}  "
              f"vol {d['vol_ratio']:.1f}x  "
              f"SMA50 ${d['sma50']}  "
              f"{label}")
        if extra:
            print(extra)

    print()
    if qual:
        print(f"  {C}Watching: {', '.join(qual)}{X}  "
              f"{DIM}({len(qual)}/{len(daily_results)} qualified){X}")
    else:
        print(f"  {Y}No stocks qualified — market may be weak or all overbought.{X}")
    print(f"{'═'*66}\n")


def print_signal(sig: dict, daily: dict):
    sym  = sig["symbol"]
    conf = sig["confidence"]
    ts   = now_et().strftime("%H:%M:%S ET")
    pat  = sig["pattern"].replace("_", " ")

    conf_label = {3: f"{G}{BLD}HIGH ★★★{X}",
                  2: f"{Y}{BLD}MEDIUM ★★{X}",
                  1: f"{DIM}LOW ★{X}"}[conf]

    hold_col = G if "3-5" in sig["hold_rec"] else (Y if "1-3" in sig["hold_rec"] else C)

    print(f"\n{LN}")
    is_pb = daily.get("pullback_setup", False)
    if is_pb:
        print(f"\n{LN}")
        print(f"  {Y}{BLD}↩ PULLBACK DISCOUNT BUY{X}  {BLD}{sym}{X}  {DIM}@ {ts}{X}")
        print(f"  Stock dipped {daily['pullback_info'].get('pullback_pct',0):.1%} off 20d-high -- buyers coming back")
    else:
        print(f"\n{LN}")
        print(f"  {G}{BLD}UP BUY SIGNAL{X}  {BLD}{sym}{X}  {DIM}@ {ts}{X}")
    print(f"  Pattern   : {pat}")
    print(f"  Confidence: {conf_label}   Hold: {hold_col}{BLD}{sig['hold_rec']}{X}")
    print(LN)

    # Daily conditions
    print(f"  {BLD}{C}── Daily Momentum Conditions (momentum.py){X}")
    for ok, txt in daily["checks"]:
        icon = f"{G}✓{X}" if ok else f"{Y}~{X}"
        print(f"  {icon} {txt}")
    print()

    # Why this trade might work
    print(f"  {BLD}── Why this trade might work (5-min){X}")
    for r in sig["reasons"]:
        print(f"  {C}→{X} {r}")
    print()

    # Price levels
    print(f"  {BLD}── Price Levels{X}")
    print(f"  Current price  : {BLD}${sig['price']}{X}")
    print(f"  {G}Buy zone       : ${sig['entry_low']} – ${sig['entry_high']}{X}"
          f"  ← enter on next 5-min bar close")
    print(f"  {G}Target         : ${sig['target']}{X}"
          f"  (+{sig['reward']:.2f} / +{sig['reward']/sig['price']*100:.1f}%)")
    print(f"  {R}Stop loss      : ${sig['stop_loss']}{X}"
          f"  (-{sig['risk']:.2f} / -{sig['risk']/sig['price']*100:.1f}%)")
    print(f"  Risk : Reward  : 1 : {sig['rr']}")
    print()

    # 5-min technicals
    print(f"  {BLD}── 5-Min Chart Snapshot{X}")
    print(f"  EMA 8 / 21     : ${sig['ema8']} / ${sig['ema21']}"
          f"  {'✓ bullish ribbon' if sig['ema8'] > sig['ema21'] else '✗ bearish'}")
    print(f"  VWAP           : ${sig['vwap']}"
          f"  {'✓ price above VWAP' if sig['price'] >= sig['vwap'] else '✗ price below VWAP'}")
    rsi_note = ("healthy" if 40 < sig["rsi_5m"] < 65
                else ("overbought" if sig["rsi_5m"] >= 65 else "oversold"))
    rsi_c = G if sig["rsi_5m"] < 65 else R
    print(f"  RSI (5-min)    : {rsi_c}{sig['rsi_5m']}{X}  {rsi_note}")
    print(f"  Volume ratio   : {sig['vol_ratio']:.1f}× average")
    print(f"  MACD histogram : {sig['hist_now']:+.4f}"
          f"  {'✓ positive' if sig['hist_now'] > 0 else '✗ negative'}")
    print()

    # Daily reference
    print(f"  {BLD}── Daily Reference Levels{X}")
    print(f"  SMA 50         : ${daily['sma50']}"
          f"  {'✓ above' if daily['price'] > daily['sma50'] else '✗ below'}")
    if daily["sma200"]:
        print(f"  SMA 200        : ${daily['sma200']}"
              f"  {'✓ long-term uptrend' if daily['price'] > daily['sma200'] else '✗ below 200'}")
    print(f"  10-day support : ${daily['recent_low']}  "
          f"resistance: ${daily['recent_high']}")
    print(f"  Daily ATR      : ${daily['daily_atr']}  "
          f"({daily['daily_atr']/daily['price']*100:.1f}% expected daily move)")
    print(LN)


# ══════════════════════════════════════════════════════════════════════════════
# Scan loop
# ══════════════════════════════════════════════════════════════════════════════

_daily_cache: dict = {}
_last_refresh = [None]


def refresh_daily(broker, symbols: list):
    """Load 1Day bars and run momentum.py filter. Cache results."""
    log.info("Refreshing daily momentum filter...")
    all_bars = broker.get_bars_multi(symbols, timeframe="1Day", limit=220)
    for sym in symbols:
        _daily_cache[sym] = check_daily_momentum(sym, all_bars.get(sym))
    _last_refresh[0] = datetime.now()
    print_daily_report(_daily_cache)


def run_scan(broker, symbols: list):
    """Main 5-min scan — fetch bars for qualified stocks, find entry patterns."""
    if not broker.is_market_open():
        nxt = broker.next_market_open()
        print(f"  {DIM}[{now_et().strftime('%H:%M:%S')}] "
              f"Market closed. Next open: {nxt}{X}")
        return

    # Refresh daily filter every 30 min
    last = _last_refresh[0]
    if last is None or (datetime.now() - last).seconds > 1800:
        refresh_daily(broker, symbols)

    qualified = [s for s in symbols if _daily_cache.get(s, {}).get("qualified")]
    if not qualified:
        print(f"  {DIM}[{now_et().strftime('%H:%M:%S')}] "
              f"No qualified stocks right now.{X}")
        return

    ts = now_et().strftime("%H:%M:%S")
    print(f"\n  {DIM}[{ts}] 5-min scan → {', '.join(qualified)}{X}")

    # Batch fetch 5-min bars — retry once with 10s wait if rate limited
    bars_batch = broker.get_bars_multi(qualified, timeframe="5Min", limit=200)
    # If all empty (rate limit), wait and retry once
    if all(v.empty for v in bars_batch.values() if hasattr(v, 'empty')):
        print(f"  {Y}Rate limit hit — retrying in 12s...{X}")
        time.sleep(12)
        bars_batch = broker.get_bars_multi(qualified, timeframe="5Min", limit=200)

    found = 0
    for sym in qualified:
        sig = find_entry_pattern(sym, bars_batch.get(sym), _daily_cache[sym])
        if sig:
            print_signal(sig, _daily_cache[sym])
            found += 1
        else:
            d = _daily_cache.get(sym, {})
            print(f"  {DIM}  {sym:6s}  no 5-min setup yet  "
                  f"(mom {d.get('momentum',0):+.1%}  "
                  f"RSI {d.get('rsi','?')}){X}")

    if found == 0:
        print(f"  {DIM}  Waiting for 5-min pattern... "
              f"(daily conditions met, watching){X}")
    else:
        print(f"\n  {G}{BLD}{found} signal(s){X} — indication only, no trades placed\n")


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def parse_args():
    p = argparse.ArgumentParser(description="Hybrid momentum scanner")
    p.add_argument("--symbols", nargs="+", default=config.SYMBOLS)
    p.add_argument("--interval", type=int, default=300,
                   help="Scan interval seconds (default 300 = 5 min)")
    return p.parse_args()


def main():
    args = parse_args()
    print(f"\n{BLD}{'='*66}{X}")
    print(f"  {BLD}HYBRID MOMENTUM SCANNER{X}  {DIM}(signal only — no trades){X}")
    print(f"  Stocks   : {', '.join(args.symbols)}")
    print(f"  Interval : every {args.interval}s")
    print(f"  Data     : {getattr(config,'DATA_PROVIDER','alpaca').upper()}")
    print(f"  Daily    : momentum≥{MOM_THRESHOLD:.0%} + SMA50 + vol≥{MOM_VOL_MULT}×")
    print(f"  Intraday : EMA8/21 ribbon + MACD cross + VWAP")
    print(f"{'='*66}\n")

    broker = AlpacaBroker()
    refresh_daily(broker, args.symbols)
    print(f"  {DIM}Waiting 15s before first 5-min scan (rate limit protection)...{X}")
    time.sleep(15)
    run_scan(broker, args.symbols)

    schedule.every(args.interval).seconds.do(run_scan, broker, args.symbols)
    schedule.every(30).minutes.do(refresh_daily, broker, args.symbols)

    print(f"{DIM}  Scanning every {args.interval}s. Ctrl+C to stop.{X}\n")
    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        print(f"\n{DIM}  Scanner stopped.{X}\n")


if __name__ == "__main__":
    main()