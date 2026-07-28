"""
harmonic_backtest.py — 谐波形态策略回测 & 验证（研究原型，仅 QQQ/SPY）

背景：用户问"谐波分析是什么策略"，要求单独跑一个原型验证 QQQ 和 SPY 是否
有效——这是研究探针，不接入 alert_engine.py。

用法：
  python harmonic_backtest.py                # 默认参数跑 QQQ/SPY 三周期
  python harmonic_backtest.py --symbol QQQ
  python harmonic_backtest.py --validate      # 加做成本压力 + walk-forward
"""

import argparse
import warnings
from pathlib import Path

import pandas as pd
import yaml

warnings.filterwarnings("ignore")

from backtesting import Backtest
from harmonic_signals import compute_harmonic_signals
from harmonic_strategy import HarmonicStrategy

with open("config.yaml") as f:
    cfg = yaml.safe_load(f)

DATA_DIR = Path(cfg["data"]["dir"])
TIMEFRAMES = ["1h", "4h", "1d"]
SYMBOLS = ["QQQ", "SPY"]

DEFAULT_PARAMS = {
    "1h": dict(atr_len=14, zigzag_atr_mult=2.5, max_wait_bars=40,
               atr_trail_mult=2.5, max_hold_bars=48, allow_short=True,
               n_contracts=1, contract_size=1,
               cash=100_000, commission=0.001, margin=0.5),
    "4h": dict(atr_len=14, zigzag_atr_mult=2.5, max_wait_bars=30,
               atr_trail_mult=2.5, max_hold_bars=20, allow_short=True,
               n_contracts=1, contract_size=1,
               cash=100_000, commission=0.001, margin=0.5),
    "1d": dict(atr_len=14, zigzag_atr_mult=2.0, max_wait_bars=20,
               atr_trail_mult=2.5, max_hold_bars=30, allow_short=True,
               n_contracts=1, contract_size=1,
               cash=100_000, commission=0.001, margin=0.5),
}

MIN_TRADES = 15
COST_BPS = [0, 5, 10, 20, 30]
PASS_BPS = 10
PASS_SHARPE = 0.6
TRAIN_FRAC = 0.6
MIN_SEGMENT_TRADES = 15


class _HARM(HarmonicStrategy):
    pass


def set_params(p: dict):
    _HARM.atr_trail_mult = float(p.get("atr_trail_mult", 2.5))
    _HARM.max_hold_bars  = int(p.get("max_hold_bars", 40))
    _HARM.allow_short    = bool(p.get("allow_short", True))
    _HARM.n_contracts    = int(p.get("n_contracts", 1))
    _HARM.contract_size  = int(p.get("contract_size", 1))


def load_data(symbol: str, tf: str) -> pd.DataFrame | None:
    path = DATA_DIR / f"{symbol}_{tf}.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.index.name = "Date"
    df.columns = [c.capitalize() for c in df.columns]
    if "Volume" not in df.columns:
        df["Volume"] = 0
    return df


def run_one(df_raw: pd.DataFrame, params: dict) -> dict | None:
    try:
        df_sig = compute_harmonic_signals(df_raw, params)
        set_params(params)
        bt = Backtest(
            df_sig, _HARM,
            cash=float(params.get("cash", 100_000)),
            commission=float(params.get("commission", 0.001)),
            margin=float(params.get("margin", 0.5)),
            exclusive_orders=True,
            finalize_trades=True,
        )
        st = bt.run()
        n = int(st.get("# Trades", 0))
        if n < MIN_TRADES:
            return None
        trades = st["_trades"]
        wins   = trades[trades["PnL"] > 0]["PnL"]
        losses = trades[trades["PnL"] < 0]["PnL"]
        avg_w  = wins.mean()   if len(wins)   else 0
        avg_l  = losses.mean() if len(losses) else 0
        rr     = abs(avg_w / avg_l) if avg_l != 0 else 0
        return {
            "sharpe": round(st.get("Sharpe Ratio", 0), 3),
            "ret":    round(st.get("Return [%]", 0), 2),
            "dd":     round(st.get("Max. Drawdown [%]", 0), 2),
            "wr":     round(st.get("Win Rate [%]", 0), 1),
            "pf":     round(st.get("Profit Factor", 0), 2),
            "rr":     round(rr, 2),
            "n":      n,
        }
    except Exception:
        return None


HDR = (f"{'标的':<6} {'周期':<4} {'收益%':>7} {'Sharpe':>7} "
       f"{'MaxDD%':>8} {'胜率%':>6} {'笔数':>5} {'PF':>5} {'RR':>5}")
SEP = "─" * 60


