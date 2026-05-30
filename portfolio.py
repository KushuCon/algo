"""
portfolio.py — Portfolio state tracking and risk management.

Handles:
  - Position sizing (how many shares to buy)
  - Stop loss / take profit monitoring
  - Daily loss limit enforcement
  - Trade journal (CSV log)
"""

import csv
import os
from datetime import datetime
from utils.logger import get_logger
from utils.helpers import pct_change, calc_shares, format_currency, format_pct
import config

log = get_logger("portfolio")


class PortfolioManager:
    def __init__(self, broker):
        self.broker         = broker
        self.daily_start_value = None  # set at market open
        self.trade_log_path = os.path.join(config.LOG_DIR, "trades.csv")
        self._init_trade_log()

    def _init_trade_log(self):
        """Create trade log CSV with header if it doesn't exist."""
        os.makedirs(config.LOG_DIR, exist_ok=True)
        if not os.path.exists(self.trade_log_path):
            with open(self.trade_log_path, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow([
                    "timestamp", "symbol", "action", "qty",
                    "price", "value", "reason", "pnl"
                ])

    def record_daily_start(self):
        """Call at market open to record starting portfolio value."""
        self.daily_start_value = self.broker.get_portfolio_value()
        log.info(f"Daily start value: {format_currency(self.daily_start_value)}")

    def is_daily_loss_limit_breached(self) -> bool:
        """Return True if we've lost more than MAX_DAILY_LOSS_PCT today."""
        if self.daily_start_value is None:
            return False
        current = self.broker.get_portfolio_value()
        loss_pct = (self.daily_start_value - current) / self.daily_start_value
        if loss_pct >= config.MAX_DAILY_LOSS_PCT:
            log.warning(
                f"Daily loss limit breached: {format_pct(-loss_pct)} "
                f"(limit: {format_pct(-config.MAX_DAILY_LOSS_PCT)})"
            )
            return True
        return False

    def calc_position_size(self, price: float, strength: float = 1.0) -> int:
        """
        Calculate how many shares to buy.
        Uses MAX_POSITION_PCT from config, scaled by signal strength.
        """
        portfolio_value = self.broker.get_portfolio_value()
        effective_pct   = config.MAX_POSITION_PCT * strength
        shares = calc_shares(portfolio_value, effective_pct, price)
        log.debug(
            f"Position size: {shares} shares @ {format_currency(price)} "
            f"({format_pct(effective_pct)} of {format_currency(portfolio_value)})"
        )
        return shares

    def check_stop_loss_take_profit(self) -> list[str]:
        """
        Check all open positions for stop loss / take profit triggers.
        Returns list of symbols to close.
        """
        to_close = []
        positions = self.broker.get_positions()

        for symbol, pos in positions.items():
            entry_price   = float(pos.avg_entry_price)
            current_price = float(pos.current_price)
            change_pct    = pct_change(entry_price, current_price)

            if change_pct <= -config.STOP_LOSS_PCT:
                log.warning(
                    f"STOP LOSS: {symbol} | Entry {format_currency(entry_price)} | "
                    f"Current {format_currency(current_price)} | {format_pct(change_pct)}"
                )
                to_close.append(symbol)
                self._log_trade(symbol, "stop_loss", int(pos.qty),
                                current_price, "Stop loss triggered",
                                pnl=(current_price - entry_price) * int(pos.qty))

            elif change_pct >= config.TAKE_PROFIT_PCT:
                log.info(
                    f"TAKE PROFIT: {symbol} | Entry {format_currency(entry_price)} | "
                    f"Current {format_currency(current_price)} | {format_pct(change_pct)}"
                )
                to_close.append(symbol)
                self._log_trade(symbol, "take_profit", int(pos.qty),
                                current_price, "Take profit triggered",
                                pnl=(current_price - entry_price) * int(pos.qty))

        return to_close

    def execute_signal(self, signal: dict):
        """
        Execute a buy or sell signal from a strategy.
        Handles position sizing, logging.
        """
        symbol   = signal["symbol"]
        action   = signal["signal"]
        price    = signal.get("price", 0)
        reason   = signal.get("reason", "")
        strength = signal.get("strength", 1.0)

        positions = self.broker.get_positions()

        if action == "buy":
            if symbol in positions:
                log.debug(f"Already holding {symbol}, skipping buy")
                return

            cash = self.broker.get_cash()
            qty  = self.calc_position_size(price, strength)
            cost = qty * price

            if cost > cash:
                log.warning(
                    f"Insufficient cash for {symbol}: need {format_currency(cost)}, "
                    f"have {format_currency(cash)}"
                )
                return

            order = self.broker.buy(symbol, qty)
            if order:
                self._log_trade(symbol, "buy", qty, price, reason)

        elif action == "sell":
            if symbol not in positions:
                log.debug(f"No position in {symbol} to sell")
                return

            pos   = positions[symbol]
            qty   = int(float(pos.qty))
            entry = float(pos.avg_entry_price)
            pnl   = (price - entry) * qty

            order = self.broker.close_position(symbol)
            if order:
                self._log_trade(symbol, "sell", qty, price, reason, pnl=pnl)
                log.info(f"PnL for {symbol}: {format_currency(pnl)} ({format_pct(pnl/(entry*qty))})")

    def _log_trade(self, symbol, action, qty, price, reason, pnl=0):
        """Append a trade to the CSV log."""
        with open(self.trade_log_path, "a", newline="") as f:
            w = csv.writer(f)
            w.writerow([
                datetime.now().isoformat(),
                symbol, action, qty, round(price, 2),
                round(qty * price, 2), reason, round(pnl, 2)
            ])

    def print_summary(self):
        """Print current portfolio summary to console."""
        acct      = self.broker.get_account()
        positions = self.broker.get_positions()
        pv        = float(acct.portfolio_value)
        cash      = float(acct.cash)

        print("\n" + "="*55)
        print(f"  Portfolio: {format_currency(pv)}")
        print(f"  Cash:      {format_currency(cash)}")
        if self.daily_start_value:
            daily_pnl = pv - self.daily_start_value
            print(f"  Daily P&L: {format_currency(daily_pnl)} ({format_pct(daily_pnl/self.daily_start_value)})")
        print(f"  Positions: {len(positions)}")
        for sym, pos in positions.items():
            unreal = float(pos.unrealized_pl)
            print(f"    {sym:6s}  qty={pos.qty:5}  "
                  f"entry={format_currency(float(pos.avg_entry_price))}  "
                  f"pnl={format_currency(unreal)}")
        print("="*55 + "\n")