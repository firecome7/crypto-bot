"""
风控模块
- 仓位计算
- 固定止损
- 移动止损（保本损 + 利润回撤）
- 持仓管理
"""
from loguru import logger
from typing import Tuple


class RiskManager:
    """
    风控管理器
    管理所有持仓的入场价、最高浮盈、止损状态
    """

    def __init__(self, config: dict):
        self.cfg = config
        self.trading_cfg = config["trading"]
        
        # 持仓状态: {symbol: position_info}
        self.positions: dict[str, dict] = {}
        
        # 参数
        self.max_positions = self.trading_cfg["max_positions"]      # 20
        self.position_pct = self.trading_cfg["position_pct"]        # 0.10
        self.stop_loss_pct = self.trading_cfg["stop_loss_pct"]      # 0.02 (占总资金)
        self.trail_activate = self.trading_cfg["trailing_activate_pct"]  # 0.03
        self.trail_drawdown = self.trading_cfg["trailing_drawdown_pct"]  # 0.60

    def can_open_position(self, symbol: str) -> bool:
        """检查是否还能开新仓"""
        if len(self.positions) >= self.max_positions:
            return False
        if symbol in self.positions:
            return False
        return True

    def calculate_position_size(self, total_balance: float, current_price: float) -> float:
        """
        计算开仓数量
        仓位价值 = 总资金 * position_pct
        数量 = 仓位价值 / 价格
        """
        position_value = total_balance * self.position_pct
        amount = position_value / current_price
        # 按交易所最小精度处理（后续合约实际下单时会做精度调整）
        return amount

    def open_position(self, symbol: str, side: str, entry_price: float, amount: float):
        """记录开仓"""
        self.positions[symbol] = {
            "side": side,           # "long" / "short"
            "entry_price": entry_price,
            "amount": amount,
            "highest_price": entry_price if side == "long" else entry_price,
            "lowest_price": entry_price if side == "short" else entry_price,
            "max_unrealized_pct": 0.0,  # 最高浮盈百分比
            "trailing_activated": False,
            "entry_time": None,     # 后续可加时间戳
        }
        logger.info(f"开仓记录: {side.upper()} {symbol} @ {entry_price}, 数量: {amount}")

    def close_position(self, symbol: str):
        """清除持仓记录"""
        pos = self.positions.pop(symbol, None)
        if pos:
            logger.info(f"平仓记录清除: {symbol}")

    def update_price(self, symbol: str, current_price: float):
        """更新价格，检查是否触发止损"""
        pos = self.positions.get(symbol)
        if not pos:
            return None
        
        # 最高/最低价更新
        if pos["side"] == "long":
            if current_price > pos["highest_price"]:
                pos["highest_price"] = current_price
            # 计算当前浮盈百分比（基于入场价）
            unrealized_pct = (current_price - pos["entry_price"]) / pos["entry_price"]
            
            # 更新最高浮盈
            if unrealized_pct > pos["max_unrealized_pct"]:
                pos["max_unrealized_pct"] = unrealized_pct
            
            # 激活移动止损
            if unrealized_pct >= self.trail_activate:
                pos["trailing_activated"] = True
            
            # 检查各种出场条件
            return self._check_exit_long(pos, current_price, unrealized_pct)
            
        else:  # short
            if current_price < pos["lowest_price"]:
                pos["lowest_price"] = current_price
            # 做空浮盈 = (入场价 - 当前价) / 入场价
            unrealized_pct = (pos["entry_price"] - current_price) / pos["entry_price"]
            
            if unrealized_pct > pos["max_unrealized_pct"]:
                pos["max_unrealized_pct"] = unrealized_pct
            
            if unrealized_pct >= self.trail_activate:
                pos["trailing_activated"] = True
            
            return self._check_exit_short(pos, current_price, unrealized_pct)

    def _check_exit_long(self, pos: dict, current_price: float, unrealized_pct: float) -> Tuple[bool, str]:
        """
        检查多头出场条件
        返回: (should_exit, reason)
        """
        entry_price = pos["entry_price"]
        
        # 1. 固定止损：亏损超过总资金的2%
        # 单笔仓位价值 = 总资金 * 10%，所以仓位亏损20% = 总资金2%
        if unrealized_pct <= -0.20:  # -20% 仓位亏损
            return True, "固定止损触发"
        
        # 2. 移动止损（盈利 >= 3% 已激活）
        if pos["trailing_activated"]:
            # 保本损
            if current_price <= entry_price:
                return True, "保本损触发（回到成本价）"
            
            # 利润回撤60%
            if pos["max_unrealized_pct"] > 0:
                retracement = (pos["max_unrealized_pct"] - unrealized_pct) / pos["max_unrealized_pct"]
                if retracement >= self.trail_drawdown:
                    return True, f"利润回撤触发 (最大{pos['max_unrealized_pct']:.2%} -> 当前{unrealized_pct:.2%})"
        
        return False, ""

    def _check_exit_short(self, pos: dict, current_price: float, unrealized_pct: float) -> Tuple[bool, str]:
        """
        检查空头出场条件
        """
        entry_price = pos["entry_price"]
        
        # 1. 固定止损
        if unrealized_pct <= -0.20:
            return True, "固定止损触发"
        
        # 2. 移动止损
        if pos["trailing_activated"]:
            # 保本损
            if current_price >= entry_price:
                return True, "保本损触发（回到成本价）"
            
            # 利润回撤60%
            if pos["max_unrealized_pct"] > 0:
                retracement = (pos["max_unrealized_pct"] - unrealized_pct) / pos["max_unrealized_pct"]
                if retracement >= self.trail_drawdown:
                    return True, f"利润回撤触发 (最大{pos['max_unrealized_pct']:.2%} -> 当前{unrealized_pct:.2%})"
        
        return False, ""

    def get_position_count(self) -> int:
        """当前持仓数"""
        return len(self.positions)

    def get_positions_summary(self) -> str:
        """获取持仓摘要"""
        if not self.positions:
            return "无持仓"
        lines = []
        for sym, pos in self.positions.items():
            lines.append(f"{sym} {pos['side'].upper()} 入场:{pos['entry_price']:.4f}")
        return "\n".join(lines)