def print_result(symbol, tf, r):
    print(f"{symbol:<6} {tf:<4} {r['ret']:>7.1f} {r['sharpe']:>7.2f} "
          f"{r['dd']:>8.1f} {r['wr']:>6.1f} {r['n']:>5} {r['pf']:>5.2f} {r['rr']:>5.2f}")


def run_backtest_mode(symbols, tfs):
    all_results = []
    for tf in tfs:
        print(f"\n{'═'*60}")
        print(f"  谐波形态（研究原型） 周期：{tf}")
        print(f"{'═'*60}")
        print(HDR)
        print(SEP)
        for sym in symbols:
            df_raw = load_data(sym, tf)
            if df_raw is None or len(df_raw) < 260:
                print(f"{sym:<6} {tf:<4}  — 无数据/数据不足")
                continue
            params = DEFAULT_PARAMS[tf].copy()
            r = run_one(df_raw, params)
            if r is None:
                print(f"{sym:<6} {tf:<4}  — 信号不足（< {MIN_TRADES} 笔）")
                continue
            print_result(sym, tf, r)
            all_results.append({"symbol": sym, "tf": tf, **r})

    if all_results:
        out = Path("logs/harmonic_backtest_results.csv")
        out.parent.mkdir(exist_ok=True)
        pd.DataFrame(all_results).to_csv(out, index=False)
        print(f"\n结果已保存至 {out}")
    else:
        print("\n全部组合信号不足或无数据——谐波形态在 QQQ/SPY 上触发太少，"
              "样本量不足以下结论。")


def _run_with_cost(df, params, bps):
    p = {**params, "commission": bps / 10000}
    return run_one(df, p)


def validate_one(symbol: str, tf: str) -> dict | None:
    df = load_data(symbol, tf)
    if df is None or len(df) < 260:
        return None
    base = DEFAULT_PARAMS[tf]
    row = {"symbol": symbol, "tf": tf}

    for bps in COST_BPS:
        res = _run_with_cost(df, base, bps)
        row[f"sharpe_{bps}bps"] = round(res["sharpe"], 3) if res else None
        if bps == 0:
            row["n"] = res["n"] if res else 0
            row["dd"] = round(res["dd"], 1) if res else None

    at_pass = row.get(f"sharpe_{PASS_BPS}bps")
    row["cost_verdict"] = ("pass" if at_pass is not None and at_pass >= PASS_SHARPE
                            else "insufficient" if at_pass is None else "fail")

    split = int(len(df) * TRAIN_FRAC)
    tr = run_one(df.iloc[:split], base)
    te = run_one(df.iloc[split:], base)
    row["train_sharpe"] = round(tr["sharpe"], 3) if tr else None
    row["train_n"] = tr["n"] if tr else 0
    row["test_sharpe"] = round(te["sharpe"], 3) if te else None
    row["test_n"] = te["n"] if te else 0

    if not te or te["n"] < MIN_SEGMENT_TRADES or not tr or tr["n"] < MIN_SEGMENT_TRADES:
        row["wf_verdict"] = "insufficient"
    elif te["sharpe"] >= PASS_SHARPE:
        row["wf_verdict"] = "pass"
    elif te["sharpe"] >= tr["sharpe"] * 0.5:
        row["wf_verdict"] = "marginal"
    else:
        row["wf_verdict"] = "fail"
    return row


def run_validate_mode(symbols, tfs):
    rows = []
    for sym in symbols:
        for tf in tfs:
            row = validate_one(sym, tf)
            if row:
                rows.append(row)
    out = pd.DataFrame(rows)
    cols = ["symbol", "tf", "n", "dd", "sharpe_0bps", "sharpe_10bps", "cost_verdict",
            "train_sharpe", "train_n", "test_sharpe", "test_n", "wf_verdict"]
    if not out.empty:
        print(out[cols].to_string(index=False))
        out_path = Path("logs/harmonic_validation.csv")
        out_path.parent.mkdir(exist_ok=True)
        out.to_csv(out_path, index=False)
        print(f"\n结果已保存至 {out_path}")
    else:
        print("全部组合信号不足，无法验证。")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", help="单标的（QQQ/SPY）")
    parser.add_argument("--tf", help="单周期 1h/4h/1d")
    parser.add_argument("--validate", action="store_true",
                         help="成本压力(0-30bps) + walk-forward(60/40)验证")
    args = parser.parse_args()

    symbols = [args.symbol.upper()] if args.symbol else SYMBOLS
    tfs     = [args.tf] if args.tf else TIMEFRAMES

    if args.validate:
        run_validate_mode(symbols, tfs)
    else:
        run_backtest_mode(symbols, tfs)


if __name__ == "__main__":
    main()
