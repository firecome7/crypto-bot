"""
信号引擎
- 方向判定（小时线BOLL中轨斜率）
- 入场信号（5分钟线）
"""
import numpy as np
from scipy import stats
from loguru import logger
from typing import List, Tuple


def calc_bollinger_bands(close: np.ndarray, period: int = 20, std_mult: float = 2.0):
    """计算BOLL带"""
    if len(close) < period:
        return None, None, None
    sma = np.mean(close[-period:])
    std = np.std(close[-period:])
    upper = sma + std_mult * std
    lower = sma - std_mult * std
    return upper, sma, lower


def calc_slope(values: np.ndarray) -> float:
    """线性回归斜率"""
    x = np.arange(len(values))
    slope, _, _, _, _ = stats.linregress(x, values)
    return slope


def check_trend_direction(hourly_close: np.ndarray, boll_period: int = 20, lookback: int = 5) -> Tuple[bool, float]:
    """
    判断小时线方向
    返回: (is_bullish, slope_value)
    用最近 lookback 根小时线的 BOLL 中轨值做线性回归
    """
    if len(hourly_close) < boll_period + lookback:
        return None, 0.0
    
    # 收集最近 lookback 根小时线的中轨值
    mids = []
    for i in range(lookback):
        end = len(hourly_close) - i
        start = end - boll_period
        segment = hourly_close[start:end]
        if len(segment) >= boll_period:
            mids.append(np.mean(segment))
    
    if len(mids) < 2:
        return None, 0.0
    
    slope = calc_slope(np.array(mids))
    return slope > 0, slope


class EntrySignalDetector:
    """
    入场信号检测器（逐币种）
    维护每个币种的5分钟K线缓存
    """

    def __init__(self, boll_period: int = 20, boll_std: float = 2.0):
        self.boll_period = boll_period
        self.boll_std = boll_std
        # K线缓存: {symbol: [kline, ...]}
        # kline: [timestamp, open, high, low, close, volume]
        self.klines: dict[str, list] = {}
        # 信号状态
        self.signal_state: dict[str, dict] = {}

    def add_kline(self, symbol: str, kline: list, is_closed: bool):
        """添加一根新K线"""
        if symbol not in self.klines:
            self.klines[symbol] = []
        
        # 如果是已完结的K线且和最后一根时间戳不同，追加
        if is_closed:
            if not self.klines[symbol] or self.klines[symbol][-1][0] != kline[0]:
                self.klines[symbol].append(kline)
                # 限制缓存大小
                if len(self.klines[symbol]) > 100:
                    self.klines[symbol] = self.klines[symbol][-100:]
                return True  # 有新K线
        return False  # 未产生新K线

    def check_long_signal(self, symbol: str, is_bullish: bool) -> Tuple[bool, str]:
        """
        检查做多信号
        返回: (has_signal, reason)
        """
        if not is_bullish:
            return False, "方向为空头"

        kl = self.klines.get(symbol, [])
        if len(kl) < self.boll_period + 3:
            return False, "K线不足"

        # 计算BOLL
        closes = np.array([k[4] for k in kl])
        lows = np.array([k[3] for k in kl])
        opens = np.array([k[1] for k in kl])
        
        upper, mid, lower = calc_bollinger_bands(closes, self.boll_period, self.boll_std)
        if lower is None:
            return False, "BOLL计算失败"

        # K1: 最低价 < BOLL下轨, 且为阴线
        k1_candidates = []
        for i in range(len(kl) - 1, -1, -1):
            # 只检查最近几根
            if len(kl) - i > 20:
                break
            
            k1_low = lows[i]
            k1_close = closes[i]
            k1_open = opens[i]
            
            if k1_low < lower and k1_close < k1_open:  # 跌破下轨 + 阴线
                # 需要后面至少还有3根K线
                if i + 3 < len(kl):
                    k2_close = closes[i + 1]
                    k2_open = opens[i + 1]
                    k3_close = closes[i + 2]
                    k3_open = opens[i + 2]
                    
                    # K2阳线
                    if k2_close <= k2_open:
                        continue
                    # K3阳线
                    if k3_close <= k3_open:
                        continue
                    
                    # 至少一根收盘价 > K1开盘价
                    if k2_close > k1_open or k3_close > k1_open:
                        # 取最新的符合条件的K1
                        k1_candidates.append({
                            "k1_index": i,
                            "k1_open": k1_open,
                            "k1_close": k1_close,
                            "entry_index": i + 3,  # K4开盘入场
                        })

        if not k1_candidates:
            return False, "未检测到信号"
        
        # 取最新的信号
        best = k1_candidates[-1]
        entry_index = best["entry_index"]
        
        self.signal_state[symbol] = {
            "type": "long",
            "k1_index": best["k1_index"],
            "entry_index": entry_index,
            "entry_price": opens[entry_index] if entry_index < len(opens) else closes[-1],
        }
        
        return True, "做多信号触发"

    def check_short_signal(self, symbol: str, is_bullish: bool) -> Tuple[bool, str]:
        """
        检查做空信号
        """
        if is_bullish:
            return False, "方向为多头"

        kl = self.klines.get(symbol, [])
        if len(kl) < self.boll_period + 3:
            return False, "K线不足"

        closes = np.array([k[4] for k in kl])
        highs = np.array([k[2] for k in kl])
        opens = np.array([k[1] for k in kl])
        
        upper, mid, lower = calc_bollinger_bands(closes, self.boll_period, self.boll_std)
        if upper is None:
            return False, "BOLL计算失败"

        k1_candidates = []
        for i in range(len(kl) - 1, -1, -1):
            if len(kl) - i > 20:
                break
            
            k1_high = highs[i]
            k1_close = closes[i]
            k1_open = opens[i]
            
            if k1_high > upper and k1_close > k1_open:  # 突破上轨 + 阳线
                if i + 3 < len(kl):
                    k2_close = closes[i + 1]
                    k2_open = opens[i + 1]
                    k3_close = closes[i + 2]
                    k3_open = opens[i + 2]
                    
                    # K2阴线
                    if k2_close >= k2_open:
                        continue
                    # K3阴线
                    if k3_close >= k3_open:
                        continue
                    
                    # 至少一根收盘价 < K1开盘价
                    if k2_close < k1_open or k3_close < k1_open:
                        k1_candidates.append({
                            "k1_index": i,
                            "k1_open": k1_open,
                            "k1_close": k1_close,
                            "entry_index": i + 3,
                        })

        if not k1_candidates:
            return False, "未检测到信号"
        
        best = k1_candidates[-1]
        entry_index = best["entry_index"]
        
        self.signal_state[symbol] = {
            "type": "short",
            "k1_index": best["k1_index"],
            "entry_index": entry_index,
            "entry_price": opens[entry_index] if entry_index < len(opens) else closes[-1],
        }
        
        return True, "做空信号触发"

    def get_signal_entry_price(self, symbol: str) -> float:
        """获取信号入场价格"""
        state = self.signal_state.get(symbol)
        return state["entry_price"] if state else None

    def clear_signal(self, symbol: str):
        """清除信号状态"""
        self.signal_state.pop(symbol, None)
