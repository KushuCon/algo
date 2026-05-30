import argparse
import time
import schedule
from datetime import datetime

import config
from broker import AlpacaBroker
from portfolio import PortfolioManager
from utils.logger import get_logger
from strategies.INTRADAY.scalp_1m import ScalpOneMin
from strategies.INTRADAY.scalp_5m import ScalpFiveMin

# ── Strategy registry ──────────────────────────────────────────────────────────
from strategies.sma_crossover      import SMAcrossover
from strategies.POSITIONAL_2_3_DAY.rsi_mean_revert    import RSIMeanRevert
from strategies.POSITIONAL_4_5_DAY.momentum           import MomentumStrategy
from strategies.POSITIONAL_2_3_DAY.ma_crossover_sl    import MACrossoverWithSL
from strategies.pairs_trading      import PairsTradingStrategy
from strategies.factor_model       import FactorModelStrategy
from strategies.stat_arb           import StatArbStrategy
from strategies.POSITIONAL_2_3_DAY.random_forest_strat import RandomForestStrategy
from strategies.ADVANCED_ML.lstm_strat         import LSTMStrategy

STRATEGY_MAP = {
    "sma":      SMAcrossover,
    "rsi":      RSIMeanRevert,
    "momentum": MomentumStrategy,
    "ma_sl":    MACrossoverWithSL,
    "pairs":    PairsTradingStrategy,
    "factor":   FactorModelStrategy,
    "stat_arb": StatArbStrategy,
    "rf":       RandomForestStrategy,
    "lstm":     LSTMStrategy,
    "scalp1": ScalpOneMin,
    "scalp5": ScalpFiveMin,
}

log = get_logger("main")


# ── Core trading loop ──────────────────────────────────────────────────────────

def run_cycle(broker: AlpacaBroker, pm: PortfolioManager, strategy, symbols: list):
    """One scan cycle: fetch bars → generate signals → execute."""
    if not broker.is_market_open():
        log.debug("Market closed — skipping cycle.")
        return

    if pm.is_daily_loss_limit_breached():
        log.warning("Daily loss limit hit — no new trades this cycle.")
        return

    # ── Stop-loss / take-profit sweep ─────────────────────────────────────────
    to_close = pm.check_stop_loss_take_profit()
    for sym in to_close:
        broker.close_position(sym)

    # ── Fetch bars for all symbols ────────────────────────────────────────────
    all_bars = {}
    tf = getattr(strategy, "TIMEFRAME", "1Day")
    bar_limit = getattr(strategy, "BAR_LIMIT", 200)
    for sym in symbols:
        bars = broker.get_bars(sym, timeframe=tf, limit=bar_limit)
        all_bars[sym] = bars if not bars.empty else None

    # ── Generate signals ──────────────────────────────────────────────────────
    signals = strategy.generate_signals(all_bars)

    # ── Execute signals ───────────────────────────────────────────────────────
    for sig in signals:
        if sig["signal"] in ("buy", "sell"):
            price = broker.get_latest_trade(sig["symbol"])
            sig["price"] = price
            pm.execute_signal(sig)

    pm.print_summary()


def eod_close(broker: AlpacaBroker):
    """Close all positions end-of-day."""
    if config.CLOSE_ALL_EOD:
        broker.cancel_all_orders()
        broker.close_all_positions()
        log.info("EOD: all positions closed.")


def market_open_setup(pm: PortfolioManager):
    """Called at market open."""
    pm.record_daily_start()
    log.info("Market open — trading day started.")


# ── CLI ────────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="Alpaca Paper Trading Bot")
    p.add_argument("--strategy", default=config.ACTIVE_STRATEGY,
                   choices=list(STRATEGY_MAP.keys()),
                   help="Strategy to run")
    p.add_argument("--symbols", nargs="+", default=config.SYMBOLS,
                   help="Symbols to trade")
    return p.parse_args()


def main():
    args = parse_args()

    if args.strategy in ("scalp1", "scalp5"):
        config.STOP_LOSS_PCT = getattr(config, "SCALP_STOP_LOSS_PCT", 0.005)
        config.TAKE_PROFIT_PCT = getattr(config, "SCALP_TAKE_PROFIT_PCT", 0.01)

    log.info(f"Starting bot | Strategy: {args.strategy} | Symbols: {args.symbols}")

    broker   = AlpacaBroker()
    pm       = PortfolioManager(broker)
    strategy = STRATEGY_MAP[args.strategy]()

    log.info(f"Strategy loaded: {strategy}")

    # ── Schedule tasks ─────────────────────────────────────────────────────────
    schedule.every().day.at(config.MARKET_OPEN).do(market_open_setup, pm)
    schedule.every().day.at(config.EOD_CLOSE_TIME).do(eod_close, broker)
    interval = 60 if args.strategy == "scalp1" else (
        300 if args.strategy == "scalp5" else config.SCAN_INTERVAL_SECONDS
    )
    schedule.every(interval).seconds.do(
        run_cycle, broker, pm, strategy, args.symbols
    )

    # Run once immediately if market is open
    if broker.is_market_open():
        market_open_setup(pm)
        run_cycle(broker, pm, strategy, args.symbols)

    log.info("Scheduler running. Press Ctrl+C to stop.")
    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("Shutting down — closing all positions.")
        eod_close(broker)


if __name__ == "__main__":
    main()
