"""
fetch_russell2000_tickers.py — 构建 Russell 2000 近似 ticker 列表

数据来源：NASDAQ 官方 symbol 目录（每日更新，免费公开）
  https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt

过滤逻辑：
  1. 仅保留 NASDAQ/NYSE/AMEX 上市普通股（排除 ETF、权证、单位、优先股）
  2. 排除已知 S&P 500 / NDX 100 大型股（这些由对应 universe 覆盖）
  3. Ticker 为纯字母 1-5 位（过滤 ADR/LP/权证后缀）

结果保存到 data/russell2000_tickers.txt（约 2000-2500 只）

建议：Russell 重组每年 6 月底，重组后重新运行本脚本。

用法：
  python3.11 fetch_russell2000_tickers.py
"""

import io
import sys
from pathlib import Path

import pandas as pd
import requests

OUT_PATH = Path("data/russell2000_tickers.txt")

# 已知大型股（S&P 500 / NDX 100 主力），排除以免重叠
LARGE_CAPS = {
    "AAPL","MSFT","NVDA","AMZN","META","GOOGL","GOOG","TSLA","AVGO","JPM","UNH",
    "V","XOM","MA","LLY","JNJ","PG","COST","HD","MRK","WMT","BAC","ABBV","CVX",
    "CRM","KO","NFLX","ORCL","AMD","PEP","TMO","ACN","CSCO","MCD","ABT","TXN",
    "WFC","ADBE","PM","DHR","NKE","INTU","NEE","LIN","IBM","CMCSA","AMGN","RTX",
    "QCOM","INTC","CAT","GE","SPGI","ISRG","HON","VZ","LOW","MS","AMAT","AXP",
    "T","BKNG","VRTX","GS","SBUX","BLK","SYK","MDLZ","PLD","ADI","BA","GILD",
    "MMC","UPS","CB","DE","REGN","ADP","SCHW","MU","LRCX","ETN","PANW","CI",
    "SO","KLAC","SNPS","BMY","PGR","DUK","TJX","COP","NOC","USB","FCX","MSI",
    "WM","ITW","CDNS","EQIX","FI","SHW","ZTS","EOG","CRWD","CME","MO","CEG",
    "ORLY","CTAS","EMR","AON","PH","MELI","MCO","COF","OKE","APH","AJG","PCAR",
    "FTNT","HCA","WELL","CARR","NXPI","PSA","CL","TDG","CHTR","F","GM","NSC",
    "PAYX","HLT","ECL","AFL","NEM","ODFL","FAST","ROST","CTSH","VRSK","SPG",
    "GWW","PWR","LULU","TROW","IDXX","BK","GEHC","NUE","DG","DLTR","SRE",
    "XEL","VLO","ACN","AMP","ANET","AVB","AWK","AZO","BBY","BDX","BIIB",
    "BR","BRO","BSX","CBOE","CBRE","CCL","CDW","CF","CFG","CHD","CMG","CMI",
    "COIN","CPB","CPRT","CSX","CTRA","D","DAL","DD","DFS","DHI","DLR","DOV",
    "DPZ","DRI","DTE","DVN","DXCM","EA","ECL","EFX","EIX","ELV","EMN","ENPH",
    "EQR","EQT","ES","ETR","EW","EXPE","EXR","FANG","FDX","FE","FIS","FITB",
    "FMC","FSLR","FTV","GD","GEN","GIS","GL","GPC","GPN","HAL","HAS","HBAN",
    "HES","HIG","HRL","HSY","HWM","ICE","IEX","IFF","IP","IRM","IT","JBHT",
    "JCI","K","KEY","KEYS","KIM","KMB","KMI","KMX","KR","LDOS","LEN","LH",
    "LHX","LMT","LNT","LUV","LVS","LYB","LYV","MAA","MAR","MAS","MCHP","MCK",
    "MDT","MLM","MNST","MOH","MOS","MRO","MRNA","MRVL","MSCI","MTB","MTD",
    "NDAQ","NI","NRG","NTAP","NTRS","NVR","NWL","OMC","ON","OXY","PAYC",
    "PCG","PEG","PFE","PFG","PHM","PLTR","PNR","PNW","POOL","PPG","PPL","PRU",
    "PTC","PYPL","RCL","RF","RJF","RMD","ROK","ROL","ROP","RVTY","SBAC",
    "SEE","SJM","SLB","STT","STX","STZ","SWK","SWKS","SYF","SYY","TAP",
    "TDY","TEL","TER","TFC","TMUS","TPR","TRMB","TRV","TSCO","TSN","TTWO",
    "TXT","TYL","UAL","UBER","ULTA","UNP","URI","VTR","VTRS","WAB","WAT",
    "WBD","WDC","WHR","WRB","WST","WTW","WY","WYNN","XYL","YUM","ZBH",
    "ZBRA","ZTS","KDP","CCEP","GFS","DDOG","ZS","SNOW","ABNB","DASH",
    # NDX additional
    "ASML","ADBE","BKNG","CRWD","MELI","MDLZ","LRCX","IDXX","ROST","PAYX",
    "ODFL","BIIB","PCAR","FAST","CTSH","VRSK","MCHP","DLTR","ALGN","NXPI",
    "CPRT","NTES","JD","PDD","RIVN","LCID","TEAM","ZM","ENPH","SIRI",
}

EXCLUDE_NAME_KW = [
    "warrant", "rights", "unit", "preferred", "trust pref",
    "depositary", "adr ", " adr", " notes", "bond ", "debenture",
    "liquidating", "acquisition", "blank check",
]


def main():
    print("下载 NASDAQ 全量股票目录...")
    url = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt"
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()

    df = pd.read_csv(io.StringIO(r.text), sep="|")
    print(f"  原始记录: {len(df)} 条")

    # 过滤普通股
    stocks = df[
        (df["Nasdaq Traded"] == "Y") &
        (df["ETF"] == "N") &
        (df["Test Issue"] == "N") &
        (df["Symbol"].str.match(r"^[A-Z]{1,5}$"))
    ].copy()

    # 过滤特殊证券名称
    mask = stocks["Security Name"].str.lower().apply(
        lambda n: not any(kw in n for kw in EXCLUDE_NAME_KW)
    )
    stocks = stocks[mask]

    # 排除大型股
    syms = [s for s in stocks["Symbol"].tolist() if s not in LARGE_CAPS]
    syms = sorted(set(syms))

    print(f"  过滤后普通股: {len(syms)} 个")
    print(f"  预计 IB 拉取耗时: {len(syms) * 6 // 3600}h {(len(syms) * 6 % 3600) // 60}m (6s/股)")

    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text("\n".join(syms))
    print(f"  已保存到 {OUT_PATH}")
    print(f"\n示例前 20: {syms[:20]}")


if __name__ == "__main__":
    main()
