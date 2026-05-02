#!/usr/bin/env python3
"""快速回测：用预计算数据，纯 numpy + 滑动窗口"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from pathlib import Path
import time

CACHE_DIR = Path(__file__).parent / "data" / "cache"
BOLL_PERIOD = 20
MIN_SLOPE_ABS = 0.05  # 斜率绝对值低于此值不做（极弱趋势过滤）
STOP_LOSS_PCT = 0.035
TRAILING_ACTIVATE = 0.03
TRAILING_DRAWDOWN = 0.40
PARTIAL_TAKE_PROFIT = 0.08
BALANCE_INIT = 10000
POSITION_SIZE = 1000
MAX_POSITIONS = 20

SYMBOLS_ALL = [
    # 前10大主流币（剔除）
    # "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    # "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT",
    
    # 中小币种（按市值排名 11-50）
    "TRXUSDT", "SUIUSDT", "APTUSDT", "PEPEUSDT", "ONDOUSDT",
    "AAVEUSDT", "HBARUSDT", "ENAUSDT", "NEARUSDT", "ARBUSDT",
    "FETUSDT", "ALGOUSDT", "TAOUSDT", "BONKUSDT", "FILUSDT",
    "PENDLEUSDT", "POPCATUSDT", "WIFUSDT", "FLOKIUSDT", "SEIUSDT",
    "EIGENUSDT", "JUPUSDT", "OPUSDT", "INJUSDT", "IMXUSDT",
    "RUNEUSDT", "MNTUSDT", "JASMYUSDT", "TIAUSDT", "SANDUSDT",
    "TURBOUSDT", "DYDXUSDT", "LDOUSDT", "ARUSDT", "OMUSDT",
    "HYPEUSDT", "MOGUSDT", "ZROUSDT", "CRVUSDT", "GALAUSDT",
]

# 先用现有的 8 个测试币种（有预计算数据的）
SYMBOLS = [
    "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT",
]

# 入场 K 线形态检测（纯 numpy，滑动窗口）
def check_signal_on_kline(cursor, opens, highs, lows, closes, volumes,
                           boll_upper, boll_lower, direction, slope_abs,
                           macd, macd_signal, macd_hist):
    """
    BOLL触轨 + K2K3确认 + 斜率方向 + MACD柱上行确认
    返回: 0=无信号, 1=做多, -1=做空
    """
    if cursor < BOLL_PERIOD + 3:
        return 0
    
    start = max(0, cursor - 25)
    for i in range(cursor - 4, start - 1, -1):
        if direction[i] == 0 or np.isnan(direction[i]):
            continue
        if slope_abs[i] < MIN_SLOPE_ABS:
            continue
        is_bullish = direction[i] > 0
        
        if np.isnan(macd_hist[i]) or np.isnan(macd_hist[max(0,i-1)]):
            continue
        
        if is_bullish:
            if not (lows[i] < boll_lower[i] and closes[i] < opens[i]):
                continue
            if not (closes[i+1] > opens[i+1] and closes[i+2] > opens[i+2]):
                continue
            if not (closes[i+1] > opens[i] or closes[i+2] > opens[i]):
                continue
            if macd_hist[i] > macd_hist[i-1] * 0.5:
                return 1
        else:
            if not (highs[i] > boll_upper[i] and closes[i] > opens[i]):
                continue
            if not (closes[i+1] < opens[i+1] and closes[i+2] < opens[i+2]):
                continue
            if not (closes[i+1] < opens[i] or closes[i+2] < opens[i]):
                continue
            if macd_hist[i] < macd_hist[i-1] * 0.5:
                return -1
    return 0

def run():
    t0 = time.time()
    
    # ── 加载所有预计算数据（每个约 8MB，8个≈64MB） ──
    print("加载预计算数据...")
    data = {}
    for sym in SYMBOLS:
        d = np.load(CACHE_DIR / f"{sym}.npz")
        data[sym] = {
            "n": len(d["close"]),
            "close": d["close"],
            "open": d["open"],
            "high": d["high"],
            "low": d["low"],
            "volume": d["volume"],
            "boll_upper": d["boll_upper"],
            "boll_lower": d["boll_lower"],
            "direction": d["direction"],
            "slope_abs": d["slope_abs"],
            "macd": d["macd"],
            "macd_signal": d["macd_signal"],
            "macd_hist": d["macd_hist"],
        }
        # 取前 3 列用于快速访问
        data[sym]["ohcl"] = np.column_stack([
            d["open"], d["high"], d["close"], d["low"]
        ])
    
    # 找共同时间范围
    min_n = min(d["n"] for d in data.values())
    max_n = max(d["n"] for d in data.values())
    
    print(f"最小长度: {min_n}, 最大长度: {max_n}, 差异: {max_n-min_n}")
    
    # ── 回测 ──
    balance = BALANCE_INIT
    positions = []  # [{sym, side, entry, entry_idx, high_water, partial_taken}]
    trades = []
    total_signals = 0
    progress_interval = min_n // 10
    
    print("开始回测...")
    for idx in range(min_n):
        if idx % progress_interval == 0:
            pct = idx / min_n * 100
            pct_used = len(positions) / MAX_POSITIONS * 100
            print(f"  {pct:.0f}% ({idx}/{min_n}), 余额: ${balance:.0f}, 持仓: {len(positions)}, 占用: {pct_used:.0f}%")
        
        # 处理每根 K 线
        for sym in SYMBOLS:
            d = data[sym]
            close = d["close"][idx]
            ohlc = d["ohcl"][idx]
            o, h, c, l = ohlc[0], ohlc[1], ohlc[2], ohlc[3]
            
            if np.isnan(close):
                continue
            
            # 更新该币种持仓
            for pos in positions[:]:
                if pos["sym"] != sym:
                    continue
                
                if pos["side"] == 1:  # long
                    pnl_pct = (close - pos["entry"]) / pos["entry"]
                else:  # short
                    pnl_pct = (pos["entry"] - close) / pos["entry"]
                
                pos["high_water"] = max(pos["high_water"], pnl_pct)
                
                # 分档止盈
                if not pos["partial_taken"] and pnl_pct >= PARTIAL_TAKE_PROFIT:
                    pos["partial_taken"] = True
                    half_pnl = pnl_pct / 2
                    gross = balance * (pos["size"] / BALANCE_INIT) * half_pnl
                    balance += gross
                    trades.append(f"{sym},{pos['entry_idx']},{idx},{'LONG' if pos['side']==1 else 'SHORT'},{pos['entry']:.2f},{close:.2f},{half_pnl:.4f},{gross:.2f},分批止盈")
                    pos["size"] /= 2
                
                # 止损
                if pnl_pct <= -STOP_LOSS_PCT:
                    gross = balance * (pos["size"] / BALANCE_INIT) * pnl_pct
                    balance += gross
                    trades.append(f"{sym},{pos['entry_idx']},{idx},{'LONG' if pos['side']==1 else 'SHORT'},{pos['entry']:.2f},{close:.2f},{pnl_pct:.4f},{gross:.2f},止损")
                    positions.remove(pos)
                    continue
                
                # 移动止盈
                if pnl_pct >= TRAILING_ACTIVATE and pos["high_water"] > 0:
                    dd = (pos["high_water"] - pnl_pct) / pos["high_water"]
                    if dd >= TRAILING_DRAWDOWN:
                        gross = balance * (pos["size"] / BALANCE_INIT) * pnl_pct
                        balance += gross
                        trades.append(f"{sym},{pos['entry_idx']},{idx},{'LONG' if pos['side']==1 else 'SHORT'},{pos['entry']:.2f},{close:.2f},{pnl_pct:.4f},{gross:.2f},止盈")
                        positions.remove(pos)
                        continue
            
            # 入场
            already_in = any(p["sym"] == sym for p in positions)
            if not already_in and len(positions) < MAX_POSITIONS:
                sig = check_signal_on_kline(
                    idx, d["open"], d["high"], d["low"], d["close"], d["volume"],
                    d["boll_upper"], d["boll_lower"], d["direction"], d["slope_abs"],
                    d["macd"], d["macd_signal"], d["macd_hist"]
                )
                if sig != 0:
                    total_signals += 1
                    entry_price = d["open"][idx]
                    if np.isnan(entry_price):
                        entry_price = close
                    positions.append({
                        "sym": sym,
                        "side": sig,
                        "entry": entry_price,
                        "entry_idx": idx,
                        "high_water": 0.0,
                        "partial_taken": False,
                        "size": POSITION_SIZE,
                    })
    
    # 尾盘平仓
    for pos in positions:
        last_close = data[pos["sym"]]["close"][min_n - 1]
        if pos["side"] == 1:
            pnl_pct = (last_close - pos["entry"]) / pos["entry"]
        else:
            pnl_pct = (pos["entry"] - last_close) / pos["entry"]
        gross = balance * (pos["size"] / BALANCE_INIT) * pnl_pct
        balance += gross
        trades.append(f"{pos['sym']},{pos['entry_idx']},{min_n-1},{'LONG' if pos['side']==1 else 'SHORT'},{pos['entry']:.2f},{last_close:.2f},{pnl_pct:.4f},{gross:.2f},尾盘平仓")
    
    # ── 结果 ──
    elapsed = time.time() - t0
    print(f"\n{'='*60}")
    print(f"8 中小币种 1年回测（快速版）")
    print(f"{'='*60}")
    print(f"耗时: {elapsed:.1f}s")
    print(f"初始资金: ${BALANCE_INIT:,}")
    print(f"最终资金: ${balance:,.0f}")
    total_ret = (balance - BALANCE_INIT) / BALANCE_INIT * 100
    print(f"总收益率: {total_ret:+.2f}%")
    
    # 分析
    trade_list = [t.split(",") for t in trades]
    if trade_list:
        pnls = np.array([float(t[7]) for t in trade_list])
        wins = pnls[pnls > 0]
        losses = pnls[pnls <= 0]
        
        print(f"\n总交易: {len(trade_list)} 笔")
        print(f"总信号: {total_signals} 次")
        print(f"胜率: {len(wins)}/{len(trade_list)} = {len(wins)/len(trade_list)*100:.1f}%")
        print(f"平均盈利: ${wins.mean():.0f}" if len(wins) > 0 else "平均盈利: -")
        print(f"平均亏损: ${losses.mean():.0f}" if len(losses) > 0 else "平均亏损: -")
        
        if len(losses) > 0 and losses.sum() != 0:
            pf = abs(wins.sum() / losses.sum())
            print(f"盈亏比: {pf:.2f}")
        
        # 夏普比率（基于每日收盘收益率）
        # 用交易记录模拟每日收益
        daily_returns = []
        if len(trade_list) < 3:
            print(f"夏普比率: 0.00 (交易太少)")
        else:
            # 从交易记录中提取收益率序列
            rets = []
            for t in trade_list:
                rets.append(float(t[6]))
            if len(rets) > 1:
                sharpe = np.mean(rets) / max(np.std(rets), 1e-10) * np.sqrt(len(rets))
                print(f"夏普比率: {sharpe:.2f}")
        
        # 按原因
        reasons = [t[8] for t in trade_list]
        for r in sorted(set(reasons)):
            mask = [t[8] == r for t in trade_list]
            r_pnls = pnls[mask]
            print(f"  {r}: {len(r_pnls)}笔, 合计${r_pnls.sum():.0f}")
        
        # 按币种
        syms_list = [t[0] for t in trade_list]
        for s in sorted(set(syms_list)):
            mask = [t[0] == s for t in trade_list]
            s_pnls = pnls[mask]
            s_wins = s_pnls[s_pnls > 0]
            print(f"  {s}: {len(s_pnls)}笔, 胜{len(s_wins)}/{len(s_pnls)}, 合计${s_pnls.sum():.0f}")
    
    print(f"\n对比 B&H:")
    total_bh = 0
    for sym in SYMBOLS:
        d = data[sym]
        bh_ret = (d["close"][min_n-1] - d["close"][0]) / d["close"][0]
        total_bh += bh_ret
    avg_bh = total_bh / len(SYMBOLS) * 100
    print(f"  B&H等权重: {avg_bh:+.2f}%")
    print(f"  策略: {total_ret:+.2f}%")

if __name__ == "__main__":
    run()
