"""调试信号：从第一个有效 idx 开始"""
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

total_checked = 0
no_dir = 0
no_slope = 0
k1_long = 0
k1_short = 0
k2k3_long = 0
k2k3_short = 0
confirm_long = 0
confirm_short = 0
macd_long = 0
macd_short = 0

for i in range(279, min(5000, n)):
    dval = direction[i]
    if np.isnan(dval) or dval == 0:
        no_dir += 1
        continue
    if np.isnan(slope_abs[i]) or slope_abs[i] < MIN_SLOPE_ABS:
        no_slope += 1
        continue
    if np.isnan(macd[i]) or np.isnan(macd_signal[i]):
        continue
    
    is_bullish = dval > 0
    total_checked += 1
    
    if is_bullish:
        if lows[i] < boll_lower[i] and closes[i] < opens[i]:
            k1_long += 1
            if i+2 < n and closes[i+1] > opens[i+1] and closes[i+2] > opens[i+2]:
                k2k3_long += 1
                if closes[i+1] > opens[i] or closes[i+2] > opens[i]:
                    confirm_long += 1
                    if macd[i] > macd_signal[i] or (i+1 < n and macd[i+1] > macd_signal[i+1]):
                        macd_long += 1
    else:
        if highs[i] > boll_upper[i] and closes[i] > opens[i]:
            k1_short += 1
            if i+2 < n and closes[i+1] < opens[i+1] and closes[i+2] < opens[i+2]:
                k2k3_short += 1
                if closes[i+1] < opens[i] or closes[i+2] < opens[i]:
                    confirm_short += 1
                    if macd[i] < macd_signal[i] or (i+1 < n and macd[i+1] < macd_signal[i+1]):
                        macd_short += 1

print(f"有效方向: {total_checked}")
print(f"方向=0/nan跳过: {no_dir}")
print(f"斜率不足跳过: {no_slope}")
print()
print("=== 做多漏斗 ===")
print(f"K1碰下轨+阴线:  {k1_long}")
print(f"+K2阳K3阳:      {k2k3_long}")
print(f"+确认:           {confirm_long}")
print(f"+MACD金叉:       {macd_long}")
print()
print("=== 做空漏斗 ===")
print(f"K1碰上轨+阳线:  {k1_short}")
print(f"+K2阴K3阴:      {k2k3_short}")
print(f"+确认:           {confirm_short}")
print(f"+MACD死叉:       {macd_short}")
