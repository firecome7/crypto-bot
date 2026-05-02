"""
交易所连接模块
- CCXT REST API 封装
- WebSocket 行情流
"""
import ccxt
import ccxt.async_support as ccxt_async
from loguru import logger
from typing import Callable
import asyncio
import json
import websockets
from datetime import datetime

from ..utils.config import load_config


class BinanceExchange:
    def __init__(self, config: dict = None):
        self.cfg = config or load_config()
        exc_cfg = self.cfg["exchange"]

        # 判断测试网
        if exc_cfg.get("testnet", True):
            self.exchange = ccxt_async.binance({
                "apiKey": exc_cfg["api_key"],
                "secret": exc_cfg["api_secret"],
                "options": {
                    "defaultType": "future",
                    "adjustForTimeDifference": True,
                },
                "urls": {
                    "api": {
                        "public": "https://testnet.binancefuture.com",
                        "private": "https://testnet.binancefuture.com",
                    },
                },
            })
            self.ws_base = "wss://testnet.binancefuture.com/ws"
        else:
            self.exchange = ccxt_async.binance({
                "apiKey": exc_cfg["api_key"],
                "secret": exc_cfg["api_secret"],
                "options": {
                    "defaultType": "future",
                    "adjustForTimeDifference": True,
                },
            })
            self.ws_base = "wss://fstream.binance.com/ws"

        self.trading_cfg = self.cfg["trading"]
        self.signal_cfg = self.cfg["signal"]
        self.leverage = exc_cfg.get("leverage", 1)
        self.margin_type = exc_cfg.get("margin_type", "isolated")

    async def init(self):
        """初始化交易所连接，设置杠杆和保证金模式"""
        await self.exchange.load_markets()
        logger.info(f"交易所初始化完成 (testnet={self.cfg['exchange'].get('testnet', True)})")

    async def set_leverage(self, symbol: str, leverage: int = None):
        lev = leverage or self.leverage
        try:
            await self.exchange.set_leverage(lev, symbol)
            logger.debug(f"设置 {symbol} 杠杆为 {lev}x")
        except Exception as e:
            logger.warning(f"设置 {symbol} 杠杆失败: {e}")

    async def fetch_klines(self, symbol: str, timeframe: str, limit: int = 100):
        """获取K线数据"""
        return await self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)

    async def fetch_usdt_tickers(self):
        """获取所有USDT永续合约的ticker"""
        markets = await self.exchange.load_markets()
        usdt_symbols = []
        for symbol, info in markets.items():
            if (
                symbol.endswith("/USDT")
                and info.get("linear", False)
                and info.get("swap", False)
                and info.get("active", False)
            ):
                usdt_symbols.append(symbol)
        return usdt_symbols

    async def fetch_ticker_24h(self, symbol: str):
        """获取24小时ticker"""
        return await self.exchange.fetch_ticker(symbol)

    async def create_market_order(self, symbol: str, side: str, amount: float):
        """市价单开仓"""
        try:
            order = await self.exchange.create_market_order(
                symbol, side, amount
            )
            logger.info(f"开仓: {side} {amount} {symbol} -> {order.get('id')}")
            return order
        except Exception as e:
            logger.error(f"开仓失败 {symbol}: {e}")
            raise

    async def create_market_close(self, symbol: str, side: str, amount: float):
        """市价单平仓"""
        try:
            close_side = "sell" if side == "buy" else "buy"
            order = await self.exchange.create_market_order(
                symbol, close_side, amount
            )
            logger.info(f"平仓: {close_side} {amount} {symbol} -> {order.get('id')}")
            return order
        except Exception as e:
            logger.error(f"平仓失败 {symbol}: {e}")
            raise

    async def fetch_balance(self):
        """获取USDT余额"""
        balance = await self.exchange.fetch_balance()
        return balance["USDT"]["total"] or 0

    async def fetch_position(self, symbol: str):
        """获取持仓信息"""
        try:
            positions = await self.exchange.fetch_positions([symbol])
            for pos in positions:
                if pos.get("symbol") == symbol:
                    return pos
            return None
        except Exception as e:
            logger.error(f"获取持仓失败 {symbol}: {e}")
            return None

    async def close(self):
        await self.exchange.close()

    # ──── WebSocket 部分 ────

    async def subscribe_klines(self, symbols: list, timeframe: str, callback: Callable):
        """
        订阅多个币种的K线 WebSocket
        symbols: ['BTCUSDT', 'ETHUSDT'] 注意不带斜杠
        callback: async def cb(symbol, kline_data)  # kline_data = [timestamp, open, high, low, close, volume]
        """
        streams = [f"{s.lower()}@kline_{timeframe}" for s in symbols]
        params = {
            "method": "SUBSCRIBE",
            "params": streams,
            "id": 1,
        }
        url = f"{self.ws_base}/{'/'.join(streams)}"
        # 用组合流
        combined_url = f"{self.ws_base}/stream?streams={'/'.join(streams)}"

        async def _listen():
            while True:
                try:
                    async with websockets.connect(combined_url) as ws:
                        logger.info(f"WebSocket 已连接: {len(symbols)} 个币种, {timeframe}")
                        async for raw in ws:
                            data = json.loads(raw)
                            if data.get("data") and data["data"].get("e") == "kline":
                                k = data["data"]["k"]
                                symbol = data["data"]["s"]  # e.g. BTCUSDT
                                kline = [
                                    k["t"],       # timestamp
                                    float(k["o"]),  # open
                                    float(k["h"]),  # high
                                    float(k["l"]),  # low
                                    float(k["c"]),  # close
                                    float(k["v"]),  # volume
                                ]
                                is_closed = k["x"]  # True = K线已完结
                                await callback(symbol, kline, is_closed)
                except Exception as e:
                    logger.error(f"WebSocket 断开: {e}, 5秒后重连...")
                    await asyncio.sleep(5)

        asyncio.create_task(_listen())
        logger.info(f"WebSocket 订阅任务已创建: {len(symbols)} 个币种")

    async def subscribe_ticker(self, symbols: list, callback: Callable):
        """订阅实时ticker（用于报价监控）"""
        streams = [f"{s.lower()}@ticker" for s in symbols]
        combined_url = f"{self.ws_base}/stream?streams={'/'.join(streams)}"

        async def _listen():
            while True:
                try:
                    async with websockets.connect(combined_url) as ws:
                        logger.info(f"Ticker WebSocket 已连接: {len(symbols)} 个币种")
                        async for raw in ws:
                            data = json.loads(raw)
                            if data.get("data") and data["data"].get("e") == "24hrTicker":
                                t = data["data"]
                                symbol = t["s"]
                                ticker = {
                                    "last": float(t["c"]),
                                    "volume": float(t["v"]),
                                    "change": float(t["p"]),
                                    "high": float(t["h"]),
                                    "low": float(t["l"]),
                                }
                                await callback(symbol, ticker)
                except Exception as e:
                    logger.error(f"Ticker WebSocket 断开: {e}, 5秒后重连...")
                    await asyncio.sleep(5)

        asyncio.create_task(_listen())


