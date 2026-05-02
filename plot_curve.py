import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path

# 读取交易记录
trades = pd.read_csv("data/backtest_10coins_fixed.csv")
trades["entry_time"] = pd.to_datetime(trades["entry_time"])
trades["exit_time"] = pd.to_datetime(trades["exit_time"])

# 生成权益曲线：按时间逐笔累加 PnL
# 按退出时间排序
trades_sorted = trades.sort_values("exit_time")

balance = 10000
equity = [(trades_sorted.iloc[0]["entry_time"] - pd.Timedelta(days=1), balance)]
for _, row in trades_sorted.iterrows():
    balance += row["pnl"]
    equity.append((row["exit_time"], balance))

df_equity = pd.DataFrame(equity, columns=["time", "balance"])
df_equity.set_index("time", inplace=True)

# 创建图表
fig, ax = plt.subplots(figsize=(16, 8))
fig.patch.set_facecolor("#0f172a")
ax.set_facecolor("#0f172a")

# 资金曲线
ax.fill_between(df_equity.index, df_equity["balance"], df_equity["balance"].min() * 0.95,
                alpha=0.15, color="#22d3ee")
ax.plot(df_equity.index, df_equity["balance"], color="#22d3ee", linewidth=2, label="Strategy")

# Buy & Hold 对比线
BALANCE_INIT = 10000
SYMBOLS = ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","DOGEUSDT","ADAUSDT","AVAXUSDT","LINKUSDT","DOTUSDT"]
data_dir = Path("data/kline")

# 计算等权重 B&H
df_btc = pd.read_parquet(data_dir / "BTCUSDT_5m.parquet")
bh_times = df_equity.index  # 对齐时间
first_close = {}
last_close = {}
for sym in SYMBOLS:
    df = pd.read_parquet(data_dir / f"{sym}_5m.parquet")
    first_close[sym] = df.iloc[0]["close"]
    last_close[sym] = df.iloc[-1]["close"]

# B&H 是一条直线（等权重买入持有不动）
bh_returns = []
for t in bh_times:
    ret = 0
    for sym in SYMBOLS:
        df = pd.read_parquet(data_dir / f"{sym}_5m.parquet")
        mask = df.index <= t
        if mask.any():
            price = df[mask].iloc[-1]["close"]
            r = (price - first_close[sym]) / first_close[sym]
            ret += r
    ret /= len(SYMBOLS)
    bh_returns.append(ret)

bh_equity = [BALANCE_INIT * (1 + r) for r in bh_returns]

ax.plot(bh_times, bh_equity, color="#fb7185", linewidth=1.5, linestyle="--", alpha=0.7, label="Buy & Hold (equal weight)")

# 装饰
ax.set_title("10 Coin Backtest: $10,000 → $18,986 (+89.86%)", color="white", fontsize=16, pad=20)
ax.set_ylabel("Portfolio Value ($)", color="white", fontsize=12)
ax.set_xlabel("")
ax.grid(True, alpha=0.15, color="#334155")
ax.tick_params(colors="white")

# 起点终点标注
ax.axhline(y=10000, color="#64748b", linestyle=":", alpha=0.4)
ax.axhline(y=18986, color="#22d3ee", linestyle=":", alpha=0.4)
ax.annotate(f"${10000:,}", xy=(df_equity.index[0], 10000), color="#94a3b8", fontsize=10, xytext=(5, -15), textcoords="offset points")
ax.annotate(f"${18986:,}", xy=(df_equity.index[-1], 18986), color="#22d3ee", fontsize=10, xytext=(-80, 5), textcoords="offset points")

# 统计信息
stats_text = (
    f"Initial:  $10,000\n"
    f"Final:    $18,986\n"
    f"Return:   +89.86%\n"
    f"Win Rate: 42.8%\n"
    f"Trades:   1,463\n"
    f"vs B&H:   -34.69%"
)
props = dict(boxstyle="round,pad=0.5", facecolor="#1e293b", edgecolor="#334155")
ax.text(0.02, 0.97, stats_text, transform=ax.transAxes, fontsize=11,
        verticalalignment="top", color="white", bbox=props, fontfamily="monospace")

legend = ax.legend(loc="lower right", facecolor="#1e293b", edgecolor="#334155", labelcolor="white")
for text in legend.get_texts():
    text.set_color("white")

plt.tight_layout()
plt.savefig("backtest_curve.png", dpi=150, bbox_inches="tight", facecolor="#0f172a")
print("已保存: backtest_curve.png")
