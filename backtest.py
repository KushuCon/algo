import argparse
import time
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

try:
    import yfinance as yf
    HAS_YF = True
except ImportError:
    HAS_YF = False

from utils.logger import get_logger
import config

# # ── Strategy registry ──────────────────────────────────────────────────────────
# from strategies.sma_crossover      import SMAcrossover
# from strategies.POSITIONAL_2_3_DAY.rsi_mean_revert    import RSIMeanRevert
# from strategies.POSITIONAL_4_5_DAY.momentum           import MomentumStrategy
# from strategies.POSITIONAL_2_3_DAY.ma_crossover_sl    import MACrossoverWithSL
# from strategies.pairs_trading      import PairsTradingStrategy
# from strategies.factor_model       import FactorModelStrategy
# from strategies.stat_arb           import StatArbStrategy
# from strategies.POSITIONAL_2_3_DAY.random_forest_strat import RandomForestStrategy
# from strategies.ADVANCED_ML.lstm_strat         import LSTMStrategy
# from strategies.INTRADAY.scalp_1m           import ScalpOneMin
# from strategies.INTRADAY.scalp_5m           import ScalpFiveMin

from strategies.POSITIONAL_2_3_DAY.rsi_mean_revert    import RSIMeanRevert
from strategies.POSITIONAL_4_5_DAY.momentum           import MomentumStrategy
from strategies.POSITIONAL_2_3_DAY.ma_crossover_sl    import MACrossoverWithSL
from strategies.POSITIONAL_2_3_DAY.random_forest_strat import RandomForestStrategy
from strategies.POSITIONAL_2_3_DAY.rs_breakout        import RSBreakoutStrategy
from strategies.ADVANCED_ML.lstm_strat                import LSTMStrategy
from strategies.INTRADAY.scalp_1m                     import ScalpOneMin
from strategies.INTRADAY.scalp_5m                     import ScalpFiveMin

STRATEGY_MAP = {
    "rsi":      RSIMeanRevert,
    "momentum": MomentumStrategy,
    "ma_sl":    MACrossoverWithSL,
    "rf":       RandomForestStrategy,
    "rs_breakout": RSBreakoutStrategy,
    "lstm":     LSTMStrategy,
    "scalp1":   ScalpOneMin,
    "scalp5":   ScalpFiveMin,
}
# STRATEGY_MAP = {
#     "sma":      SMAcrossover,
#     "rsi":      RSIMeanRevert,
#     "momentum": MomentumStrategy,
#     "ma_sl":    MACrossoverWithSL,
#     "pairs":    PairsTradingStrategy,
#     "factor":   FactorModelStrategy,
#     "stat_arb": StatArbStrategy,
#     "rf":       RandomForestStrategy,
#     "lstm":     LSTMStrategy,
#     "scalp1": ScalpOneMin,
#     "scalp5": ScalpFiveMin,
# }

log = get_logger("backtest")


# ── Data fetching ──────────────────────────────────────────────────────────────

_OHLCV_COLS = ("open", "high", "low", "close", "volume")
_BARS_PER_TRADING_DAY = {"1Min": 390, "5Min": 78, "15Min": 26, "1Hour": 7}


def _alpaca_keys_configured() -> bool:
    key = getattr(config, "ALPACA_API_KEY", "") or ""
    secret = getattr(config, "ALPACA_SECRET_KEY", "") or ""
    placeholders = ("YOUR_API_KEY_HERE", "YOUR_SECRET_KEY_HERE", "")
    return bool(key and secret and key not in placeholders and secret not in placeholders)


