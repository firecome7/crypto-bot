"""直接打印背离检测的中间值"""
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
macd_signal = ema(macd_line, 9)
macd_hist = macd_line - macd_signal

n = len(closes)
window = 24
count = 0

for i in range(50, n):
    if np.isnan(macd_hist[i]) or np.isnan(macd_line[i]):
        continue
    
    start = max(0, i - window)
    mid = start + window // 2
    
    first_half = closes[start:mid+1]
    second_half = closes[mid+1:i+1]
    
    if len(first_half) == 0 or len(second_half) == 0:
        continue
    
    # 底背离
    first_min = np.min(first_half)
    first_min_idx = np.argmin(first_half) + start
    second_min = np.min(second_half)
    second_min_idx = np.argmin(second_half) + mid + 1
    
    if second_min < first_min:
        first_macd = macd_hist[first_min_idx]
        second_macd = macd_hist[second_min_idx]
        if not np.isnan(first_macd) and not np.isnan(second_macd):
            if second_macd > first_macd:
                if count < 5:
                    print(f"底背离 @ idx={second_min_idx}: price={second_min:.2f}<{first_min:.2f}, macd_hist={second_macd:.4f}>{first_macd:.4f}")
                count += 1

    # 顶背离
    first_max = np.max(first_half)
    first_max_idx = np.argmax(first_half) + start
    second_max = np.max(second_half)
    second_max_idx = np.argmax(second_half) + mid + 1
    
    if second_max > first_max:
        first_macd = macd_hist[first_max_idx]
        second_macd = macd_hist[second_max_idx]
        if not np.isnan(first_macd) and not np.isnan(second_macd):
            if second_macd < first_macd:
                if count < 5:
                    print(f"顶背离 @ idx={second_max_idx}: price={second_max:.2f}>{first_max:.2f}, macd_hist={second_macd:.4f}<{first_macd:.4f}")
                count += 1

print(f"\n总背离信号: {count}")
