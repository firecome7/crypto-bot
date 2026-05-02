"""
每日复盘模块
- 读取当日交易日志
- 统计胜率、盈亏比
- 信号分类分析
- 生成 Markdown 报告
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from loguru import logger


class DailyAnalyzer:
    """每日复盘分析器"""

    def __init__(self, config: dict):
        self.log_path = Path(config["data"]["trade_log_path"])
        self.analysis_path = Path(config["data"]["analysis_path"])
        self.analysis_path.mkdir(parents=True, exist_ok=True)

    def load_trades(self, date_str: str = None) -> list:
        """加载指定日期的交易记录"""
        if date_str is None:
            date_str = datetime.now().strftime("%Y-%m-%d")
        
        filepath = self.log_path / f"trades_{date_str}.jsonl"
        if not filepath.exists():
            return []
        
        trades = []
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if line:
                    trades.append(json.loads(line))
        return trades

    def analyze(self, date_str: str = None) -> dict:
        """分析当日交易"""
        trades = self.load_trades(date_str)
        
        result = {
            "date": date_str or datetime.now().strftime("%Y-%m-%d"),
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "max_win": 0.0,
            "max_loss": 0.0,
            "long_short_stats": {"long": {"count": 0, "pnl": 0.0}, "short": {"count": 0, "pnl": 0.0}},
            "exit_reasons": {},
            "symbols": {},
        }

        if not trades:
            return result

        # 按pair配对开平仓
        open_trades = {}
        closed_trades = []

        for t in trades:
            if t["action"] == "open":
                key = t["symbol"]
                open_trades[key] = t
            elif t["action"] == "close":
                closed_trades.append(t)

        wins = []
        losses = []

        for t in closed_trades:
            pnl = t.get("pnl", 0)
            pnl_pct = t.get("pnl_pct", 0)
            result["total_trades"] += 1
            result["total_pnl"] += pnl

            if pnl > 0:
                wins.append(pnl)
                result["wins"] += 1
            else:
                losses.append(pnl)
                result["losses"] += 1

            # 方向统计
            side = t.get("side", "unknown")
            if side in result["long_short_stats"]:
                result["long_short_stats"][side]["count"] += 1
                result["long_short_stats"][side]["pnl"] += pnl

            # 退出原因
            reason = t.get("reason", "未知")
            if reason not in result["exit_reasons"]:
                result["exit_reasons"][reason] = {"count": 0, "pnl": 0.0}
            result["exit_reasons"][reason]["count"] += 1
            result["exit_reasons"][reason]["pnl"] += pnl

            # 币种统计
            sym = t.get("symbol", "unknown")
            if sym not in result["symbols"]:
                result["symbols"][sym] = {"count": 0, "pnl": 0.0}
            result["symbols"][sym]["count"] += 1
            result["symbols"][sym]["pnl"] += pnl

        if result["total_trades"] > 0:
            result["win_rate"] = round(result["wins"] / result["total_trades"] * 100, 1)

        if wins:
            result["avg_win"] = round(sum(wins) / len(wins), 2)
            result["max_win"] = round(max(wins), 2)
        if losses:
            result["avg_loss"] = round(sum(losses) / len(losses), 2)
            result["max_loss"] = round(min(losses), 2)

        result["total_pnl"] = round(result["total_pnl"], 2)

        return result

    def generate_report(self, analysis: dict) -> str:
        """生成Markdown分析报告"""
        date_str = analysis["date"]
        lines = []
        lines.append(f"# 交易复盘报告 — {date_str}")
        lines.append("")

        total = analysis["total_trades"]
        if total == 0:
            lines.append("**当日无交易**")
            lines.append("")
            return "\n".join(lines)

        # 概览
        lines.append("## 📊 今日概览")
        lines.append(f"- **总交易次数**: {total}")
        lines.append(f"- **盈利笔数**: {analysis['wins']} | **亏损笔数**: {analysis['losses']}")
        lines.append(f"- **胜率**: {analysis['win_rate']}%")
        lines.append(f"- **总盈亏**: `{analysis['total_pnl']:+.2f} USDT`")
        lines.append(f"- **平均盈利**: {analysis['avg_win']:+.2f} | **平均亏损**: {analysis['avg_loss']:+.2f}")
        lines.append(f"- **最大单笔盈利**: {analysis['max_win']:+.2f} | **最大单笔亏损**: {analysis['max_loss']:+.2f}")
        lines.append("")

        # 多空统计
        lines.append("## 📈 多空统计")
        for side, stats in analysis["long_short_stats"].items():
            label = "多头" if side == "long" else "空头"
            lines.append(f"- **{label}**: {stats['count']} 笔, 盈亏 {stats['pnl']:+.2f} USDT")
        lines.append("")

        # 退出原因分析
        lines.append("## 🚪 退出原因分析")
        for reason, stats in sorted(analysis["exit_reasons"].items(), key=lambda x: abs(x[1]["pnl"]), reverse=True):
            lines.append(f"- **{reason}**: {stats['count']} 笔, 盈亏 {stats['pnl']:+.2f} USDT")
        lines.append("")

        # 币种统计
        lines.append("## 🪙 币种盈亏排名")
        symbols_sorted = sorted(analysis["symbols"].items(), key=lambda x: x[1]["pnl"], reverse=True)
        for sym, stats in symbols_sorted:
            lines.append(f"- **{sym}**: {stats['count']} 笔, 盈亏 {stats['pnl']:+.2f} USDT")
        lines.append("")

        # 总结与建议
        lines.append("## 💡 总结建议")
        if analysis["win_rate"] >= 60:
            lines.append("✅ 胜率较高 (>60%)，策略表现稳定。")
        elif analysis["win_rate"] >= 45:
            lines.append("⚠️ 胜率中等，关注亏损笔数较高的信号。")
        else:
            lines.append("❌ 胜率偏低 (<45%)，建议检查信号参数或市场状态。")

        # 亏损信号分析
        loss_reasons = {r: s for r, s in analysis["exit_reasons"].items() if s["pnl"] < 0}
        if loss_reasons:
            worst = max(loss_reasons.items(), key=lambda x: abs(x[1]["pnl"]))
            lines.append(f"🔍 **主要亏损来源**: {worst[0]}（{-worst[1]['pnl']:.2f} USDT）")

        lines.append("")

        return "\n".join(lines)

    def save_report(self, report: str, date_str: str = None):
        """保存报告"""
        if date_str is None:
            date_str = datetime.now().strftime("%Y-%m-%d")
        filepath = self.analysis_path / f"report_{date_str}.md"
        with open(filepath, "w") as f:
            f.write(report)
        logger.info(f"复盘报告已保存: {filepath}")
