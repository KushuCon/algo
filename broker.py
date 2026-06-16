# # """
# # broker.py — Alpaca API wrapper.
# # Handles all communication with Alpaca: account info,
# # placing orders, getting bars, checking positions.
# # """

# # import alpaca_trade_api as tradeapi
# # import pandas as pd
# # from datetime import datetime, timedelta
# # from utils.logger import get_logger
# # import config

# # log = get_logger("broker")


# # def _to_alpaca_timeframe(timeframe: str):
# #     """Map string timeframe to alpaca_trade_api TimeFrame."""
# #     if timeframe == "1Day":
# #         return tradeapi.TimeFrame.Day
# #     if timeframe == "1Hour":
# #         return tradeapi.TimeFrame.Hour
# #     if timeframe == "1Min":
# #         return tradeapi.TimeFrame.Minute
# #     if timeframe == "5Min":
# #         return tradeapi.TimeFrame(5, tradeapi.TimeFrame.Minute)
# #     if timeframe == "15Min":
# #         return tradeapi.TimeFrame(15, tradeapi.TimeFrame.Minute)
# #     raise ValueError(f"Unsupported timeframe: {timeframe}")


# # class AlpacaBroker:
# #     """
# #     Thin wrapper around alpaca_trade_api.
# #     All order placement and market data comes through here.
# #     """

# #     def __init__(self):
# #         self.api = tradeapi.REST(
# #             key_id     = config.ALPACA_API_KEY,
# #             secret_key = config.ALPACA_SECRET_KEY,
# #             base_url   = config.ALPACA_BASE_URL,
# #             api_version= "v2",
# #         )
# #         self._verify_connection()

# #     def _verify_connection(self):
# #         """Confirm we can connect and print account info."""
# #         try:
# #             acct = self.api.get_account()
# #             log.info(f"Connected to Alpaca | Status: {acct.status} | "
# #                      f"Cash: ${float(acct.cash):,.2f} | "
# #                      f"Portfolio: ${float(acct.portfolio_value):,.2f}")
# #         except Exception as e:
# #             log.error(f"Failed to connect to Alpaca: {e}")
# #             raise

# #     # ── Account & Portfolio ───────────────────────────────────────────────────

# #     def get_account(self):
# #         """Return the Alpaca account object."""
# #         return self.api.get_account()

# #     def get_portfolio_value(self) -> float:
# #         return float(self.api.get_account().portfolio_value)

# #     def get_cash(self) -> float:
# #         return float(self.api.get_account().cash)

# #     def get_positions(self) -> dict:
# #         """Return {symbol: position_object} for all open positions."""
# #         positions = self.api.list_positions()
# #         return {p.symbol: p for p in positions}

# #     def get_position(self, symbol: str):
# #         """Return position for a single symbol, or None if not held."""
# #         try:
# #             return self.api.get_position(symbol)
# #         except Exception:
# #             return None

# #     # ── Market Data ───────────────────────────────────────────────────────────

# #     def get_bars(self, symbol: str, timeframe: str = "1Day",
# #                  limit: int = 100, feed: str | None = None) -> pd.DataFrame:
# #         """
# #         Fetch OHLCV bars for a symbol.

# #         timeframe options: "1Min", "5Min", "15Min", "1Hour", "1Day"
# #         feed: "iex" for free paper accounts; "sip" requires a paid data plan
# #         Returns DataFrame with columns: open, high, low, close, volume
# #         """
# #         feed = feed or getattr(config, "ALPACA_DATA_FEED", "iex")
# #         end   = datetime.now()
# #         alpaca_tf = _to_alpaca_timeframe(timeframe)

# #         if timeframe == "1Day":
# #             start = end - timedelta(days=limit + 50)
# #         else:
# #             # Intraday: fetch enough calendar days to cover `limit` bars
# #             bars_per_day = {"1Min": 390, "5Min": 78, "15Min": 26, "1Hour": 7}
# #             per_day = bars_per_day.get(timeframe, 78)
# #             start = end - timedelta(days=max(3, (limit // per_day) + 3))

# #         bars = self.api.get_bars(
# #             symbol,
# #             alpaca_tf,
# #             start.strftime("%Y-%m-%d"),
# #             end.strftime("%Y-%m-%d"),
# #             adjustment="raw",
# #             feed=feed,
# #         ).df

# #         if bars.empty:
# #             log.warning(f"No bars returned for {symbol}")
# #             return bars