def _normalize_ohlcv(df: pd.DataFrame, symbol: str | None = None) -> pd.DataFrame:
    """
    Flatten yfinance MultiIndex columns to lowercase open/high/low/close/volume.
    Handles yfinance 0.2.x and 1.x column layouts.
    """
    if df is None or df.empty:
        return pd.DataFrame()

    out = df.copy()

    if isinstance(out.columns, pd.MultiIndex):
        tickers = [str(t) for t in out.columns.get_level_values(-1).unique()]
        top = [str(t) for t in out.columns.get_level_values(0).unique()]
        if symbol and symbol in tickers:
            out = out.xs(symbol, axis=1, level=-1, drop_level=True)
        elif symbol and symbol in top:
            out = out[symbol].copy()
        elif len(tickers) == 1:
            out.columns = out.columns.droplevel(-1)
        elif len(top) == 1:
            out.columns = out.columns.droplevel(0)
        else:
            out.columns = [
                c[0] if isinstance(c, tuple) else c for c in out.columns
            ]

    rename = {}
    for col in out.columns:
        if isinstance(col, tuple):
            name = col[0]
        else:
            name = col
        key = str(name).lower().strip()
        if key in ("adj close", "adjclose", "adj_close"):
            key = "close"
        rename[col] = key
    out = out.rename(columns=rename)

    keep = [c for c in _OHLCV_COLS if c in out.columns]
    if "close" not in keep and "adj close" in out.columns:
        out["close"] = out["adj close"]
        keep = [c for c in _OHLCV_COLS if c in out.columns]

    if not keep:
        return pd.DataFrame()

    out = out[list(keep)].dropna(how="all")
    return out


def _fetch_yfinance(symbols: list, days: int) -> dict:
    """One batched Yahoo request (fewer rate limits) then per-symbol normalize."""
    period = f"{days + 90}d"
    all_bars: dict = {s: None for s in symbols}

    log.info(f"Downloading {len(symbols)} symbol(s) from Yahoo ({period})...")
    time.sleep(0.5)

    if len(symbols) == 1:
        raw = yf.download(
            symbols[0],
            period=period,
            progress=False,
            auto_adjust=True,
            threads=False,
        )
        norm = _normalize_ohlcv(raw, symbols[0])
        if not norm.empty:
            all_bars[symbols[0]] = norm.tail(days)
            log.info(f"  {symbols[0]}: {len(all_bars[symbols[0]])} bars (yfinance)")
        return all_bars

    raw = yf.download(
        symbols,
        period=period,
        group_by="ticker",
        progress=False,
        auto_adjust=True,
        threads=False,
    )

    if raw.empty:
        return all_bars

    if isinstance(raw.columns, pd.MultiIndex):
        tickers_level0 = set(raw.columns.get_level_values(0).astype(str))
        for sym in symbols:
            if sym not in tickers_level0:
                continue
            norm = _normalize_ohlcv(raw[sym].copy(), sym)
            if not norm.empty:
                all_bars[sym] = norm.tail(days)
                log.info(f"  {sym}: {len(all_bars[sym])} bars (yfinance)")
    else:
        norm = _normalize_ohlcv(raw)
        if len(symbols) == 1 and not norm.empty:
            all_bars[symbols[0]] = norm.tail(days)

    return all_bars


def _fetch_alpaca(
    symbols: list,
    days: int,
    timeframe: str = "1Day",
    bar_limit: int = 500,
) -> dict:
    """Historical bars from Alpaca paper API (uses config keys)."""
    from broker import AlpacaBroker

    broker = AlpacaBroker()
    if timeframe == "1Day":
        limit = days + 60
    else:
        per_day = _BARS_PER_TRADING_DAY.get(timeframe, 78)
        limit = max(bar_limit, days * per_day + 50)
    all_bars: dict = {}

    for sym in symbols:
        log.info(f"Downloading {sym} ({timeframe}, limit={limit}) from Alpaca...")
        bars = broker.get_bars(sym, timeframe=timeframe, limit=limit)
        if bars is None or bars.empty:
            log.warning(f"No Alpaca bars for {sym}")
            all_bars[sym] = None
            continue
        bars = bars.copy()
        bars.columns = [str(c).lower() for c in bars.columns]
        keep = [c for c in _OHLCV_COLS if c in bars.columns]
        bars = bars[keep].dropna(how="all")
        if timeframe == "1Day":
            tail_n = days
        else:
            per_day = _BARS_PER_TRADING_DAY.get(timeframe, 78)
            tail_n = min(days * per_day, len(bars), bar_limit * 2)
        all_bars[sym] = bars.tail(tail_n)
        log.info(f"  {sym}: {len(all_bars[sym])} bars (Alpaca)")

    return all_bars


