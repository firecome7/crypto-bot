"""验证修复后的斜率"""
import pandas as pd, numpy as np
from scipy import stats

df = pd.read_parquet("data/kline/BTCUSDT_5m.parquet")
df_h1 = df["close"].resample("1h").last().dropna()

def calc_slope(values):
    x = np.arange(len(values))
    return stats.linregress(x, values).slope

def check_trend(hourly_close, boll_period=20, lookback=5):
    if len(hourly_close) < boll_period + lookback: return None, 0.0
    mids = []
    for i in range(lookback):
        end = len(hourly_close) - i
        start = end - boll_period
        segment = hourly_close[start:end]
        if len(segment) >= boll_period:
            mids.append(np.mean(segment))
    if len(mids) < 2: return None, 0.0
    slope = calc_slope(np.array(mids))
    return slope > 0, slope

# 测试一段数据
close = df_h1.iloc[30:60].values
bull, slope = check_trend(close)
print(f"样本: {close[:3]} ... {close[-3:]}")
print(f"多头: {bull}, 斜率: {slope:.6f}")

# 全量统计
slopes = []
for i in range(30, len(df_h1)):
    seg = df_h1.iloc[i-25:i].values  # 传 25 根，含 5 根 lookback buffer
    bull, s = check_trend(seg)
    if bull is not None:
        slopes.append(s)

arr = np.array(slopes)
print(f"\n全量统计 ({len(arr)} 样本):")
print(f"  斜率中位数: {np.median(arr):.6f}")
print(f"  绝对值中位数: {np.median(np.abs(arr)):.6f}")
print(f"  绝对值25%: {np.percentile(np.abs(arr), 25):.6f}")
print(f"  绝对值10%: {np.percentile(np.abs(arr), 10):.6f}")
print(f"  非零比例: {(np.abs(arr) > 0).mean()*100:.1f}%")
print(f"  >0.1: {(np.abs(arr) > 0.1).mean()*100:.1f}%")
print(f"  >0.01: {(np.abs(arr) > 0.01).mean()*100:.1f}%")
