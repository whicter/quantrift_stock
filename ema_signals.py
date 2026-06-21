"""
ema_signals.py — EMA Pullback 策略信号计算

输出列：
  ema21   — 21期 EMA（入场触发线）
  ema50   — 50期 EMA（中期趋势 / 出场线）
  ema200  — 200期 EMA（牛熊过滤）
  atrVal  — 14期 ATR（止损定大小）
  rsiVal  — RSI（回调深度过滤）
"""

import pandas as pd

from indicators import _ema, _atr, _rsi


def compute_ema_signals(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """
    输入标准 OHLCV DataFrame，返回追加了 EMA Pullback 信号列的新 DataFrame。
    """
    high  = df["High"]
    low   = df["Low"]
    close = df["Close"]

    ema_fast_len = int(params.get("ema_fast_len", 21))
    ema_mid_len  = int(params.get("ema_mid_len",  50))
    ema_slow_len = int(params.get("ema_slow_len", 200))
    atr_len      = int(params.get("atr_len",      14))
    rsi_len      = int(params.get("rsi_len",      14))

    result = df.copy()
    result["ema21"]  = _ema(close, ema_fast_len)
    result["ema50"]  = _ema(close, ema_mid_len)
    result["ema200"] = _ema(close, ema_slow_len)
    result["atrVal"] = _atr(high, low, close, atr_len)
    result["rsiVal"] = _rsi(close, rsi_len)
    return result
