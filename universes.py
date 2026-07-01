"""
universes.py — 各指数成分股列表 + 基准 ETF 配置

更新频率：每年初检查一次成分股变动（S&P 500 每年约 10-20 只变动）。
最后更新：2025 Q4

用法：
    from universes import get_universe
    tickers, benchmark, label = get_universe("sp500")
"""

# ── Dow Jones Industrial Average（30 只，固定）─────────────────────────────────

DOW30 = [
    "AAPL", "AMGN", "AXP", "BA",   "CAT", "CRM",  "CSCO", "CVX",  "DIS", "DOW",
    "GS",   "HD",   "HON", "IBM",   "JNJ", "JPM",  "KO",   "MCD",  "MMM", "MRK",
    "MSFT", "NKE",  "PG",  "SHW",   "TRV", "UNH",  "V",    "VZ",   "WMT",
    # 注：INTC 已于 2024-11 被 NVDA 替代；如需更新在此改动
    "NVDA",
]

# ── Nasdaq-100（约 100 只）────────────────────────────────────────────────────

NDX100 = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "GOOG",  "TSLA", "AVGO",
    "COST", "NFLX", "AMD",  "ASML", "CSCO", "ADBE",  "PEP",   "QCOM", "INTC",
    "INTU", "CMCSA","AMAT", "TXN",  "HON",  "AMGN",  "SBUX",  "ISRG", "BKNG",
    "VRTX", "MU",   "LRCX", "KLAC", "SNPS", "CDNS",  "ADI",   "REGN", "PANW",
    "CRWD", "MELI", "MDLZ", "CTAS", "AEP",  "ORLY",  "FTNT",  "DXCM",
    "MNST", "CHTR", "LULU", "MRVL", "IDXX", "ROST",  "PAYX",  "CEG",  "ODFL",
    "EXC",  "BIIB", "PCAR", "FAST", "CTSH", "VRSK",  "KDP",   "ON",   "MCHP",
    "XEL",  "GFS",  "CCEP", "CDW",  "DDOG", "ZS",    "SIRI",  "ENPH", "ZM",
    "ALGN", "NXPI", "CPRT", "TTWO", "NTES", "JD",    "PDD",
    "PLTR", "SNOW", "RIVN", "ABNB", "DASH", "UBER",  "COIN",
]

# ── S&P 500 代表性成分（按市值分层，约 400 只主力股）──────────────────────────
# 剔除：BRK.B（IB 合约名为 BRK B，需单独处理）、外国 ADR 流动性差的标的
# Russell 2000 小市值部分不在此列

