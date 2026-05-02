#!/usr/bin/env python3
"""预计算回测数据：斜率 + BOLL + MACD，存为 numpy .npz 文件"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pandas as pd
from pathlib import Path
from scipy import stats
import time

DATA_DIR = Path(__file__).parent / "data" / "kline"
CACHE_DIR = Path(__file__).parent / "data" / "cache"
BOLL_PERIOD = 20
BOLL_STD = 2.0
SLOPE_LOOKBACK = 5

SYMBOLS = [
    "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT",
]

def calc_slope(values):
    x = np.arange(len(values))
    return stats.linregress(x, values).slope

def compute_symbol(sym):
    t0 = time.time()
    df_5m = pd.read_parquet(DATA_DIR / f"{sym}_5m.parquet")
    
    # 提取 numpy array
    ts = df_5m.index.values.astype(np.int64)
    opens = df_5m["open"].values.astype(np.float64)
    highs = df_5m["high"].values.astype(np.float64)
    lows = df_5m["low"].values.astype(np.float64)
    closes = df_5m["close"].values.astype(np.float64)
    volumes = df_5m["volume"].values.astype(np.float64)
    n = len(closes)
    
    # ── 预计算 5m BOLL ──
    print(f"  {sym}: 计算 BOLL...")
    boll_upper = np.full(n, np.nan)
    boll_mid = np.full(n, np.nan)
    boll_lower = np.full(n, np.nan)
    for i in range(BOLL_PERIOD - 1, n):
        seg = closes[i - BOLL_PERIOD + 1 : i + 1]
        sma = np.mean(seg)
        std = np.std(seg)
        boll_upper[i] = sma + BOLL_STD * std
        boll_mid[i] = sma
        boll_lower[i] = sma - BOLL_STD * std
    
    # ── 预计算 5m MACD(12,26,9) ──
    print(f"  {sym}: 计算 MACD...")
    # 用 pandas ewm 算，正确处理 nan
    df_5m["ema12"] = df_5m["close"].ewm(span=12, adjust=False).mean()
    df_5m["ema26"] = df_5m["close"].ewm(span=26, adjust=False).mean()
    df_5m["macd_line"] = df_5m["ema12"] - df_5m["ema26"]
    df_5m["macd_signal"] = df_5m["macd_line"].ewm(span=9, adjust=False).mean()
    df_5m["macd_hist"] = df_5m["macd_line"] - df_5m["macd_signal"]
    
    macd = df_5m["macd_line"].values.astype(np.float64)
    macd_signal = df_5m["macd_signal"].values.astype(np.float64)
    macd_hist = df_5m["macd_hist"].values.astype(np.float64)
    
    # ── 预计算 1h 斜率 ──
    print(f"  {sym}: 计算斜率...")
    df_h1 = df_5m["close"].resample("1h").last().dropna()
    h1_closes = df_h1.values.astype(np.float64)
    h1_ts = df_h1.index.values.astype(np.int64)
    h1_n = len(h1_closes)
    
    h1_slopes = np.full(h1_n, np.nan)
    h1_direction = np.full(h1_n, np.nan)
    for i in range(BOLL_PERIOD + SLOPE_LOOKBACK - 1, h1_n):
        mids = []
        for j in range(SLOPE_LOOKBACK):
            end = i - j + 1
            start = end - BOLL_PERIOD
            if start >= 0:
                mids.append(np.mean(h1_closes[start:end]))
        if len(mids) >= 2:
            slope = calc_slope(np.array(mids))
            h1_slopes[i] = slope
            h1_direction[i] = 1.0 if slope > 0 else 0.0
    
    # ── 对齐时间 ──
    print(f"  {sym}: 对齐时间...")
    h1_idx_map = np.searchsorted(h1_ts, ts, side="right") - 1
    h1_idx_map = np.clip(h1_idx_map, 0, h1_n - 1)
    dir_5m = h1_direction[h1_idx_map]
    slope_5m = h1_slopes[h1_idx_map]
    
    # ── 检测 MACD 背离 ──
    # 底背离：价格新低但 MACD 没新低
    # 顶背离：价格新高但 MACD 没新高
    print(f"  {sym}: 检测背离...")
    bullish_div = np.full(n, 0, dtype=np.int8)
    bearish_div = np.full(n, 0, dtype=np.int8)
    
    window = 24  # 2 小时 = 24 根 5m
    for i in range(50, n):
        if np.isnan(macd_hist[i]) or np.isnan(macd[i]):
            continue
        
        start = max(0, i - window)
        
        # 取最近 window 根的价格和 MACD hist
        price_window = closes[start:i+1]
        hist_window = macd_hist[start:i+1]
        
        # 如果价格在走低（最近 low < 窗口最低）
        # 但 MACD hist 在走高（最近 hist > 窗口中间位置的 hist）
        # = 底背离
        mid = start + window // 2
        mid_hist = macd_hist[mid] if mid < i and not np.isnan(macd_hist[mid]) else 0
        
        # 简单底背离：价格创 window 新低，但 MACD hist 比前一次的最低谷高
        if len(price_window) >= window:
            # 前半段最低
            first_half = closes[start:mid+1]
            if len(first_half) > 0:
                first_min = np.min(first_half)
                first_min_idx = np.argmin(first_half) + start
                
                # 后半段（包含当前）
                second_half = closes[mid+1:i+1]
                if len(second_half) > 0:
                    second_min = np.min(second_half)
                    second_min_idx = np.argmin(second_half) + mid + 1
                    
                    # 底部背离：后半段价格更低，但 MACD hist 更高
                    if second_min < first_min:
                        first_macd = macd_hist[first_min_idx]
                        second_macd = macd_hist[second_min_idx]
                        if not np.isnan(first_macd) and not np.isnan(second_macd):
                            if second_macd > first_macd:
                                bullish_div[second_min_idx] = 1
                    
                    # 顶部背离：后半段价格更高，但 MACD hist 更低
                    first_max = np.max(first_half)
                    first_max_idx = np.argmax(first_half) + start
                    second_max = np.max(second_half)
                    second_max_idx = np.argmax(second_half) + mid + 1
                    
                    if second_max > first_max:
                        first_macd = macd_hist[first_max_idx]
                        second_macd = macd_hist[second_max_idx]
                        if not np.isnan(first_macd) and not np.isnan(second_macd):
                            if second_macd < first_macd:
                                bearish_div[second_max_idx] = 1
    
    # ── 保存 ──
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out_path = CACHE_DIR / f"{sym}.npz"
    np.savez_compressed(
        out_path,
        ts=ts,
        open=opens,
        high=highs,
        low=lows,
        close=closes,
        volume=volumes,
        boll_upper=boll_upper,
        boll_mid=boll_mid,
        boll_lower=boll_lower,
        macd=macd,
        macd_signal=macd_signal,
        macd_hist=macd_hist,
        direction=dir_5m,
        slope_abs=np.abs(slope_5m),
        h1_ts=h1_ts,
        h1_slopes=h1_slopes,
        h1_direction=h1_direction,
        bullish_div=bullish_div,
        bearish_div=bearish_div,
    )
    
    elapsed = time.time() - t0
    print(f"  ✅ {sym}: {n} 根, {elapsed:.1f}s")
    return out_path

if __name__ == "__main__":
    print("开始预计算（含 MACD 背离）...")
    t0 = time.time()
    for sym in SYMBOLS:
        compute_symbol(sym)
    print(f"\n全部完成! 耗时 {time.time()-t0:.0f}s")
