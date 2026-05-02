"""对比快速版 vs 原版：用 BTC 跑几个关键点对比"""
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

# ── 方法 A: 原版 check_entry（用 klines list） ──
def calc_boll(close, period=20, std=2.0):
    if len(close) < period: return None, None, None
    sma = np.mean(close[-period:])
    s = np.std(close[-period:])
    return sma + std*s, sma, sma - std*s

def original_check_entry(klines, is_bullish):
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
        return False, 0
    else:
        for i in range(n-4, max(0, n-25), -1):
            if highs[i] > upper and closes[i] > opens[i]:
                if closes[i+1] < opens[i+1] and closes[i+2] < opens[i+2]:
                    if closes[i+1] < opens[i] or closes[i+2] < opens[i]:
                        return True, opens[i+3]
        return False, 0

# ── 快速版 check_signal_on_kline ──
def fast_check_signal(cursor, opens, highs, lows, closes,
                       boll_upper, boll_lower, direction):
    if cursor < BOLL_PERIOD + 3: return 0
    start = max(0, cursor - 25)
    for i in range(cursor - 4, start - 1, -1):
        if direction[i] == 0 or np.isnan(direction[i]): continue
        is_bullish = direction[i] > 0
        if is_bullish:
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

# 用 BNBUSDT 对比
sym = "BNBUSDT"
print(f"对比 {sym} 的信号检测...\n")

# 加载两种数据
d = np.load(CACHE_DIR / f"{sym}.npz")
df = pd.read_parquet(DATA_DIR / f"{sym}_5m.parquet")
df_h1 = df["close"].resample("1h").last().dropna()

# 取前 200 根 K 线对比
n_check = 200
orig_signals = []
fast_signals = []

for idx in range(BOLL_PERIOD + 5, n_check):
    # 原版：用 klines list
    klines = []
    for j in range(max(0, idx - 100), idx + 1):
        r = df.iloc[j]
        klines.append([0, r["open"], r["high"], r["low"], r["close"], r["volume"]])
    
    # 方向（用 idx 时刻的小时线）
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
        has_sig, price = original_check_entry(klines[:-1], is_bullish)
        if has_sig:
            orig_signals.append(idx)
    
    # 快速版
    sig = fast_check_signal(idx, d["open"], d["high"], d["low"], d["close"],
                             d["boll_upper"], d["boll_lower"], d["direction"])
    if sig != 0:
        fast_signals.append(idx)

print(f"原版信号: {len(orig_signals)} 次 @ {orig_signals[:10]}")
print(f"快速版信号: {len(fast_signals)} 次 @ {fast_signals[:10]}")

if set(orig_signals) == set(fast_signals):
    print("✅ 完全一致!")
else:
    only_orig = set(orig_signals) - set(fast_signals)
    only_fast = set(fast_signals) - set(orig_signals)
    if only_orig:
        print(f"原版有但快速版无: {sorted(only_orig)[:10]}")
    if only_fast:
        print(f"快速版有但原版无: {sorted(only_fast)[:10]}")
