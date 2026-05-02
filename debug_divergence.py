"""调试 MACD 背离检测"""
import numpy as np, pandas as pd
from pathlib import Path

sym = "BNBUSDT"
df = pd.read_parquet(f"data/kline/{sym}_5m.parquet")
closes = df["close"].values.astype(np.float64)

# 手动算 MACD
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
macd_signal = ema(macd_line, 9)
macd_hist = macd_line - macd_signal

# 检测底背离: 价格新低 + MACD 没新低
lookback = 60
bullish = 0
bearish = 0

sample_idx = []
for i in range(100, min(500, len(closes))):
    if np.isnan(macd_line[i]) or np.isnan(macd_signal[i]):
        continue
    
    start = max(0, i - lookback)
    
    # 底背离
    min_idx = np.argmin(closes[start:i+1]) + start
    if min_idx >= i: continue
    
    min_price = closes[min_idx]
    min_macd = macd_line[min_idx]
    
    if closes[i] < min_price and macd_line[i] > min_macd and not np.isnan(macd_line[i]) and not np.isnan(min_macd):
        bullish += 1
        sample_idx.append(i)
        if len(sample_idx) <= 3:
            print(f"底背离 @ idx={i}, price={closes[i]:.2f}<{min_price:.2f}, macd={macd_line[i]:.2f}>{min_macd:.2f}")

print(f"\n底背离: {bullish}")
print(f"顶背离: {bearish}")
print(f"样本: {sample_idx[:10]}")
