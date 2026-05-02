"""查一下典型斜率值分布"""
import pandas as pd
import numpy as np
from pathlib import Path
from scipy import stats

SYMBOLS = ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","DOGEUSDT","ADAUSDT","AVAXUSDT","LINKUSDT","DOTUSDT"]

def calc_slope(values):
    x = np.arange(len(values))
    res = stats.linregress(x, values)
    return res.slope

all_slopes = []
for sym in SYMBOLS[:3]:  # 先看 3 个
    df = pd.read_parquet(f"data/kline/{sym}_5m.parquet")
    df_h1 = df["close"].resample("1h").last().dropna()
    
    for i in range(30, len(df_h1)):
        segment = df_h1.iloc[i-25:i].values  # 取最近 25 根小时线
        slope = calc_slope(segment)
        all_slopes.append(abs(slope))

slopes = np.array(all_slopes)
print(f"样本数: {len(slopes)}")
print(f"平均斜率绝对值: {slopes.mean():.6f}")
print(f"中位数: {np.median(slopes):.6f}")
print(f"25%分位: {np.percentile(slopes, 25):.6f}")
print(f"75%分位: {np.percentile(slopes, 75):.6f}")
print(f"90%分位: {np.percentile(slopes, 90):.6f}")
print(f"99%分位: {np.percentile(slopes, 99):.6f}")
print()

# 看 BTC 的斜率范围
df_btc = pd.read_parquet("data/kline/BTCUSDT_5m.parquet")
df_h1 = df_btc["close"].resample("1h").last().dropna()
sample_slopes = []
for i in range(30, len(df_h1)):
    segment = df_h1.iloc[i-25:i].values
    slope = calc_slope(segment)
    sample_slopes.append(slope)
    
arr = np.array(sample_slopes)
print(f"BTC 斜率:")
print(f"  min: {arr.min():.6f}")
print(f"  max: {arr.max():.6f}")
print(f"  中位数: {np.median(arr):.6f}")
print(f"  绝对值平均: {np.abs(arr).mean():.6f}")
print(f"  绝对值中位数: {np.median(np.abs(arr)):.6f}")
print(f"  绝对值25%分位: {np.percentile(np.abs(arr), 25):.6f}")
