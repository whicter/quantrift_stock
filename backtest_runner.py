"""
backtest_runner.py — 批量回测所有标的 × 所有周期

用法：
  python backtest_runner.py                        # 全量
  python backtest_runner.py --symbol NVDA          # 单标的
  python backtest_runner.py --symbol NVDA --tf 1h  # 单标的单周期
  python backtest_runner.py --sort sharpe          # 按指定指标排序（sharpe/dd/wr/ret）
"""

import argparse
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
    cfg["symbols"]["mag7"]
    + cfg["symbols"]["semis"]
    + cfg["symbols"]["etfs"]
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
    _S.n_contracts           = int(p.get("n_contracts", 1))
    _S.contract_size         = int(p.get("contract_size", 1))


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


def run_backtest(symbol: str, tf: str, params: dict) -> dict | None:
    df_raw = load_data(symbol, tf)
    if df_raw is None or len(df_raw) < 50:
        return None

    try:
        df_sig = compute_signals(df_raw, params)
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", help="单标的，如 NVDA")
    parser.add_argument("--tf", help="单周期，如 1h / 4h / 1d")
    parser.add_argument("--sort", default="sharpe",
                        choices=["sharpe", "dd", "wr", "ret"],
                        help="最终排名排序依据")
    args = parser.parse_args()

    symbols = [args.symbol.upper()] if args.symbol else ALL_SYMBOLS
    tfs     = [args.tf] if args.tf else TIMEFRAMES

    all_results = []

    for tf in tfs:
        tf_defaults = cfg["timeframes"][tf]
        print(f"\n{'═'*65}")
        print(f"  周期：{tf}  (adx≥{tf_defaults['adx_threshold']}  ut_key={tf_defaults['ut_key']}  "
              f"min_score={tf_defaults['min_score']})")
        print(f"{'═'*65}")
        print(HDR)
        print(SEP)

        for sym in symbols:
            params = get_params(sym, tf)
            r = run_backtest(sym, tf, params)
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
