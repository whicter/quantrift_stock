"""
data_providers.py — 统一数据接入层

设计原则：
  - MarketDataProvider 是抽象基类，定义统一接口
  - 每个数据源实现一个子类
  - get_provider() 按 config.yaml 中 data.provider 字段路由
  - alert_engine / fetch_data 通过 get_provider() 获取实例，不感知具体来源

当前实现：
  - YFinanceProvider   → yfinance（免费，15 分钟延时）

未来扩展（加一个类即可）：
  - TastytradeProvider → tastytrade API（实时，需账号）
  - IBProvider         → IB Gateway reqHistoricalData（实时，需 CBOE 订阅）
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import yaml

with open("config.yaml") as _f:
    _cfg = yaml.safe_load(_f)

DATA_DIR = Path(_cfg["data"]["dir"])


# ── 抽象基类 ─────────────────────────────────────────────────────────────────

class MarketDataProvider(ABC):
    """数据接入基类。子类只需实现 fetch_ohlcv 和 fetch_vix。"""

    @abstractmethod
    def fetch_ohlcv(self, symbol: str, tf: str,
                    start: str, end: str | None = None) -> pd.DataFrame | None:
        """
        拉取 OHLCV 历史数据，返回标准格式 DataFrame（index=Date，列=Open/High/Low/Close/Volume）。
        用于 fetch_data.py 批量下载和回测数据准备。
        """
        ...

    @abstractmethod
    def fetch_vix(self) -> float | None:
        """
        获取最新 VIX 收盘值。
        用于 alert_engine 实时扫描时计算 Market Regime Score。
        返回 float，或 None（获取失败时）。
        """
        ...

    # ── 通用工具（子类可选覆盖） ───────────────────────────────────────────

    def save_ohlcv(self, symbol: str, tf: str, df: pd.DataFrame):
        """保存到标准 CSV 路径 data/{symbol}_{tf}.csv。"""
        path = DATA_DIR / f"{symbol}_{tf}.csv"
        DATA_DIR.mkdir(exist_ok=True)
        df.to_csv(path)

    def load_ohlcv(self, symbol: str, tf: str) -> pd.DataFrame | None:
        """从本地 CSV 加载（回测时用，不触发网络请求）。"""
        path = DATA_DIR / f"{symbol}_{tf}.csv"
        if not path.exists():
            return None
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        df.index.name = "Date"
        df.columns = [c.capitalize() for c in df.columns]
        if "Volume" not in df.columns:
            df["Volume"] = 0
        return df


# ── yfinance 实现 ─────────────────────────────────────────────────────────────

class YFinanceProvider(MarketDataProvider):
    """
    通过 yfinance 拉取数据。
    - OHLCV：支持所有 yfinance 可查询标的和周期
    - VIX：yfinance 符号 ^VIX，15 分钟延时，对日线 Regime Score 无影响
    """

    # yfinance interval 映射
    _INTERVAL_MAP = {"1h": "1h", "4h": "1h", "1d": "1d"}
    # VIX 的 yfinance 符号
    VIX_SYMBOL = "^VIX"

    def fetch_ohlcv(self, symbol: str, tf: str,
                    start: str, end: str | None = None) -> pd.DataFrame | None:
        try:
            import yfinance as yf
        except ImportError:
            raise ImportError("请安装 yfinance：pip install yfinance")

        interval = self._INTERVAL_MAP.get(tf, "1d")
        kwargs = {"start": start, "interval": interval, "auto_adjust": True, "progress": False}
        if end:
            kwargs["end"] = end

        raw = yf.download(symbol, **kwargs)
        if raw is None or raw.empty:
            return None

        # 标准化列名
        df = raw[["Open", "High", "Low", "Close", "Volume"]].copy()
        df.index.name = "Date"

        # 4h 由 1h 重采样
        if tf == "4h":
            df = (df.resample("4h", closed="right", label="right")
                    .agg({"Open": "first", "High": "max",
                          "Low": "min", "Close": "last", "Volume": "sum"})
                    .dropna())

        return df

    def fetch_vix(self) -> float | None:
        try:
            import yfinance as yf
            ticker = yf.Ticker(self.VIX_SYMBOL)
            hist = ticker.history(period="5d")
            if hist.empty:
                return None
            return float(hist["Close"].iloc[-1])
        except Exception as e:
            print(f"  [VIX] yfinance 获取失败: {e}")
            return None


# ── Tastytrade 实现 ───────────────────────────────────────────────────────────

class TastytradeProvider(MarketDataProvider):
    """
    通过 tastytrade REST API 拉取数据（需有效账号）。

    凭证通过环境变量注入（.env 文件 + python-dotenv）：
      TT_USERNAME      — 用户名
      TT_PASSWORD      — 密码
      TT_REMEMBER_TOKEN — 长期 token，首次手动登录后自动写入，后续免密续期

    认证流程：
      1. 优先用 remember-token 续期（POST /sessions，header 带 Remember-Token）
      2. 失败时回落到 username/password（需人工完成 OTP，不适合无人值守）

    VIX 数据：GET /market-metrics?symbols=VIX → implied-volatility-index 字段
    """

    BASE_URL = "https://api.tastytrade.com"
    VIX_SYMBOL = "$VIX.X"

    def __init__(self):
        self._username = os.environ.get("TT_USERNAME")
        self._password = os.environ.get("TT_PASSWORD")
        self._remember_token = os.environ.get("TT_REMEMBER_TOKEN")
        if not self._username:
            raise EnvironmentError(
                "TastytradeProvider 需要 TT_USERNAME 环境变量\n"
                "  在项目根目录创建 .env 文件并写入凭证"
            )
        self._session_token: str | None = None

    def _login(self) -> bool:
        """用 remember-token 或 password 获取 session-token。"""
        import requests as _r

        h = {"Content-Type": "application/json", "Accept": "application/json"}

        # 优先用 remember-token 续期（无需 OTP）
        if self._remember_token:
            resp = _r.post(
                f"{self.BASE_URL}/sessions",
                json={"login": self._username, "remember-me": True},
                headers={**h, "Authorization": f"Bearer {self._remember_token}"},
                timeout=15,
            )
            if resp.status_code == 201:
                data = resp.json().get("data", {})
                self._session_token = data.get("session-token")
                # 更新 remember-token（服务器可能轮换）
                new_rt = data.get("remember-token")
                if new_rt and new_rt != self._remember_token:
                    self._remember_token = new_rt
                    self._save_remember_token(new_rt)
                return True

        # 回落到 password（无人值守模式下只有无 OTP 时才成功）
        if self._password:
            resp = _r.post(
                f"{self.BASE_URL}/sessions",
                json={"login": self._username, "password": self._password, "remember-me": True},
                headers=h,
                timeout=15,
            )
            if resp.status_code == 201:
                data = resp.json().get("data", {})
                self._session_token = data.get("session-token")
                rt = data.get("remember-token")
                if rt:
                    self._remember_token = rt
                    self._save_remember_token(rt)
                return True

        return False

    @staticmethod
    def _save_remember_token(token: str):
        """将 remember-token 写回 .env 文件（如果存在）。"""
        env_path = Path(".env")
        if not env_path.exists():
            return
        content = env_path.read_text()
        import re
        if "TT_REMEMBER_TOKEN" in content:
            content = re.sub(r"TT_REMEMBER_TOKEN=.*", f"TT_REMEMBER_TOKEN={token}", content)
        else:
            content = content.rstrip("\n") + f"\nTT_REMEMBER_TOKEN={token}\n"
        env_path.write_text(content)

    def _get(self, path: str, params: dict | None = None):
        """带自动重登录的 GET 请求。"""
        import requests as _r

        if not self._session_token:
            if not self._login():
                return None

        h = {"Authorization": self._session_token, "Accept": "application/json"}
        resp = _r.get(f"{self.BASE_URL}{path}", headers=h, params=params, timeout=15)

        if resp.status_code == 401:
            # token 过期，重新登录
            self._session_token = None
            if not self._login():
                return None
            h["Authorization"] = self._session_token
            resp = _r.get(f"{self.BASE_URL}{path}", headers=h, params=params, timeout=15)

        return resp if resp.ok else None

    def fetch_ohlcv(self, symbol: str, tf: str,
                    start: str, end: str | None = None) -> pd.DataFrame | None:
        raise NotImplementedError("TastytradeProvider.fetch_ohlcv 待实现")

    def fetch_vix(self) -> float | None:
        """
        VIX 指数只是 Regime Score 的参考值，不是 tastytrade 可交易品种。
        tastytrade REST API 无法直接获取 VIX 指数价格（需 DXLink websocket）。
        直接复用 YFinanceProvider（^VIX，15 分钟延时，对日线 Regime 判断无影响）。
        """
        return YFinanceProvider().fetch_vix()


# ── 工厂函数 ──────────────────────────────────────────────────────────────────

_PROVIDERS: dict[str, type[MarketDataProvider]] = {
    "yfinance":    YFinanceProvider,
    "tastytrade":  TastytradeProvider,
}


def get_provider(name: str | None = None) -> MarketDataProvider:
    """
    返回配置的数据提供者实例。
    优先级：参数 name > config.yaml data.provider > 默认 yfinance
    """
    name = name or _cfg.get("data", {}).get("provider", "yfinance")
    cls = _PROVIDERS.get(name)
    if cls is None:
        raise ValueError(f"未知数据提供者: '{name}'，可选: {list(_PROVIDERS.keys())}")
    return cls()
