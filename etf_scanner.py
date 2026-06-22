"""
etf_scanner.py — ETF 板块轮动 + 超跌抄底扫描器

两套信号：
  1. Rotation Score (0-100)：找当前资金流入的强势板块（追强）
  2. Reversal Score (0-100)：找超跌后开始修复的板块（抄底）

市场环境过滤（Risk-On / Neutral / Risk-Off）决定策略权重：
  Risk-On  → 轮动追强为主
  Neutral  → 只看回踩 / 相对强势板块
  Risk-Off → 观察防御板块，不追高，只做超跌极端情况

用法：
  python etf_scanner.py              # 全量扫描，控制台输出
  python etf_scanner.py --top 5      # 每类显示前 5（默认 10）
  python etf_scanner.py --telegram   # 同时推送 Telegram
  python etf_scanner.py --period 2y  # 使用 2 年数据（默认 1y）
"""

import argparse
import os
import warnings
from datetime import datetime

import numpy as np
import pandas as pd
import yaml
from pathlib import Path

warnings.filterwarnings("ignore")

with open("config.yaml") as _f:
    _cfg = yaml.safe_load(_f)

DATA_DIR = Path(_cfg["data"]["dir"])

# ── ETF 分组 ─────────────────────────────────────────────────────────────────

ETF_GROUPS = {
    "大板块":    ["XLK", "XLC", "XLY", "XLP", "XLV", "XLF", "XLI", "XLE", "XLB", "XLU", "XLRE"],
    "科技/AI":   ["IGV", "CIBR", "HACK", "SKYY", "CLOU", "BOTZ", "ARTY", "AIQ"],
    "半导体":    ["SMH", "SOXX", "XSD"],
    "金融细分":  ["KBE", "KRE", "KIE"],
    "医疗/生技": ["XBI", "IBB", "IHI"],
    "国防/运输": ["ITA", "XAR", "IYT"],
    "消费/住宅": ["XHB", "ITB", "XRT"],
    "能源/资源": ["XOP", "ICLN", "TAN", "GDX", "GDXJ"],
    "房地产":    ["VNQ", "IYR", "SRVR", "DTCR"],
}

ALL_ETFS = [sym for syms in ETF_GROUPS.values() for sym in syms]
BENCHMARK = "SPY"

ETF_NAMES = {
    "XLK":  "科技",        "XLC":  "通信服务",    "XLY":  "可选消费",
    "XLP":  "必需消费",    "XLV":  "医疗",        "XLF":  "金融",
    "XLI":  "工业",        "XLE":  "能源",        "XLB":  "原材料",
    "XLU":  "公用事业",    "XLRE": "房地产",
    "SMH":  "半导体",      "SOXX": "半导体",      "XSD":  "半导体等权",
    "IGV":  "软件",        "CIBR": "网络安全",    "HACK": "网络安全",
    "SKYY": "云计算",      "CLOU": "云计算",      "BOTZ": "AI/机器人",
    "ARTY": "AI/未来科技", "AIQ":  "AI/科技",
    "KBE":  "银行",        "KRE":  "区域银行",    "KIE":  "保险",
    "XBI":  "生物科技等权","IBB":  "生物科技",    "IHI":  "医疗设备",
    "ITA":  "航空航天/国防","XAR": "航空航天等权", "IYT":  "运输",
    "XHB":  "住宅建筑/家装","ITB": "住宅建筑",    "XRT":  "零售等权",
    "XOP":  "油气勘探/生产","ICLN":"清洁能源",    "TAN":  "太阳能",
    "GDX":  "金矿",        "GDXJ": "小型金矿",
    "VNQ":  "REITs/房地产","IYR":  "REITs/房地产",
    "SRVR": "数据中心REITs","DTCR":"数据中心/数字基建",
}

# 防御 ETF：Risk-Off 时用于判断避险资金流向
DEFENSIVE = {"XLP", "XLV", "XLU", "VNQ", "IYR"}

# 高波动抄底 ETF：更适合 Reversal 策略
HIGH_BETA_REVERSAL = {"KRE", "XBI", "TAN", "ICLN", "XOP", "GDX", "GDXJ", "XRT", "XSD"}


