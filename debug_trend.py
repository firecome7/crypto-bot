"""调试 check_trend 的 mids"""
import pandas as pd
import numpy as np
from scipy import stats

df = pd.read_parquet("data/kline/BTCUSDT_5m.parquet")
df_h1 = df["close"].resample("1h").last().dropna()

def calc_slope(values):
    x = np.arange(len(values))
    res = stats.linregress(x, values)
    return res.slope

# 取一段实际数据
close = df_h1.iloc[30:60].values
print(f"close 长度: {len(close)}")
print(f"close 前5个值: {close[:5]}")
print(f"close 后5个值: {close[-5:]}")
print()

boll_period = 20
lookback = 5

mids = []
for i in range(lookback):
    end_idx = -(lookback - i - 1) if (lookback - i - 1) > 0 else len(close)
    start_idx = -(boll_period + lookback - i - 1)
    
    print(f"i={i}: start_idx={start_idx}, end_idx={end_idx}")
    print(f"  slice: close[{start_idx}:{end_idx}]")
    
    segment = close[start_idx:end_idx] if end_idx > 0 else close[start_idx:]
    print(f"  segment len={len(segment)}, values={[round(x,1) for x in segment]}")
    
    if len(segment) >= boll_period:
        m = np.mean(segment[-boll_period:])
        mids.append(m)
        print(f"  mean={m}")

print()
print(f"mids: {mids}")
if len(mids) >= 2:
    slope = calc_slope(np.array(mids))
    print(f"slope: {slope}")
    print(f"slope > 0: {slope > 0}")
