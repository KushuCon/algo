"""
run.py — Single entry point for everything.

USAGE:
  # Backtest a strategy on historical data
  python run.py backtest --strategy momentum --days 365
  python run.py backtest --strategy dip_rider --days 365
  python run.py backtest --strategy rs_breakout --days 180

  # Live scan: runs all active strategies on latest bars, prints dashboard
  python run.py scan

  # Live scan with custom symbols
  python run.py scan --symbols NVDA AMD SNDK MU

STRATEGIES AVAILABLE:
  momentum    — 4-5 day momentum swing (enhanced, dual-timeframe)
  dip_rider   — buy the dip + average down + trailing stop (NEW)
  rs_breakout — relative strength breakout (medium-term)
"""

import argparse
import sys
from datetime import datetime

# ── Strategy registry ──────────────────────────────────────────────────────────
from strategies.momentum     import MomentumStrategy
from strategies.rs_breakout  import RSBreakoutStrategy
from strategies.dip_rider                        import DipRiderStrategy

STRATEGY_MAP = {
    "momentum":    MomentumStrategy,
    "dip_rider":   DipRiderStrategy,
    "rs_breakout": RSBreakoutStrategy,
}

import config
from utils.logger import get_logger

log = get_logger("run")

# ── Stock universe (15 stocks, split by data source) ──────────────────────────
SYMBOLS_YAHOO  = ["NVDA", "AMD", "ARM", "MU", "QCOM", "TSLA", "GE", "PLTR"]
SYMBOLS_ALPACA = ["SNDK", "WDC", "CRWV", "STX", "BE", "SPCX", "DRAM"]
ALL_SYMBOLS    = SYMBOLS_YAHOO + SYMBOLS_ALPACA


# ═══════════════════════════════════════════════════════════════════════════════
# BACKTEST MODE
# ═══════════════════════════════════════════════════════════════════════════════

def run_backtest(strategy_name: str, symbols: list, days: int, capital: float):
    from backtest import fetch_history, run_backtest as _bt, compute_metrics, print_report
    from utils.report_generator import generate_report

    strategy_cls = STRATEGY_MAP[strategy_name]

    log.info(f"Backtesting [{strategy_name}] on {symbols} | {days}d")

    # Smart split: Yahoo for first 8, Alpaca for rest
    yf_syms  = [s for s in symbols if s in SYMBOLS_YAHOO]
    alp_syms = [s for s in symbols if s in SYMBOLS_ALPACA]
    other    = [s for s in symbols if s not in SYMBOLS_YAHOO + SYMBOLS_ALPACA]

    all_bars = {}

    if yf_syms or other:
        from backtest import _fetch_yfinance
        all_bars.update(_fetch_yfinance(yf_syms + other, days))

    if alp_syms:
        from backtest import _fetch_alpaca
        all_bars.update(_fetch_alpaca(alp_syms, days))

    strategy = strategy_cls()

    # DipRider uses wider stops
    if strategy_name == "dip_rider":
        stop_loss   = getattr(config, "DIPRIDER_HARD_STOP_PCT", 0.25)
        take_profit = 999.0   # no fixed take-profit — trailing stop handles exit
    else:
        stop_loss   = config.STOP_LOSS_PCT
        take_profit = config.TAKE_PROFIT_PCT

    results = _bt(
        strategy, all_bars,
        initial_capital=capital,
        stop_loss_pct=stop_loss,
        take_profit_pct=take_profit,
    )
    metrics = compute_metrics(results)
    print_report(strategy_name, symbols, results, metrics)
    generate_report(strategy_name=strategy_name, symbols=symbols,
                    results=results, metrics=metrics, days=days)


# ═══════════════════════════════════════════════════════════════════════════════
# LIVE SCAN MODE
# ═══════════════════════════════════════════════════════════════════════════════

