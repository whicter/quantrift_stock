"""
harmonic_strategy.py — 谐波形态入场 × ATR 追踪出场（研究原型）

入场：harmonic_signals.py 算出的 D 点触及信号（做多/做空）
出场：
  初始止损种子 = 信号 bar 的 X 点价格（谐波结构本身的失效位），而非固定
  ATR 倍数——这是与 mr_strategy.py 唯一的出场差异，其余（ATR 追踪只朝有利
  方向移动、时间止损）逻辑完全一致，便于横向比较两个策略。
"""

from backtesting import Strategy


class HarmonicStrategy(Strategy):
    atr_trail_mult: float = 2.5   # 追踪止损：trail = close - N × ATR（只升不降）
    max_hold_bars:  int   = 40    # 超过 N 根 bar 强制平仓
    allow_short:    bool  = True

    n_contracts:   int = 1
    contract_size: int = 1

    def init(self):
        self._entry_dir  = 0
        self._trail_stop = 0.0
        self._bars_held  = 0
        self._trade_size = (self.n_contracts * self.contract_size
                            if self.n_contracts > 0 else None)

    def next(self):
        close = self.data.Close[-1]
        atr   = float(self.data.atrVal[-1])
        if atr <= 0:
            atr = close * 0.01

        if self.position:
            self._bars_held += 1
            d = self._entry_dir

            candidate = close - d * self.atr_trail_mult * atr
            if d == 1 and candidate > self._trail_stop:
                self._trail_stop = candidate
            elif d == -1 and candidate < self._trail_stop:
                self._trail_stop = candidate

            hit_trail = (d == 1 and close < self._trail_stop) or \
                        (d == -1 and close > self._trail_stop)
            hit_time  = self._bars_held >= self.max_hold_bars

            if hit_trail or hit_time:
                self.position.close()
                self._entry_dir  = 0
                self._trail_stop = 0.0
                self._bars_held  = 0
            return

        long_signal  = bool(self.data.harmLong[-1])
        short_signal = self.allow_short and bool(self.data.harmShort[-1])

        if long_signal:
            self._entry_dir  = 1
            self._bars_held   = 0
            self._trail_stop  = float(self.data.harmSL[-1])  # X 点价格，谐波结构失效位
            self.buy(size=self._trade_size)
        elif short_signal:
            self._entry_dir  = -1
            self._bars_held   = 0
            self._trail_stop  = float(self.data.harmSL[-1])
            self.sell(size=self._trade_size)