# ── 数据加载（从本地 CSV） ────────────────────────────────────────────────────

def _load_csv(symbol: str) -> pd.DataFrame | None:
    """读取 data/{symbol}_1d.csv，标准化列名，返回 OHLCV DataFrame。"""
    path = DATA_DIR / f"{symbol}_1d.csv"
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        df.index.name = "Date"
        df.columns = [c.capitalize() for c in df.columns]
        df = df[["Open", "High", "Low", "Close", "Volume"]].dropna(how="all")
        return df if len(df) >= 20 else None
    except Exception:
        return None


def load_data(symbols: list[str]) -> dict[str, pd.DataFrame]:
    """从本地 CSV 加载 ETF 日线数据（由 fetch_etf_data.py 提前下载）。"""
    result: dict[str, pd.DataFrame] = {}
    missing = []

    all_syms = list(dict.fromkeys(symbols + [BENCHMARK, "QQQ"]))
    for sym in all_syms:
        df = _load_csv(sym)
        if df is not None:
            result[sym] = df
        else:
            missing.append(sym)

    if missing:
        print(f"  ⚠ 缺少 CSV（请先跑 fetch_etf_data.py）：{missing}")

    # VIX 从 IB 下载的 CSV 读取（存为 VIX_1d.csv）
    vix_df = _load_csv("VIX")
    if vix_df is not None:
        result["^VIX"] = vix_df

    ok = len([s for s in all_syms if s in result])
    print(f"  已加载: {ok}/{len(all_syms)} 个 ETF  VIX: {'✓' if '^VIX' in result else '✗'}")
    return result


# ── 市场环境判断 ──────────────────────────────────────────────────────────────

def calc_market_regime(data: dict[str, pd.DataFrame]) -> dict:
    """
    regime: "risk_on" | "neutral" | "risk_off"

    Risk-On:   SPY > 200MA  且  20MA > 50MA  且  QQQ/SPY 趋势向上  且  VIX < 25
    Neutral:   SPY > 200MA  且  VIX < 25  但不满足 Risk-On 全部条件
    Risk-Off:  SPY < 200MA  或  VIX >= 25
    """
    spy = data.get(BENCHMARK)
    qqq = data.get("QQQ")
    vix = data.get("^VIX")

    if spy is None or len(spy) < 50:
        return {"regime": "unknown", "details": {}}

    close_spy = spy["Close"]
    sma200    = close_spy.rolling(200).mean()
    sma50     = close_spy.rolling(50).mean()
    sma20     = close_spy.rolling(20).mean()

    spy_last  = float(close_spy.iloc[-1])
    sm200_val = float(sma200.iloc[-1]) if not pd.isna(sma200.iloc[-1]) else None
    sm50_val  = float(sma50.iloc[-1])  if not pd.isna(sma50.iloc[-1])  else None
    sm20_val  = float(sma20.iloc[-1])  if not pd.isna(sma20.iloc[-1])  else None

    vix_val = None
    if vix is not None and len(vix) > 0:
        vix_val = float(vix["Close"].iloc[-1])

    above_200 = (sm200_val is not None) and (spy_last > sm200_val)
    bull_ma   = (sm20_val is not None) and (sm50_val is not None) and (sm20_val > sm50_val)
    vix_calm  = (vix_val is None) or (vix_val < 25)

    qqq_spy_up = False
    if qqq is not None and len(qqq) > 21:
        rs = qqq["Close"] / close_spy.reindex(qqq["Close"].index, method="ffill")
        rs_ma = rs.rolling(20).mean()
        qqq_spy_up = bool(rs.iloc[-1] > rs_ma.iloc[-1]) if not pd.isna(rs_ma.iloc[-1]) else False

    if above_200 and bull_ma and qqq_spy_up and vix_calm:
        regime = "risk_on"
    elif above_200 and vix_calm:
        regime = "neutral"
    else:
        regime = "risk_off"

    return {
        "regime":        regime,
        "spy_last":      round(spy_last, 2),
        "sma200":        round(sm200_val, 2) if sm200_val else None,
        "sma50":         round(sm50_val,  2) if sm50_val  else None,
        "sma20":         round(sm20_val,  2) if sm20_val  else None,
        "above_200":     above_200,
        "bull_ma":       bull_ma,
        "qqq_spy_up":    qqq_spy_up,
        "vix":           round(vix_val, 1) if vix_val else None,
    }


