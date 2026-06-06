"""
Markov Regime Detection Engine
================================
ใช้ Gaussian HMM (Hidden Markov Model) จาก hmmlearn
เพื่อแยกแยะ 5 สภาวะตลาด:

  STRONG_BULL | BULL | RANGE | BEAR | STRONG_BEAR

Features ที่ใช้ train HMM (4 dimensions):
  1. daily_return        — log return รายวัน
  2. rolling_vol_20      — rolling std 20 วัน (annualised)
  3. momentum_score      — EMA12/EMA26 spread normalised
  4. rsi_normalised      — (RSI - 50) / 50  → [-1, +1]

Outputs:
  current_regime        : str
  regime_probability    : float (0–1)
  confidence            : float (0–100)
  transition_matrix     : dict[str, dict[str, float]]
  expected_next_regime  : str
  regime_probs_all      : dict[str, float]  ทุก state
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from hmmlearn.hmm import GaussianHMM

logger = logging.getLogger(__name__)

N_STATES   = 5
N_ITER     = 200
RANDOM_SEED = 42

# ── State labels — assigned AFTER fitting by sorting mean return ──────────────
STATE_LABELS = ["STRONG_BEAR", "BEAR", "RANGE", "BULL", "STRONG_BULL"]


@dataclass(frozen=True)
class RegimeResult:
    current_regime:       str
    regime_probability:   float          # probability of current state (0–1)
    confidence:           float          # 0–100  (probability × clarity score)
    regime_probs_all:     dict[str, float]
    transition_matrix:    dict[str, dict[str, float]]
    expected_next_regime: str
    feature_snapshot:     dict[str, float]
    trade_permission:     str            # LONG_ONLY | SHORT_ONLY | BOTH | NO_TRADE
    position_size_mult:   float          # 0.50 | 0.75 | 1.00


# ──────────────────────────────────────────────────────────────────────────────
# FEATURE ENGINEERING
# ──────────────────────────────────────────────────────────────────────────────
def _build_features(df: pd.DataFrame) -> np.ndarray:
    """
    Build (T × 4) feature matrix from OHLCV + EMA/RSI columns.
    Requires: Close, EMA12, EMA26, RSI14
    """
    close = df["Close"]

    log_ret  = np.log(close / close.shift(1)).fillna(0)
    roll_vol = log_ret.rolling(20).std().fillna(log_ret.std()) * np.sqrt(252)

    ema12 = df.get("EMA12", close.ewm(span=12, adjust=False).mean())
    ema26 = df.get("EMA26", close.ewm(span=26, adjust=False).mean())
    momentum = ((ema12 - ema26) / ema26.replace(0, np.nan)).fillna(0)

    rsi14 = df.get("RSI14", pd.Series(50.0, index=df.index))
    rsi_norm = ((rsi14 - 50) / 50).fillna(0)

    X = np.column_stack([
        log_ret.to_numpy(),
        roll_vol.to_numpy(),
        momentum.to_numpy(),
        rsi_norm.to_numpy(),
    ])
    return X.astype(np.float64)


# ──────────────────────────────────────────────────────────────────────────────
# STATE → LABEL MAPPING  (by mean return ascending)
# ──────────────────────────────────────────────────────────────────────────────
def _assign_labels(model: GaussianHMM) -> list[str]:
    """
    Map HMM hidden states → regime labels by sorting mean daily return.
    State with lowest mean return → STRONG_BEAR, highest → STRONG_BULL.
    """
    mean_returns = model.means_[:, 0]   # feature 0 = log return
    order = np.argsort(mean_returns)    # ascending
    labels = [""] * N_STATES
    for rank, state_idx in enumerate(order):
        labels[state_idx] = STATE_LABELS[rank]
    return labels


# ──────────────────────────────────────────────────────────────────────────────
# TRADE PERMISSION
# ──────────────────────────────────────────────────────────────────────────────
_PERMISSION_MAP = {
    "STRONG_BULL": ("LONG_ONLY",  1.00),
    "BULL":        ("LONG_ONLY",  0.75),
    "RANGE":       ("BOTH",       0.50),
    "BEAR":        ("SHORT_ONLY", 0.75),
    "STRONG_BEAR": ("SHORT_ONLY", 1.00),
}


# ──────────────────────────────────────────────────────────────────────────────
# MAIN ENGINE
# ──────────────────────────────────────────────────────────────────────────────
class MarkovRegimeEngine:
    """
    Fits a GaussianHMM on the provided DataFrame and decodes the current regime.

    Usage
    -----
    engine = MarkovRegimeEngine()
    result = engine.detect(df)
    """

    def __init__(self, n_states: int = N_STATES, n_iter: int = N_ITER):
        self.n_states  = n_states
        self.n_iter    = n_iter
        self._model: GaussianHMM | None = None
        self._labels: list[str] = []

    # ── Fit ───────────────────────────────────────────────────────────────────
    def _fit(self, X: np.ndarray) -> None:
        model = GaussianHMM(
            n_components = self.n_states,
            covariance_type = "diag",
            n_iter = self.n_iter,
            random_state = RANDOM_SEED,
            verbose = False,
        )
        model.fit(X)
        self._model  = model
        self._labels = _assign_labels(model)
        logger.debug("HMM fitted  converged=%s", model.monitor_.converged)

    # ── Decode ────────────────────────────────────────────────────────────────
    def detect(self, df: pd.DataFrame) -> RegimeResult:
        """
        Fit HMM on df and return current regime with full metadata.

        Parameters
        ----------
        df : daily OHLCV DataFrame — must have Close, EMA12, EMA26, RSI14
        """
        if len(df) < 60:
            raise ValueError("Need ≥ 60 bars to fit HMM reliably")

        X = _build_features(df)

        try:
            self._fit(X)
        except Exception as exc:
            logger.error("HMM fit failed: %s", exc)
            raise

        # Viterbi decode → most likely state sequence
        state_sequence = self._model.predict(X)
        current_state  = int(state_sequence[-1])
        current_regime = self._labels[current_state]

        # Posterior probabilities for the last observation
        log_posteriors = self._model.predict_proba(X)
        last_probs     = log_posteriors[-1]          # shape (n_states,)

        # Map state → label → probability
        regime_probs_all: dict[str, float] = {
            self._labels[i]: round(float(last_probs[i]), 4)
            for i in range(self.n_states)
        }
        regime_probability = regime_probs_all[current_regime]

        # Confidence = probability × (1 + structure_clarity)
        # structure_clarity: how much higher is the top prob vs 2nd highest
        sorted_probs = sorted(last_probs, reverse=True)
        clarity = (sorted_probs[0] - sorted_probs[1]) if len(sorted_probs) >= 2 else 0
        confidence = round(float(regime_probability * (1 + clarity)) * 100, 1)
        confidence = min(100.0, confidence)

        # Transition matrix  (transmat_ rows = from state, cols = to state)
        trans = self._model.transmat_
        transition_matrix: dict[str, dict[str, float]] = {}
        for i, from_label in enumerate(self._labels):
            transition_matrix[from_label] = {
                self._labels[j]: round(float(trans[i, j]), 4)
                for j in range(self.n_states)
            }

        # Expected next regime = argmax of current state's transition row
        next_state_idx    = int(np.argmax(trans[current_state]))
        expected_next     = self._labels[next_state_idx]

        # Feature snapshot for the report
        last_row = X[-1]
        feature_snapshot = {
            "daily_return":   round(float(last_row[0]) * 100, 4),   # in %
            "rolling_vol_20": round(float(last_row[1]) * 100, 2),   # annualised %
            "momentum_score": round(float(last_row[2]) * 100, 2),   # EMA spread %
            "rsi_normalised": round(float(last_row[3]), 3),
        }

        permission, size_mult = _PERMISSION_MAP.get(current_regime, ("NO_TRADE", 0.0))

        return RegimeResult(
            current_regime       = current_regime,
            regime_probability   = round(regime_probability, 4),
            confidence           = confidence,
            regime_probs_all     = regime_probs_all,
            transition_matrix    = transition_matrix,
            expected_next_regime = expected_next,
            feature_snapshot     = feature_snapshot,
            trade_permission     = permission,
            position_size_mult   = size_mult,
        )
