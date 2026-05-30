"""
utils/helpers.py — Shared helper functions.
"""

from datetime import datetime
import pytz

ET = pytz.timezone("America/New_York")


def now_et() -> datetime:
    """Current time in US Eastern."""
    return datetime.now(ET)


def is_market_hours() -> bool:
    """Basic check if we're within normal trading hours (no holidays check)."""
    now = now_et()
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    open_time  = now.replace(hour=9,  minute=30, second=0, microsecond=0)
    close_time = now.replace(hour=16, minute=0,  second=0, microsecond=0)
    return open_time <= now <= close_time


def pct_change(entry: float, current: float) -> float:
    """Return percentage change from entry to current."""
    if entry == 0:
        return 0.0
    return (current - entry) / entry


def format_currency(value: float) -> str:
    return f"${value:,.2f}"


def format_pct(value: float) -> str:
    sign = "+" if value >= 0 else ""
    return f"{sign}{value*100:.2f}%"


def calc_shares(portfolio_value: float, max_pct: float,
                price: float) -> int:
    """
    How many whole shares can we buy?
    portfolio_value: total portfolio in $
    max_pct: max fraction to allocate (e.g. 0.10 = 10%)
    price: current share price
    """
    budget = portfolio_value * max_pct
    return max(1, int(budget / price))