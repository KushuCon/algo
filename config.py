# """
# config.py — All configuration lives here.
# Replace ALPACA_API_KEY and ALPACA_SECRET_KEY with your actual keys.
# Get free paper trading keys: https://app.alpaca.markets
# """

# # ─── Alpaca API Keys ───────────────────────────────────────────────────────────
# # STEP 1: Sign up at https://app.alpaca.markets (free)
# # STEP 2: Go to Paper Trading > API Keys > Generate New Key
# ALPACA_API_KEY    = "PKUB3KATFKFW3UGRCR4FJCU2AI"
# ALPACA_SECRET_KEY = "BpYWw6tWAm9nUTaAFztrh38BwkaBxYutQFvnCcHgeEfH"

# # Paper trading base URL — DO NOT change this for paper trading
# ALPACA_BASE_URL = "https://paper-api.alpaca.markets"

# # Market data feed for bars/quotes: "iex" (free paper) or "sip" (paid subscription)
# ALPACA_DATA_FEED = "iex"

# # ─── Universe of stocks to trade ──────────────────────────────────────────────
# SYMBOLS = ["AAPL", "MSFT", "NVDA", "AMZN", "TSLA"]

# # ─── Strategy to use ──────────────────────────────────────────────────────────
# # Options: "sma_crossover" | "rsi_mean_revert" | "momentum"
# ACTIVE_STRATEGY = "sma_crossover"

# # ─── Risk Management ──────────────────────────────────────────────────────────
# MAX_POSITION_PCT     = 0.10   # Max 10% of portfolio in any single stock
# STOP_LOSS_PCT        = 0.02   # Exit if position drops 2% from entry
# TAKE_PROFIT_PCT      = 0.06   # Exit if position gains 6% from entry
# MAX_DAILY_LOSS_PCT   = 0.05   # Pause trading if daily loss > 5% of portfolio
# CLOSE_ALL_EOD        = True   # Close all positions before market close

# # ─── SMA Crossover Strategy Params ────────────────────────────────────────────
# SMA_FAST_PERIOD  = 9    # Fast SMA period (days)
# SMA_SLOW_PERIOD  = 21   # Slow SMA period (days)

# # ─── RSI Mean Reversion Params ────────────────────────────────────────────────
# RSI_PERIOD       = 14   # RSI lookback period
# RSI_OVERSOLD     = 30   # Buy when RSI drops below this
# RSI_OVERBOUGHT   = 70   # Sell when RSI rises above this

# # ─── Momentum Strategy Params ─────────────────────────────────────────────────
# MOMENTUM_LOOKBACK = 20  # Days to measure momentum
# MOMENTUM_THRESHOLD = 0.05  # Require 5% momentum to enter

# # ─── Scheduling ───────────────────────────────────────────────────────────────
# # Market hours (Eastern Time)
# MARKET_OPEN  = "09:30"
# MARKET_CLOSE = "16:00"
# EOD_CLOSE_TIME = "15:50"  # Close positions 10min before market close
# SCAN_INTERVAL_SECONDS = 60  # How often to run strategy signals

# # ─── Logging ──────────────────────────────────────────────────────────────────
# LOG_DIR   = "logs"
# LOG_LEVEL = "INFO"   # "DEBUG" | "INFO" | "WARNING" | "ERROR"



# # ─── MA Crossover + Stop Loss Params ──────────────────────────────────────────
# MA_FAST_PERIOD    = 12     # Fast EMA period
# MA_SLOW_PERIOD    = 26     # Slow EMA period
# MA_ATR_PERIOD     = 14     # ATR period for stop distance
# MA_ATR_MULT       = 2.0    # Stop = entry ± ATR_MULT × ATR
# MA_RISK_PER_TRADE = 0.01   # Risk 1% of portfolio per trade

# # ─── Pairs Trading Params ─────────────────────────────────────────────────────
# PAIRS_LOOKBACK    = 60     # Rolling OLS window (bars)
# PAIRS_ENTRY_Z     = 2.0    # Enter trade when |Z| > this
# PAIRS_EXIT_Z      = 0.5    # Exit trade when |Z| < this

