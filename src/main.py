"""
主程序入口
- 事件驱动主循环
- 每日8点自动更新交易对
- WebSocket行情 → 信号检测 → 风控检查 → 执行
"""
import asyncio
import signal
import sys
from datetime import datetime, time
from loguru import logger
import numpy as np

from ..utils.config import load_config
from ..exchange.binance_exchange import BinanceExchange
from ..exchange.data_manager import DataManager, DailyScreener
from ..signal.signal_engine import EntrySignalDetector, check_trend_direction
from ..risk.risk_manager import RiskManager
from ..executor.executor import Executor, TradeRecorder
from ..analysis.daily_analyzer import DailyAnalyzer


class CryptoBot:
    """币圈自动交易机器人"""

    def __init__(self, config_path: str = None):
        self.cfg = load_config(config_path)
        
        # 初始化各模块
        self.exchange = BinanceExchange(self.cfg)
        self.data_mgr = DataManager(self.cfg)
        self.screener = DailyScreener(self.cfg)
        self.signal_detector = EntrySignalDetector(
            boll_period=self.cfg["signal"]["entry"]["boll_period"],
            boll_std=self.cfg["signal"]["entry"]["boll_std"],
        )
        self.risk_mgr = RiskManager(self.cfg)
        self.recorder = TradeRecorder(self.cfg)
        self.executor = Executor(self.exchange, self.risk_mgr, self.recorder, self.cfg)
        self.analyzer = DailyAnalyzer(self.cfg)

        # 运行状态
        self.running = False
        self.current_pairs = []  # 当前监控的币种列表
        
        # 方向缓存: {symbol: (is_bullish, slope)}
        self.trend_cache: dict[str, tuple[bool, float]] = {}
        
        # 小时线K线缓存（用于方向判定）
        self.hourly_klines: dict[str, list] = {}

        # 配置日志
        logger.add(
            self.cfg.get("logging", {}).get("file", "bot.log"),
            level=self.cfg.get("logging", {}).get("level", "INFO"),
            rotation="1 day",
            retention="30 days",
        )

    async def init(self):
        """初始化交易所连接"""
        await self.exchange.init()
        logger.info("机器人初始化完成")

    async def load_hourly_klines(self, symbols: list):
        """加载初始小时线K线用于方向判定"""
        for s in symbols:
            try:
                idx = s.find("USDT")
                symbol_fmt = s[:idx] + "/" + s[idx:] if idx > 0 else s
                klines = await self.exchange.fetch_klines(symbol_fmt, "1h", limit=50)
                if klines:
                    self.hourly_klines[s] = klines
                await asyncio.sleep(0.1)
            except Exception as e:
                logger.warning(f"加载 {s} 小时线失败: {e}")

    def update_trend(self, symbol: str):
        """更新方向判定"""
        hourly = self.hourly_klines.get(symbol)
        if not hourly or len(hourly) < 30:
            return
        
        closes = np.array([k[4] for k in hourly])
        is_bullish, slope = check_trend_direction(
            closes,
            boll_period=self.cfg["signal"]["trend"]["boll_period"],
            lookback=self.cfg["signal"]["trend"]["slope_lookback"],
        )
        if is_bullish is not None:
            self.trend_cache[symbol] = (is_bullish, slope)

    async def on_5m_kline(self, symbol: str, kline: list, is_closed: bool):
        """5分钟K线回调处理"""
        # 1. 持久化存储
        if is_closed:
            self.data_mgr.append_kline(symbol, kline)

        # 2. 更新信号检测器
        added = self.signal_detector.add_kline(symbol, kline, is_closed)
        
        # 3. 如果该币种已有持仓，检查出场条件
        if symbol in self.risk_mgr.positions:
            current_price = kline[4]  # close
            should_exit, reason = self.risk_mgr.update_price(symbol, current_price)
            if should_exit:
                logger.info(f"出场信号: {symbol} — {reason}")
                await self.executor.execute_close(symbol, reason)
            return

        # 4. 无持仓，检查入场信号
        if not is_closed:
            return  # 只在K线完结时判断入场（确认信号）

        is_bullish, _ = self.trend_cache.get(symbol, (None, 0))
        if is_bullish is None:
            return  # 方向尚未确定

        # 做多检查
        has_signal, reason = self.signal_detector.check_long_signal(symbol, is_bullish)
        if has_signal:
            price = self.signal_detector.get_signal_entry_price(symbol)
            logger.info(f"做多信号: {symbol} @ {price}")
            ok = await self.executor.execute_open_long(symbol, price)
            if ok:
                self.signal_detector.clear_signal(symbol)
            return

        # 做空检查
        has_signal, reason = self.signal_detector.check_short_signal(symbol, is_bullish)
        if has_signal:
            price = self.signal_detector.get_signal_entry_price(symbol)
            logger.info(f"做空信号: {symbol} @ {price}")
            ok = await self.executor.execute_open_short(symbol, price)
            if ok:
                self.signal_detector.clear_signal(symbol)

    async def on_hourly_kline(self, symbol: str, kline: list, is_closed: bool):
        """小时K线回调处理（用于方向判定）"""
        if not is_closed:
            return
        
        if symbol not in self.hourly_klines:
            self.hourly_klines[symbol] = []
        
        # 更新缓存
        ts = kline[0]
        if not self.hourly_klines[symbol] or self.hourly_klines[symbol][-1][0] != ts:
            self.hourly_klines[symbol].append(kline)
            if len(self.hourly_klines[symbol]) > 100:
                self.hourly_klines[symbol] = self.hourly_klines[symbol][-100:]
            
            # 更新方向判定
            self.update_trend(symbol)
            
            bull, slope = self.trend_cache.get(symbol, (None, 0))
            direction = "多头" if bull else "空头" if bull is not None else "未知"
            logger.debug(f"方向更新: {symbol} -> {direction} (slope={slope:.6f})")

    async def daily_schedule(self):
        """每日定时任务"""
        while self.running:
            now = datetime.now()
            target_time = self.cfg["data"]["daily_update_time"]
            target_hour, target_min = map(int, target_time.split(":"))
            
            next_run = now.replace(hour=target_hour, minute=target_min, second=0, microsecond=0)
            if now >= next_run:
                next_run = next_run.replace(day=next_run.day + 1)
            
            wait_secs = (next_run - now).total_seconds()
            logger.info(f"下次每日更新: {next_run.isoformat()} (等待 {wait_secs/3600:.1f} 小时)")
            
            await asyncio.sleep(wait_secs)
            
            if not self.running:
                break
            
            try:
                logger.info("===== 执行每日更新 =====")
                new_pairs = await self.screener.run_daily_update(self.exchange)
                
                # 更新交易对并重新订阅WebSocket
                old_pairs = set(self.current_pairs)
                new_set = set(new_pairs)
                
                if old_pairs != new_set:
                    self.current_pairs = new_pairs
                    # 重新订阅 5m K线
                    # 注意: 这里需要重启WebSocket连接
                    logger.info(f"币种列表已更新: {len(new_pairs)} 个")
                    
                    # 重新加载小时线数据
                    await self.load_hourly_klines(new_pairs)
                
                # 生成昨日复盘报告
                yesterday = now.strftime("%Y-%m-%d")
                analysis = self.analyzer.analyze(yesterday)
                report = self.analyzer.generate_report(analysis)
                self.analyzer.save_report(report, yesterday)
                logger.info(f"复盘报告已生成: {yesterday}")
                
            except Exception as e:
                logger.error(f"每日更新失败: {e}")

    async def start(self):
        """启动机器人"""
        self.running = True
        
        # 1. 初始化
        await self.init()
        
        # 2. 获取初始交易对列表
        logger.info("获取初始交易对列表...")
        self.current_pairs = await self.screener.run_daily_update(self.exchange)
        
        # 3. 加载小时线方向数据
        logger.info("加载小时线数据用于方向判定...")
        await self.load_hourly_klines(self.current_pairs)
        for s in self.current_pairs:
            self.update_trend(s)
        
        # 4. 启动每日定时任务
        asyncio.create_task(self.daily_schedule())
        
        # 5. 订阅 WebSocket 行情
        clean_symbols = [s for s in self.current_pairs]  # BTCUSDT 格式
        
        # 订阅5分钟K线（入场信号）
        await self.exchange.subscribe_klines(
            clean_symbols,
            "5m",
            self.on_5m_kline,
        )
        
        # 订阅小时K线（方向判定）
        await self.exchange.subscribe_klines(
            clean_symbols,
            "1h",
            self.on_hourly_kline,
        )
        
        logger.info(f"===== 机器人启动完成 =====")
        logger.info(f"监控币种: {len(self.current_pairs)} 个")
        logger.info(f"最大持仓: {self.risk_mgr.max_positions} 个")
        logger.info(f"单笔仓位: {self.risk_mgr.position_pct*100}% 总资金")
        
        # 保持运行
        try:
            while self.running:
                await asyncio.sleep(10)
                
                # 定期输出状态
                pos_count = self.risk_mgr.get_position_count()
                if pos_count > 0:
                    logger.info(f"当前持仓: {pos_count}/{self.risk_mgr.max_positions}")
                    
        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        """停止机器人"""
        self.running = False
        self.data_mgr.flush_all()
        logger.info("机器人已停止")


async def main():
    bot = CryptoBot()
    await bot.start()


if __name__ == "__main__":
    asyncio.run(main())