# ── Rotation Score ────────────────────────────────────────────────────────────

def calc_rotation_score(sym: str, data: dict[str, pd.DataFrame]) -> dict | None:
    """
    Rotation Score (0-100)：追强板块排名

    因子：
      +15  收盘价 > 50MA
      +15  收盘价 > 200MA
      +15  20 日收益 > SPY 20 日收益
      +15  60 日收益 > SPY 60 日收益
      +15  ETF/SPY 相对强度 > 其 20 日均线
      +15  ETF/SPY 相对强度处于 20 日新高（±0.5%）
      +10  成交量 > 20 日均量

    合计 100 分。
    """
    df  = data.get(sym)
    spy = data.get(BENCHMARK)
    if df is None or spy is None or len(df) < 65:
        return None

    close    = df["Close"]
    vol      = df["Volume"]
    spy_c    = spy["Close"].reindex(close.index, method="ffill")

    last     = float(close.iloc[-1])
    sma50    = float(close.rolling(50).mean().iloc[-1])
    sma200_v = close.rolling(200).mean().iloc[-1]
    sma200   = float(sma200_v) if not pd.isna(sma200_v) else None

    ret20_e  = float(close.pct_change(20).iloc[-1])
    ret60_e  = float(close.pct_change(60).iloc[-1])
    ret20_s  = float(spy_c.pct_change(20).iloc[-1])
    ret60_s  = float(spy_c.pct_change(60).iloc[-1])

    rs       = close / spy_c
    rs_now   = float(rs.iloc[-1])
    rs_sma   = float(rs.rolling(20).mean().iloc[-1])
    rs_hi20  = float(rs.rolling(20).max().iloc[-1])

    vol_now  = float(vol.iloc[-1])
    vol_sma  = float(vol.rolling(20).mean().iloc[-1]) if vol.rolling(20).mean().iloc[-1] > 0 else 0

    score = 0
    if not pd.isna(sma50)   and last > sma50:                              score += 15
    if sma200 and last > sma200:                                           score += 15
    if not pd.isna(ret20_e) and not pd.isna(ret20_s) and ret20_e > ret20_s: score += 15
    if not pd.isna(ret60_e) and not pd.isna(ret60_s) and ret60_e > ret60_s: score += 15
    if not pd.isna(rs_sma)  and rs_now > rs_sma:                          score += 15
    if not pd.isna(rs_hi20) and rs_hi20 > 0 and (rs_now / rs_hi20) >= 0.995: score += 15
    if vol_sma > 0 and vol_now > vol_sma:                                  score += 10

    rel20 = (ret20_e - ret20_s) * 100 if not (pd.isna(ret20_e) or pd.isna(ret20_s)) else 0.0
    rel60 = (ret60_e - ret60_s) * 100 if not (pd.isna(ret60_e) or pd.isna(ret60_s)) else 0.0

    return {
        "symbol":    sym,
        "score":     score,
        "close":     round(last, 2),
        "vs50ma":    round((last / sma50 - 1) * 100, 1)   if not pd.isna(sma50) else None,
        "vs200ma":   round((last / sma200 - 1) * 100, 1)  if sma200 else None,
        "rel20d":    round(rel20, 1),
        "rel60d":    round(rel60, 1),
        "rs_hi":     round((rs_now / rs_hi20 - 1) * 100, 1) if not pd.isna(rs_hi20) and rs_hi20 > 0 else None,
        "vol_ratio": round(vol_now / vol_sma, 2) if vol_sma > 0 else None,
    }


# ── Reversal Score ────────────────────────────────────────────────────────────