def fetch_history(
    symbols: list,
    days: int,
    source: str = "auto",
    timeframe: str = "1Day",
    bar_limit: int = 500,
) -> dict:
    """
    Fetch OHLCV for backtesting.

    source:
      auto     — yfinance batch, then Alpaca for any missing symbols
      yfinance — Yahoo only
      alpaca   — Alpaca only (requires API keys in config.py)
    timeframe / bar_limit — use strategy TIMEFRAME and BAR_LIMIT for intraday
    """
    symbols = list(symbols)
    all_bars: dict = {s: None for s in symbols}
    intraday = timeframe != "1Day"

    if intraday and source in ("auto", "yfinance"):
        log.info(f"Intraday {timeframe}: using Alpaca only (yfinance skipped).")
        source = "alpaca"

    if source in ("auto", "yfinance") and not intraday:
        if not HAS_YF:
            if source == "yfinance":
                raise ImportError(
                    "yfinance not installed. Run: pip install yfinance"
                )
            log.warning("yfinance not installed — skipping Yahoo.")
        else:
            try:
                all_bars = _fetch_yfinance(symbols, days)
            except Exception as e:
                log.warning(f"yfinance batch download failed: {e}")

    missing = [
        s for s in symbols
        if all_bars.get(s) is None
        or (isinstance(all_bars.get(s), pd.DataFrame) and all_bars[s].empty)
    ]

    if missing and source in ("auto", "alpaca"):
        if not _alpaca_keys_configured():
            if source == "alpaca":
                raise ValueError(
                    "Alpaca API keys not set in config.py (ALPACA_API_KEY / ALPACA_SECRET_KEY)."
                )
            for sym in missing:
                log.warning(f"No data for {sym}")
        else:
            if source == "auto" and missing:
                log.info(f"Using Alpaca fallback for: {missing}")
            alpaca_part = _fetch_alpaca(
                missing, days, timeframe=timeframe, bar_limit=bar_limit
            )
            all_bars.update(alpaca_part)

    for sym in symbols:
        df = all_bars.get(sym)
        if df is None or (isinstance(df, pd.DataFrame) and df.empty):
            log.warning(f"No data for {sym}")
            all_bars[sym] = None

    return all_bars


# ── Backtesting engine ─────────────────────────────────────────────────────────

