"""
mr_signals.py — 均值回归策略信号计算

复用 indicators.py 中的基础函数，输出 MR 策略所需列：
  bbUpper, bbMiddle, bbLower  — 布林带
  rsiVal                      — RSI
  adxVal                      — ADX
  atrVal                      — ATR
  isChoppy                    — 震荡过滤（CI）
  zScore                      — 价格相对布林带的 z-score（-1 到 +1）
"""

import numpy as np
import pandas as pd

from indicators import _atr, _adx, _rsi, _ema, _sma, _rma, _true_range


def compute_mr_signals(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """
    输入标准 OHLCV DataFrame，返回追加了 MR 信号列的新 DataFrame。
    """
    high  = df["High"]
    low   = df["Low"]
    close = df["Close"]

    # ── 布林带 ────────────────────────────────────────────────────
    bb_len  = int(params.get("bb_len", 20))
    bb_mult = float(params.get("bb_mult", 2.0))
    bb_mid  = _sma(close, bb_len)
    bb_std  = close.rolling(bb_len, min_periods=bb_len).std(ddof=1)
    bb_upper = bb_mid + bb_mult * bb_std
    bb_lower = bb_mid - bb_mult * bb_std

    # z-score：price 在布林带中的相对位置（-1=下轨，0=中轨，+1=上轨）
    band_width = bb_upper - bb_lower
    z_score = (2 * (close - bb_mid) / band_width.replace(0, np.nan)).clip(-2, 2)

    # ── RSI ──────────────────────────────────────────────────────
    rsi_len = int(params.get("rsi_len", 14))
    rsi_val = _rsi(close, rsi_len)

    # ── ADX ──────────────────────────────────────────────────────
    adx_len = int(params.get("adx_len", 14))
    adx_val = _adx(high, low, close, adx_len)

    # ── ATR ──────────────────────────────────────────────────────
    atr_val = _atr(high, low, close, 14)

    # ── Choppiness Index ─────────────────────────────────────────
    ci_len   = int(params.get("ci_len", 14))
    tr       = _true_range(high, low, close)
    ci_atr   = tr.rolling(ci_len, min_periods=ci_len).sum()
    ci_range = (high.rolling(ci_len).max() - low.rolling(ci_len).min())
    choppiness = 100 * np.log10(ci_atr / ci_range) / np.log10(ci_len)
    ci_threshold = float(params.get("ci_threshold", 50.0))
    is_choppy = (choppiness > ci_threshold).fillna(False)

    # ── Volume MA ────────────────────────────────────────────────
    vol_len = int(params.get("vol_len", 20))
    vol_ma  = df["Volume"].rolling(vol_len, min_periods=vol_len).mean()

    # ── Trend Filter SMA ─────────────────────────────────────────
    trend_len  = int(params.get("trend_filter_len", 200))
    trend_sma  = _sma(close, trend_len)
    above_trend = (close > trend_sma).fillna(False)

    result = df.copy()
    result["bbUpper"]    = bb_upper
    result["bbMiddle"]   = bb_mid
    result["bbLower"]    = bb_lower
    result["zScore"]     = z_score
    result["rsiVal"]     = rsi_val
    result["adxVal"]     = adx_val
    result["atrVal"]     = atr_val
    result["isChoppy"]   = is_choppy.astype(float)
    result["volMA"]      = vol_ma
    result["trendSMA"]   = trend_sma
    result["aboveTrend"] = above_trend.astype(float)
    return result