def calc_reversal_score(sym: str, data: dict[str, pd.DataFrame]) -> dict | None:
    """
    Reversal Score (0-100)：超跌反转候选

    前提：RSI(14) < 40  且  收盘价 < 50MA × 0.95
    (未满足前提直接返回 score=0 / phase='未超跌')

    反转信号（满足前提后）：
      +15  RSI(14) < 30（极度超跌）
      +15  收盘价 < 50MA × 0.92（深度偏离）
      +10  成交量 > 1.5× 均量（恐慌性抛售放量）
      +15  收盘价 > 5MA（止跌）
      +15  收盘价 > 前日最高价（反包）
      +15  ETF/SPY 连续 3 天相对强度上升
      +15  收盘价距 20MA 偏离 < 5%（均线修复中）

    Score ≥ 45 → "反转确认"；否则 "超跌待确认"
    """
    df  = data.get(sym)
    spy = data.get(BENCHMARK)
    if df is None or spy is None or len(df) < 30:
        return None

    close   = df["Close"]
    high    = df["High"]
    vol     = df["Volume"]
    spy_c   = spy["Close"].reindex(close.index, method="ffill")

    last    = float(close.iloc[-1])
    sma50_v = close.rolling(50).mean().iloc[-1]
    sma20_v = close.rolling(20).mean().iloc[-1]
    sma5_v  = close.rolling(5).mean().iloc[-1]
    sma50   = float(sma50_v) if not pd.isna(sma50_v) else None
    sma20   = float(sma20_v) if not pd.isna(sma20_v) else None
    sma5    = float(sma5_v)  if not pd.isna(sma5_v)  else None

    vol_now = float(vol.iloc[-1])
    vol_sma = float(vol.rolling(20).mean().iloc[-1]) if vol.rolling(20).mean().iloc[-1] > 0 else 0

    # RSI(14)
    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    rsi   = float((100 - 100 / (1 + gain / (loss + 1e-9))).iloc[-1])

    # ETF/SPY 相对强度连续 3 天上升
    rs     = (close / spy_c).dropna()
    rs3up  = bool((rs.diff().iloc[-3:] > 0).all()) if len(rs) >= 3 else False

    prev_high = float(high.iloc[-2]) if len(high) >= 2 else None

    # 超跌前提
    base_oversold = (rsi < 40) and (sma50 is not None) and (last < sma50 * 0.95)

    vs50 = round((last / sma50 - 1) * 100, 1) if sma50 else None
    vs20 = round((last / sma20 - 1) * 100, 1) if sma20 else None

    if not base_oversold:
        return {
            "symbol": sym, "score": 0, "rsi": round(rsi, 1),
            "close": round(last, 2), "vs50ma": vs50, "vs20ma": vs20,
            "rs3up": rs3up, "phase": "未超跌",
        }

    score = 0
    if rsi < 30:                                                    score += 15
    if sma50 and last < sma50 * 0.92:                              score += 15
    if vol_sma > 0 and vol_now > vol_sma * 1.5:                    score += 10
    if sma5 and last > sma5:                                        score += 15
    if prev_high and last > prev_high:                              score += 15
    if rs3up:                                                        score += 15
    if sma20 and abs(last / sma20 - 1) < 0.05:                    score += 15

    phase = "反转确认" if score >= 45 else "超跌待确认"

    return {
        "symbol": sym,
        "score":  score,
        "rsi":    round(rsi, 1),
        "close":  round(last, 2),
        "vs50ma": vs50,
        "vs20ma": vs20,
        "rs3up":  rs3up,
        "phase":  phase,
    }


# ── 输出 ─────────────────────────────────────────────────────────────────────

REGIME_EMOJI = {
    "risk_on":  "🟢",
    "neutral":  "🟡",
    "risk_off": "🔴",
    "unknown":  "⚪",
}
REGIME_CN = {
    "risk_on":  "Risk-On  进攻",
    "neutral":  "Neutral  观望",
    "risk_off": "Risk-Off 防御",
    "unknown":  "未知",
}