# #         bars = bars.tail(limit).copy()
# #         log.debug(f"Got {len(bars)} bars for {symbol}")
# #         return bars

# #     def get_latest_quote(self, symbol: str) -> dict:
# #         """Return latest bid/ask for a symbol."""
# #         quote = self.api.get_latest_quote(symbol)
# #         return {
# #             "ask": float(quote.ap),
# #             "bid": float(quote.bp),
# #             "mid": (float(quote.ap) + float(quote.bp)) / 2,
# #         }

# #     def get_latest_trade(self, symbol: str) -> float:
# #         """Return last trade price."""
# #         trade = self.api.get_latest_trade(symbol)
# #         return float(trade.p)

# #     # ── Orders ────────────────────────────────────────────────────────────────

# #     def buy(self, symbol: str, qty: float, order_type: str = "market") -> object:
# #         """
# #         Place a buy order.
# #         qty can be fractional (e.g. 0.5 shares) on supported symbols.
# #         """
# #         log.info(f"BUY  {symbol} x{qty} [{order_type}]")
# #         try:
# #             order = self.api.submit_order(
# #                 symbol         = symbol,
# #                 qty            = qty,
# #                 side           = "buy",
# #                 type           = order_type,
# #                 time_in_force  = "day",
# #             )
# #             log.info(f"Order placed: {order.id} | {symbol} x{qty}")
# #             return order
# #         except Exception as e:
# #             log.error(f"Failed to place BUY order for {symbol}: {e}")
# #             return None

# #     def sell(self, symbol: str, qty: float, order_type: str = "market") -> object:
# #         """Place a sell order."""
# #         log.info(f"SELL {symbol} x{qty} [{order_type}]")
# #         try:
# #             order = self.api.submit_order(
# #                 symbol        = symbol,
# #                 qty           = qty,
# #                 side          = "sell",
# #                 type          = order_type,
# #                 time_in_force = "day",
# #             )
# #             log.info(f"Order placed: {order.id} | {symbol} x{qty}")
# #             return order
# #         except Exception as e:
# #             log.error(f"Failed to place SELL order for {symbol}: {e}")
# #             return None

# #     def close_position(self, symbol: str) -> object:
# #         """Close entire position in a symbol."""
# #         log.info(f"Closing entire position: {symbol}")
# #         try:
# #             return self.api.close_position(symbol)
# #         except Exception as e:
# #             log.error(f"Failed to close {symbol}: {e}")
# #             return None

# #     def close_all_positions(self):
# #         """Close ALL open positions (used at EOD)."""
# #         log.info("Closing all positions (EOD)")
# #         try:
# #             self.api.close_all_positions()
# #             log.info("All positions closed.")
# #         except Exception as e:
# #             log.error(f"Failed to close all positions: {e}")

# #     def cancel_all_orders(self):
# #         """Cancel all open orders."""
# #         self.api.cancel_all_orders()

# #     # ── Market Status ─────────────────────────────────────────────────────────

# #     def is_market_open(self) -> bool:
# #         """Return True if the US market is currently open."""
# #         clock = self.api.get_clock()
# #         return clock.is_open

# #     def next_market_open(self) -> datetime:
# #         clock = self.api.get_clock()
# #         return clock.next_open.replace(tzinfo=None)

# #     def get_orders(self, status: str = "all", limit: int = 50) -> list:
# #         """Return recent orders."""
# #         return self.api.list_orders(status=status, limit=limit)



# """
# broker.py — Market data from Twelve Data (low-delay) + Alpaca for orders.

# Data flow:
#   get_bars()         → Twelve Data (5-min/1-day real bars)  → Alpaca fallback
#   get_latest_trade() → Twelve Data real-time price          → Alpaca fallback
#   buy/sell/orders    → Alpaca paper account (unchanged)
#   is_market_open()   → Alpaca clock (unchanged)

# Twelve Data batching:
#   All symbols fetched together in ONE API call per cycle.
#   Cache lasts 10 seconds → effectively 1 call per 5-min scan cycle.
#   Free plan: 8 calls/min, 800/day → you'll use ~2-3 calls per cycle = fine.
# """

# import time
# import requests
# import pandas as pd
# import alpaca_trade_api as tradeapi
# from datetime import datetime, timedelta
# from zoneinfo import ZoneInfo

# from utils.logger import get_logger
# import config

# log = get_logger("broker")

