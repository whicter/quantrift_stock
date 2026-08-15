"""
sector_map.py — 标的 → 板块映射（带本地缓存）

用途：把同一轮扫描里同板块的信号合并成一条 Telegram 消息（用户 2026-08-15 要求
"全部发出来，同板块的放在一条里发"）。合并除了减少消息条数，更重要的是让
**相关性集中度**一眼可见——同一板块同时出 5 条做多，本质是同一个赌注下了 5 次，
分开发会看不出来。

板块来源优先级：
  1. 手工覆盖 `_OVERRIDES`：ETF（yfinance 对 ETF 的 sector 字段常为空）和
     项目里已有明确分类的标的（如 SEMI_SYMBOLS）
  2. 本地缓存 `data/.sector_map.json`
  3. yfinance `.info["sector"]`（较慢，仅对未知标的调用一次后写入缓存）
  4. 都拿不到 → "其他"

缓存不设过期：标的所属板块几乎不变，且拿不到时会退回"其他"而非报错。
"""

import json
from pathlib import Path

CACHE_PATH = Path("data/.sector_map.json")

# yfinance 对 ETF/基金的 sector 多为空；这些按投资主题手工归类，
# 与 etf_scanner.py 的分组保持一致。
_OVERRIDES = {
    # 宽基 / 基准
    "QQQ": "宽基ETF", "SPY": "宽基ETF", "VOO": "宽基ETF", "VTI": "宽基ETF",
    "SPYM": "宽基ETF", "SPMO": "宽基ETF", "DGRO": "宽基ETF", "PKW": "宽基ETF",
    "FDVV": "宽基ETF", "LVHI": "宽基ETF", "VYM": "宽基ETF", "FOF": "宽基ETF",
    # 半导体（与 alert_engine.SEMI_SYMBOLS 对齐）
    "SOXX": "半导体", "SMH": "半导体", "MU": "半导体", "MRVL": "半导体",
    "STX": "半导体", "SNDK": "半导体", "NVDA": "半导体", "INTC": "半导体",
    "AMD": "半导体", "AMAT": "半导体", "KLAC": "半导体", "TSM": "半导体",
    "GFS": "半导体", "QCOM": "半导体", "MKSI": "半导体", "ONTO": "半导体",
    # 主题 / 商品
    "USO": "能源商品", "SLV": "贵金属", "REMX": "稀土矿业", "USAR": "稀土矿业",
    "MSOS": "大麻", "TMC": "深海采矿", "HBM": "矿业", "MP": "稀土矿业",
    "LTL": "杠杆ETF", "SPXC": "工业",
}


# yfinance 返回英文板块名，统一译成中文与项目其余输出保持一致。
_ZH = {
    "Technology": "科技", "Financial Services": "金融", "Healthcare": "医疗",
    "Communication Services": "通信服务", "Consumer Cyclical": "可选消费",
    "Consumer Defensive": "必需消费", "Industrials": "工业", "Energy": "能源",
    "Basic Materials": "原材料", "Utilities": "公用事业", "Real Estate": "房地产",
}


def _load_cache() -> dict:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text())
    except Exception:
        return {}


def _save_cache(data: dict) -> None:
    try:
        CACHE_PATH.parent.mkdir(exist_ok=True)
        CACHE_PATH.write_text(json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True))
    except Exception:
        pass


_cache: dict | None = None


def sector_of(symbol: str, allow_fetch: bool = True) -> str:
    """返回标的所属板块；未知且不允许联网时返回"其他"。"""
    global _cache
    symbol = symbol.upper()
    if symbol in _OVERRIDES:
        return _OVERRIDES[symbol]
    if _cache is None:
        _cache = _load_cache()
    if symbol in _cache:
        return _ZH.get(_cache[symbol], _cache[symbol])
    if not allow_fetch:
        return "其他"
    sector = "其他"
    try:
        import yfinance as yf
        info = yf.Ticker(symbol).info or {}
        sector = info.get("sector") or "其他"
    except Exception:
        pass
    _cache[symbol] = sector
    _save_cache(_cache)
    return _ZH.get(sector, sector)


def warm(symbols) -> None:
    """预热缓存：对未知标的批量查一次，避免扫描中途逐个联网拖慢。"""
    global _cache
    if _cache is None:
        _cache = _load_cache()
    unknown = [s.upper() for s in symbols
               if s.upper() not in _OVERRIDES and s.upper() not in _cache]
    for sym in unknown:
        sector_of(sym)
