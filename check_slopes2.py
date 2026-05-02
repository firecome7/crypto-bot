"""检查 check_trend 的斜率值分布"""
import pandas as pd
import numpy as np
from pathlib import Path
from scipy import stats

SYMBOLS = ["BTCUSDT","ETHUSDT","SOLUSDT","DOGEUSDT"]

def calc_slope(values):
    x = np.arange(len(values))
    res = stats.linregress(x, values)
    return res.slope

def check_trend(hourly_close, boll_period=20, lookback=5):
    if len(hourly_close) < boll_period + lookback: return None, 0.0
    mids = []
    for i in range(lookback):
        end = -(lookback - i - 1) if (lookback - i - 1) > 0 else len(hourly_close)
        start = -(boll_period + lookback - i - 1)
        segment = hourly_close[start:end] if end > 0 else hourly_close[start:]
        if len(segment) >= boll_period:
            mids.append(np.mean(segment[-boll_period:]))
    if len(mids) < 2: return None, 0.0
    slope = calc_slope(np.array(mids))
    return slope > 0, slope

for sym in SYMBOLS:
    df = pd.read_parquet(f"data/kline/{sym}_5m.parquet")
    df_h1 = df["close"].resample("1h").last().dropna()
    
    slopes = []
    for i in range(30, len(df_h1)):
        segment = df_h1.iloc[i-30:i].values
        bull, slope = check_trend(segment)
        if bull is not None:
            slopes.append(slope)
    
    arr = np.array(slopes)
    print(f"{sym}:")
    print(f"  样本: {len(arr)}")
    print(f"  斜率中位数: {np.median(arr):.6f}")
    print(f"  绝对值中位数: {np.median(np.abs(arr)):.6f}")
    print(f"  绝对值25%: {np.percentile(np.abs(arr), 25):.6f}")
    print(f"  绝对值10%: {np.percentile(np.abs(arr), 10):.6f}")
    print(f"  绝对值5%: {np.percentile(np.abs(arr), 5):.6f}")
    print(f"  非零比例: {(np.abs(arr) > 0.001).mean()*100:.1f}%")
    print(f"  >0.1: {(np.abs(arr) > 0.1).mean()*100:.1f}%")
    print(f"  >0.01: {(np.abs(arr) > 0.01).mean()*100:.1f}%")
    print()
