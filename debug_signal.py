"""调试信号检测：看看每一步过滤掉了多少"""
import numpy as np
from pathlib import Path

CACHE_DIR = Path("data/cache")
sym = "BNBUSDT"
d = np.load(CACHE_DIR / f"{sym}.npz")

closes = d["close"]
opens = d["open"]
highs = d["high"]
lows = d["low"]
boll_upper = d["boll_upper"]
boll_lower = d["boll_lower"]
direction = d["direction"]
slope_abs = d["slope_abs"]
macd = d["macd"]
macd_signal = d["macd_signal"]
macd_hist = d["macd_hist"]

MIN_SLOPE_ABS = 0.05
n = len(closes)

# 统计每一步的通过数
total_checked = 0
passed_direction = 0
passed_slope = 0
passed_k1_long = 0  # 触下轨+阴线
passed_k2k3_long = 0  # K2阳K3阳
passed_k1_short = 0
passed_k2k3_short = 0
passed_macd_long = 0
passed_macd_short = 0

for i in range(50, n):
    if np.isnan(direction[i]) or direction[i] == 0:
        continue
    if np.isnan(slope_abs[i]):
        continue
    if np.isnan(macd[i]) or np.isnan(macd_signal[i]):
        continue
    
    is_bullish = direction[i] > 0
    total_checked += 1
    
    if slope_abs[i] < MIN_SLOPE_ABS:
        continue
    passed_slope += 1
    
    if is_bullish:
        if lows[i] < boll_lower[i] and closes[i] < opens[i]:
            passed_k1_long += 1
            if i+2 < n and closes[i+1] > opens[i+1] and closes[i+2] > opens[i+2]:
                passed_k2k3_long += 1
                if closes[i+1] > opens[i] or closes[i+2] > opens[i]:
                    if macd[i] > macd_signal[i] or (i+1 < n and macd[i+1] > macd_signal[i+1]):
                        passed_macd_long += 1
    else:
        if highs[i] > boll_upper[i] and closes[i] > opens[i]:
            passed_k1_short += 1
            if i+2 < n and closes[i+1] < opens[i+1] and closes[i+2] < opens[i+2]:
                passed_k2k3_short += 1
                if closes[i+1] < opens[i] or closes[i+2] < opens[i]:
                    if macd[i] < macd_signal[i] or (i+1 < n and macd[i+1] < macd_signal[i+1]):
                        passed_macd_short += 1

print(f"总检查数: {total_checked}")
print(f"过斜率阈值: {passed_slope}")
print(f"")
print(f"做多链:")
print(f"  K1触下轨+阴线: {passed_k1_long}")
print(f"  +K2阳K3阳: {passed_k2k3_long}")
print(f"  +确认: {passed_k2k3_long} (同上一行)")
print(f"  +MACD金叉: {passed_macd_long}")
print(f"")
print(f"做空链:")
print(f"  K1触上轨+阳线: {passed_k1_short}")
print(f"  +K2阴K3阴: {passed_k2k3_short}")
print(f"  +确认: {passed_k2k3_short}")
print(f"  +MACD死叉: {passed_macd_short}")
