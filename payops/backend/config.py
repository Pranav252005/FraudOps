"""Domain configuration for the payment-ops simulation.

Everything the simulator, detector and agent know about the world lives here so
the demo can be re-shaped (more banks, different rails) without touching logic.
"""
from __future__ import annotations

# --- Dimensions -------------------------------------------------------------

BANKS = ["HDFC", "ICICI", "SBI", "AXIS", "KOTAK", "YES", "IDFC", "PNB"]
METHODS = ["UPI", "CARD", "NETBANKING", "WALLET"]

# Which rails Razorpay can route each method over. This is what makes a reroute
# possible: a method with >1 eligible PSP has somewhere healthy to go.
PSPS_BY_METHOD = {
    "UPI":        ["AXIS-PSP", "YES-PSP", "ICICI-PSP"],
    "CARD":       ["HDFC-ACQ", "ICICI-ACQ", "YES-ACQ"],
    "NETBANKING": ["DIRECT"],
    "WALLET":     ["WALLET-AGG"],
}

ALL_PSPS = sorted({p for v in PSPS_BY_METHOD.values() for p in v})

# Default routing weights the agent is allowed to rewrite at runtime.
DEFAULT_ROUTING = {
    "UPI":        {"AXIS-PSP": 0.45, "YES-PSP": 0.35, "ICICI-PSP": 0.20},
    "CARD":       {"HDFC-ACQ": 0.45, "ICICI-ACQ": 0.35, "YES-ACQ": 0.20},
    "NETBANKING": {"DIRECT": 1.0},
    "WALLET":     {"WALLET-AGG": 1.0},
}

# Share of total traffic. Roughly mirrors the Indian mix: UPI dominant.
METHOD_MIX = {"UPI": 0.62, "CARD": 0.22, "NETBANKING": 0.10, "WALLET": 0.06}
BANK_MIX = {
    "HDFC": 0.21, "ICICI": 0.16, "SBI": 0.19, "AXIS": 0.12,
    "KOTAK": 0.09, "YES": 0.07, "IDFC": 0.08, "PNB": 0.08,
}

MERCHANT_CATEGORIES = ["E-commerce", "Travel", "EdTech", "Gaming", "Utilities", "SaaS"]
REGIONS = ["North", "South", "West", "East"]

# --- Health model -----------------------------------------------------------

# Healthy long-run success rate per (bank, method). Cards are the weakest rail,
# wallets the strongest -- the same shape you see in real Indian payment data.
BASE_SUCCESS = {
    "UPI":        {"HDFC": 0.951, "ICICI": 0.944, "SBI": 0.918, "AXIS": 0.947,
                   "KOTAK": 0.939, "YES": 0.933, "IDFC": 0.942, "PNB": 0.905},
    "CARD":       {"HDFC": 0.902, "ICICI": 0.887, "SBI": 0.845, "AXIS": 0.881,
                   "KOTAK": 0.874, "YES": 0.862, "IDFC": 0.869, "PNB": 0.831},
    "NETBANKING": {"HDFC": 0.884, "ICICI": 0.871, "SBI": 0.822, "AXIS": 0.866,
                   "KOTAK": 0.858, "YES": 0.845, "IDFC": 0.851, "PNB": 0.808},
    "WALLET":     {"HDFC": 0.972, "ICICI": 0.969, "SBI": 0.964, "AXIS": 0.970,
                   "KOTAK": 0.967, "YES": 0.963, "IDFC": 0.966, "PNB": 0.958},
}

# Small persistent per-PSP quality differences (healthy state).
PSP_HEALTH = {
    "AXIS-PSP": 1.000, "YES-PSP": 0.994, "ICICI-PSP": 0.997,
    "HDFC-ACQ": 1.000, "ICICI-ACQ": 0.996, "YES-ACQ": 0.991,
    "DIRECT": 1.000, "WALLET-AGG": 1.000,
}

# Volume shape across the day (IST). Index = hour.
HOUR_VOLUME = [
    0.22, 0.14, 0.09, 0.07, 0.08, 0.13, 0.24, 0.42,
    0.61, 0.78, 0.90, 0.98, 1.00, 0.95, 0.88, 0.86,
    0.90, 0.95, 1.00, 1.06, 1.08, 0.92, 0.66, 0.40,
]
WEEKDAY_VOLUME = [1.00, 1.02, 1.01, 1.03, 1.08, 1.12, 0.94]  # Mon..Sun

# Success is slightly worse at peak load, and netbanking suffers in the
# 00:00-03:00 bank maintenance window. This is the seasonality that makes a
# static threshold wrong and a per-hour baseline right.
def hour_health(method: str, hour: int) -> float:
    load = HOUR_VOLUME[hour]
    f = 1.0 - 0.022 * max(0.0, load - 0.75)
    if method == "NETBANKING" and hour in (0, 1, 2):
        f *= 0.955
    if method == "UPI" and hour in (19, 20, 21):
        f *= 0.994
    return f

import os

BASE_TPM = 5200          # transactions per simulated minute at load factor 1.0
# One tick advances the simulation by one minute. The wall-clock spacing is
# adjustable so a demo can be slowed down enough to narrate.
SECONDS_PER_TICK = float(os.environ.get("PAYOPS_TICK_SECONDS", "1.4"))
MINUTES_PER_TICK = 1

# --- Failure taxonomy -------------------------------------------------------

# Healthy failure mix per method: what normal failure looks like.
NORMAL_ERRORS = {
    "UPI": {"INSUFFICIENT_FUNDS": 0.34, "UPI_USER_DECLINED": 0.27,
            "PSP_TIMEOUT": 0.14, "INVALID_VPA": 0.13, "ISSUER_TIMEOUT": 0.12},
    "CARD": {"DO_NOT_HONOUR": 0.31, "INSUFFICIENT_FUNDS": 0.22,
             "AUTH_3DS_DROPOFF": 0.24, "ISSUER_TIMEOUT": 0.13, "ACQUIRER_ERROR": 0.10},
    "NETBANKING": {"BANK_PAGE_TIMEOUT": 0.36, "USER_ABANDONED": 0.33,
                   "INSUFFICIENT_FUNDS": 0.18, "BANK_DOWN": 0.13},
    "WALLET": {"INSUFFICIENT_BALANCE": 0.52, "USER_ABANDONED": 0.31,
               "WALLET_TIMEOUT": 0.17},
}

# When a rail degrades, failures do not spread evenly -- they pile into one
# code. That skew is the single strongest diagnostic signal.
OUTAGE_ERROR = {
    "UPI":        {"psp": "PSP_TIMEOUT", "issuer": "ISSUER_TIMEOUT"},
    "CARD":       {"psp": "ACQUIRER_ERROR", "issuer": "ISSUER_TIMEOUT"},
    "NETBANKING": {"psp": "BANK_PAGE_TIMEOUT", "issuer": "BANK_DOWN"},
    "WALLET":     {"psp": "WALLET_TIMEOUT", "issuer": "WALLET_TIMEOUT"},
}

# --- Detection tuning -------------------------------------------------------

WINDOW_MINUTES = 3        # rolling evaluation window
MIN_WINDOW_VOLUME = 60    # below this, a slice is too thin to judge
Z_ALERT = -4.0            # sustained z below this opens an incident
Z_CLEAR = -1.75           # z above this for CLEAR_WINDOWS closes it
BREACH_WINDOWS = 2        # consecutive breaching windows before we page
CLEAR_WINDOWS = 3
MIN_ABS_DROP = 0.015      # ignore statistically-loud but operationally-trivial dips

HISTORY_DAYS = 14         # baseline warm-up backfilled at boot
SPARK_POINTS = 40