# ET = ZoneInfo("America/New_York")
# UTC = ZoneInfo("UTC")

# # ── Twelve Data timeframe map ─────────────────────────────────────────────────
# _TD_TF = {
#     "1Min":  "1min",
#     "5Min":  "5min",
#     "15Min": "15min",
#     "1Hour": "1h",
#     "1Day":  "1day",
# }

# # ── Alpaca timeframe map ──────────────────────────────────────────────────────
# def _to_alpaca_timeframe(timeframe: str):
#     if timeframe == "1Day":  return tradeapi.TimeFrame.Day
#     if timeframe == "1Hour": return tradeapi.TimeFrame.Hour
#     if timeframe == "1Min":  return tradeapi.TimeFrame.Minute
#     if timeframe == "5Min":  return tradeapi.TimeFrame(5,  tradeapi.TimeFrame.Minute)
#     if timeframe == "15Min": return tradeapi.TimeFrame(15, tradeapi.TimeFrame.Minute)
#     raise ValueError(f"Unsupported timeframe: {timeframe}")


# # ══════════════════════════════════════════════════════════════════════════════
# # Twelve Data helper
# # ══════════════════════════════════════════════════════════════════════════════

# class _TwelveDataCache:
#     """
#     Batched cache for Twelve Data bars.
#     One API call fetches ALL symbols at once → cached 10 seconds.
#     """

#     def __init__(self, api_key: str):
#         self._key   = api_key
#         self._cache: dict[str, pd.DataFrame] = {}   # (symbols_key, tf, limit) → df per symbol
#         self._ts:    dict[str, float] = {}           # cache timestamp
#         self._TTL   = 10                             # seconds

#     def _cache_key(self, symbols: list, timeframe: str, limit: int) -> str:
#         return f"{'_'.join(sorted(symbols))}|{timeframe}|{limit}"

#     def _is_fresh(self, key: str) -> bool:
#         return key in self._ts and (time.time() - self._ts[key]) < self._TTL

#     def get_bars_batch(self, symbols: list, timeframe: str,
#                        limit: int) -> dict[str, pd.DataFrame]:
#         """
#         Return {symbol: DataFrame} for all symbols.
#         Uses cache if fresh, otherwise fetches from Twelve Data.
#         """
#         ck = self._cache_key(symbols, timeframe, limit)
#         if self._is_fresh(ck):
#             log.debug(f"TwelveData cache hit [{timeframe}] {symbols}")
#             return {s: self._cache.get(f"{ck}|{s}", pd.DataFrame()) for s in symbols}

#         td_tf = _TD_TF.get(timeframe, "1day")
#         sym_str = ",".join(symbols)

#         # outputsize: how many bars to request
#         outputsize = min(limit + 10, 5000)

#         url = "https://api.twelvedata.com/time_series"
#         params = {
#             "symbol":     sym_str,
#             "interval":   td_tf,
#             "outputsize": outputsize,
#             "apikey":     self._key,
#             "timezone":   "America/New_York",
#             "order":      "ASC",
#         }

#         try:
#             resp = requests.get(url, params=params, timeout=10)
#             resp.raise_for_status()
#             data = resp.json()
#         except Exception as e:
#             log.error(f"Twelve Data fetch error: {e}")
#             return {s: pd.DataFrame() for s in symbols}

#         result = {}

#         # Single symbol returns dict directly; multiple returns {symbol: dict}
#         if len(symbols) == 1:
#             data = {symbols[0]: data}

#         for sym in symbols:
#             sym_data = data.get(sym, {})
#             values   = sym_data.get("values", [])

#             if not values:
#                 log.warning(f"No Twelve Data bars for {sym} [{timeframe}]")
#                 result[sym] = pd.DataFrame()
#                 self._cache[f"{ck}|{sym}"] = pd.DataFrame()
#                 continue

#             df = pd.DataFrame(values)
#             df["datetime"] = pd.to_datetime(df["datetime"])
#             # Localize ET → convert to UTC (matches Alpaca index format)
#             df["datetime"] = df["datetime"].dt.tz_localize(ET).dt.tz_convert(UTC)
#             df = df.set_index("datetime")
#             df = df.rename(columns={
#                 "open": "open", "high": "high",
#                 "low":  "low",  "close": "close", "volume": "volume"
#             })
#             for col in ["open", "high", "low", "close", "volume"]:
#                 df[col] = pd.to_numeric(df[col], errors="coerce")