def run_backtest(strategy, all_bars: dict,
                 initial_capital: float = 100_000,
                 max_position_pct: float = config.MAX_POSITION_PCT,
                 stop_loss_pct: float    = config.STOP_LOSS_PCT,
                 take_profit_pct: float  = config.TAKE_PROFIT_PCT,
                 ) -> dict:
    """
    Walk-forward simulation: step through each day, generate signals,
    simulate fills at next-open price, track P&L.

    Returns a results dict with equity curve and trade log.
    """
    # Align all bars to a common date index
    symbols = [s for s, b in all_bars.items() if b is not None]
    if not symbols:
        raise ValueError("No valid bars to backtest.")

    common_idx = None
    for sym in symbols:
        idx = all_bars[sym].index
        common_idx = idx if common_idx is None else common_idx.intersection(idx)

    cash      = initial_capital
    positions = {}   # {symbol: {"qty": int, "entry": float}}
    equity_curve = []
    trades    = []

    for i, date in enumerate(common_idx):
        if i < 50:  # warm-up
            equity_curve.append({"date": date, "equity": cash})
            continue

        # Slice bars up to today so strategy can't look ahead
        sliced = {}
        for sym in symbols:
            sliced[sym] = all_bars[sym].loc[:date].copy()

        # ── Stop-loss / Take-profit exits ─────────────────────────────────────
        to_close = []
        for sym, pos in positions.items():
            if sym not in sliced or sliced[sym].empty:
                continue
            curr_price = float(sliced[sym]["close"].iloc[-1])
            chg = (curr_price - pos["entry"]) / pos["entry"]
            if chg <= -stop_loss_pct:
                to_close.append((sym, curr_price, "stop_loss", chg))
            elif chg >= take_profit_pct:
                to_close.append((sym, curr_price, "take_profit", chg))

        for sym, price, reason, chg in to_close:
            pos  = positions.pop(sym)
            pnl  = (price - pos["entry"]) * pos["qty"]
            cash += price * pos["qty"]
            trades.append({"date": date, "symbol": sym, "action": reason,
                           "price": price, "qty": pos["qty"], "pnl": pnl})

        # ── Generate signals ──────────────────────────────────────────────────
        signals = strategy.generate_signals(sliced)

        for sig in signals:
            sym    = sig["symbol"]
            action = sig["signal"]
            if sliced[sym] is None or sliced[sym].empty:
                continue
            price    = float(sliced[sym]["close"].iloc[-1])
            strength = sig.get("strength", 1.0)

            if action == "buy" and sym not in positions:
                portfolio_val = cash + sum(
                    float(sliced[s]["close"].iloc[-1]) * p["qty"]
                    for s, p in positions.items()
                    if s in sliced and not sliced[s].empty
                )
                budget = portfolio_val * max_position_pct * strength
                qty    = max(1, int(budget / price))
                cost   = qty * price
                if cost <= cash:
                    cash -= cost
                    positions[sym] = {"qty": qty, "entry": price}
                    trades.append({"date": date, "symbol": sym, "action": "buy",
                                   "price": price, "qty": qty, "pnl": 0})

            elif action == "sell" and sym in positions:
                pos  = positions.pop(sym)
                pnl  = (price - pos["entry"]) * pos["qty"]
                cash += price * pos["qty"]
                trades.append({"date": date, "symbol": sym, "action": "sell",
                               "price": price, "qty": pos["qty"], "pnl": pnl})

        # ── Mark-to-market equity ─────────────────────────────────────────────
        mkt_val = sum(
            float(sliced[s]["close"].iloc[-1]) * p["qty"]
            for s, p in positions.items()
            if s in sliced and not sliced[s].empty
        )
        equity_curve.append({"date": date, "equity": cash + mkt_val})

    # Close any open positions at final price
    for sym, pos in positions.items():
        if sym in sliced and not sliced[sym].empty:
            price = float(sliced[sym]["close"].iloc[-1])
            pnl   = (price - pos["entry"]) * pos["qty"]
            cash += price * pos["qty"]
            trades.append({"date": common_idx[-1], "symbol": sym,
                           "action": "close_eob", "price": price,
                           "qty": pos["qty"], "pnl": pnl})

    eq_df = pd.DataFrame(equity_curve).set_index("date")
    tr_df = pd.DataFrame(trades)

    return {
        "equity_curve": eq_df,
        "trades":       tr_df,
        "initial":      initial_capital,
        "final":        float(eq_df["equity"].iloc[-1]),
    }


# ── Performance metrics ────────────────────────────────────────────────────────

def compute_metrics(results: dict) -> dict:
    eq   = results["equity_curve"]["equity"]
    rets = eq.pct_change().dropna()

    total_ret  = (results["final"] - results["initial"]) / results["initial"]
    n_days     = len(eq)
    ann_ret    = (1 + total_ret) ** (252 / n_days) - 1
    ann_vol    = rets.std() * np.sqrt(252)
    sharpe     = ann_ret / ann_vol if ann_vol > 0 else 0.0

    rolling_max = eq.cummax()
    drawdown    = (eq - rolling_max) / rolling_max
    max_dd      = float(drawdown.min())

    tr_df    = results["trades"]
    n_trades = len(tr_df[tr_df["action"].isin(["sell","stop_loss","take_profit","close_eob"])]) if not tr_df.empty else 0
    wins     = int((tr_df["pnl"] > 0).sum()) if not tr_df.empty else 0
    win_rate = wins / n_trades if n_trades > 0 else 0

    calmar   = ann_ret / abs(max_dd) if max_dd != 0 else 0.0

    return {
        "total_return":   total_ret,
        "annual_return":  ann_ret,
        "annual_vol":     ann_vol,
        "sharpe":         sharpe,
        "calmar":         calmar,
        "max_drawdown":   max_dd,
        "n_trades":       n_trades,
        "win_rate":       win_rate,
    }


