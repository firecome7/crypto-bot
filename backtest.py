#!/usr/bin/env python3
"""BTC 1年回测：BOLL + 中轨斜率方向 + 5m入场信号"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
from scipy import stats

# ── 策略参数 ──
TREND_PERIOD = "1h"       # 方向判定周期
ENTRY_PERIOD = "5m"       # 入场周期
BOLL_PERIOD = 20
BOLL_STD = 2.0
SLOPE_LOOKBACK = 5
POSITION_PCT = 0.10       # 单笔10%仓位
STOP_LOSS_PCT = 0.02      # 2%止损
TRAILING_ACTIVATE = 0.03  # 3%启动保本
TRAILING_DRAWDOWN = 0.60  # 利润回撤60%平仓
BALANCE_INIT = 10000      # 初始资金

# ── 辅助函数 ──
def calc_boll(close, period=20, std=2.0):
    if len(close) < period:
        return None, None, None
    sma = np.mean(close[-period:])
    s = np.std(close[-period:])
    return sma + std*s, sma, sma - std*s

def calc_slope(values):
    x = np.arange(len(values))
    res = stats.linregress(x, values)
    return res.slope

def check_trend(hourly_close, boll_period=20, lookback=5):
    """判断小时线方向，返回 (多头?, 斜率)"""
    if len(hourly_close) < boll_period + lookback:
        return None, 0.0
    # 计算最近 lookback 根小时线的中轨值
    mids = []
    for i in range(lookback):
        end = -(lookback - i - 1) if (lookback - i - 1) > 0 else len(hourly_close)
        start = -(boll_period + lookback - i - 1)
        segment = hourly_close[start:end] if end > 0 else hourly_close[start:]
        if len(segment) >= boll_period:
            mids.append(np.mean(segment[-boll_period:]))
    if len(mids) < 2:
        return None, 0.0
    slope = calc_slope(np.array(mids))
    return slope > 0, slope

def check_entry(klines_5m, is_bullish, boll_period=20, boll_std=2.0):
    """
    检查入场信号
    klines_5m: list of [ts, o, h, l, c, v]
    返回 (有信号?, 入场价格, 原因)
    """
    if len(klines_5m) < boll_period + 3:
        return False, 0, "K线不足"
    
    closes = np.array([k[4] for k in klines_5m])
    opens = np.array([k[1] for k in klines_5m])
    highs = np.array([k[2] for k in klines_5m])
    lows = np.array([k[3] for k in klines_5m])
    
    upper, mid, lower = calc_boll(closes, boll_period, boll_std)
    if lower is None:
        return False, 0, "BOLL计算失败"
    
    n = len(closes)
    if is_bullish:
        # 做多：K1跌破下轨+阴线, K2阳线, K3阳线
        for i in range(n-4, max(0, n-25), -1):
            if lows[i] < lower and closes[i] < opens[i]:  # K1
                if closes[i+1] > opens[i+1] and closes[i+2] > opens[i+2]:  # K2阳 K3阳
                    if closes[i+1] > opens[i] or closes[i+2] > opens[i]:  # 确认
                        return True, opens[i+3], f"做多@K1={i}"
        return False, 0, "未检测到信号"
    else:
        # 做空：K1突破上轨+阳线, K2阴线, K3阴线
        for i in range(n-4, max(0, n-25), -1):
            if highs[i] > upper and closes[i] > opens[i]:  # K1
                if closes[i+1] < opens[i+1] and closes[i+2] < opens[i+2]:  # K2阴 K3阴
                    if closes[i+1] < opens[i] or closes[i+2] < opens[i]:  # 确认
                        return True, opens[i+3], f"做空@K1={i}"
        return False, 0, "未检测到信号"

# ── 主回测 ──
def run_backtest():
    data_dir = Path(__file__).parent / "data" / "kline"
    
    # 加载 BTC 5m 和 15m（15m 用于模拟小时线方向）
    print("加载数据...")
    df_5m = pd.read_parquet(data_dir / "BTCUSDT_5m.parquet")
    df_15m = pd.read_parquet(data_dir / "BTCUSDT_15m.parquet")
    
    # 重采样 5m -> 1h 作为趋势判定
    df_1h = df_5m["close"].resample("1h").last().dropna()
    
    print(f"5m数据: {len(df_5m)} 根 ({df_5m.index.min()} ~ {df_5m.index.max()})")
    print(f"1h数据: {len(df_1h)} 根")
    
    # ── 回测 ──
    trades = []
    balance = BALANCE_INIT
    peak_balance = BALANCE_INIT
    
    # 逐根5m K线模拟
    hourly_buffer = {}  # symbol -> list of hourly close prices
    entry_buffer = {}   # symbol -> list of 5m klines
    current_position = None  # {side, entry_price, entry_idx, high_water, size}
    
    total_bars = len(df_5m)
    progress_interval = total_bars // 10
    
    print("\n开始回测...")
    for idx, (ts, row) in enumerate(df_5m.iterrows()):
        if idx % progress_interval == 0:
            pct = idx / total_bars * 100
            print(f"  进度: {pct:.0f}% ({idx}/{total_bars}), 余额: ${balance:.0f}, 持仓: {current_position is not None}")
        
        kline = [int(ts.timestamp()*1000), row.open, row.high, row.low, row.close, row.volume]
        
        # ── 方向判定（每小时更新一次） ──
        # 用 5m 重采样到 1h
        hour_key = ts.floor("1h")
        if hour_key not in hourly_buffer:
            # 取最近 30 根小时线
            closes_1h = df_1h.loc[:hour_key].tail(30).values
            if len(closes_1h) >= 25:
                hourly_buffer[hour_key] = closes_1h
                is_bullish, slope = check_trend(closes_1h)
            else:
                is_bullish = None
                slope = 0.0
        else:
            # 复用上一小时的判定
            last_hour = list(hourly_buffer.keys())[-1]
            is_bullish, slope = check_trend(hourly_buffer[last_hour])
        
        # ── 持仓管理 ──
        if current_position is not None:
            current_price = row.close
            # 止损
            if current_position["side"] == "long":
                pnl_pct = (current_price - current_position["entry_price"]) / current_position["entry_price"]
            else:
                pnl_pct = (current_position["entry_price"] - current_price) / current_position["entry_price"]
            
            # 更新最高水位
            if pnl_pct > current_position["high_water"]:
                current_position["high_water"] = pnl_pct
            
            # 止损检查
            if pnl_pct <= -STOP_LOSS_PCT:
                pnl_dollar = balance * POSITION_PCT * pnl_pct / (1 + pnl_pct * (1 if current_position["side"] == "long" else 1))
                # 简化：按比例算利润
                gross_pnl = balance * POSITION_PCT * pnl_pct
                balance += gross_pnl
                trades.append({"entry_time": current_position["entry_time"],
                               "exit_time": ts, "side": current_position["side"],
                               "entry_price": current_position["entry_price"],
                               "exit_price": current_price,
                               "pnl_pct": pnl_pct, "pnl_dollar": gross_pnl,
                               "reason": "止损"})
                current_position = None
                peak_balance = max(peak_balance, balance)
                continue
            
            # 移动止盈
            if pnl_pct >= TRAILING_ACTIVATE:
                drawdown = (current_position["high_water"] - pnl_pct) / current_position["high_water"] if current_position["high_water"] > 0 else 0
                if drawdown >= TRAILING_DRAWDOWN:
                    gross_pnl = balance * POSITION_PCT * pnl_pct
                    balance += gross_pnl
                    trades.append({"entry_time": current_position["entry_time"],
                                   "exit_time": ts, "side": current_position["side"],
                                   "entry_price": current_position["entry_price"],
                                   "exit_price": current_price,
                                   "pnl_pct": pnl_pct, "pnl_dollar": gross_pnl,
                                   "reason": "移动止盈"})
                    current_position = None
                    peak_balance = max(peak_balance, balance)
                    continue
        
        # ── 入场信号检测 ──
        if current_position is None and is_bullish is not None:
            # 维护 5m K线缓存
            if "BTC" not in entry_buffer:
                entry_buffer["BTC"] = []
            entry_buffer["BTC"].append(kline)
            if len(entry_buffer["BTC"]) > 100:
                entry_buffer["BTC"] = entry_buffer["BTC"][-100:]
            
            has_signal, entry_price, reason = check_entry(entry_buffer["BTC"], is_bullish)
            if has_signal:
                current_position = {
                    "side": "long" if is_bullish else "short",
                    "entry_price": entry_price,
                    "entry_time": ts,
                    "high_water": 0,
                }
                # 开仓扣减成本（假设成交在入场价）
                cost = balance * POSITION_PCT
                pnl_pct = (row.close - entry_price) / entry_price if is_bullish else (entry_price - row.close) / entry_price
                # 不立即扣钱，出场时统一结算
    
    # ── 未平仓强制平仓 ──
    if current_position is not None:
        last_price = df_5m.iloc[-1].close
        if current_position["side"] == "long":
            pnl_pct = (last_price - current_position["entry_price"]) / current_position["entry_price"]
        else:
            pnl_pct = (current_position["entry_price"] - last_price) / current_position["entry_price"]
        gross_pnl = balance * POSITION_PCT * pnl_pct
        balance += gross_pnl
        trades.append({"entry_time": current_position["entry_time"],
                       "exit_time": df_5m.index[-1], "side": current_position["side"],
                       "entry_price": current_position["entry_price"],
                       "exit_price": last_price,
                       "pnl_pct": pnl_pct, "pnl_dollar": gross_pnl,
                       "reason": "回测结束平仓"})
    
    # ── 结果分析 ──
    print("\n" + "="*50)
    print("回测结果")
    print("="*50)
    print(f"初始余额: ${BALANCE_INIT:,.0f}")
    print(f"最终余额: ${balance:,.0f}")
    total_return = (balance - BALANCE_INIT) / BALANCE_INIT * 100
    print(f"总收益率: {total_return:+.2f}%")
    
    df_trades = pd.DataFrame(trades) if trades else pd.DataFrame()
    if len(df_trades) > 0:
        win_trades = df_trades[df_trades["pnl_dollar"] > 0]
        loss_trades = df_trades[df_trades["pnl_dollar"] <= 0]
        
        print(f"\n总交易次数: {len(df_trades)}")
        print(f"盈利次数: {len(win_trades)} ({len(win_trades)/len(df_trades)*100:.1f}%)")
        print(f"亏损次数: {len(loss_trades)} ({len(loss_trades)/len(df_trades)*100:.1f}%)")
        
        if len(win_trades) > 0:
            print(f"平均盈利: ${win_trades['pnl_dollar'].mean():.0f} ({win_trades['pnl_pct'].mean()*100:+.2f}%)")
        if len(loss_trades) > 0:
            print(f"平均亏损: ${loss_trades['pnl_dollar'].mean():.0f} ({loss_trades['pnl_pct'].mean()*100:+.2f}%)")
        
        if len(loss_trades) > 0:
            profit_factor = abs(win_trades["pnl_dollar"].sum() / loss_trades["pnl_dollar"].sum()) if len(win_trades) > 0 and loss_trades["pnl_dollar"].sum() != 0 else 0
            print(f"盈亏比: {profit_factor:.2f}")
        
        print(f"\n最大单笔盈利: ${df_trades['pnl_dollar'].max():.0f}")
        print(f"最大单笔亏损: ${df_trades['pnl_dollar'].min():.0f}")
        
        # 最大回撤（简化）
        print(f"\n按原因分布:")
        for reason, grp in df_trades.groupby("reason"):
            print(f"  {reason}: {len(grp)} 笔")
        
        # 保存交易记录
        df_trades.to_csv(Path(__file__).parent / "data" / "backtest_trades.csv", index=False)
        print(f"\n交易记录已保存到 data/backtest_trades.csv")
    else:
        print("无交易记录")
    
    # Buy & Hold 对比
    btc_start = df_5m.iloc[0].close
    btc_end = df_5m.iloc[-1].close
    btc_return = (btc_end - btc_start) / btc_start * 100
    print(f"\n对比 Buy & Hold:")
    print(f"  BTC: ${btc_start:.0f} -> ${btc_end:.0f} ({btc_return:+.2f}%)")
    print(f"  策略: {total_return:+.2f}%")

if __name__ == "__main__":
    run_backtest()
