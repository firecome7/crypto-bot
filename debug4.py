"""看价格分段实际值"""
import numpy as np, pandas as pd
from pathlib import Path

sym = "BNBUSDT"
df = pd.read_parquet(f"data/kline/{sym}_5m.parquet")
closes = df["close"].values.astype(np.float64)

window = 24
count_min = 0
count_max = 0

for i in range(5000, 5500):
    start = max(0, i - window)
    mid = start + window // 2
    
    first = closes[start:mid+1]
    second = closes[mid+1:i+1]
    if len(first) == 0 or len(second) == 0: continue
    
    fmin = np.min(first)
    smin = np.min(second)
    fmax = np.max(first)
    smax = np.max(second)
    
    if smin < fmin:
        count_min += 1
    if smax > fmax:
        count_max += 1

print(f"后半段有新低: {count_min}/500")
print(f"后半段有新高: {count_max}/500")

# 看看前后半段的具体数值对比
i = 5000
start = max(0, i - window)
mid = start + window // 2
print(f"\ni={i}, start={start}, mid={mid}")
print(f"前半段 closes[{start}:{mid+1}] = {closes[start:mid+1].tolist()}")
print(f"后半段 closes[{mid+1}:{i+1}] = {closes[mid+1:i+1].tolist()}")
print(f"前半段最低: {np.min(closes[start:mid+1]):.2f}")
print(f"后半段最低: {np.min(closes[mid+1:i+1]):.2f}")