# ──── 交易对管理 ────

async def get_top_usdt_pairs(
    exchange: BinanceExchange,
    exclude_top: int = 10,
    count: int = 40,
) -> list:
    """
    获取按24h交易量排序的USDT永续合约，剔除前exclude_top大主流币
    返回格式: ['BTCUSDT', 'ETHUSDT', ...]
    """
    # 获取所有合约
    markets = await exchange.exchange.load_markets()
    usdt_swap = []
    for symbol, info in markets.items():
        if (
            symbol.endswith("/USDT")
            and info.get("linear", False)
            and info.get("swap", False)
            and info.get("active", False)
        ):
            usdt_swap.append(symbol)

    # 获取24h交易量
    vol_data = []
    for sym in usdt_swap:
        try:
            ticker = await exchange.exchange.fetch_ticker(sym)
            vol = float(ticker.get("quoteVolume", 0) or 0)
            vol_data.append((sym, vol))
        except:
            pass
        await asyncio.sleep(0.1)  # 限流

    # 按交易量降序排列
    vol_data.sort(key=lambda x: x[1], reverse=True)

    # 剔除前N大主流币
    candidates = vol_data[exclude_top:]
    # 取后count个
    selected = [s[0].replace("/", "") for s in candidates[:count]]

    logger.info(f"交易对筛选完成: 剔除前{exclude_top}, 取{count}个")
    logger.info(f"选中币种: {selected[:10]}...")
    return selected