#             df = df.sort_index().tail(limit)
#             result[sym]             = df
#             self._cache[f"{ck}|{sym}"] = df

#         self._ts[ck] = time.time()
#         log.debug(f"TwelveData fetched {len(symbols)} symbols [{timeframe}] outputsize={outputsize}")
#         return result

#     def get_price(self, symbol: str) -> float | None:
#         """Real-time price via Twelve Data /price endpoint."""
#         try:
#             resp = requests.get(
#                 "https://api.twelvedata.com/price",
#                 params={"symbol": symbol, "apikey": self._key},
#                 timeout=5,
#             )
#             data = resp.json()
#             return float(data.get("price", 0)) or None
#         except Exception as e:
#             log.error(f"Twelve Data price error {symbol}: {e}")
#             return None


# # ══════════════════════════════════════════════════════════════════════════════
# # Main broker class
# # ══════════════════════════════════════════════════════════════════════════════

# class AlpacaBroker:
#     """
#     Market data → Twelve Data (low-delay).
#     Orders / account / positions → Alpaca paper account.
#     """

#     def __init__(self):
#         self.api = tradeapi.REST(
#             key_id     = config.ALPACA_API_KEY,
#             secret_key = config.ALPACA_SECRET_KEY,
#             base_url   = config.ALPACA_BASE_URL,
#             api_version= "v2",
#         )
#         self._verify_connection()

#         # Twelve Data client (used when DATA_PROVIDER == "twelvedata")
#         self._td = _TwelveDataCache(config.TWELVE_DATA_API_KEY)

#         # Which provider to use
#         self._provider = getattr(config, "DATA_PROVIDER", "alpaca")
#         log.info(f"Data provider: {self._provider.upper()}")

#     def _verify_connection(self):
#         try:
#             acct = self.api.get_account()
#             log.info(f"Alpaca connected | Status: {acct.status} | "
#                      f"Cash: ${float(acct.cash):,.2f} | "
#                      f"Portfolio: ${float(acct.portfolio_value):,.2f}")
#         except Exception as e:
#             log.error(f"Failed to connect to Alpaca: {e}")
#             raise

#     # ── Account & Portfolio (Alpaca only) ─────────────────────────────────────

#     def get_account(self):
#         return self.api.get_account()

#     def get_portfolio_value(self) -> float:
#         return float(self.api.get_account().portfolio_value)

#     def get_cash(self) -> float:
#         return float(self.api.get_account().cash)

#     def get_positions(self) -> dict:
#         return {p.symbol: p for p in self.api.list_positions()}

#     def get_position(self, symbol: str):
#         try:
#             return self.api.get_position(symbol)
#         except Exception:
#             return None

#     # ── Market Data (Twelve Data primary, Alpaca fallback) ────────────────────

#     def get_bars(self, symbol: str, timeframe: str = "1Day",
#                  limit: int = 100, feed: str | None = None) -> pd.DataFrame:
#         """
#         Fetch OHLCV bars.
#         Uses Twelve Data when DATA_PROVIDER="twelvedata", else Alpaca IEX.
#         Always returns DataFrame with: open, high, low, close, volume
#         """
#         if self._provider == "twelvedata":
#             result = self._td.get_bars_batch([symbol], timeframe, limit)
#             df = result.get(symbol, pd.DataFrame())
#             if not df.empty:
#                 return df
#             log.warning(f"Twelve Data empty for {symbol}, falling back to Alpaca")

#         # Alpaca fallback
#         return self._get_bars_alpaca(symbol, timeframe, limit, feed)

#     def get_bars_multi(self, symbols: list, timeframe: str = "1Day",
#                        limit: int = 100) -> dict[str, pd.DataFrame]:
#         """
#         Fetch bars for MULTIPLE symbols in one batched call.
#         Use this in scanners to minimise API calls.
#         """
#         if self._provider == "twelvedata":
#             result = self._td.get_bars_batch(symbols, timeframe, limit)
#             # Fill any missing symbols with Alpaca fallback
#             for sym in symbols:
#                 if sym not in result or result[sym].empty:
#                     log.warning(f"Twelve Data missing {sym}, falling back to Alpaca")
#                     result[sym] = self._get_bars_alpaca(sym, timeframe, limit)
#             return result

#         # All from Alpaca
#         return {s: self._get_bars_alpaca(s, timeframe, limit) for s in symbols}

