"""深度分析尾盘平仓"""
import pandas as pd
from pathlib import Path

trades = pd.read_csv("data/backtest_10coins_fixed.csv")
tails = trades[trades["reason"] == "尾盘平仓"]

print(f"尾盘平仓 {len(tails)} 笔:\n")

for _, row in tails.iterrows():
    df = pd.read_parquet(f"data/kline/{row['symbol']}_5m.parquet")
    mask = (df.index >= row["entry_time"]) & (df.index <= row["exit_time"])
    seg = df[mask]
    if len(seg) == 0: continue
    
    if row["side"] == "long":
        high_ever = seg["high"].max()
        high_pct = (high_ever - row["entry"]) / row["entry"] * 100
        exit_pct = (row["exit"] - row["entry"]) / row["entry"] * 100
        
        # 检查高位后是否跌了 60%
        triggered = False
        for i in range(len(seg)):
            h = seg.iloc[:i+1]["high"].max()
            ret = (h - row["entry"]) / row["entry"]
            if ret >= 0.03:
                dd = (h - seg.iloc[i]["close"]) / h
                if dd >= 0.60:
                    cl = seg.iloc[i]["close"]
                    r = (cl - row["entry"]) / row["entry"]
                    print(f"{row['symbol']}: 在{str(seg.index[i])[:19]}就应该止盈! ret={r*100:.1f}%, high当时=${h:.2f}")
                    triggered = True
                    break
        
        if not triggered:
            print(f"{row['symbol']}: 峰值{high_pct:+.2f}%后未触发60%回撤止盈")
        
        print(f"  entry=${row['entry']:.2f}, peak=+{high_pct:.1f}%, exit={exit_pct:+.1f}%")
        print(f"  duration: {row['entry_time'][:10]} ~ {row['exit_time'][:10]}")
    print()
