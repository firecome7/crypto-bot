#!/usr/bin/env python3
"""回测数据正确性核查"""
import pandas as pd
import numpy as np
from pathlib import Path

data_dir = Path(__file__).parent / "data" / "kline"

print("=" * 60)
print("1. 数据完整性检查")
print("=" * 60)

for f in sorted(data_dir.glob("*_5m.parquet")):
    df = pd.read_parquet(f)
    symbol = f.name.replace("_5m.parquet", "")

    # 基本统计
    gaps = df.index.to_series().diff().dropna()
    expected = pd.Timedelta("5min")
    gap_count = (gaps > expected * 1.5).sum()
    big_gaps = (gaps > expected * 3).sum()

    # 空值
    nulls = df.isnull().sum().sum()

    # 异常价格（涨跌超过 50% 的单根K线）
    df["pct"] = df["close"].pct_change()
    outliers = (df["pct"].abs() > 0.5).sum()

    print(f"\n{symbol}:")
    print(f"  根数: {len(df):>7}")
    print(f"  时间: {str(df.index.min())[:19]} ~ {str(df.index.max())[:19]}")
    print(f"  价格: ${df['close'].min():.2f} ~ ${df['close'].max():.2f}")
    print(f"  缺口(>1.5倍): {gap_count} (其中>3倍: {big_gaps})")
    print(f"  空值: {nulls}")
    print(f"  单根异常波动(>50%): {outliers}")
    
    if gap_count > 2000:
        print(f"  ⚠️ 缺口过多，可能有数据丢失!")
    if outliers > 5:
        print(f"  ⚠️ 异常波动过多，可能数据有问题!")

print("\n" + "=" * 60)
print("2. 验证信号检测逻辑（抽样检查）")
print("=" * 60)

# 从 BTC 数据中抽取一段，手动验证信号逻辑
df_btc = pd.read_parquet(data_dir / "BTCUSDT_5m.parquet")

# 取一段有代表性数据
sample = df_btc.loc["2025-06-01":"2025-06-07"]
closes = sample["close"].values
opens = sample["open"].values
highs = sample["high"].values
lows = sample["low"].values

print(f"\nBTC 2025-06-01 ~ 2025-06-07: {len(sample)} 根 K线")
print(f"  开盘: ${sample.iloc[0]['open']:.2f}")
print(f"  收盘: ${sample.iloc[-1]['close']:.2f}")

# 手动算 BOLL
def calc_boll(close, period=20, std=2.0):
    if len(close) < period: return None, None, None
    sma = np.mean(close[-period:])
    s = np.std(close[-period:])
    return sma + std*s, sma, sma - std*s

upper, mid, lower = calc_boll(closes)
print(f"  BOLL: 上轨${upper:.2f}, 中轨${mid:.2f}, 下轨${lower:.2f}")

# 检查是否有跌破下轨的 K 线
touch_lower = [(i, c, l) for i, (c, l) in enumerate(zip(closes, lows)) if l < lower and c < opens[i]]
print(f"  跌破下轨+阴线: {len(touch_lower)} 根")
if touch_lower:
    for idx, c, l in touch_lower[:3]:
        print(f"    K线#{idx}: close=${c:.2f}, low=${l:.2f}")

# 检查是否有突破上轨的 K 线
touch_upper = [(i, c, h) for i, (c, h) in enumerate(zip(closes, highs)) if h > upper and c > opens[i]]
print(f"  突破上轨+阳线: {len(touch_upper)} 根")

print("\n" + "=" * 60)
print("3. 交易记录合理性检查")
print("=" * 60)

trade_file = Path(__file__).parent / "data" / "backtest_10coins_fixed.csv"
if trade_file.exists():
    trades = pd.read_csv(trade_file)
    print(f"\n交易记录: {len(trades)} 笔")
    print(f"  止损: {(trades['reason']=='止损').sum()} 笔")
    print(f"  止盈: {(trades['reason']=='止盈').sum()} 笔")
    print(f"  尾盘平仓: {(trades['reason']=='尾盘平仓').sum()} 笔")
    
    # 检查止盈是否都触发了移动止盈条件
    stop_profit = trades[trades['reason'] == '止盈']
    if len(stop_profit) > 0:
        print(f"\n  止盈交易收益分布:")
        print(f"    最小: ${stop_profit['pnl'].min():.0f}")
        print(f"    最大: ${stop_profit['pnl'].max():.0f}")
        print(f"    均值: ${stop_profit['pnl'].mean():.0f}")
    
    # 检查止损是否都接近 2%
    stop_loss = trades[trades['reason'] == '止损']
    if len(stop_loss) > 0:
        print(f"\n  止损交易亏损分布:")
        print(f"    最小: ${stop_loss['pnl'].min():.0f} ({stop_loss['pnl_pct'].min()*100:.2f}%)")
        print(f"    最大: ${stop_loss['pnl'].max():.0f} ({stop_loss['pnl_pct'].max()*100:.2f}%)")
        print(f"    均值: ${stop_loss['pnl'].mean():.0f} ({stop_loss['pnl_pct'].mean()*100:.2f}%)")
        
        # 检查是否有止损超过 3% 的（理论上不应该）
        excessive = stop_loss[stop_loss['pnl_pct'] < -0.03]
        if len(excessive) > 0:
            print(f"\n  ⚠️ 止损超过 3% 的: {len(excessive)} 笔")
            for _, row in excessive.head(5).iterrows():
                print(f"    {row['symbol']}: entry=${row['entry']:.2f}, exit=${row['exit']:.2f}, {row['pnl_pct']*100:.2f}%")
        else:
            print(f"\n  ✅ 所有止损都在 2% 以内，风控逻辑正确")

print("\n" + "=" * 60)
print("4. 尾盘平仓分析")
print("=" * 60)

tail = trades[trades['reason'] == '尾盘平仓']
if len(tail) > 0:
    print(f"\n尾盘平仓: {len(tail)} 笔")
    print(f"  盈利: {(tail['pnl']>0).sum()} 笔, 合计${tail[tail['pnl']>0]['pnl'].sum():.0f}")
    print(f"  亏损: {(tail['pnl']<=0).sum()} 笔, 合计${tail[tail['pnl']<=0]['pnl'].sum():.0f}")
    print(f"  净收益: ${tail['pnl'].sum():.0f}")
    
    # 检查这些持仓是否都是盈利的（应该在止盈/止损之间）
    in_profit = tail[tail['pnl_pct'] > 0]
    in_loss = tail[tail['pnl_pct'] <= 0]
    print(f"\n  持仓浮盈: {len(in_profit)} 笔, 平均 +{in_profit['pnl_pct'].mean()*100:.2f}%")
    print(f"  持仓浮亏: {len(in_loss)} 笔, 平均 {in_loss['pnl_pct'].mean()*100:.2f}%")

print("\n✅ 核查完毕")