def print_report(strategy_name: str, symbols: list,
                 results: dict, metrics: dict):
    tr_df = results["trades"]
    print("\n" + "=" * 60)
    print(f"  BACKTEST REPORT - {strategy_name.upper()}")
    print(f"  Symbols: {', '.join(symbols)}")
    print("=" * 60)
    print(f"  Initial capital : ${results['initial']:>12,.2f}")
    print(f"  Final value     : ${results['final']:>12,.2f}")
    print(f"  Total return    : {metrics['total_return']:>+.2%}")
    print(f"  Annual return   : {metrics['annual_return']:>+.2%}")
    print(f"  Annual vol      : {metrics['annual_vol']:>.2%}")
    print(f"  Sharpe ratio    : {metrics['sharpe']:>.3f}")
    print(f"  Calmar ratio    : {metrics['calmar']:>.3f}")
    print(f"  Max drawdown    : {metrics['max_drawdown']:>.2%}")
    print(f"  Total trades    : {metrics['n_trades']}")
    print(f"  Win rate        : {metrics['win_rate']:>.1%}")
    print("-" * 60)
    if not tr_df.empty:
        total_pnl = tr_df["pnl"].sum()
        print(f"  Total P&L       : ${total_pnl:>+,.2f}")
        print(f"\n  Last 5 trades:")
        for _, row in tr_df.tail(5).iterrows():
            sign = "+" if row["pnl"] >= 0 else ""
            print(f"    {str(row['date'])[:10]}  {row['symbol']:6s}  "
                  f"{row['action']:12s}  ${row['price']:>8.2f}  "
                  f"pnl={sign}${row['pnl']:.2f}")
    print("=" * 60 + "\n")


# ── CLI ────────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="Strategy Backtester")
    p.add_argument("--strategy", default="sma",
                   choices=list(STRATEGY_MAP.keys()))
    p.add_argument("--symbols", nargs="+", default=config.SYMBOLS)
    p.add_argument("--days",    type=int, default=365)
    p.add_argument("--capital", type=float, default=100_000)
    p.add_argument(
        "--source",
        default="auto",
        choices=("auto", "yfinance", "alpaca"),
        help="Data source: auto=yfinance then Alpaca fallback",
    )
    return p.parse_args()


def main():
    args = parse_args()
    strategy_cls = STRATEGY_MAP[args.strategy]
    tf = getattr(strategy_cls, "TIMEFRAME", "1Day")
    bar_limit = getattr(strategy_cls, "BAR_LIMIT", 500)

    log.info(
        f"Backtesting {args.strategy} on {args.symbols} | "
        f"{args.days}d | {tf} | source={args.source}"
    )

    fetch_syms = list(args.symbols)
    if args.strategy == "rs_breakout" and "SPY" not in fetch_syms:
        fetch_syms.append("SPY")

    all_bars = fetch_history(
        fetch_syms,
        args.days,
        source=args.source,
        timeframe=tf,
        bar_limit=bar_limit,
    )
    strategy = strategy_cls()

    stop_loss = config.STOP_LOSS_PCT
    take_profit = config.TAKE_PROFIT_PCT
    if args.strategy in ("scalp1", "scalp5"):
        stop_loss = getattr(config, "SCALP_STOP_LOSS_PCT", 0.005)
        take_profit = getattr(config, "SCALP_TAKE_PROFIT_PCT", 0.01)

    results = run_backtest(
        strategy,
        all_bars,
        initial_capital=args.capital,
        stop_loss_pct=stop_loss,
        take_profit_pct=take_profit,
    )
    metrics = compute_metrics(results)
    print_report(args.strategy, args.symbols, results, metrics)

    # Save equity curve + trades to CSV
    # Save equity curve + trades to CSV (existing logs)
    results["equity_curve"].to_csv("logs/backtest_equity.csv")
    if not results["trades"].empty:
        results["trades"].to_csv("logs/backtest_trades.csv", index=False)
    log.info("Results saved to logs/backtest_equity.csv and logs/backtest_trades.csv")

    # ── Auto-generate HTML report + CSV in /reports/ ──────────────────────────
    from utils.report_generator import generate_report
    generate_report(
        strategy_name=args.strategy,
        symbols=args.symbols,
        results=results,
        metrics=metrics,
        days=args.days,
    )


if __name__ == "__main__":
    main()