def print_regime(r: dict):
    emoji = REGIME_EMOJI.get(r["regime"], "⚪")
    cn    = REGIME_CN.get(r["regime"], "未知")
    print(f"\n  市场环境: {emoji} {cn}")
    if r.get("spy_last"):
        vix_str = f"  VIX: {r['vix']}" if r.get("vix") else ""
        print(f"  SPY ${r['spy_last']}  50MA ${r['sma50']}  200MA {r['sma200']}")
        print(f"  20MA{'>' if r['bull_ma'] else '<'}50MA  "
              f"QQQ/SPY: {'↑' if r['qqq_spy_up'] else '↓'}"
              f"{vix_str}")


def _fmt(val, fmt="+.1f", suffix="%") -> str:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "  N/A"
    return f"{val:{fmt}}{suffix}"


def print_rotation_table(rows: list[dict], top_n: int):
    rows = sorted(rows, key=lambda x: -x["score"])[:top_n]
    hdr = f"  {'标的':<6} {'类型':<10} {'分':>4} {'收盘':>7} {'vs50MA':>7} {'vs200MA':>8} {'RS20d':>7} {'RS60d':>7} {'量比':>5}"
    print(hdr)
    print("  " + "─" * 67)
    for r in rows:
        tag  = "★" if r["symbol"] in HIGH_BETA_REVERSAL else " "
        name = ETF_NAMES.get(r["symbol"], "")[:10]
        print(f"  {r['symbol']:<6}{tag} {name:<10} {r['score']:>3} "
              f"  {r['close']:>7.2f}"
              f"  {_fmt(r['vs50ma']):>7}"
              f"  {_fmt(r['vs200ma']):>8}"
              f"  {_fmt(r['rel20d']):>7}"
              f"  {_fmt(r['rel60d']):>7}"
              f"  {_fmt(r['vol_ratio'], '.2f', 'x'):>5}")


def print_reversal_table(rows: list[dict], top_n: int):
    active = [r for r in rows if r.get("phase") != "未超跌"]
    if not active:
        print("  （无超跌标的）")
        return
    active = sorted(active, key=lambda x: -x["score"])[:top_n]
    hdr = f"  {'标的':<6} {'类型':<10} {'分':>4} {'RSI':>5} {'收盘':>7} {'vs50MA':>7} {'vs20MA':>7} {'RS3↑':>5}  阶段"
    print(hdr)
    print("  " + "─" * 72)
    for r in active:
        name = ETF_NAMES.get(r["symbol"], "")[:10]
        print(f"  {r['symbol']:<6}  {name:<10} {r['score']:>3} "
              f"  {r['rsi']:>5.1f}"
              f"  {r['close']:>7.2f}"
              f"  {_fmt(r['vs50ma']):>7}"
              f"  {_fmt(r['vs20ma']):>7}"
              f"  {'✓' if r.get('rs3up') else '✗':>5}  "
              f"{r['phase']}")


def print_group_summary(rotation_rows: list[dict]):
    print("\n  分组 Top3（轮动）：")
    for group, syms in ETF_GROUPS.items():
        group_rows = sorted(
            [r for r in rotation_rows if r["symbol"] in syms],
            key=lambda x: -x["score"],
        )[:3]
        if group_rows:
            tags = "  ".join(f"{r['symbol']}({r['score']})" for r in group_rows)
            print(f"    {group:<8}: {tags}")