#     def _get_bars_alpaca(self, symbol: str, timeframe: str,
#                          limit: int, feed: str | None = None) -> pd.DataFrame:
#         feed = feed or getattr(config, "ALPACA_DATA_FEED", "iex")
#         end  = datetime.now()
#         alpaca_tf = _to_alpaca_timeframe(timeframe)

#         if timeframe == "1Day":
#             start = end - timedelta(days=limit + 50)
#         else:
#             bars_per_day = {"1Min": 390, "5Min": 78, "15Min": 26, "1Hour": 7}
#             per_day = bars_per_day.get(timeframe, 78)
#             start = end - timedelta(days=max(3, (limit // per_day) + 3))

#         try:
#             bars = self.api.get_bars(
#                 symbol, alpaca_tf,
#                 start.strftime("%Y-%m-%d"),
#                 end.strftime("%Y-%m-%d"),
#                 adjustment="raw", feed=feed,
#             ).df
#             if bars.empty:
#                 log.warning(f"Alpaca: no bars for {symbol}")
#                 return bars
#             return bars.tail(limit).copy()
#         except Exception as e:
#             log.error(f"Alpaca get_bars failed for {symbol}: {e}")
#             return pd.DataFrame()

#     def get_latest_trade(self, symbol: str) -> float:
#         """Real-time last price. Twelve Data first, Alpaca fallback."""
#         if self._provider == "twelvedata":
#             price = self._td.get_price(symbol)
#             if price:
#                 return price
#         try:
#             return float(self.api.get_latest_trade(symbol).p)
#         except Exception as e:
#             log.error(f"get_latest_trade failed {symbol}: {e}")
#             return 0.0

#     def get_latest_quote(self, symbol: str) -> dict:
#         """Return ask/bid/mid. Uses Twelve Data price when available."""
#         if self._provider == "twelvedata":
#             price = self._td.get_price(symbol)
#             if price:
#                 return {"ask": price, "bid": price, "mid": price}
#         try:
#             q = self.api.get_latest_quote(symbol)
#             return {
#                 "ask": float(q.ap),
#                 "bid": float(q.bp),
#                 "mid": (float(q.ap) + float(q.bp)) / 2,
#             }
#         except Exception as e:
#             log.error(f"get_latest_quote failed {symbol}: {e}")
#             return {"ask": 0.0, "bid": 0.0, "mid": 0.0}

#     # ── Orders (Alpaca only — unchanged) ──────────────────────────────────────

#     def buy(self, symbol: str, qty: float, order_type: str = "market"):
#         log.info(f"BUY  {symbol} x{qty} [{order_type}]")
#         try:
#             order = self.api.submit_order(
#                 symbol=symbol, qty=qty, side="buy",
#                 type=order_type, time_in_force="day",
#             )
#             log.info(f"Order placed: {order.id} | {symbol} x{qty}")
#             return order
#         except Exception as e:
#             log.error(f"BUY failed {symbol}: {e}")
#             return None

#     def sell(self, symbol: str, qty: float, order_type: str = "market"):
#         log.info(f"SELL {symbol} x{qty} [{order_type}]")
#         try:
#             order = self.api.submit_order(
#                 symbol=symbol, qty=qty, side="sell",
#                 type=order_type, time_in_force="day",
#             )
#             log.info(f"Order placed: {order.id} | {symbol} x{qty}")
#             return order
#         except Exception as e:
#             log.error(f"SELL failed {symbol}: {e}")
#             return None

#     def close_position(self, symbol: str):
#         log.info(f"Closing position: {symbol}")
#         try:
#             return self.api.close_position(symbol)
#         except Exception as e:
#             log.error(f"close_position failed {symbol}: {e}")
#             return None

#     def close_all_positions(self):
#         log.info("Closing all positions (EOD)")
#         try:
#             self.api.close_all_positions()
#         except Exception as e:
#             log.error(f"close_all_positions failed: {e}")

#     def cancel_all_orders(self):
#         self.api.cancel_all_orders()

#     # ── Market Status (Alpaca clock) ──────────────────────────────────────────

#     def is_market_open(self) -> bool:
#         return self.api.get_clock().is_open

#     def next_market_open(self) -> datetime:
#         return self.api.get_clock().next_open.replace(tzinfo=None)

#     def get_orders(self, status: str = "all", limit: int = 50) -> list:
#         return self.api.list_orders(status=status, limit=limit)