# # ─── Factor Model Params ──────────────────────────────────────────────────────
# FACTOR_MOM_LOOKBACK = 252  # 12-month momentum lookback
# FACTOR_MOM_SKIP     = 21   # Skip most recent month (standard practice)
# FACTOR_MOM_WEIGHT   = 0.6  # Momentum factor weight
# FACTOR_VAL_WEIGHT   = 0.4  # Value factor weight
# FACTOR_LONG_TOP_N   = 2    # Buy top N ranked stocks
# FACTOR_SHORT_BOT_N  = 1    # Sell bottom N ranked stocks

# # ─── Statistical Arbitrage Params ─────────────────────────────────────────────
# STAT_ARB_LOOKBACK  = 120   # Bars used for cointegration test + OLS
# STAT_ARB_Z_WINDOW  = 30    # Rolling window for Z-score normalisation
# STAT_ARB_ENTRY_Z   = 2.0   # Enter when |Z| exceeds this
# STAT_ARB_EXIT_Z    = 0.5   # Exit when |Z| falls below this
# STAT_ARB_PVALUE    = 0.05  # Max p-value to accept cointegration

# # ─── Random Forest ML Params ──────────────────────────────────────────────────
# RF_TRAIN_BARS     = 200    # Training set size (bars)
# RF_N_ESTIMATORS   = 100    # Number of trees
# RF_MAX_DEPTH      = 5      # Max tree depth (prevent overfitting)
# RF_BUY_THRESH     = 0.60   # Buy if P(up) >= this
# RF_SELL_THRESH    = 0.40   # Sell if P(up) <= this
# RF_RETRAIN_EVERY  = 1      # Retrain every N cycles (1 = daily)

# # ─── LSTM ML Params ───────────────────────────────────────────────────────────
# LSTM_SEQ_LEN       = 20    # Input sequence length (bars)
# LSTM_TRAIN_BARS    = 300   # Training set size (bars)
# LSTM_HIDDEN        = 64    # LSTM hidden units
# LSTM_LAYERS        = 2     # Number of LSTM layers
# LSTM_EPOCHS        = 20    # Training epochs
# LSTM_LR            = 1e-3  # Learning rate
# LSTM_BATCH         = 32    # Mini-batch size
# LSTM_BUY_THRESH    = 0.60  # Buy if P(up) >= this
# LSTM_SELL_THRESH   = 0.40  # Sell if P(up) <= this
# LSTM_RETRAIN_EVERY = 5     # Retrain every N cycles

# # ─── Strategy map (update ACTIVE_STRATEGY to switch) ──────────────────────────
# # Options: "sma" | "rsi" | "momentum" | "ma_sl" | "pairs" | "factor"
# #          "stat_arb" | "rf" | "lstm"
# ACTIVE_STRATEGY = "sma"


# SCALP1_RSI_PERIOD     = 9
# SCALP1_RSI_OVERSOLD   = 35
# SCALP1_RSI_OVERBOUGHT = 65
# SCALP1_VOL_PERIOD     = 20
# SCALP1_VOL_MULT       = 1.5
# SCALP1_EOD_CUTOFF     = "15:30"

# SCALP5_EMA_FAST    = 8
# SCALP5_EMA_SLOW    = 21
# SCALP5_MACD_FAST   = 12
# SCALP5_MACD_SLOW   = 26
# SCALP5_MACD_SIG    = 9
# SCALP5_MIN_RIBBON  = 0.002
# SCALP5_OPEN_SKIP   = "09:45"
# SCALP5_EOD_CUTOFF  = "15:30"

# # Tighter risk when running scalp1 / scalp5 (main.py applies these)
# SCALP_STOP_LOSS_PCT   = 0.005   # 0.5%
# SCALP_TAKE_PROFIT_PCT = 0.01    # 1.0%



