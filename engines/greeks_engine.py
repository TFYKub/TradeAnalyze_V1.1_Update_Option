"""
Black-Scholes Greeks Calculator
================================
Computes Delta, Gamma, Theta, Vega, Rho for European options.

References
----------
- Hull, J.C. "Options, Futures, and Other Derivatives" (10th ed.)
- Put-call parity: delta_call - delta_put = 1  ✓
"""

import math
import logging

from scipy.stats import norm

logger = logging.getLogger(__name__)

RISK_FREE_RATE = 0.05          # annualised, adjustable
MIN_IV        = 0.001           # floor to avoid division by zero
MIN_T         = 1 / 365         # floor = 1 day


def black_scholes_greeks(
    S: float,          # spot price
    K: float,          # strike price
    T: float,          # time-to-expiry in years
    sigma: float,      # implied volatility (annualised)
    r: float = RISK_FREE_RATE,
    option_type: str = "call",   # "call" | "put"
) -> dict:
    """
    Return a dict with keys: delta, gamma, theta, vega, rho.

    Returns empty dict if inputs are degenerate (T≤0, sigma≤0, S≤0, K≤0).
    """

    if any(v <= 0 for v in (S, K)):
        return {}

    T     = max(T, MIN_T)
    sigma = max(sigma, MIN_IV)
    sign  = 1 if option_type == "call" else -1

    try:
        sqrt_T = math.sqrt(T)
        d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt_T)
        d2 = d1 - sigma * sqrt_T

        pdf_d1 = norm.pdf(d1)
        cdf_d1 = norm.cdf(sign * d1)
        cdf_d2 = norm.cdf(sign * d2)
        disc   = math.exp(-r * T)

        delta = sign * cdf_d1
        gamma = pdf_d1 / (S * sigma * sqrt_T)
        # Theta per calendar day
        theta = (
            -(S * pdf_d1 * sigma) / (2 * sqrt_T)
            - sign * r * K * disc * cdf_d2
        ) / 365
        vega  = S * pdf_d1 * sqrt_T / 100   # per 1 % IV move
        rho   = sign * K * T * disc * cdf_d2 / 100   # per 1 % rate move

        return {
            "delta": round(float(delta), 5),
            "gamma": round(float(gamma), 6),
            "theta": round(float(theta), 5),
            "vega":  round(float(vega),  5),
            "rho":   round(float(rho),   5),
        }

    except Exception as exc:
        logger.debug(f"greeks error S={S} K={K} T={T} sigma={sigma}: {exc}")
        return {}


def greeks_signal_score(greeks: dict, option_type: str) -> dict:
    """
    Convert Greeks into trading-signal hints.

    Returns a dict with human-readable flags used downstream.
    """

    delta = abs(greeks.get("delta", 0))
    gamma = greeks.get("gamma", 0)
    theta = greeks.get("theta", 0)
    vega  = greeks.get("vega",  0)

    return {
        # Moneyness proxy
        "moneyness": (
            "ITM"  if delta > 0.65 else
            "OTM"  if delta < 0.35 else
            "ATM"
        ),
        # Gamma risk flag
        "high_gamma": gamma > 0.05,

        # Theta decay category
        "theta_category": (
            "FAST_DECAY" if theta < -0.15 else
            "SLOW_DECAY" if theta > -0.05 else
            "MODERATE_DECAY"
        ),

        # Vega exposure category
        "vega_category": (
            "HIGH_VEGA"    if vega > 0.25 else
            "LOW_VEGA"     if vega < 0.08 else
            "MODERATE_VEGA"
        ),

        # Directional bias from delta
        "direction_bias": (
            "STRONG_DIRECTIONAL" if delta > 0.70 else
            "MODERATE_DIRECTIONAL" if delta > 0.45 else
            "NEUTRAL_GAMMA_PLAY"
        ),
    }