"""
broker.py — Market data from Twelve Data (low-delay) + Alpaca for orders.

Data flow:
  get_bars()         → Twelve Data (5-min/1-day real bars)  → Alpaca fallback
  get_latest_trade() → Twelve Data real-time price          → Alpaca fallback
  buy/sell/orders    → Alpaca paper account (unchanged)
  is_market_open()   → Alpaca clock (unchanged)

Twelve Data batching:
  All symbols fetched together in ONE API call per cycle.
  Cache lasts 10 seconds → effectively 1 call per 5-min scan cycle.
  Free plan: 8 calls/min, 800/day → you'll use ~2-3 calls per cycle = fine.
"""

import time
import requests
import pandas as pd
import alpaca_trade_api as tradeapi
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from utils.logger import get_logger
import config

log = get_logger("broker")

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

# ── Twelve Data timeframe map ─────────────────────────────────────────────────
_TD_TF = {
    "1Min":  "1min",
    "5Min":  "5min",
    "15Min": "15min",
    "1Hour": "1h",
    "1Day":  "1day",
}

# ── Alpaca timeframe map ──────────────────────────────────────────────────────
def _to_alpaca_timeframe(timeframe: str):
    if timeframe == "1Day":  return tradeapi.TimeFrame.Day
    if timeframe == "1Hour": return tradeapi.TimeFrame.Hour
    if timeframe == "1Min":  return tradeapi.TimeFrame.Minute
    if timeframe == "5Min":  return tradeapi.TimeFrame(5,  tradeapi.TimeFrame.Minute)
    if timeframe == "15Min": return tradeapi.TimeFrame(15, tradeapi.TimeFrame.Minute)
    raise ValueError(f"Unsupported timeframe: {timeframe}")


# ══════════════════════════════════════════════════════════════════════════════
# Twelve Data helper
# ══════════════════════════════════════════════════════════════════════════════

class _TwelveDataCache:
    """
    Batched cache for Twelve Data bars.
    One API call fetches ALL symbols at once → cached 10 seconds.
    """

    def __init__(self, api_key: str):
        self._key   = api_key
        self._cache: dict[str, pd.DataFrame] = {}   # (symbols_key, tf, limit) → df per symbol
        self._ts:    dict[str, float] = {}           # cache timestamp
        self._TTL   = 10                             # seconds

    def _cache_key(self, symbols: list, timeframe: str, limit: int) -> str:
        return f"{'_'.join(sorted(symbols))}|{timeframe}|{limit}"

    def _is_fresh(self, key: str) -> bool:
        return key in self._ts and (time.time() - self._ts[key]) < self._TTL

    def get_bars_batch(self, symbols: list, timeframe: str,
                       limit: int) -> dict[str, pd.DataFrame]:
        """
        Return {symbol: DataFrame} for all symbols.
        Uses cache if fresh, otherwise fetches from Twelve Data.
        """
        ck = self._cache_key(symbols, timeframe, limit)
        if self._is_fresh(ck):
            log.debug(f"TwelveData cache hit [{timeframe}] {symbols}")
            return {s: self._cache.get(f"{ck}|{s}", pd.DataFrame()) for s in symbols}

        td_tf = _TD_TF.get(timeframe, "1day")
        sym_str = ",".join(symbols)

        # outputsize: how many bars to request
        outputsize = min(limit + 10, 5000)

        url = "https://api.twelvedata.com/time_series"
        params = {
            "symbol":     sym_str,
            "interval":   td_tf,
            "outputsize": outputsize,
            "apikey":     self._key,
            "timezone":   "America/New_York",
            "order":      "ASC",
        }

        for attempt in range(2):
            try:
                resp = requests.get(url, params=params, timeout=10)
                if resp.status_code == 429:
                    wait = 15 * (attempt + 1)
                    log.warning(f"Twelve Data rate limit (429) — waiting {wait}s then retry")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                break
            except Exception as e:
                log.error(f"Twelve Data fetch error: {e}")
                return {s: pd.DataFrame() for s in symbols}
        else:
            log.error("Twelve Data rate limit persists after retry — falling back")
            return {s: pd.DataFrame() for s in symbols}

        result = {}

        # Single symbol returns dict directly; multiple returns {symbol: dict}
        if len(symbols) == 1:
            data = {symbols[0]: data}

        for sym in symbols:
            sym_data = data.get(sym, {})
            values   = sym_data.get("values", [])

            if not values:
                log.warning(f"No Twelve Data bars for {sym} [{timeframe}]")
                result[sym] = pd.DataFrame()
                self._cache[f"{ck}|{sym}"] = pd.DataFrame()
                continue

            df = pd.DataFrame(values)
            df["datetime"] = pd.to_datetime(df["datetime"])
            # Localize ET → convert to UTC (matches Alpaca index format)
            df["datetime"] = df["datetime"].dt.tz_localize(ET).dt.tz_convert(UTC)
            df = df.set_index("datetime")
            df = df.rename(columns={
                "open": "open", "high": "high",
                "low":  "low",  "close": "close", "volume": "volume"
            })
            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")

            df = df.sort_index().tail(limit)
            result[sym]             = df
            self._cache[f"{ck}|{sym}"] = df

        self._ts[ck] = time.time()
        log.debug(f"TwelveData fetched {len(symbols)} symbols [{timeframe}] outputsize={outputsize}")
        return result

    def get_price(self, symbol: str) -> float | None:
        """Real-time price via Twelve Data /price endpoint."""
        try:
            resp = requests.get(
                "https://api.twelvedata.com/price",
                params={"symbol": symbol, "apikey": self._key},
                timeout=5,
            )
            data = resp.json()
            return float(data.get("price", 0)) or None
        except Exception as e:
            log.error(f"Twelve Data price error {symbol}: {e}")
            return None


