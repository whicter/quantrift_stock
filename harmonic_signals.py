"""
harmonic_signals.py — 谐波形态（Gartley/Bat/Butterfly/Crab）信号计算，研究原型

方法（刻意避免 lookahead）：
  1. 用 ATR 阈值 zigzag 识别摆动点（pivot）：价格从跟踪中的极值反向突破
     atr_mult×ATR 后，该极值才被"确认"为 pivot。确认时刻必然晚于实际高低点
     发生的时刻，但只用到确认那一刻为止已知的数据，不窥视未来。
  2. 每当第 4 个 pivot（记为 C）被确认，此刻 X-A-B-C 全部已知。按四种经典
     谐波形态的斐波那契比例窗口（AB/XA、BC/AB）匹配形态类型（可能同时匹配
     多种，取并集）。
  3. 用匹配形态的 CD/BC 与 AD/XA 比例窗口，从已确认的 X-A-B-C 投射 D 点的
     价格区间（PRZ，潜在反转区）——这一步只用已确认的历史 pivot 价格计算，
     不依赖任何未来 bar。
  4. 从 C 之后逐 bar 检查该 bar 的 High/Low 是否触及 PRZ；触及则在该 bar
     收盘产生信号（backtesting.py 按项目惯例于下一 bar 开盘成交）。若价格
     先跌破/突破 X 点（结构失效）或超过 max_wait_bars 仍未触及，则该 PRZ
     作废，不产生信号。

出场沿用 mr_strategy.py 的机制（ATR 追踪 + 时间止损），初始止损种子改为
X 点价格（谐波结构本身定义的失效位），而非固定 ATR 倍数——这是本原型与
MR 策略的唯一出场差异。斐波那契目标位出场（TP1/TP2 回撤至 A 点附近）留
待原型验证入场逻辑本身有效后再细化，当前不做。
"""

import numpy as np
import pandas as pd

from indicators import _atr

# 四种经典谐波形态的比例窗口（AB/XA, BC/AB, CD/BC, AD/XA），标准教材区间
# 各放宽约 ±3-5% 容差，避免过度精确匹配导致样本量过小。
PATTERNS = {
    "gartley":   dict(ab_xa=(0.55, 0.68), bc_ab=(0.35, 0.90), cd_bc=(1.10, 1.65), ad_xa=(0.73, 0.85)),
    "bat":       dict(ab_xa=(0.35, 0.53), bc_ab=(0.35, 0.90), cd_bc=(1.55, 2.65), ad_xa=(0.83, 0.95)),
    "butterfly": dict(ab_xa=(0.73, 0.85), bc_ab=(0.35, 0.90), cd_bc=(1.55, 2.30), ad_xa=(1.20, 1.65)),
    "crab":      dict(ab_xa=(0.35, 0.65), bc_ab=(0.35, 0.90), cd_bc=(2.20, 3.65), ad_xa=(1.55, 1.65)),
}


def _find_pivots(high: np.ndarray, low: np.ndarray, atr: np.ndarray, atr_mult: float):
    """ATR 阈值 zigzag。返回 [(bar_pos, price, 'H'/'L'), ...]，按确认顺序
    （由构造保证严格交替），每个 pivot 仅使用确认时刻为止已知的数据。"""
    n = len(high)
    pivots: list[tuple[int, float, str]] = []
    if n < 2:
        return pivots

    # 引导期：从 bar0 起同时跟踪两侧候选极值，谁先突破阈值谁定初始方向。
    # 引导期本身不产生 pivot（避免把序列起点误判为真实转折），对多年历史
    # 回测的影响可忽略。
    direction = 0
    up_price, up_pos = high[0], 0
    dn_price, dn_pos = low[0], 0
    i = 1
    while direction == 0 and i < n:
        a = atr[i]
        if np.isfinite(a) and a > 0:
            if high[i] > up_price:
                up_price, up_pos = high[i], i
            if low[i] < dn_price:
                dn_price, dn_pos = low[i], i
            if low[i] <= up_price - atr_mult * a:
                direction, ext_price, ext_pos = -1, low[i], i
                break
            if high[i] >= dn_price + atr_mult * a:
                direction, ext_price, ext_pos = 1, high[i], i
                break
        i += 1
    else:
        return pivots

    for j in range(i + 1, n):
        a = atr[j]
        if not (np.isfinite(a) and a > 0):
            continue
        hi, lo = high[j], low[j]
        if direction == 1:
            if hi > ext_price:
                ext_price, ext_pos = hi, j
            elif lo <= ext_price - atr_mult * a:
                pivots.append((ext_pos, ext_price, "H"))
                direction, ext_price, ext_pos = -1, lo, j
        else:
            if lo < ext_price:
                ext_price, ext_pos = lo, j
            elif hi >= ext_price + atr_mult * a:
                pivots.append((ext_pos, ext_price, "L"))
                direction, ext_price, ext_pos = 1, hi, j
    return pivots


