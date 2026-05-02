#!/usr/bin/env python3
"""全量 10 币种回测（修正资金管理）"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
from scipy import stats

BOLL_PERIOD = 20
BOLL_STD = 2.0
SLOPE_LOOKBACK = 5
# MIN_SLOPE_ABS = 0.5  # 暂不启用，先跑修复后的基准
STOP_LOSS_PCT = 0.02
TRAILING_ACTIVATE = 0.03
TRAILING_DRAWDOWN = 0.50  # 50% 利润回撤止盈
PARTIAL_TAKE_PROFIT = 0.08  # 8% 利润先止盈一半
BALANCE_INIT = 10000
POSITION_SIZE = 1000  # 单笔固定 $1000（10% of 初始资金）
MAX_POSITIONS = 20

SYMBOLS = [
    # "BTCUSDT", "ETHUSDT",  # 剔除主流大币
    "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT",
]

def calc_boll(close, period=20, std=2.0):
    if len(close) < period: return None, None, None
    sma = np.mean(close[-period:])
    s = np.std(close[-period:])
    return sma + std*s, sma, sma - std*s

def calc_slope(values):
    x = np.arange(len(values))
    res = stats.linregress(x, values)
    return res.slope

def check_trend(hourly_close, boll_period=20, lookback=5):
    """判断小时线方向，返回 (多头?, 斜率)"""
    if len(hourly_close) < boll_period + lookback: return None, 0.0
    # 收集最近 lookback 个点的 BOLL 中轨值
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

def check_entry(klines, is_bullish):
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

class Position:
    __slots__ = ("symbol", "side", "entry", "entry_time", "high_water", "size", "partial_taken")
    def __init__(self, symbol, side, entry, entry_time, size):
        self.symbol = symbol
        self.side = side
        self.entry = entry
        self.entry_time = entry_time
        self.high_water = 0.0
        self.size = size
        self.partial_taken = False  # 是否已执行分批止盈

def run():
    data_dir = Path(__file__).parent / "data" / "kline"
    balance = BALANCE_INIT
    positions = []  # 全局持仓列表
    all_trades = []
    total_signals = 0
    
    # 为每个币种预加载数据
    print("加载数据...")
    coin_data = {}
    for sym in SYMBOLS:
        df = pd.read_parquet(data_dir / f"{sym}_5m.parquet")
        df_h1 = df["close"].resample("1h").last().dropna()
        coin_data[sym] = {"df": df, "df_h1": df_h1}
    
    # 找出所有币种的共同时间范围
    print("整理时间线...")
    all_dfs = [coin_data[s]["df"] for s in SYMBOLS]
    common_start = max(df.index.min() for df in all_dfs)
    common_end = min(df.index.max() for df in all_dfs)
    print(f"  共同时间: {common_start} ~ {common_end}")
    
    # 按时间推进，所有币种同时模拟
    # 先按 5m 频率对齐所有 K 线
    print("对齐K线...")
    aligned = {}
    for sym in SYMBOLS:
        df = coin_data[sym]["df"]
        mask = (df.index >= common_start) & (df.index <= common_end)
        aligned[sym] = df[mask]
    
    total_bars = len(aligned[SYMBOLS[0]])
    progress_interval = total_bars // 10
    
    print("开始回测...")
    for idx in range(total_bars):
        if idx % progress_interval == 0:
            pct = idx / total_bars * 100
            pct_used = sum(p.size for p in positions) / BALANCE_INIT * 100 if positions else 0
            print(f"  进度: {pct:.0f}% ({idx}/{total_bars}), 余额: ${balance:.0f}, 持仓: {len(positions)}, 占用: {pct_used:.1f}%")
        
        ts = aligned[SYMBOLS[0]].index[idx]
        
        # ── 每个币种检查信号和持仓 ──
        for sym in SYMBOLS:
            row = aligned[sym].iloc[idx]
            kline = [int(ts.timestamp()*1000), row.open, row.high, row.low, row.close, row.volume]
            
            # 方向判定
            df_h1 = coin_data[sym]["df_h1"]
            hour_key = ts.floor("1h")
            if hour_key in df_h1.index:
                closes_h1 = df_h1.loc[:hour_key].tail(30).values
                if len(closes_h1) >= 25:
                    is_bullish, slope = check_trend(closes_h1)
                    # # 斜率绝对值太小意味着横盘，不做方向判定
                    # if abs(slope) < MIN_SLOPE_ABS:
                    #     is_bullish = None
                else:
                    is_bullish = None
            else:
                is_bullish = None
            
            # 更新该币种持仓
            for pos in positions[:]:
                if pos.symbol != sym:
                    continue
                
                if pos.side == "long":
                    pnl_pct = (row.close - pos.entry) / pos.entry
                else:
                    pnl_pct = (pos.entry - row.close) / pos.entry
                
                pos.high_water = max(pos.high_water, pnl_pct)
                
                # 分档止盈：到 8% 先止盈一半
                if not pos.partial_taken and pnl_pct >= PARTIAL_TAKE_PROFIT:
                    pos.partial_taken = True
                    half_pnl = pnl_pct / 2  # 一半仓位止盈
                    gross = balance * (pos.size / BALANCE_INIT) * half_pnl
                    balance += gross
                    all_trades.append({"symbol": sym, "entry_time": pos.entry_time,
                        "exit_time": ts, "side": pos.side, "entry": pos.entry,
                        "exit": row.close, "pnl_pct": half_pnl, "pnl": gross, "reason": "分批止盈"})
                    # 另一半继续持有
                    pos.size = pos.size / 2
                
                # 止损
                if pnl_pct <= -STOP_LOSS_PCT:
                    gross = balance * (pos.size / BALANCE_INIT) * pnl_pct
                    balance += gross
                    all_trades.append({"symbol": sym, "entry_time": pos.entry_time,
                        "exit_time": ts, "side": pos.side, "entry": pos.entry,
                        "exit": row.close, "pnl_pct": pnl_pct, "pnl": gross, "reason": "止损"})
                    positions.remove(pos)
                    continue
                
                # 移动止盈
                if pnl_pct >= TRAILING_ACTIVATE and pos.high_water > 0:
                    dd = (pos.high_water - pnl_pct) / pos.high_water
                    if dd >= TRAILING_DRAWDOWN:
                        gross = balance * (pos.size / BALANCE_INIT) * pnl_pct
                        balance += gross
                        all_trades.append({"symbol": sym, "entry_time": pos.entry_time,
                            "exit_time": ts, "side": pos.side, "entry": pos.entry,
                            "exit": row.close, "pnl_pct": pnl_pct, "pnl": gross, "reason": "止盈"})
                        positions.remove(pos)
                        continue
            
            # 入场信号检测（如果该币种无持仓）
            already_in = any(p.symbol == sym for p in positions)
            if not already_in and is_bullish is not None and len(positions) < MAX_POSITIONS:
                # 维护该币种 5m K线缓存 - 从数据里取最近100根
                start_idx = max(0, idx - 100)
                recent_klines = []
                for j in range(start_idx, idx + 1):
                    r = aligned[sym].iloc[j]
                    recent_klines.append([int(aligned[sym].index[j].timestamp()*1000), r.open, r.high, r.low, r.close, r.volume])
                
                has_sig, price = check_entry(recent_klines, is_bullish)
                if has_sig:
                    total_signals += 1
                    # 仓位 = 余额 * 10% / 当前价格（用 USDT 数量表示仓位大小）
                    position_size = POSITION_SIZE
                    positions.append(Position(sym, "long" if is_bullish else "short",
                        price, ts, position_size))
    
    # ── 尾盘强制平仓 ──
    for pos in positions[:]:
        sym = pos.symbol
        last_row = aligned[sym].iloc[-1]
        last_close = last_row.close
        if pos.side == "long":
            pnl_pct = (last_close - pos.entry) / pos.entry
        else:
            pnl_pct = (pos.entry - last_close) / pos.entry
        gross = balance * (pos.size / BALANCE_INIT) * pnl_pct
        balance += gross
        all_trades.append({"symbol": sym, "entry_time": pos.entry_time,
            "exit_time": aligned[sym].index[-1], "side": pos.side,
            "entry": pos.entry, "exit": last_close,
            "pnl_pct": pnl_pct, "pnl": gross, "reason": "尾盘平仓"})
    
    # ─── 结果 ───
    print("\n" + "="*60)
    print("10 币种 1年回测结果（修正资金管理）")
    print("="*60)
    print(f"初始资金: ${BALANCE_INIT:,.0f}")
    print(f"最终资金: ${balance:,.0f}")
    total_ret = (balance - BALANCE_INIT) / BALANCE_INIT * 100
    print(f"总收益率: {total_ret:+.2f}%")
    
    df_t = pd.DataFrame(all_trades)
    if len(df_t) > 0:
        wins = df_t[df_t["pnl"] > 0]
        losses = df_t[df_t["pnl"] <= 0]
        
        print(f"\n总交易: {len(df_t)} 笔")
        print(f"总信号: {total_signals} 次")
        print(f"胜率: {len(wins)}/{len(df_t)} = {len(wins)/len(df_t)*100:.1f}%")
        
        if len(wins) > 0:
            print(f"平均盈利: ${wins['pnl'].mean():.0f} ({wins['pnl_pct'].mean()*100:+.2f}%)")
            print(f"最大盈利: ${wins['pnl'].max():.0f}")
        if len(losses) > 0:
            print(f"平均亏损: ${losses['pnl'].mean():.0f} ({losses['pnl_pct'].mean()*100:+.2f}%)")
            print(f"最大亏损: ${losses['pnl'].min():.0f}")
        
        if len(losses) > 0 and losses["pnl"].sum() != 0:
            pf = abs(wins["pnl"].sum() / losses["pnl"].sum())
        else:
            pf = float('inf')
        print(f"盈亏比(Profit Factor): {pf:.2f}")
        
        print(f"\n按原因:")
        for reason, grp in df_t.groupby("reason"):
            ret = grp["pnl"].sum()
            print(f"  {reason}: {len(grp)}笔, 合计${ret:.0f}")
        
        print(f"\n按币种:")
        for sym, grp in df_t.groupby("symbol"):
            ret = grp["pnl"].sum()
            n = len(grp)
            wins_sym = len(grp[grp["pnl"] > 0])
            print(f"  {sym}: {n}笔, 胜{wins_sym}/{n}, 合计${ret:.0f}")
    
    # B&H
    print(f"\n对比 Buy & Hold (等权重 10币种):")
    total_bh = 0
    for sym in SYMBOLS:
        df = pd.read_parquet(data_dir / f"{sym}_5m.parquet")
        bh_ret = (df.iloc[-1].close - df.iloc[0].close) / df.iloc[0].close
        total_bh += bh_ret
    avg_bh = total_bh / len(SYMBOLS) * 100
    print(f"  均值: {avg_bh:+.2f}%")
    print(f"  策略: {total_ret:+.2f}%")
    
    df_t.to_csv(data_dir.parent / "backtest_10coins_fixed.csv", index=False)
    print(f"\n交易记录: data/backtest_10coins_fixed.csv")

if __name__ == "__main__":
    run()