def build_telegram_msg(regime: dict, rotation: list[dict], reversal: list[dict],
                       top_n: int = 5) -> str:
    emoji  = REGIME_EMOJI.get(regime["regime"], "⚪")
    cn     = {"risk_on": "Risk-On", "neutral": "Neutral", "risk_off": "Risk-Off"}.get(regime["regime"], "?")
    vix_s  = f"  VIX:{regime['vix']}" if regime.get("vix") else ""
    ts     = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [f"📡 ETF 板块扫描  {ts} ET",
             f"市场: {emoji} {cn}{vix_s}"]

    # 轮动 Top
    top_rot = sorted(rotation, key=lambda x: -x["score"])[:top_n]
    if top_rot:
        lines.append(f"\n🔥 轮动强势板块 Top{top_n}")
        for r in top_rot:
            name = ETF_NAMES.get(r["symbol"], "")
            lines.append(
                f"  {r['symbol']:<5} {name:<10}  {r['score']}/100  "
                f"RS20d:{_fmt(r['rel20d'],'+ .1f','%')}  "
                f"RS60d:{_fmt(r['rel60d'],'+ .1f','%')}"
            )

    # 反转候选
    rev_active = sorted(
        [r for r in reversal if r.get("phase") != "未超跌"],
        key=lambda x: -x["score"],
    )[:top_n]
    if rev_active:
        lines.append(f"\n⚡ 超跌反转候选 Top{top_n}")
        for r in rev_active:
            name = ETF_NAMES.get(r["symbol"], "")
            lines.append(
                f"  {r['symbol']:<5} {name:<10}  {r['score']}/100  "
                f"RSI:{r['rsi']:.0f}  "
                f"vs50MA:{_fmt(r['vs50ma'],'+ .1f','%')}  "
                f"{r['phase']}"
            )

    return "\n".join(lines)


def send_telegram(msg: str):
    import json
    import urllib.parse
    import urllib.request

    token   = os.getenv("TG_TOKEN")   or _cfg.get("telegram", {}).get("token", "")
    chat_id = os.getenv("TG_CHAT_ID") or _cfg.get("telegram", {}).get("chat_id", "")
    if not token or not chat_id:
        print("  ⚠ Telegram 未配置")
        return
    url  = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": msg}).encode()
    try:
        with urllib.request.urlopen(url, data=data, timeout=10) as resp:
            result = json.loads(resp.read())
        if result.get("ok"):
            print("  ✅ Telegram 已发送")
        else:
            print(f"  ❌ Telegram 失败: {result}")
    except Exception as e:
        print(f"  ❌ Telegram 异常: {e}")


# ── 入口 ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="ETF 板块轮动 + 超跌抄底扫描")
    parser.add_argument("--top",      type=int, default=10,
                        help="每类显示前 N 个（默认 10）")
    parser.add_argument("--telegram", action="store_true",
                        help="同时推送 Telegram")
    args = parser.parse_args()

    bar = "═" * 65
    print(f"\n{bar}")
    print(f"  ETF 板块轮动 + 超跌扫描  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{bar}")

    # 1. 加载数据（从本地 CSV）
    print("  加载 ETF 数据...")
    data = load_data(ALL_ETFS)

    # 2. 市场环境
    regime = calc_market_regime(data)
    print_regime(regime)

    # 3. 计算各 ETF 分数
    rotation_rows: list[dict] = []
    reversal_rows: list[dict] = []
    for sym in ALL_ETFS:
        rot = calc_rotation_score(sym, data)
        rev = calc_reversal_score(sym, data)
        if rot:
            rotation_rows.append(rot)
        if rev:
            reversal_rows.append(rev)

    # 4. 轮动强势榜
    print(f"\n{'─'*65}")
    print("  🔥 板块轮动强势排名（追强）  ★=高波动反转型 ETF")
    print(f"{'─'*65}")
    print_rotation_table(rotation_rows, args.top)
    print_group_summary(rotation_rows)

    # 5. 超跌反转榜
    print(f"\n{'─'*65}")
    print("  ⚡ 超跌反转候选（抄底）")
    print(f"{'─'*65}")
    print_reversal_table(reversal_rows, args.top)

    # 6. 分组 Top3（反转）
    rev_active = [r for r in reversal_rows if r.get("phase") != "未超跌"]
    if rev_active:
        print("\n  分组 Top3（超跌）：")
        for group, syms in ETF_GROUPS.items():
            g = sorted(
                [r for r in rev_active if r["symbol"] in syms],
                key=lambda x: -x["score"],
            )[:3]
            if g:
                tags = "  ".join(f"{r['symbol']}({r['score']})" for r in g)
                print(f"    {group:<8}: {tags}")

    # 7. Telegram
    if args.telegram:
        msg = build_telegram_msg(regime, rotation_rows, reversal_rows, top_n=5)
        send_telegram(msg)

    print(f"\n{bar}\n")


if __name__ == "__main__":
    main()