def _project_zone(x_p, a_p, b_p, c_p, xa, bc, matched, bullish):
    """用匹配到的每个形态各自的 CD/BC ∩ AD/XA 区间投射 D 点价格区间，
    多个匹配形态取并集（"谐波形态"整体信号，不绑定单一形态）。"""
    candidates = []
    for name in matched:
        r = PATTERNS[name]
        if bullish:
            cd_lo, cd_hi = c_p - r["cd_bc"][1] * bc, c_p - r["cd_bc"][0] * bc
            ad_lo, ad_hi = a_p - r["ad_xa"][1] * xa, a_p - r["ad_xa"][0] * xa
        else:
            cd_lo, cd_hi = c_p + r["cd_bc"][0] * bc, c_p + r["cd_bc"][1] * bc
            ad_lo, ad_hi = a_p + r["ad_xa"][0] * xa, a_p + r["ad_xa"][1] * xa
        lo = max(min(cd_lo, cd_hi), min(ad_lo, ad_hi))
        hi = min(max(cd_lo, cd_hi), max(ad_lo, ad_hi))
        if lo <= hi:
            candidates.append((lo, hi))
    if not candidates:
        return None
    return min(c[0] for c in candidates), max(c[1] for c in candidates)


def compute_harmonic_signals(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """输入标准 OHLCV DataFrame，返回追加谐波信号列的新 DataFrame：
      harmLong / harmShort — 该 bar 收盘触及 PRZ 且形态未失效（0/1）
      harmSL               — 信号 bar 的止损种子（X 点价格，仅信号 bar 有值）
      atrVal                — ATR（策略追踪止损复用）
    """
    high  = df["High"].to_numpy(dtype=float)
    low   = df["Low"].to_numpy(dtype=float)
    close = df["Close"]
    n = len(df)

    atr_len      = int(params.get("atr_len", 14))
    zigzag_mult  = float(params.get("zigzag_atr_mult", 2.5))
    max_wait_bars = int(params.get("max_wait_bars", 40))
    allow_short   = bool(params.get("allow_short", True))

    atr_series = _atr(df["High"], df["Low"], close, atr_len)
    atr = atr_series.to_numpy(dtype=float)

    pivots = _find_pivots(high, low, atr, zigzag_mult)

    long_sig  = np.zeros(n)
    short_sig = np.zeros(n)
    sl_level  = np.full(n, np.nan)

    for k in range(3, len(pivots)):
        X, A, B, C = pivots[k - 3], pivots[k - 2], pivots[k - 1], pivots[k]
        x_p, a_p, b_p, c_p = X[1], A[1], B[1], C[1]
        c_pos = C[0]
        bullish = C[2] == "H"   # X,A,B,C = L,H,L,H -> D 预期为低点，做多
        if not bullish and not allow_short:
            continue

        xa, ab, bc = abs(a_p - x_p), abs(b_p - a_p), abs(c_p - b_p)
        if xa <= 0 or ab <= 0 or bc <= 0:
            continue
        ab_xa, bc_ab = ab / xa, bc / ab

        matched = [name for name, r in PATTERNS.items()
                   if r["ab_xa"][0] <= ab_xa <= r["ab_xa"][1]
                   and r["bc_ab"][0] <= bc_ab <= r["bc_ab"][1]]
        if not matched:
            continue

        zone = _project_zone(x_p, a_p, b_p, c_p, xa, bc, matched, bullish)
        if zone is None:
            continue
        prz_lo, prz_hi = zone

        # 从 C 之后逐 bar 扫描：触及 PRZ → 信号；跌破/突破 X 点 → 结构失效；
        # 超时未触及 → 放弃。只用每根 bar 自身收盘时已知的 High/Low。
        end = min(n, c_pos + 1 + max_wait_bars)
        for j in range(c_pos + 1, end):
            if bullish:
                if low[j] < x_p:
                    break
                if low[j] <= prz_hi:
                    long_sig[j] = 1
                    sl_level[j] = x_p
                    break
            else:
                if high[j] > x_p:
                    break
                if high[j] >= prz_lo:
                    short_sig[j] = 1
                    sl_level[j] = x_p
                    break

    result = df.copy()
    result["harmLong"]  = long_sig
    result["harmShort"] = short_sig
    result["harmSL"]    = sl_level
    result["atrVal"]    = atr_series
    return result
