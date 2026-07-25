"""
etf_rotation_backtest.py — 宽基/被动配置ETF 周频相对强弱轮动回测

背景：2026-07-25 watchlist 批量回测里，VUG/VYM/VXUS/JEPI 等 34 只宽基/资产配置类
ETF 用 Confluence/RSI2/Breakout/MR 四套"绝对水平择时"策略全部不达标——这类 ETF
本身波动率低、没有明确的超买超卖或突破特征，绝对水平择时策略结构性抓不到边际。

复用 mag7_rotation.py 已验证有效的方法论（相对强弱排名 + top-N 轮动 + 可选
risk-off 过滤），但标的池换成这批宽基/配置 ETF：比较"谁相对更强"而不是判断
"现在该不该买这一只"。

用法：
  python etf_rotation_backtest.py                       # top=2, rs=60d
  python etf_rotation_backtest.py --top 3 --rs-period 90
  python etf_rotation_backtest.py --risk-off
  python etf_rotation_backtest.py --scan                # 参数敏感性扫描
"""

import argparse
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

from mag7_rotation import run_rotation, calc_metrics, run_sensitivity, print_holding_dist

# 2026-07-25 watchlist 批量回测中未被四套策略覆盖的宽基/被动配置 ETF
ETF_UNIVERSE = [
    "VGRO", "QQQM", "VPL", "VUG", "AVGV", "VXUS", "VT", "VGK", "XSMO",
    "AOK", "AOA", "AOR", "RSP", "IJR", "VB", "VCR", "VYM", "VYMI", "RTH",
    "FLCA", "AVDV", "DFAW", "SCHG", "JEPI", "JEPQ", "ICF", "REM",
    "AVUV", "AVIV", "AVNM", "AVGE", "SCHD", "QQQX", "QQQI",
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=2, help="持仓只数（默认 2）")
    parser.add_argument("--rs-period", type=int, default=60, help="RS 计算周期（交易日，默认 60）")
    parser.add_argument("--risk-off", action="store_true", help="QQQ < 200SMA 时空仓")
    parser.add_argument("--scan", action="store_true", help="参数敏感性扫描")
    args = parser.parse_args()

    if args.scan:
        results = run_sensitivity(
            top_ns=[1, 2, 3, 4],
            rs_periods=[20, 40, 60, 90],
            use_risk_off=args.risk_off,
        )
        if results:
            best = max(results, key=lambda x: x["sharpe"])
            print(f"\n  最优: top_n={best['top_n']}  rs={best['rs_period']}d"
                  f"  Sharpe={best['sharpe']:.3f}  MaxDD={best['max_dd']:.1f}%")
        print("\n  基准：等权持有全部 ETF（每周再平衡）")
        rec_bm = run_rotation(top_n=len(ETF_UNIVERSE), rs_period=60, use_risk_off=False, symbols=ETF_UNIVERSE)
        m_bm = calc_metrics(rec_bm)
        print(f"  Sharpe={m_bm['sharpe']:.3f}  年化={m_bm['ann_ret']:.1f}%  MaxDD={m_bm['max_dd']:.1f}%")
    else:
        rec = run_rotation(top_n=args.top, rs_period=args.rs_period,
                           use_risk_off=args.risk_off, symbols=ETF_UNIVERSE)
        m = calc_metrics(rec)
        print(f"\n{'═'*55}")
        print(f"  ETF轮动  top={args.top}  rs={args.rs_period}d  risk_off={args.risk_off}")
        print(f"{'═'*55}")
        print(f"  总收益:   {m['total_ret']:.1f}%")
        print(f"  年化收益: {m['ann_ret']:.1f}%  年化波动: {m['ann_vol']:.1f}%")
        print(f"  Sharpe:   {m['sharpe']:.3f}")
        print(f"  最大回撤: {m['max_dd']:.1f}%")
        print(f"  周胜率:   {m['wr']:.1f}%  （{m['n_weeks']} 周）")
        print_holding_dist(rec)

        print(f"\n  基准：等权持有全部 ETF")
        rec_bm = run_rotation(top_n=len(ETF_UNIVERSE), rs_period=60, use_risk_off=False, symbols=ETF_UNIVERSE)
        m_bm = calc_metrics(rec_bm)
        print(f"  Sharpe={m_bm['sharpe']:.3f}  年化={m_bm['ann_ret']:.1f}%  MaxDD={m_bm['max_dd']:.1f}%")

        out = Path("logs/etf_rotation.csv")
        out.parent.mkdir(exist_ok=True)
        rec.to_csv(out)
        print(f"\n  结果已保存至 {out}")


if __name__ == "__main__":
    main()
