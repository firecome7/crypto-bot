"""逐行调示 idx=279"""
import numpy as np
from pathlib import Path

d = np.load("data/cache/BNBUSDT.npz")
i = 279

print(f"idx={i}")
print(f"direction: {d['direction'][i]}")
print(f"isnan: {np.isnan(d['direction'][i])}")
print(f"==0: {d['direction'][i] == 0}")
print(f"slope_abs: {d['slope_abs'][i]}")
print(f"slope_abs < 0.05: {d['slope_abs'][i] < 0.05}")
print(f"macd: {d['macd'][i]}")
print(f"macd_signal: {d['macd_signal'][i]}")
print(f"isnan(macd): {np.isnan(d['macd'][i])}")
print(f"close: {d['close'][i]}, open: {d['open'][i]}")
print(f"low: {d['low'][i]}")
print(f"boll_lower: {d['boll_lower'][i]}")
print(f"lows < boll_lower: {d['low'][i] < d['boll_lower'][i]}")
print(f"close < open: {d['close'][i] < d['open'][i]}")

# 尝试过一遍条件
dval = d['direction'][i]
if np.isnan(dval) or dval == 0:
    print("=> 被 direction 过滤")
elif np.isnan(d['slope_abs'][i]) or d['slope_abs'][i] < 0.05:
    print("=> 被 slope 过滤")
elif np.isnan(d['macd'][i]) or np.isnan(d['macd_signal'][i]):
    print("=> 被 macd nan 过滤")
else:
    print("=> 通过了前三关，可以进入做多/做空检测")
