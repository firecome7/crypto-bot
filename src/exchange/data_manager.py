"""
数据管理模块
- K线数据本地持久化（Parquet格式）
- 每日8点更新交易对列表
- 数据读取与历史查询
"""
import os
import json
import asyncio
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, date, timezone, timedelta
from loguru import logger

from src.exchange.binance_exchange import BinanceExchange, get_top_usdt_pairs

# 测试网固定币种列表（用于测试信号逻辑）
TESTNET_PAIRS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT",
]


class DataManager:
    """
    K线数据管理
    存储结构:
      data/kline/raw/{symbol}_{timeframe}.parquet  — 追加式存储
      data/market/pairs_{date}.json                 — 每日交易对列表
    """

    def __init__(self, config: dict):
        self.cfg = config
        self.base_path = Path(config["data"]["kline_path"])
        self.market_path = Path(config["data"]["market_path"])
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.market_path.mkdir(parents=True, exist_ok=True)
        self.timeframe = config["signal"]["entry"]["period"]  # 5m
        self.buffer: dict[str, list] = {}  # 内存缓冲，定期写入
        self.buffer_size = 100

    def save_klines(self, symbol: str, klines: list):
        """保存K线数据（追加式）"""
        filepath = self.base_path / f"{symbol}_{self.timeframe}.parquet"
        
        df_new = pd.DataFrame(
            klines,
            columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        df_new["timestamp"] = pd.to_datetime(df_new["timestamp"], unit="ms")
        df_new["symbol"] = symbol
        df_new.set_index("timestamp", inplace=True)

        if filepath.exists():
            df_old = pd.read_parquet(filepath)
            # 去重
            combined = pd.concat([df_old, df_new])
            combined = combined[~combined.index.duplicated(keep="last")]
            combined.sort_index(inplace=True)
            combined.to_parquet(filepath)
        else:
            df_new.to_parquet(filepath)

    def append_kline(self, symbol: str, kline: list):
        """将单根K线加入缓冲，满N根后批量写入"""
        if symbol not in self.buffer:
            self.buffer[symbol] = []
        self.buffer[symbol].append(kline)
        
        if len(self.buffer[symbol]) >= self.buffer_size:
            self.save_klines(symbol, self.buffer[symbol])
            self.buffer[symbol] = []
            logger.debug(f"数据持久化: {symbol} ({self.buffer_size}根)")

    def flush_all(self):
        """强制写入所有缓冲数据"""
        for symbol, klines in self.buffer.items():
            if klines:
                self.save_klines(symbol, klines)
                self.buffer[symbol] = []
        logger.info("所有缓冲数据已写入磁盘")

    def load_recent_klines(self, symbol: str, limit: int = 200, timeframe: str = None) -> pd.DataFrame:
        """加载最近N根K线"""
        tf = timeframe or self.timeframe
        filepath = self.base_path / f"{symbol}_{tf}.parquet"
        if not filepath.exists():
            return pd.DataFrame()
        df = pd.read_parquet(filepath)
        if limit and len(df) > limit:
            df = df.tail(limit)
        return df

    def save_daily_pairs(self, pairs: list):
        """保存每日交易对列表"""
        today = date.today().isoformat()
        filepath = self.market_path / f"pairs_{today}.json"
        with open(filepath, "w") as f:
            json.dump({
                "date": today,
                "time": datetime.now().isoformat(),
                "pairs": pairs,
            }, f, indent=2)
        logger.info(f"交易对列表已保存: {len(pairs)} 个币种")

    def load_latest_pairs(self) -> list:
        """加载最近一次的交易对列表"""
        files = sorted(self.market_path.glob("pairs_*.json"), reverse=True)
        if not files:
            return []
        with open(files[0]) as f:
            data = json.load(f)
        return data["pairs"]


class DailyScreener:
    """
    每日选币器
    每天 08:00 运行，更新监控币种列表
    """

    def __init__(self, config: dict):
        self.cfg = config
        self.data_mgr = DataManager(config)
        self.trading_cfg = config["trading"]

    async def run_daily_update(self, exchange: BinanceExchange):
        """
        执行每日8点更新
        1. 获取交易对列表
        2. 保存到文件
        3. 返回新列表
        """
        logger.info("开始每日选币更新...")
        
        # Demo/Testnet 模式用固定币种列表（无真实交易量数据）
        if self.cfg["exchange"].get("mode", "demo") in ("demo", "testnet"):
            pairs = TESTNET_PAIRS
            logger.info(f"测试网模式: 使用固定币种列表 {pairs}")
        else:
            pairs = await get_top_usdt_pairs(
                exchange,
                exclude_top=self.trading_cfg["exclude_top_n"],
                count=self.trading_cfg["watch_count"],
            )
        
        self.data_mgr.save_daily_pairs(pairs)
        
        # 为每个新币种填充初始K线数据
        for symbol in pairs:
            try:
                symbol_with_slash = symbol[:3] + "/" + symbol[3:] if len(symbol) == 7 else "/".join([symbol[:-4], symbol[-4:]])
                # 调整格式: BTCUSDT -> BTC/USDT
                idx = symbol.find("USDT")
                if idx > 0:
                    symbol_formatted = symbol[:idx] + "/" + symbol[idx:]
                else:
                    symbol_formatted = symbol
                
                klines = await exchange.fetch_klines(symbol_formatted, "5m", limit=100)
                if klines:
                    self.data_mgr.save_klines(symbol, klines)
                    logger.debug(f"已加载 {symbol} 初始K线数据: {len(klines)} 根")
                await asyncio.sleep(0.2)  # 限流
            except Exception as e:
                logger.warning(f"加载 {symbol} 初始数据失败: {e}")
        
        logger.info(f"每日选币完成: {len(pairs)} 个币种")
        return pairs

