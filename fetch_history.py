#!/usr/bin/env python3
"""拉取历史 K 线数据到本地 Parquet 文件"""
import asyncio, sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ccxt.async_support as ccxt
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
from loguru import logger

# 配置
SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT",
    "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
]
TIMEFRAMES = ["5m", "15m"]
DATA_DIR = Path(__file__).parent / "data" / "kline"
LIMIT = 1000
DAYS_BACK = 365

async def fetch_all(symbol: str, timeframe: str, ex):
    """拉取全部历史 K 线, 返回 (klines, req_count)"""
    since = int((datetime.now() - timedelta(days=DAYS_BACK)).timestamp() * 1000)
    now = int(datetime.now().timestamp() * 1000)
    all_klines = []
    req_count = 0
    while since < now:
        try:
            klines = await ex.fetch_ohlcv(symbol, timeframe, since=since, limit=LIMIT)
            if not klines:
                break
            req_count += 1
            all_klines.extend(klines)
            since = klines[-1][0] + 1
            if req_count % 20 == 0:
                last = datetime.fromtimestamp(klines[-1][0]/1000)
                logger.info(f"  {symbol} {timeframe}: {len(all_klines)} 根, 到 {last}")
            await asyncio.sleep(0.15)
        except Exception as e:
            logger.warning(f"请求失败, 等待 2s: {e}")
            await asyncio.sleep(2)
    return all_klines, req_count

async def main():
    ex = ccxt.binance({"options": {"defaultType": "future"}})
    for symbol in SYMBOLS:
        for tf in TIMEFRAMES:
            filepath = DATA_DIR / f"{symbol.replace('/', '')}_{tf}.parquet"
            if filepath.exists():
                df_old = pd.read_parquet(filepath)
                old_count = len(df_old)
                oldest = df_old.index.min()
                newest = df_old.index.max()
                logger.info(f"{symbol} {tf}: 已有 {old_count} 根 ({oldest} ~ {newest})")
                days = (datetime.now() - oldest.to_pydatetime()).days if hasattr(oldest, 'to_pydatetime') else 0
                if days >= DAYS_BACK:
                    logger.info(f"  数据已足够, 跳过")
                    continue
            logger.info(f"开始拉取 {symbol} {tf}...")
            t0 = time.time()
            klines, req_count = await fetch_all(symbol, tf, ex)
            elapsed = time.time() - t0
            if not klines:
                logger.warning(f"  无数据")
                continue
            df = pd.DataFrame(klines, columns=["timestamp", "open", "high", "low", "close", "volume"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            df.set_index("timestamp", inplace=True)
            df = df[~df.index.duplicated(keep="last")]
            df.sort_index(inplace=True)
            if filepath.exists():
                df_old = pd.read_parquet(filepath)
                df = pd.concat([df_old, df])
                df = df[~df.index.duplicated(keep="last")]
                df.sort_index(inplace=True)
            filepath.parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(filepath)
            logger.info(f"✅ {symbol} {tf}: {len(df)} 根, 耗时 {elapsed:.0f}s, 请求 {req_count}次")
            del klines, df
    await ex.close()
    logger.info("全部完成!")

if __name__ == "__main__":
    logger.remove()
    logger.add(sys.stderr, format="{time:HH:mm:ss} | {message}", level="INFO")
    asyncio.run(main())
