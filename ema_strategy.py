"""
ema_strategy.py — EMA Pullback 趋势跟踪策略

适用品种：大市值慢牛股（MSFT、AMZN、GOOGL、META、AAPL）及宽基 ETF（SPY、QQQ、SOXX、SMH）

核心逻辑：
  不同于动量突破（ConfluenceStrategy）和均值回归（MeanReversionStrategy），
  本策略捕捉"上升趋势中的回调买入"——价格回踩 21 EMA 时分批入场，
  用 ATR 追踪止盈骑住趋势，而非在中轨止盈。

入场（只做多）：
  ① close > ema200  — 价格在牛市（200 EMA 上方）
  ② close > ema50   — 中期趋势完好（50 EMA 支撑）
  ③ low  ≤ ema21 × (1 + touch_band) 且 close ≥ ema21 × (1 - touch_band)
     — 当日低点触及 21 EMA 但收盘未深度跌破（EMA 支撑确认）
  ④ rsi < rsi_dip   — RSI 轻度回落（通常 45-55，不要求超卖）

出场：
  ① ATR 追踪止损：trail = max(trail, close - atr_trail_mult × ATR)，只升不降
  ② 趋势破坏：close < ema50（跌破中期趋势线）
  ③ 时间止损：超过 max_hold_bars 根 bar

关键差异：
  vs ConfluenceStrategy：不需要 ADX 高、不需要 UTBot/SSL 同时触发；
                         专为低 ADX 的慢牛环境设计
  vs MeanReversionStrategy：出场用追踪止损而非中轨，可跑出 2-5× RR
"""

import math

from backtesting import Strategy


class EMABounceStrategy(Strategy):
    # ── EMA 参数 ────────────────────────────────────────────────────────────
    ema_fast_len: int   = 21    # 入场触发 EMA（21 日均线）
    ema_mid_len:  int   = 50    # 中期趋势线 / 出场线（50 日均线）
    ema_slow_len: int   = 200   # 牛熊过滤线（200 日均线）

    # ── 入场条件 ────────────────────────────────────────────────────────────
    rsi_dip:    float = 52.0   # RSI 须低于此值（轻度回调即可，不要求超卖）
    touch_band: float = 0.003  # EMA21 触碰容差（±0.3%）

    # ── 出场：ATR 追踪止损 ───────────────────────────────────────────────────
    atr_trail_mult: float = 2.5  # trail_stop = close - N × ATR（只升不降）
    atr_sl_mult:    float = 1.5  # 入场时初始止损种子：entry - M × ATR

    # ── 时间止损 ────────────────────────────────────────────────────────────
    max_hold_bars: int = 60     # 默认 60 根 bar（1d: ≈3个月）

    # ── 合约设置 ────────────────────────────────────────────────────────────
    n_contracts:   int = 1
    contract_size: int = 1

    def init(self):
        self._trail_stop  = 0.0
        self._entry_price = 0.0
        self._bars_held   = 0
        self._trade_size  = (self.n_contracts * self.contract_size
                             if self.n_contracts > 0 else None)

    def next(self):
        # 200 EMA 需要足够数据预热
        if len(self.data.Close) < self.ema_slow_len + 5:
            return

        close  = self.data.Close[-1]
        low    = self.data.Low[-1]
        ema21  = float(self.data.ema21[-1])
        ema50  = float(self.data.ema50[-1])
        ema200 = float(self.data.ema200[-1])
        atr    = float(self.data.atrVal[-1])
        rsi    = float(self.data.rsiVal[-1])

        # 防御：指标未就绪则跳过
        if any(math.isnan(v) for v in [ema21, ema50, ema200, atr, rsi]):
            return
        if atr <= 0:
            atr = close * 0.01

        # ── 持仓管理 ──────────────────────────────────────────────────────
        if self.position:
            self._bars_held += 1

            # 更新追踪止损（只升不降）
            candidate = close - self.atr_trail_mult * atr
            if candidate > self._trail_stop:
                self._trail_stop = candidate

            # ① ATR 追踪止损触发
            if close < self._trail_stop:
                self.position.close()
                self._bars_held  = 0
                self._trail_stop = 0.0
                return

            # ② 跌破 50 EMA = 中期趋势破坏
            if close < ema50:
                self.position.close()
                self._bars_held  = 0
                self._trail_stop = 0.0
                return

            # ③ 时间止损
            if self._bars_held >= self.max_hold_bars:
                self.position.close()
                self._bars_held  = 0
                self._trail_stop = 0.0
            return

        # ── 入场条件检查 ───────────────────────────────────────────────────

        # ① 价格在 200 EMA 上方（牛市）
        if close <= ema200:
            return

        # ② 价格在 50 EMA 上方（中期趋势完好）
        if close <= ema50:
            return

        # ③ 当日低点触及 21 EMA，收盘仍在 EMA 附近或上方（EMA 支撑确认）
        touched = (
            low   <= ema21 * (1.0 + self.touch_band) and
            close >= ema21 * (1.0 - self.touch_band)
        )
        if not touched:
            return

        # ④ RSI 轻度回落（排除顶部超买区域）
        if rsi >= self.rsi_dip:
            return

        # ── 开仓 ──────────────────────────────────────────────────────────
        self._entry_price = close
        self._bars_held   = 0
        # 初始止损种子（同时作为追踪止损的下界起点）
        self._trail_stop  = close - self.atr_sl_mult * atr
        self.buy(size=self._trade_size)
