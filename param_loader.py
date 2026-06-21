"""
param_loader.py — 参数加载器

优先级：symbol 级别覆盖 > timeframe 全局默认
用法：
  from param_loader import get_params
  params = get_params("NVDA", "1h")
"""

from copy import deepcopy
from pathlib import Path

import yaml

with open(Path(__file__).parent / "config.yaml") as f:
    _cfg = yaml.safe_load(f)


def get_params(symbol: str, tf: str) -> dict:
    """返回合并后的参数：timeframe 默认值 + symbol 覆盖。"""
    params = deepcopy(_cfg["timeframes"][tf])
    overrides = (
        _cfg.get("symbol_params") or {}
    ).get(symbol, {}).get(tf, {})
    params.update(overrides)
    return params
