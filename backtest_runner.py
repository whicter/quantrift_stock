"""
backtest_runner.py — 批量回测所有标的 × 所有周期

用法：
  python backtest_runner.py                              # 全量
  python backtest_runner.py --symbol NVDA                # 单标的
  python backtest_runner.py --symbol NVDA --tf 1h        # 单标的单周期
  python backtest_runner.py --sort sharpe                # 按指定指标排序（sharpe/dd/wr/ret）
  python backtest_runner.py --symbol TSLA --optimize     # 网格优化（adx/ut_key/min_score）
"""

import argparse
import itertools
import warnings
from pathlib import Path

import pandas as pd
import yaml

warnings.filterwarnings("ignore")

from backtesting import Backtest
from indicators import compute_signals
from param_loader import get_params
from strategy import ConfluenceStrategy

with open("config.yaml") as f:
    cfg = yaml.safe_load(f)

DATA_DIR = Path(cfg["data"]["dir"])

ALL_SYMBOLS = (
    cfg["symbols"].get("momentum", [])
    + cfg["symbols"].get("high_vol", [])
    + cfg["symbols"].get("storage", [])
    + cfg["symbols"].get("mega_cap", [])
    + cfg["symbols"].get("watch", [])
    + cfg["symbols"].get("pending", [])
    + cfg["symbols"].get("sector_etf", [])
    + cfg["symbols"].get("broad_etf", [])
)

TIMEFRAMES = ["1h", "4h", "1d"]


class _S(ConfluenceStrategy):
    pass


def set_params(p: dict):
    _S.min_score           = int(p.get("min_score", 5))
    _S.adx_threshold       = float(p.get("adx_threshold", 25.0))
    _S.use_adx             = bool(p.get("use_adx", True))
    _S.use_bbmc_dir        = bool(p.get("use_bbmc_dir", True))
    _S.use_vol             = bool(p.get("use_vol", True))
    _S.vol_mult            = float(p.get("vol_mult", 1.0))
    _S.allow_short         = bool(p.get("allow_short", True))
    _S.reversal_score      = int(p.get("reversal_score", 2))
    _S.conflict_threshold  = int(p.get("conflict_threshold", 2))
    _S.use_squeeze_mr      = bool(p.get("use_squeeze_mr", False))
    _S.use_staged_tp       = bool(p.get("use_staged_tp", True))
    _S.atr_tp1_mult        = float(p.get("atr_tp1_mult", 1.0))
    _S.atr_tp2_mult        = float(p.get("atr_tp2_mult", 2.0))
    _S.tp1_portion         = float(p.get("tp1_portion", 0.34))
    _S.use_trend_filter      = bool(p.get("use_trend_filter", False))
    _S.allow_reversal_flip   = bool(p.get("allow_reversal_flip", True))
    _S.use_fixed_initial_sl  = bool(p.get("use_fixed_initial_sl", False))
    _S.atr_sl_mult           = float(p.get("atr_sl_mult", 1.5))
    _S.n_contracts               = int(p.get("n_contracts", 1))
    _S.contract_size             = int(p.get("contract_size", 1))
    _S.use_regime_filter         = bool(p.get("use_regime_filter", False))
    _S.min_market_score          = int(p.get("min_market_score", 2))
    _S.use_breakeven_after_tp1   = bool(p.get("use_breakeven_after_tp1", False))


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


def run_backtest(symbol: str, tf: str, params: dict,
                 df_qqq: pd.DataFrame | None = None) -> dict | None:
    df_raw = load_data(symbol, tf)
    if df_raw is None or len(df_raw) < 50:
        return None

    try:
        df_sig = compute_signals(df_raw, params, df_qqq)
        set_params(params)
        bt = Backtest(
            df_sig, _S,
            cash=float(params.get("cash", 100_000)),
            commission=float(params.get("commission", 0.001)),
            margin=float(params.get("margin", 0.5)),
            exclusive_orders=True,
            finalize_trades=True,
        )
        st = bt.run()
        trades = st["_trades"]
        wins   = trades[trades["PnL"] > 0]["PnL"]
        losses = trades[trades["PnL"] < 0]["PnL"]
        avg_w  = wins.mean()   if len(wins)   else 0
        avg_l  = losses.mean() if len(losses) else 0
        rr     = abs(avg_w / avg_l) if avg_l != 0 else 0
        return {
            "symbol": symbol,
            "tf":     tf,
            "ret":    round(st.get("Return [%]", 0), 1),
            "sharpe": round(st.get("Sharpe Ratio", 0), 2),
            "dd":     round(st.get("Max. Drawdown [%]", 0), 1),
            "wr":     round(st.get("Win Rate [%]", 0), 1),
            "n":      int(st.get("# Trades", 0)),
            "pf":     round(st.get("Profit Factor", 0), 2),
            "rr":     round(rr, 2),
        }
    except Exception as e:
        print(f"  [{symbol} {tf}] ERROR: {e}")
        return None


