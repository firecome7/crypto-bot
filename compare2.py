"""取更多数据对比信号"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pandas as pd
from pathlib import Path
from scipy import stats

CACHE_DIR = Path("data/cache")
DATA_DIR = Path("data/kline")
BOLL_PERIOD = 20

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

def calc_boll(close, period=20, std=2.0):
    if len(close) < period: return None, None, None
    sma = np.mean(close[-period:])
    s = np.std(close[-period:])
    return sma + std*s, sma, sma - std*s

def orig_entry(klines, is_bullish):
    if len(klines) < BOLL_PERIOD + 3: return False, 0
    closes = np.array([k[4] for k in klines])
    opens = np.array([k[1] for k in klines])
    highs = np.array([k[2] for k in klines])
    lows = np.array([k[3] for k in klines])
    upper, mid, lower = calc_boll(closes)
    if lower is None: return False, 0
    n = len(closes)
    if is_bullish:
        for i in range(n-4, max(0, n-25), -1):
            if lows[i] < lower and closes[i] < opens[i]:
                if closes[i+1] > opens[i+1] and closes[i+2] > opens[i+2]:
                    if closes[i+1] > opens[i] or closes[i+2] > opens[i]:
                        return True, opens[i+3]
    else:
        for i in range(n-4, max(0, n-25), -1):
            if highs[i] > upper and closes[i] > opens[i]:
                if closes[i+1] < opens[i+1] and closes[i+2] < opens[i+2]:
                    if closes[i+1] < opens[i] or closes[i+2] < opens[i]:
                        return True, opens[i+3]
    return False, 0

def fast_sig(cursor, opens, highs, lows, closes, boll_upper, boll_lower, direction):
    if cursor < BOLL_PERIOD + 3: return 0
    start = max(0, cursor - 25)
    for i in range(cursor - 4, start - 1, -1):
        if direction[i] == 0 or np.isnan(direction[i]): continue
        bullish = direction[i] > 0
        if bullish:
            if lows[i] < boll_lower[i] and closes[i] < opens[i]:
                if closes[i+1] > opens[i+1] and closes[i+2] > opens[i+2]:
                    if closes[i+1] > opens[i] or closes[i+2] > opens[i]:
                        return 1
        else:
            if highs[i] > boll_upper[i] and closes[i] > opens[i]:
                if closes[i+1] < opens[i+1] and closes[i+2] < opens[i+2]:
                    if closes[i+1] < opens[i] or closes[i+2] < opens[i]:
                        return -1
    return 0

# 用 BNB 中间一段 (50000 ~ 50500)
sym = "BNBUSDT"
d = np.load(CACHE_DIR / f"{sym}.npz")
df = pd.read_parquet(DATA_DIR / f"{sym}_5m.parquet")
df_h1 = df["close"].resample("1h").last().dropna()

start = 50000
end = 50500
orig_list = []
fast_list = []

for idx in range(start, end):
    if idx >= len(df):
        break
    
    # 原版
    klines = []
    for j in range(max(0, idx - 100), idx + 1):
        r = df.iloc[j]
        klines.append([0, r["open"], r["high"], r["low"], r["close"], r["volume"]])
    
    ts = df.index[idx]
    hour_key = ts.floor("1h")
    if hour_key in df_h1.index:
        closes_h1 = df_h1.loc[:hour_key].tail(30).values
        if len(closes_h1) >= 25:
            is_bullish, slope = check_trend(closes_h1)
        else:
            is_bullish = None
    else:
        is_bullish = None
    
    if is_bullish is not None:
        has, _ = orig_entry(klines[:-1], is_bullish)
        if has:
            orig_list.append(idx)
    
    sig = fast_sig(idx, d["open"], d["high"], d["low"], d["close"],
                    d["boll_upper"], d["boll_lower"], d["direction"])
    if sig != 0:
        fast_list.append(idx)

print(f"区间 {start}-{end}:")
print(f"  原版: {len(orig_list)} 次")
print(f"  快速: {len(fast_list)} 次")

if orig_list == fast_list:
    print("✅ 完全一致")
else:
    only_o = set(orig_list) - set(fast_list)
    only_f = set(fast_list) - set(orig_list)
    print(f"  原版独有: {sorted(only_o)[:10]}")
    print(f"  快速独有: {sorted(only_f)[:10]}")
    
    # 检查第一个差异点
    if only_o:
        i = list(only_o)[0]
        print(f"\n原版独有 idx={i} 详细诊断:")
        # 原版方向
        ts = df.index[i]
        hk = ts.floor("1h")
        ch = df_h1.loc[:hk].tail(30).values
        bull, sl = check_trend(ch)
        print(f"  原版方向: {bull}, 斜率: {sl}")
        
        # 快速版方向
        print(f"  快速方向值: {d['direction'][i]}")
        print(f"  快速方向前5: {d['direction'][i-5:i+1]}")