def run_scan(symbols: list):
    """
    Fetch the latest ~60 days of daily bars for all symbols,
    run all active strategies, and print a unified signal dashboard.
    """
    from backtest import _fetch_yfinance, _fetch_alpaca

    print(f"\n{'═'*65}")
    print(f"  📡 LIVE SCAN  —  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Symbols: {', '.join(symbols)}")
    print(f"{'═'*65}\n")

    # Fetch data
    yf_syms  = [s for s in symbols if s in SYMBOLS_YAHOO]
    alp_syms = [s for s in symbols if s in SYMBOLS_ALPACA]
    other    = [s for s in symbols if s not in SYMBOLS_YAHOO + SYMBOLS_ALPACA]

    all_bars = {}
    try:
        if yf_syms or other:
            all_bars.update(_fetch_yfinance(yf_syms + other, 90))
    except Exception as e:
        log.warning(f"Yahoo fetch error: {e}")

    try:
        if alp_syms:
            all_bars.update(_fetch_alpaca(alp_syms, 90))
    except Exception as e:
        log.warning(f"Alpaca fetch error: {e}")

    # Run each strategy silently, collect signals
    strategies = {
        "momentum":    MomentumStrategy(),
        "dip_rider":   DipRiderStrategy(),
        "rs_breakout": RSBreakoutStrategy(),
    }

    # Collect all signals per symbol
    all_signals: dict[str, list] = {sym: [] for sym in symbols}

    for strat_name, strat in strategies.items():
        try:
            sigs = strat.generate_signals(all_bars)
            for sig in sigs:
                sym = sig["symbol"]
                if sym in all_signals:
                    all_signals[sym].append((strat_name, sig))
        except Exception as e:
            log.warning(f"{strat_name} error: {e}")

    # ── Print unified dashboard ────────────────────────────────────────────────
    ICONS = {
        "buy":  "🟢 BUY",
        "sell": "🔴 SELL",
        "hold": "⚪ HOLD",
    }

    for sym in symbols:
        bars = all_bars.get(sym)
        if bars is None or bars.empty:
            print(f"  {sym:6s}  ⚠️  No data\n")
            continue

        price = float(bars["close"].iloc[-1])
        price_1d = float(bars["close"].iloc[-2]) if len(bars) > 1 else price
        chg_1d   = (price - price_1d) / price_1d

        print(f"  {'─'*61}")
        print(f"  {sym:6s}  ${price:>9.2f}  ({chg_1d:+.1%} today)")
        print(f"  {'─'*61}")

        sigs = all_signals.get(sym, [])
        if not sigs:
            print(f"    No signals\n")
            continue

        for strat_name, sig in sigs:
            action = sig.get("signal", "hold")
            icon   = ICONS.get(action, "⚪")
            reason = sig.get("reason", "")

            print(f"    [{strat_name:12s}]  {icon:12s}  {reason}")

            # Print key levels for actionable signals
            if action == "buy":
                if "hard_stop"   in sig: print(f"       Hard Stop  : ${sig['hard_stop']}")
                if "avg_down_at" in sig: print(f"       Avg Down At: ${sig['avg_down_at']} (if it falls further)")
                if "trail_stop"  in sig and sig["trail_stop"]: print(f"       Trail Stop : ${sig['trail_stop']}")

            elif action == "sell":
                pass  # reason already includes all info

            elif action == "hold" and strat_name == "dip_rider":
                if sig.get("trail_stop"): print(f"       Trail Stop : ${sig['trail_stop']}")
                if sig.get("hard_stop"):  print(f"       Hard Stop  : ${sig['hard_stop']}")
                if sig.get("pnl_pct") is not None:
                    pnl = sig["pnl_pct"]
                    icon_pnl = "📈" if pnl > 0 else "📉"
                    print(f"       P&L        : {icon_pnl} {pnl:+.1%}")

        print()

    print(f"{'═'*65}\n")


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Algo Trading — Unified Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="mode", required=True)

    # backtest sub-command
    bt = sub.add_parser("backtest", help="Run historical backtest")
    bt.add_argument("--strategy", required=True, choices=list(STRATEGY_MAP.keys()))
    bt.add_argument("--symbols",  nargs="+", default=ALL_SYMBOLS)
    bt.add_argument("--days",     type=int,   default=365)
    bt.add_argument("--capital",  type=float, default=100_000)

    # scan sub-command
    sc = sub.add_parser("scan", help="Live signal scan (all strategies)")
    sc.add_argument("--symbols", nargs="+", default=ALL_SYMBOLS)

    args = parser.parse_args()

    if args.mode == "backtest":
        run_backtest(args.strategy, args.symbols, args.days, args.capital)

    elif args.mode == "scan":
        run_scan(args.symbols)


if __name__ == "__main__":
    main()