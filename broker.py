"""
broker.py — Alpaca API wrapper.
Handles all communication with Alpaca: account info,
placing orders, getting bars, checking positions.
"""

import alpaca_trade_api as tradeapi
import pandas as pd
from datetime import datetime, timedelta
from utils.logger import get_logger
import config

log = get_logger("broker")


def _to_alpaca_timeframe(timeframe: str):
    """Map string timeframe to alpaca_trade_api TimeFrame."""
    if timeframe == "1Day":
        return tradeapi.TimeFrame.Day
    if timeframe == "1Hour":
        return tradeapi.TimeFrame.Hour
    if timeframe == "1Min":
        return tradeapi.TimeFrame.Minute
    if timeframe == "5Min":
        return tradeapi.TimeFrame(5, tradeapi.TimeFrame.Minute)
    if timeframe == "15Min":
        return tradeapi.TimeFrame(15, tradeapi.TimeFrame.Minute)
    raise ValueError(f"Unsupported timeframe: {timeframe}")


class AlpacaBroker:
    """
    Thin wrapper around alpaca_trade_api.
    All order placement and market data comes through here.
    """

    def __init__(self):
        self.api = tradeapi.REST(
            key_id     = config.ALPACA_API_KEY,
            secret_key = config.ALPACA_SECRET_KEY,
            base_url   = config.ALPACA_BASE_URL,
            api_version= "v2",
        )
        self._verify_connection()

    def _verify_connection(self):
        """Confirm we can connect and print account info."""
        try:
            acct = self.api.get_account()
            log.info(f"Connected to Alpaca | Status: {acct.status} | "
                     f"Cash: ${float(acct.cash):,.2f} | "
                     f"Portfolio: ${float(acct.portfolio_value):,.2f}")
        except Exception as e:
            log.error(f"Failed to connect to Alpaca: {e}")
            raise

    # ── Account & Portfolio ───────────────────────────────────────────────────

    def get_account(self):
        """Return the Alpaca account object."""
        return self.api.get_account()

    def get_portfolio_value(self) -> float:
        return float(self.api.get_account().portfolio_value)

    def get_cash(self) -> float:
        return float(self.api.get_account().cash)

    def get_positions(self) -> dict:
        """Return {symbol: position_object} for all open positions."""
        positions = self.api.list_positions()
        return {p.symbol: p for p in positions}

    def get_position(self, symbol: str):
        """Return position for a single symbol, or None if not held."""
        try:
            return self.api.get_position(symbol)
        except Exception:
            return None

    # ── Market Data ───────────────────────────────────────────────────────────

    def get_bars(self, symbol: str, timeframe: str = "1Day",
                 limit: int = 100, feed: str | None = None) -> pd.DataFrame:
        """
        Fetch OHLCV bars for a symbol.

        timeframe options: "1Min", "5Min", "15Min", "1Hour", "1Day"
        feed: "iex" for free paper accounts; "sip" requires a paid data plan
        Returns DataFrame with columns: open, high, low, close, volume
        """
        feed = feed or getattr(config, "ALPACA_DATA_FEED", "iex")
        end   = datetime.now()
        alpaca_tf = _to_alpaca_timeframe(timeframe)

        if timeframe == "1Day":
            start = end - timedelta(days=limit + 50)
        else:
            # Intraday: fetch enough calendar days to cover `limit` bars
            bars_per_day = {"1Min": 390, "5Min": 78, "15Min": 26, "1Hour": 7}
            per_day = bars_per_day.get(timeframe, 78)
            start = end - timedelta(days=max(3, (limit // per_day) + 3))

        bars = self.api.get_bars(
            symbol,
            alpaca_tf,
            start.strftime("%Y-%m-%d"),
            end.strftime("%Y-%m-%d"),
            adjustment="raw",
            feed=feed,
        ).df

        if bars.empty:
            log.warning(f"No bars returned for {symbol}")
            return bars

        bars = bars.tail(limit).copy()
        log.debug(f"Got {len(bars)} bars for {symbol}")
        return bars

    def get_latest_quote(self, symbol: str) -> dict:
        """Return latest bid/ask for a symbol."""
        quote = self.api.get_latest_quote(symbol)
        return {
            "ask": float(quote.ap),
            "bid": float(quote.bp),
            "mid": (float(quote.ap) + float(quote.bp)) / 2,
        }

    def get_latest_trade(self, symbol: str) -> float:
        """Return last trade price."""
        trade = self.api.get_latest_trade(symbol)
        return float(trade.p)

    # ── Orders ────────────────────────────────────────────────────────────────

    def buy(self, symbol: str, qty: float, order_type: str = "market") -> object:
        """
        Place a buy order.
        qty can be fractional (e.g. 0.5 shares) on supported symbols.
        """
        log.info(f"BUY  {symbol} x{qty} [{order_type}]")
        try:
            order = self.api.submit_order(
                symbol         = symbol,
                qty            = qty,
                side           = "buy",
                type           = order_type,
                time_in_force  = "day",
            )
            log.info(f"Order placed: {order.id} | {symbol} x{qty}")
            return order
        except Exception as e:
            log.error(f"Failed to place BUY order for {symbol}: {e}")
            return None

    def sell(self, symbol: str, qty: float, order_type: str = "market") -> object:
        """Place a sell order."""
        log.info(f"SELL {symbol} x{qty} [{order_type}]")
        try:
            order = self.api.submit_order(
                symbol        = symbol,
                qty           = qty,
                side          = "sell",
                type          = order_type,
                time_in_force = "day",
            )
            log.info(f"Order placed: {order.id} | {symbol} x{qty}")
            return order
        except Exception as e:
            log.error(f"Failed to place SELL order for {symbol}: {e}")
            return None

    def close_position(self, symbol: str) -> object:
        """Close entire position in a symbol."""
        log.info(f"Closing entire position: {symbol}")
        try:
            return self.api.close_position(symbol)
        except Exception as e:
            log.error(f"Failed to close {symbol}: {e}")
            return None

    def close_all_positions(self):
        """Close ALL open positions (used at EOD)."""
        log.info("Closing all positions (EOD)")
        try:
            self.api.close_all_positions()
            log.info("All positions closed.")
        except Exception as e:
            log.error(f"Failed to close all positions: {e}")

    def cancel_all_orders(self):
        """Cancel all open orders."""
        self.api.cancel_all_orders()

    # ── Market Status ─────────────────────────────────────────────────────────

    def is_market_open(self) -> bool:
        """Return True if the US market is currently open."""
        clock = self.api.get_clock()
        return clock.is_open

    def next_market_open(self) -> datetime:
        clock = self.api.get_clock()
        return clock.next_open.replace(tzinfo=None)

    def get_orders(self, status: str = "all", limit: int = 50) -> list:
        """Return recent orders."""
        return self.api.list_orders(status=status, limit=limit)