# # RS Breakout Strategy
# RS_LOOKBACK = 10              # Days for RS vs SPY
# RS_THRESHOLD = 1.05           # Fixed: 5% outperformance (was 1.50)
# RS_USE_PERCENTILE = True      # Use top N% instead of fixed
# RS_TOP_PCT = 0.20             # Top 20% of stocks by RS
# RS_BREAKOUT_DAYS = 20         # 20-day high breakout
# RS_MACD_FAST = 12
# RS_MACD_SLOW = 26
# RS_MACD_SIGNAL = 9
# RS_VOL_MULT = 1.3             # Volume 1.3x average
# RS_ATR_PERIOD = 14
# RS_ATR_STOP_MULT = 2.0        # Stop at entry - 2x ATR
# RS_ATR_TARGET_MULT = 3.0      # Target at entry + 3x ATR
# RS_TRAIL_ATR_MULT = 1.5       # Trail at highest - 1.5x ATR
# RS_MAX_HOLD = 7               # Max 7 days
# RS_MIN_HOLD_EXIT = 3          # Min 3 days before MACD exit
# RS_SPY_TREND_DAYS = 50        # SPY 50-day SMA filter
# RS_BREADTH_FILTER = True      # Market breadth check



"""
config.py — All configuration lives here.
Replace ALPACA_API_KEY and ALPACA_SECRET_KEY with your actual keys.
Get free paper trading keys: https://app.alpaca.markets
"""

# ─── Alpaca API Keys ───────────────────────────────────────────────────────────
ALPACA_API_KEY    = "PKUB3KATFKFW3UGRCR4FJCU2AI"
ALPACA_SECRET_KEY = "BpYWw6tWAm9nUTaAFztrh38BwkaBxYutQFvnCcHgeEfH"
ALPACA_BASE_URL   = "https://paper-api.alpaca.markets"
ALPACA_DATA_FEED  = "iex"

# ─── Market Data Provider ─────────────────────────────────────────────────────
# "twelvedata" = low-delay intraday bars (recommended)
# "alpaca"     = original IEX delayed feed (fallback)
DATA_PROVIDER       = "twelvedata"
TWELVE_DATA_API_KEY = "0bec98c23b3142a590d4f9efe7520fe1"

# ─── Universe of stocks to trade ──────────────────────────────────────────────
SYMBOLS = ["NVDA", "TSLA", "AMD", "QCOM", "MU", "ARM", "NOW", "STX", "MRVL", "GE"]

# ─── Strategy to use ──────────────────────────────────────────────────────────
ACTIVE_STRATEGY = "momentum"

# ─── Risk Management ──────────────────────────────────────────────────────────
MAX_POSITION_PCT     = 0.10
STOP_LOSS_PCT        = 0.02
TAKE_PROFIT_PCT      = 0.06
MAX_DAILY_LOSS_PCT   = 0.05
CLOSE_ALL_EOD        = True

# ─── SMA Crossover Strategy Params ────────────────────────────────────────────
SMA_FAST_PERIOD  = 9
SMA_SLOW_PERIOD  = 21

# ─── RSI Mean Reversion Params ────────────────────────────────────────────────
RSI_PERIOD       = 14
RSI_OVERSOLD     = 30
RSI_OVERBOUGHT   = 70

# ─── Momentum Strategy Params ─────────────────────────────────────────────────
MOMENTUM_LOOKBACK  = 20
MOMENTUM_THRESHOLD = 0.05

# ─── Scheduling ───────────────────────────────────────────────────────────────
MARKET_OPEN           = "09:30"
MARKET_CLOSE          = "16:00"
EOD_CLOSE_TIME        = "15:50"
SCAN_INTERVAL_SECONDS = 60

# ─── Logging ──────────────────────────────────────────────────────────────────
LOG_DIR   = "logs"
LOG_LEVEL = "INFO"

# ─── MA Crossover + Stop Loss Params ──────────────────────────────────────────
MA_FAST_PERIOD    = 12
MA_SLOW_PERIOD    = 26
MA_ATR_PERIOD     = 14
MA_ATR_MULT       = 2.0
MA_RISK_PER_TRADE = 0.01

# ─── Pairs Trading Params ─────────────────────────────────────────────────────
PAIRS_LOOKBACK = 60
PAIRS_ENTRY_Z  = 2.0
PAIRS_EXIT_Z   = 0.5

