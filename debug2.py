"""看 MACD 和价格的波谷关系"""
import numpy as np, pandas as pd
from pathlib import Path

sym = "BNBUSDT"
df = pd.read_parquet(f"data/kline/{sym}_5m.parquet")
closes = df["close"].values.astype(np.float64)

def ema(arr, period):
    result = np.full(len(arr), np.nan)
    alpha = 2.0 / (period + 1)
    result[period-1] = np.mean(arr[:period])
    for i in range(period, len(arr)):
        result[i] = arr[i] * alpha + result[i-1] * (1 - alpha)
    return result

ema12 = ema(closes, 12)
ema26 = ema(closes, 26)
macd_line = ema12 - ema26

# 看 1000-1100 段
count = 0
for i in range(1000, 1100):
    if np.isnan(macd_line[i]): continue
    start = max(0, i - 30)
    min_idx = np.argmin(closes[start:i+1]) + start
    if min_idx >= i: continue
    
    min_price = closes[min_idx]
    min_macd = macd_line[min_idx]
    
    if closes[i] < min_price:
        count += 1
        if count <= 10:
            lower = macd_line[i] < min_macd
            print(f"idx={i}: price={closes[i]:.2f}<{min_price:.2f}, macd_cur={macd_line[i]:.2f}, macd_min={min_macd:.2f}, macd更低={lower}")

if count == 0:
    print("无价格新低情况")
    
# 直接对比价格和 MACD 的走势
print("\n--- 看 5000-5100 段价格变化 ---")
for i in range(5000, 5050):
    if i > 0:
        pct = (closes[i] - closes[i-1]) / closes[i-1] * 100
        macd_pct = macd_line[i] - macd_line[i-1]
        if abs(pct) > 0.3:  # 价格波动超过 0.3%
            print(f"idx={i}: price={closes[i]:.2f} ({pct:+.2f}%), macd={macd_line[i]:.2f} ({macd_pct:+.2f})")