SP500 = [
    # Mega cap (>$500B)
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "GOOG",  "TSLA", "AVGO",
    "JPM",  "UNH",  "V",    "XOM",  "MA",   "LLY",   "JNJ",   "PG",   "COST",
    "HD",   "MRK",  "WMT",  "BAC",  "ABBV", "CVX",   "CRM",   "KO",   "NFLX",
    "ORCL", "AMD",  "PEP",  "TMO",  "ACN",  "CSCO",  "MCD",   "ABT",  "TXN",
    "WFC",  "ADBE", "PM",   "DHR",  "NKE",  "INTU",  "NEE",   "LIN",  "IBM",
    "CMCSA","AMGN",
    # Large cap
    "RTX",  "QCOM", "INTC", "CAT",  "GE",   "SPGI",  "ISRG",  "HON",  "VZ",
    "LOW",  "MS",   "AMAT", "AXP",  "T",    "BKNG",  "VRTX",  "GS",   "SBUX",
    "BLK",  "SYK",  "MDLZ", "PLD",  "ADI",  "BA",    "GILD",  "MMC",  "UPS",
    "CB",   "DE",   "REGN", "ADP",  "SCHW", "MU",    "LRCX",  "ETN",  "PANW",
    "CI",   "SO",   "KLAC", "SNPS", "BMY",  "PGR",   "DUK",   "TJX",  "COP",
    "NOC",  "USB",  "FCX",  "MSI",  "WM",   "ITW",   "CDNS",  "EQIX", "FI",
    "SHW",  "ZTS",  "EOG",  "CRWD", "CME",  "MO",    "CEG",   "ORLY", "TT",
    "CTAS", "EMR",  "AON",  "PH",   "MELI", "MCO",   "COF",   "OKE",  "APH",
    "AJG",  "PCAR", "FTNT", "HCA",  "WELL", "CARR",  "NXPI",  "PSA",  "CL",
    "TDG",  "CHTR", "F",    "GM",   "NSC",  "PAYX",  "HLT",   "ECL",  "AFL",
    "NEM",  "ODFL", "FAST", "ROST", "CTSH", "VRSK",  "SPG",   "GWW",  "PWR",
    "LULU", "TROW", "IDXX", "BK",   "GEHC", "NUE",   "DG",    "DLTR", "SRE",
    "XEL",  "VLO",  "ACGL", "ALB",  "AMP",  "ANET",  "AVB",   "AWK",  "AZO",
    "BBY",  "BDX",  "BIIB", "BR",   "BRO",  "BSX",   "CBOE",  "CBRE", "CCL",
    "CDW",  "CF",   "CFG",  "CHD",  "CMG",  "CMI",   "COIN",  "CPB",  "CPRT",
    "CSX",  "CTRA", "D",    "DAL",  "DD",   "DFS",   "DHI",   "DLR",  "DOV",
    "DPZ",  "DRI",  "DTE",  "DVN",  "DXCM", "EA",    "ED",    "EFX",  "EIX",
    "ELV",  "EMN",  "ENPH", "EQR",  "EQT",  "ES",    "ETR",   "EW",   "EXPE",
    "EXR",  "FANG", "FDX",  "FE",   "FIS",  "FITB",  "FMC",   "FSLR", "FTV",
    "GD",   "GEN",  "GIS",  "GL",   "GNRC", "GPC",   "GPN",   "HAL",  "HAS",
    "HBAN", "HES",  "HIG",  "HRL",  "HSY",  "HWM",   "ICE",   "IEX",  "IFF",
    "IP",   "IRM",  "IT",   "J",    "JBHT", "JCI",   "K",     "KEY",  "KEYS",
    "KIM",  "KMB",  "KMI",  "KMX",  "KR",   "LDOS",  "LEN",   "LH",   "LHX",
    "LMT",  "LNT",  "LUV",  "LVS",  "LYB",  "LYV",   "MAA",   "MAR",  "MAS",
    "MCHP", "MCK",  "MDT",  "MLM",  "MNST", "MOH",   "MOS",   "MRO",  "MRNA",
    "MRVL", "MSCI", "MTB",  "MTD",  "NDAQ", "NI",    "NRG",   "NTAP", "NTRS",
    "NVR",  "NWL",  "OMC",  "ON",   "OXY",  "PAYC",  "PCG",   "PEG",  "PFE",
    "PFG",  "PHM",  "PLTR", "PNR",  "PNW",  "POOL",  "PPG",   "PPL",  "PRU",
    "PTC",  "PYPL", "RCL",  "RF",   "RJF",  "RMD",   "ROK",   "ROL",  "ROP",
    "RVTY", "SBAC", "SEE",  "SJM",  "SLB",  "STT",   "STX",   "STZ",  "SWK",
    "SWKS", "SYF",  "SYY",  "TAP",  "TDY",  "TEL",   "TER",   "TFC",  "TMUS",
    "TPR",  "TRMB", "TRV",  "TSCO", "TSN",  "TTWO",  "TXT",   "TYL",  "UAL",
    "UBER", "ULTA", "UNP",  "URI",  "VTR",  "VTRS",  "WAB",   "WAT",  "WBD",
    "WDC",  "WHR",  "WRB",  "WST",  "WTW",  "WY",    "WYNN",  "XYL",  "YUM",
    "ZBH",  "ZBRA", "ZTS",  "KDP",  "CCEP", "GFS",   "DDOG",  "ZS",   "SNOW",
    "ABNB", "DASH",
]

# ── Russell 2000（从本地文件加载，由 fetch_russell2000_tickers.py 生成）─────────
# 文件路径：data/russell2000_tickers.txt（每行一个 ticker）
# 生成方式：从 NASDAQ 官方 symbol 目录过滤普通股（约 2000-2500 只）

def _load_russell2000() -> list[str]:
    """读取本地 Russell 2000 ticker 列表，文件不存在时返回空列表。"""
    from pathlib import Path
    path = Path("data/russell2000_tickers.txt")
    if not path.exists():
        raise FileNotFoundError(
            "Russell 2000 ticker 列表不存在。\n"
            "请先运行：python3.11 fetch_russell2000_tickers.py\n"
            f"（文件路径：{path.resolve()}）"
        )
    tickers = [t.strip() for t in path.read_text().splitlines() if t.strip()]
    return sorted(set(tickers))


# ── 指数配置 ──────────────────────────────────────────────────────────────────

_CONFIGS = {
    "dow30":     {"label": "Dow 30",      "tickers": DOW30,  "benchmark": "DIA"},
    "ndx100":    {"label": "NDX 100",     "tickers": NDX100, "benchmark": "QQQ"},
    "sp500":     {"label": "S&P 500",     "tickers": SP500,  "benchmark": "SPY"},
    "russell2000": {"label": "Russell 2000", "tickers": None, "benchmark": "IWM"},  # 从文件加载
    "all": {
        "label":     "NDX+SPX+Dow",
        "tickers":   None,   # 运行时合并
        "benchmark": "SPY",
    },
}


def get_universe(name: str) -> tuple[list[str], str, str]:
    """
    返回 (去重后的标的列表, 基准ETF代码, 显示名称)。

    name: "dow30" | "ndx100" | "sp500" | "russell2000" | "all"
    """
    if name not in _CONFIGS:
        raise ValueError(f"未知 universe: {name}，可选: {list(_CONFIGS)}")
    cfg = _CONFIGS[name]
    if name == "all":
        tickers = sorted(set(DOW30 + NDX100 + SP500))
    elif name == "russell2000":
        tickers = _load_russell2000()
    else:
        tickers = sorted(set(cfg["tickers"]))
    return tickers, cfg["benchmark"], cfg["label"]