# ─── Factor Model Params ──────────────────────────────────────────────────────
FACTOR_MOM_LOOKBACK = 252
FACTOR_MOM_SKIP     = 21
FACTOR_MOM_WEIGHT   = 0.6
FACTOR_VAL_WEIGHT   = 0.4
FACTOR_LONG_TOP_N   = 2
FACTOR_SHORT_BOT_N  = 1

# ─── Statistical Arbitrage Params ─────────────────────────────────────────────
STAT_ARB_LOOKBACK = 120
STAT_ARB_Z_WINDOW = 30
STAT_ARB_ENTRY_Z  = 2.0
STAT_ARB_EXIT_Z   = 0.5
STAT_ARB_PVALUE   = 0.05

# ─── Random Forest ML Params ──────────────────────────────────────────────────
RF_TRAIN_BARS     = 200
RF_N_ESTIMATORS   = 100
RF_MAX_DEPTH      = 5
RF_BUY_THRESH     = 0.60
RF_SELL_THRESH    = 0.40
RF_RETRAIN_EVERY  = 1

# ─── LSTM ML Params ───────────────────────────────────────────────────────────
LSTM_SEQ_LEN       = 20
LSTM_TRAIN_BARS    = 300
LSTM_HIDDEN        = 64
LSTM_LAYERS        = 2
LSTM_EPOCHS        = 20
LSTM_LR            = 1e-3
LSTM_BATCH         = 32
LSTM_BUY_THRESH    = 0.60
LSTM_SELL_THRESH   = 0.40
LSTM_RETRAIN_EVERY = 5

# ─── Scalp Strategy Params ────────────────────────────────────────────────────
SCALP1_RSI_PERIOD     = 9
SCALP1_RSI_OVERSOLD   = 35
SCALP1_RSI_OVERBOUGHT = 65
SCALP1_VOL_PERIOD     = 20
SCALP1_VOL_MULT       = 1.5
SCALP1_EOD_CUTOFF     = "15:30"

SCALP5_EMA_FAST    = 8
SCALP5_EMA_SLOW    = 21
SCALP5_MACD_FAST   = 12
SCALP5_MACD_SLOW   = 26
SCALP5_MACD_SIG    = 9
SCALP5_MIN_RIBBON  = 0.002
SCALP5_OPEN_SKIP   = "09:45"
SCALP5_EOD_CUTOFF  = "15:30"

SCALP_STOP_LOSS_PCT   = 0.005
SCALP_TAKE_PROFIT_PCT = 0.01

# ─── RS Breakout Strategy ─────────────────────────────────────────────────────
RS_LOOKBACK        = 10
RS_THRESHOLD       = 1.05
RS_USE_PERCENTILE  = True
RS_TOP_PCT         = 0.20
RS_BREAKOUT_DAYS   = 20
RS_MACD_FAST       = 12
RS_MACD_SLOW       = 26
RS_MACD_SIGNAL     = 9
RS_VOL_MULT        = 1.3
RS_ATR_PERIOD      = 14
RS_ATR_STOP_MULT   = 2.0
RS_ATR_TARGET_MULT = 3.0
RS_TRAIL_ATR_MULT  = 1.5
RS_MAX_HOLD        = 7
RS_MIN_HOLD_EXIT   = 3
RS_SPY_TREND_DAYS  = 50
RS_BREADTH_FILTER  = True

# Momentum Enhanced Settings
MOMENTUM_LOOKBACK_LONG = 252
MOMENTUM_LOOKBACK_SHORT = 20
MOMENTUM_LOOKBACK_FAST = 10
MOMENTUM_THRESHOLD = 0.05
MOMENTUM_VOL_CRISIS_FLOOR = 0.50
MOMENTUM_MAX_DRAWDOWN = 0.10
MOMENTUM_ATR_MULT = 2.5
MOMENTUM_SCALE_TIERS = [(0.05, 0.33), (0.10, 0.33)]
MOMENTUM_QUALITY_FILTER = True
MOMENTUM_SECTOR_NEUTRAL = True
MOMENTUM_CORR_CAP = 3