# ══════════════════════════════════════════════════════════════════════════════
# Main broker class
# ══════════════════════════════════════════════════════════════════════════════

class AlpacaBroker:
    """
    Market data → Twelve Data (low-delay).
    Orders / account / positions → Alpaca paper account.
    """

    def __init__(self):
        self.api = tradeapi.REST(
            key_id     = config.ALPACA_API_KEY,
            secret_key = config.ALPACA_SECRET_KEY,
            base_url   = config.ALPACA_BASE_URL,
            api_version= "v2",
        )
        self._verify_connection()

        # Twelve Data client (used when DATA_PROVIDER == "twelvedata")
        self._td = _TwelveDataCache(config.TWELVE_DATA_API_KEY)

        # Which provider to use
        self._provider = getattr(config, "DATA_PROVIDER", "alpaca")
        log.info(f"Data provider: {self._provider.upper()}")

    def _verify_connection(self):
        try:
            acct = self.api.get_account()
            log.info(f"Alpaca connected | Status: {acct.status} | "
                     f"Cash: ${float(acct.cash):,.2f} | "
                     f"Portfolio: ${float(acct.portfolio_value):,.2f}")
        except Exception as e:
            log.error(f"Failed to connect to Alpaca: {e}")
            raise

    # ── Account & Portfolio (Alpaca only) ─────────────────────────────────────

    def get_account(self):
        return self.api.get_account()

    def get_portfolio_value(self) -> float:
        return float(self.api.get_account().portfolio_value)

    def get_cash(self) -> float:
        return float(self.api.get_account().cash)

    def get_positions(self) -> dict:
        return {p.symbol: p for p in self.api.list_positions()}

    def get_position(self, symbol: str):
        try:
            return self.api.get_position(symbol)
        except Exception:
            return None

    # ── Market Data (Twelve Data primary, Alpaca fallback) ────────────────────

    def get_bars(self, symbol: str, timeframe: str = "1Day",
                 limit: int = 100, feed: str | None = None) -> pd.DataFrame:
        """
        Fetch OHLCV bars.
        Uses Twelve Data when DATA_PROVIDER="twelvedata", else Alpaca IEX.
        Always returns DataFrame with: open, high, low, close, volume
        """
        if self._provider == "twelvedata":
            result = self._td.get_bars_batch([symbol], timeframe, limit)
            df = result.get(symbol, pd.DataFrame())
            if not df.empty:
                return df
            log.warning(f"Twelve Data empty for {symbol}, falling back to Alpaca")

        # Alpaca fallback
        return self._get_bars_alpaca(symbol, timeframe, limit, feed)

    def get_bars_multi(self, symbols: list, timeframe: str = "1Day",
                       limit: int = 100) -> dict[str, pd.DataFrame]:
        """
        Fetch bars for MULTIPLE symbols in one batched call.
        Use this in scanners to minimise API calls.
        """
        if self._provider == "twelvedata":
            result = self._td.get_bars_batch(symbols, timeframe, limit)
            # Fill any missing symbols with Alpaca fallback
            for sym in symbols:
                if sym not in result or result[sym].empty:
                    log.warning(f"Twelve Data missing {sym}, falling back to Alpaca")
                    result[sym] = self._get_bars_alpaca(sym, timeframe, limit)
            return result

        # All from Alpaca
        return {s: self._get_bars_alpaca(s, timeframe, limit) for s in symbols}

    def _get_bars_alpaca(self, symbol: str, timeframe: str,
                         limit: int, feed: str | None = None) -> pd.DataFrame:
        feed = feed or getattr(config, "ALPACA_DATA_FEED", "iex")
        end  = datetime.now()
        alpaca_tf = _to_alpaca_timeframe(timeframe)

        if timeframe == "1Day":
            start = end - timedelta(days=limit + 50)
        else:
            bars_per_day = {"1Min": 390, "5Min": 78, "15Min": 26, "1Hour": 7}
            per_day = bars_per_day.get(timeframe, 78)
            start = end - timedelta(days=max(3, (limit // per_day) + 3))

        try:
            bars = self.api.get_bars(
                symbol, alpaca_tf,
                start.strftime("%Y-%m-%d"),
                end.strftime("%Y-%m-%d"),
                adjustment="raw", feed=feed,
            ).df
            if bars.empty:
                log.warning(f"Alpaca: no bars for {symbol}")
                return bars
            return bars.tail(limit).copy()
        except Exception as e:
            log.error(f"Alpaca get_bars failed for {symbol}: {e}")
            return pd.DataFrame()

    def get_latest_trade(self, symbol: str) -> float:
        """Real-time last price. Twelve Data first, Alpaca fallback."""
        if self._provider == "twelvedata":
            price = self._td.get_price(symbol)
            if price:
                return price
        try:
            return float(self.api.get_latest_trade(symbol).p)
        except Exception as e:
            log.error(f"get_latest_trade failed {symbol}: {e}")
            return 0.0

    def get_latest_quote(self, symbol: str) -> dict:
        """Return ask/bid/mid. Uses Twelve Data price when available."""
        if self._provider == "twelvedata":
            price = self._td.get_price(symbol)
            if price:
                return {"ask": price, "bid": price, "mid": price}
        try:
            q = self.api.get_latest_quote(symbol)
            return {
                "ask": float(q.ap),
                "bid": float(q.bp),
                "mid": (float(q.ap) + float(q.bp)) / 2,
            }
        except Exception as e:
            log.error(f"get_latest_quote failed {symbol}: {e}")
            return {"ask": 0.0, "bid": 0.0, "mid": 0.0}

    # ── Orders (Alpaca only — unchanged) ──────────────────────────────────────

    def buy(self, symbol: str, qty: float, order_type: str = "market"):
        log.info(f"BUY  {symbol} x{qty} [{order_type}]")
        try:
            order = self.api.submit_order(
                symbol=symbol, qty=qty, side="buy",
                type=order_type, time_in_force="day",
            )
            log.info(f"Order placed: {order.id} | {symbol} x{qty}")
            return order
        except Exception as e:
            log.error(f"BUY failed {symbol}: {e}")
            return None

    def sell(self, symbol: str, qty: float, order_type: str = "market"):
        log.info(f"SELL {symbol} x{qty} [{order_type}]")
        try:
            order = self.api.submit_order(
                symbol=symbol, qty=qty, side="sell",
                type=order_type, time_in_force="day",
            )
            log.info(f"Order placed: {order.id} | {symbol} x{qty}")
            return order
        except Exception as e:
            log.error(f"SELL failed {symbol}: {e}")
            return None

    def close_position(self, symbol: str):
        log.info(f"Closing position: {symbol}")
        try:
            return self.api.close_position(symbol)
        except Exception as e:
            log.error(f"close_position failed {symbol}: {e}")
            return None

    def close_all_positions(self):
        log.info("Closing all positions (EOD)")
        try:
            self.api.close_all_positions()
        except Exception as e:
            log.error(f"close_all_positions failed: {e}")

    def cancel_all_orders(self):
        self.api.cancel_all_orders()

    # ── Market Status (Alpaca clock) ──────────────────────────────────────────

    def is_market_open(self) -> bool:
        return self.api.get_clock().is_open

    def next_market_open(self) -> datetime:
        return self.api.get_clock().next_open.replace(tzinfo=None)

    def get_orders(self, status: str = "all", limit: int = 50) -> list:
        return self.api.list_orders(status=status, limit=limit)

