"""
执行模块
- 订单执行
- 交易日志记录
- 持仓同步（与交易所状态对齐）
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from loguru import logger

from ..exchange.binance_exchange import BinanceExchange
from ..risk.risk_manager import RiskManager


class TradeRecorder:
    """交易记录器"""
    
    def __init__(self, config: dict):
        self.log_path = Path(config["data"]["trade_log_path"])
        self.log_path.mkdir(parents=True, exist_ok=True)
        # 当日日志
        self.daily_trades = []
        self.daily_file = self.log_path / f"trades_{datetime.now().strftime('%Y-%m-%d')}.jsonl"

    def record_entry(self, symbol: str, side: str, price: float, amount: float, total_balance: float, reason: str):
        """记录入场"""
        record = {
            "time": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "action": "open",
            "side": side,
            "price": price,
            "amount": amount,
            "position_value": price * amount,
            "total_balance": total_balance,
            "reason": reason,
        }
        self._write(record)
        return record

    def record_exit(self, symbol: str, side: str, entry_price: float, exit_price: float, 
                    amount: float, total_balance: float, reason: str):
        """记录出场"""
        pnl_amount = (exit_price - entry_price) * amount if side == "long" else (entry_price - exit_price) * amount
        pnl_pct = (exit_price - entry_price) / entry_price if side == "long" else (entry_price - exit_price) / entry_price
        
        record = {
            "time": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "action": "close",
            "side": side,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "amount": amount,
            "pnl": round(pnl_amount, 2),
            "pnl_pct": round(pnl_pct * 100, 2),
            "total_balance": total_balance,
            "reason": reason,
        }
        self._write(record)
        return record

    def _write(self, record: dict):
        with open(self.daily_file, "a") as f:
            f.write(json.dumps(record) + "\n")
        self.daily_trades.append(record)

    def get_daily_trades(self) -> list:
        """获取当天所有交易"""
        return self.daily_trades


class Executor:
    """
    执行器
    根据信号执行开仓和平仓
    """

    def __init__(self, exchange: BinanceExchange, risk_mgr: RiskManager, recorder: TradeRecorder, config: dict):
        self.exchange = exchange
        self.risk = risk_mgr
        self.recorder = recorder
        self.cfg = config

    async def execute_open_long(self, symbol: str, entry_price: float):
        """执行做多开仓"""
        if not self.risk.can_open_position(symbol):
            logger.info(f"{symbol} 已达最大持仓数，跳过")
            return False

        try:
            total_balance = await self.exchange.fetch_balance()
            if total_balance <= 0:
                logger.error(f"余额不足: {total_balance}")
                return False

            amount = self.risk.calculate_position_size(total_balance, entry_price)
            if amount <= 0:
                logger.error(f"计算数量为0: {symbol}")
                return False

            # 格式化symbol
            idx = symbol.find("USDT")
            symbol_formatted = symbol[:idx] + "/" + symbol[idx:] if idx > 0 else symbol

            # 设置杠杆
            await self.exchange.set_leverage(symbol_formatted)

            # 市价单开多
            order = await self.exchange.create_market_order(symbol_formatted, "buy", amount)
            
            # 记录持仓
            self.risk.open_position(symbol, "long", entry_price, amount)
            
            # 记录交易日志
            self.recorder.record_entry(
                symbol, "long", entry_price, amount, total_balance, "做多信号"
            )
            
            return True

        except Exception as e:
            logger.error(f"做多开仓失败 {symbol}: {e}")
            return False

    async def execute_open_short(self, symbol: str, entry_price: float):
        """执行做空开仓"""
        if not self.risk.can_open_position(symbol):
            logger.info(f"{symbol} 已达最大持仓数，跳过")
            return False

        try:
            total_balance = await self.exchange.fetch_balance()
            if total_balance <= 0:
                logger.error(f"余额不足: {total_balance}")
                return False

            amount = self.risk.calculate_position_size(total_balance, entry_price)
            if amount <= 0:
                logger.error(f"计算数量为0: {symbol}")
                return False

            idx = symbol.find("USDT")
            symbol_formatted = symbol[:idx] + "/" + symbol[idx:] if idx > 0 else symbol

            await self.exchange.set_leverage(symbol_formatted)
            order = await self.exchange.create_market_order(symbol_formatted, "sell", amount)
            
            self.risk.open_position(symbol, "short", entry_price, amount)
            self.recorder.record_entry(
                symbol, "short", entry_price, amount, total_balance, "做空信号"
            )
            
            return True

        except Exception as e:
            logger.error(f"做空开仓失败 {symbol}: {e}")
            return False

    async def execute_close(self, symbol: str, reason: str):
        """平仓"""
        pos = self.risk.positions.get(symbol)
        if not pos:
            logger.warning(f"{symbol} 无持仓记录，跳过平仓")
            return False

        try:
            idx = symbol.find("USDT")
            symbol_formatted = symbol[:idx] + "/" + symbol[idx:] if idx > 0 else symbol

            # 使用当前持仓量
            position = await self.exchange.fetch_position(symbol_formatted)
            if not position or float(position.get("contracts", 0)) <= 0:
                logger.warning(f"{symbol} 交易所无持仓，清理本地记录")
                self.risk.close_position(symbol)
                return False

            amount = float(position["contracts"])
            close_side = "sell" if pos["side"] == "long" else "buy"
            
            # 获取当前市价用于记录
            current_price = float(position.get("markPrice", 0))
            
            # 市价平仓
            order = await self.exchange.create_market_close(symbol_formatted, pos["side"], amount)
            
            # 记录出场
            total_balance = await self.exchange.fetch_balance()
            self.recorder.record_exit(
                symbol, pos["side"], pos["entry_price"], current_price,
                amount, total_balance, reason
            )
            
            # 清除持仓
            self.risk.close_position(symbol)
            
            return True

        except Exception as e:
            logger.error(f"平仓失败 {symbol}: {e}")
            return False
