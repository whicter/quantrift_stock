"""
mr_strategy.py — 均值回归进场 × ATR 追踪出场（MR + Trend Hybrid）

适用品种：大市值慢牛股（MSFT、AMZN、GOOGL、META、AAPL）及宽基 ETF（SPY、QQQ、SOXX、SMH）

入场逻辑（MR 高精度进场，保留高胜率）：
  做多：z-score ≤ -0.9（接近布林带下轨）+ RSI 超卖 + ADX 低 + close > trendSMA

出场逻辑（改为趋势追踪，骑住大行情）：
  ATR 追踪止损：trail = max(trail, close - atr_trail_mult × ATR)，只升不降
  初始止损种子：入场价 - atr_sl_mult × ATR（保护初始风险）
  时间止损：超过 max_hold_bars 根 bar 强制平仓

核心思路：
  MR 进场 → BB 下轨 + RSI 超卖 → 精确捕捉回调低点 → 高胜率
  ATR 追踪出场 → 不在中轨止盈 → 让利润在趋势中奔跑 → 高 RR
"""

from backtesting import Strategy


class MeanReversionStrategy(Strategy):
    # ── 布林带 ──────────────────────────────────────────────────
    bb_len:   int   = 20
    bb_mult:  float = 2.0

    # ── 入场条件 ────────────────────────────────────────────────
    rsi_os:   float = 40.0   # RSI 超卖阈值（做多）
    rsi_ob:   float = 60.0   # RSI 超买阈值（做空，默认关闭）
    adx_max:  float = 25.0   # ADX 上限（超过则市场处于趋势，不开仓）
    use_ci:   bool  = False  # 是否用震荡指数过滤（默认关闭）

    # ── 出场：ATR 追踪止损 ───────────────────────────────────────
    atr_trail_mult: float = 2.5  # 追踪止损：trail = close - N × ATR（只升不降）
    atr_sl_mult:    float = 2.0  # 初始止损种子：entry - M × ATR

    # ── 时间止损 ────────────────────────────────────────────────
    max_hold_bars: int = 30    # 超过 N 根 bar 强制平仓

    # ── 趋势过滤 ────────────────────────────────────────────────
    use_trend_filter: bool = True   # 开启后只在 close > trendSMA 时做多

    # ── 方向控制 ────────────────────────────────────────────────
    allow_short: bool = False   # 大牛市品种默认只做多

    # ── 合约设置 ────────────────────────────────────────────────
    n_contracts:   int = 1
    contract_size: int = 1

    def init(self):
        self._entry_price = 0.0
        self._entry_dir   = 0      # +1 多, -1 空
        self._trail_stop  = 0.0    # ATR 追踪止损价格
        self._bars_held   = 0
        self._trade_size  = (self.n_contracts * self.contract_size
                             if self.n_contracts > 0 else None)

    def next(self):
        if len(self.data.Close) < self.bb_len + 5:
            return

        close = self.data.Close[-1]
        rsi   = self.data.rsiVal[-1]
        adx   = self.data.adxVal[-1]
        atr   = float(self.data.atrVal[-1])
        if atr <= 0:
            atr = close * 0.01

        # ── 持仓管理 ─────────────────────────────────────────────
        if self.position:
            self._bars_held += 1
            d = self._entry_dir

            # 更新 ATR 追踪止损（只向有利方向移动）
            candidate = close - d * self.atr_trail_mult * atr
            if d == 1 and candidate > self._trail_stop:
                self._trail_stop = candidate
            elif d == -1 and candidate < self._trail_stop:
                self._trail_stop = candidate

            # ① ATR 追踪止损触发
            hit_trail = (d == 1 and close < self._trail_stop) or \
                        (d == -1 and close > self._trail_stop)

            # ② 时间止损
            hit_time = self._bars_held >= self.max_hold_bars

            if hit_trail or hit_time:
                self.position.close()
                self._entry_dir  = 0
                self._trail_stop = 0.0
                self._bars_held  = 0
            return

        # ── 入场条件检查 ─────────────────────────────────────────
        is_choppy    = bool(self.data.isChoppy[-1])
        above_trend  = bool(self.data.aboveTrend[-1])
        ok_adx       = adx < self.adx_max
        ok_choppy    = (not self.use_ci) or is_choppy
        ok_trend_long  = (not self.use_trend_filter) or above_trend
        ok_trend_short = (not self.use_trend_filter) or (not above_trend)

        z = float(self.data.zScore[-1])
        touch_lower = z <= -0.9
        touch_upper = z >=  0.9

        long_signal  = (touch_lower and rsi < self.rsi_os
                        and ok_adx and ok_choppy and ok_trend_long)
        short_signal = (self.allow_short and touch_upper
                        and rsi > self.rsi_ob and ok_adx
                        and ok_choppy and ok_trend_short)

        if long_signal:
            self._entry_price = close
            self._entry_dir   = 1
            self._bars_held   = 0
            self._trail_stop  = close - self.atr_sl_mult * atr  # 初始止损种子
            self.buy(size=self._trade_size)

        elif short_signal:
            self._entry_price = close
            self._entry_dir   = -1
            self._bars_held   = 0
            self._trail_stop  = close + self.atr_sl_mult * atr
            self.sell(size=self._trade_size)