HDR = (f"{'标的':<8} {'周期':<5} {'收益%':>7} {'Sharpe':>7} "
       f"{'MaxDD%':>8} {'胜率%':>6} {'笔数':>5} {'PF':>5} {'RR':>5}")
SEP = "─" * 65


def print_result(r: dict):
    print(f"{r['symbol']:<8} {r['tf']:<5} {r['ret']:>7.1f} {r['sharpe']:>7.2f} "
          f"{r['dd']:>8.1f} {r['wr']:>6.1f} {r['n']:>5} {r['pf']:>5.2f} {r['rr']:>5.2f}")


OPTIMIZE_GRID = {
    "adx_threshold": [15.0, 20.0, 25.0, 30.0],
    "ut_key":        [1.0, 1.5, 2.0, 2.5, 3.0],
    "min_score":     [3, 4, 5],
}


def run_optimize(symbol: str, tfs: list[str]):
    """Grid search over adx_threshold × ut_key × min_score for a single symbol."""
    keys   = list(OPTIMIZE_GRID.keys())
    values = list(OPTIMIZE_GRID.values())
    combos = list(itertools.product(*values))
    total  = len(combos) * len(tfs)
    print(f"\n优化 {symbol}：{len(combos)} 参数组合 × {len(tfs)} 周期 = {total} 次回测\n")

    all_results = []
    done = 0
    for tf in tfs:
        base_params = get_params(symbol, tf)
        df_qqq = load_data("QQQ", tf)
        for combo in combos:
            override = dict(zip(keys, combo))
            params = {**base_params, **override}
            r = run_backtest(symbol, tf, params, df_qqq)
            done += 1
            if done % 20 == 0:
                print(f"  进度 {done}/{total}…")
            if r is None:
                continue
            r.update(override)
            all_results.append(r)

    if not all_results:
        print("无有效回测结果")
        return

    df = pd.DataFrame(all_results)
    # 过滤笔数 < 10
    df = df[df["n"] >= 10]

    # 按周期分别打印 Top 5
    for tf in tfs:
        sub = df[df["tf"] == tf].sort_values("sharpe", ascending=False).head(5)
        if sub.empty:
            continue
        print(f"\n{'═'*75}")
        print(f"  {symbol} {tf} — Top 5 (按 Sharpe)")
        print(f"{'═'*75}")
        print(f"{'adx':>6} {'ut_key':>7} {'score':>6} | "
              f"{'Sharpe':>7} {'WR%':>6} {'笔数':>5} {'PF':>5} {'RR':>5}")
        print("─" * 75)
        for _, row in sub.iterrows():
            print(f"{row['adx_threshold']:>6.0f} {row['ut_key']:>7.1f} {row['min_score']:>6.0f} | "
                  f"{row['sharpe']:>7.2f} {row['wr']:>6.1f} {row['n']:>5} {row['pf']:>5.2f} {row['rr']:>5.2f}")

    # 全局最优（跨周期）
    best = df.sort_values("sharpe", ascending=False).head(10)
    print(f"\n{'═'*75}")
    print(f"  {symbol} 全局 Top 10")
    print(f"{'═'*75}")
    print(f"{'tf':>4} {'adx':>6} {'ut_key':>7} {'score':>6} | "
          f"{'Sharpe':>7} {'WR%':>6} {'笔数':>5} {'PF':>5} {'RR':>5}")
    print("─" * 75)
    for _, row in best.iterrows():
        print(f"{row['tf']:>4} {row['adx_threshold']:>6.0f} {row['ut_key']:>7.1f} {row['min_score']:>6.0f} | "
              f"{row['sharpe']:>7.2f} {row['wr']:>6.1f} {row['n']:>5} {row['pf']:>5.2f} {row['rr']:>5.2f}")

    out_path = Path(f"logs/optimize_{symbol}.csv")
    out_path.parent.mkdir(exist_ok=True)
    df.to_csv(out_path, index=False)
    print(f"\n完整结果已保存至 {out_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", help="单标的，如 NVDA")
    parser.add_argument("--tf", help="单周期，如 1h / 4h / 1d")
    parser.add_argument("--sort", default="sharpe",
                        choices=["sharpe", "dd", "wr", "ret"],
                        help="最终排名排序依据")
    parser.add_argument("--optimize", action="store_true",
                        help="网格优化 adx_threshold / ut_key / min_score（需指定 --symbol）")
    parser.add_argument("--cost-test", action="store_true", dest="cost_test",
                        help="成本压力测试：在 0/5/10/20/30 bps 下跑回测（需指定 --symbol --tf）")
    args = parser.parse_args()

    symbols = [args.symbol.upper()] if args.symbol else ALL_SYMBOLS
    tfs     = [args.tf] if args.tf else TIMEFRAMES

    if args.optimize:
        if not args.symbol:
            parser.error("--optimize 需要指定 --symbol")
        run_optimize(args.symbol.upper(), tfs)
        return

    if args.cost_test:
        if not args.symbol or not args.tf:
            parser.error("--cost-test 需要指定 --symbol 和 --tf")
        sym = args.symbol.upper()
        tf  = args.tf
        df_qqq = load_data("QQQ", tf)
        bps_levels = [0, 5, 10, 20, 30]
        print(f"\n{'═'*65}")
        print(f"  成本压力测试：{sym} {tf}")
        print(f"{'═'*65}")
        print(f"{'bps':>5} {'Sharpe':>7} {'WR%':>6} {'笔数':>5} {'RR':>5} {'MaxDD%':>8}")
        print("─" * 45)
        for bps in bps_levels:
            params = get_params(sym, tf)
            params["commission"] = bps / 10000
            r = run_backtest(sym, tf, params, df_qqq)
            if r:
                flag = "  ✅" if r["sharpe"] >= 0.7 else "  ❌"
                print(f"{bps:>5} {r['sharpe']:>7.2f} {r['wr']:>6.1f} {r['n']:>5} "
                      f"{r['rr']:>5.2f} {r['dd']:>8.1f}{flag}")
            else:
                print(f"{bps:>5}  — 信号不足")
        return

    all_results = []

    for tf in tfs:
        tf_defaults = cfg["timeframes"][tf]
        df_qqq = load_data("QQQ", tf)   # 用于 Market Regime Score
        print(f"\n{'═'*65}")
        print(f"  周期：{tf}  (adx≥{tf_defaults['adx_threshold']}  ut_key={tf_defaults['ut_key']}  "
              f"min_score={tf_defaults['min_score']})")
        print(f"{'═'*65}")
        print(HDR)
        print(SEP)

        for sym in symbols:
            params = get_params(sym, tf)
            r = run_backtest(sym, tf, params, df_qqq)
            if r is None:
                print(f"{sym:<8} {tf:<5}  — 无数据或数据不足")
                continue
            print_result(r)
            all_results.append(r)

    if len(all_results) > 1:
        sort_key = {"sharpe": "sharpe", "dd": "dd", "wr": "wr", "ret": "ret"}[args.sort]
        reverse  = sort_key != "dd"
        ranked   = sorted(all_results, key=lambda x: x[sort_key], reverse=reverse)

        print(f"\n{'═'*65}")
        print(f"  最终排名（按 {args.sort} {'降序' if reverse else '升序'}）")
        print(f"{'═'*65}")
        print(HDR)
        print(SEP)
        for r in ranked:
            print_result(r)

        # 保存结果到 CSV
        df_out = pd.DataFrame(all_results)
        out_path = Path("logs/backtest_results.csv")
        out_path.parent.mkdir(exist_ok=True)
        df_out.to_csv(out_path, index=False)
        print(f"\n结果已保存至 {out_path}")


if __name__ == "__main__":
    main()
