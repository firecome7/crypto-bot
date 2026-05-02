"""验证资金管理逻辑"""
import pandas as pd

trades = pd.read_csv("data/backtest_10coins_fixed.csv")

# 检查每笔止损/止盈的 PnL 计算
print("资金管理验证:")
print(f"每笔仓位大小: $1000\n")

# 检查几笔止损
samples = trades[trades["reason"].isin(["止损", "止盈"])].head(10)
for _, row in samples.iterrows():
    expected_pnl = 1000 * row["pnl_pct"]
    actual_pnl = row["pnl"]
    print(f"{row['symbol']} {row['reason']}: pnl_pct={row['pnl_pct']*100:.2f}%, 预期pnl=${expected_pnl:.2f}, 实际=${actual_pnl:.2f}")
    if abs(expected_pnl - actual_pnl) > 0.01:
        print(f"  ⚠️ 不匹配!")

print()

# 检查尾盘平仓 - 这些是持有了很久的
tails = trades[trades["reason"] == "尾盘平仓"]
print(f"尾盘平仓 {len(tails)} 笔:")
for _, row in tails.iterrows():
    expected_pnl = 1000 * row["pnl_pct"]
    print(f"  {row['symbol']}: holding {row['pnl_pct']*100:.2f}% -> pnl=${expected_pnl:.0f}")

print()

# 总PnL验证
gross_pnl = trades["pnl"].sum()
print(f"交易总PnL: ${gross_pnl:.0f}")
print(f"最终余额: ${10000 + gross_pnl:.0f}")
print(f"总收益率: {(10000 + gross_pnl - 10000)/10000*100:.2f}%")
