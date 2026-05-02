"""检查异常止损"""
import pandas as pd
from pathlib import Path

trades = pd.read_csv("data/backtest_10coins_fixed.csv")
excessive = trades[(trades["reason"]=="止损") & (trades["pnl_pct"] < -0.03)]
print(f"止损超过3%的: {len(excessive)} 笔\n")

for _, row in excessive.head(10).iterrows():
    print(f"{row['symbol']}: entry=${row['entry']:.2f}, exit=${row['exit']:.2f}, pnl={row['pnl_pct']*100:.2f}%")
    print(f"  {row['entry_time']} -> {row['exit_time']}")
    
    df = pd.read_parquet(f"data/kline/{row['symbol']}_5m.parquet")
    mask = (df.index >= row['entry_time']) & (df.index <= row['exit_time'])
    seg = df[mask]
    if len(seg) > 1:
        if row["side"] == "long":
            stop = row["entry"] * 0.98
            actual_min = seg["low"].min()
            gap = (actual_min - stop) / stop * 100
            print(f"  止损价: ${stop:.2f}, 实际最低: ${actual_min:.2f} (穿{gap:.2f}%)")
        else:
            stop = row["entry"] * 1.02
            actual_max = seg["high"].max()
            gap = (stop - actual_max) / stop * 100
            print(f"  止损价: ${stop:.2f}, 实际最高: ${actual_max:.2f} (穿{gap:.2f}%)")
    print()
