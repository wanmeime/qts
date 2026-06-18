#!/usr/bin/env python3
"""
报警引擎
检测价格突破、涨跌幅、成交量异动等条件
"""
import logging
from typing import Dict, List, Tuple
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

_CST = timezone(timedelta(hours=8))


class AlertEngine:
    """报警引擎"""

    def __init__(self, config: dict):
        self.config = config.get("alerts", {})
        self.change_cfg = self.config.get("change_threshold", {})
        self.volume_cfg = self.config.get("volume_surge", {})
        self.market_cfg = self.config.get("market_crash", {})
        self.tech_cfg = self.config.get("technical", {})

    def check_all(self, stock_data: Dict[str, Dict], index_data: Dict[str, Dict]) -> List[Dict]:
        """
        检查所有报警条件。

        Args:
            stock_data: {code: {name, price, change_pct, volume, ...}}
            index_data: {code: {name, price, change_pct, ...}}

        Returns:
            报警列表 [{code, name, type, level, message, price, change_pct}]
        """
        alerts = []

        # 1. 大盘异动
        alerts.extend(self._check_market_alerts(index_data))

        # 2. 个股报警
        for code, data in stock_data.items():
            alerts.extend(self._check_stock_alerts(code, data))

        return alerts

    def _check_market_alerts(self, index_data: Dict[str, Dict]) -> List[Dict]:
        """检查大盘异动"""
        alerts = []
        if not self.market_cfg.get("enabled", True):
            return alerts

        crash_pct = self.market_cfg.get("crash_pct", -2.0)
        surge_pct = self.market_cfg.get("surge_pct", 2.0)

        for code, data in index_data.items():
            change = data.get("change_pct", 0)
            name = data.get("name", code)
            price = data.get("price", 0)

            if change <= crash_pct:
                alerts.append({
                    "code": code,
                    "name": name,
                    "type": "market_crash",
                    "level": "critical",
                    "message": f"⚠️ {name} 急跌 {change:.2f}%，现价 {price:.2f}",
                    "price": price,
                    "change_pct": change,
                })
            elif change >= surge_pct:
                alerts.append({
                    "code": code,
                    "name": name,
                    "type": "market_surge",
                    "level": "info",
                    "message": f"📈 {name} 大涨 {change:.2f}%，现价 {price:.2f}",
                    "price": price,
                    "change_pct": change,
                })

        return alerts

    def _check_stock_alerts(self, code: str, data: Dict) -> List[Dict]:
        """检查个股报警"""
        alerts = []
        name = data.get("name", code)
        price = data.get("price", 0)
        change_pct = data.get("change_pct", 0)
        volume = data.get("volume", 0)

        if not price:
            return alerts

        # 涨跌幅报警
        if self.change_cfg.get("enabled", True):
            big_drop = self.change_cfg.get("big_drop_pct", -3.0)
            big_rise = self.change_cfg.get("big_rise_pct", 5.0)
            limit_up = self.change_cfg.get("limit_up", True)

            if change_pct <= big_drop:
                alerts.append({
                    "code": code,
                    "name": name,
                    "type": "big_drop",
                    "level": "warning",
                    "message": f"🔴 {name}({code}) 跌幅 {change_pct:.2f}%，现价 {price:.2f}",
                    "price": price,
                    "change_pct": change_pct,
                })
            elif change_pct >= big_rise:
                alerts.append({
                    "code": code,
                    "name": name,
                    "type": "big_rise",
                    "level": "info",
                    "message": f"🟢 {name}({code}) 大涨 {change_pct:.2f}%，现价 {price:.2f}",
                    "price": price,
                    "change_pct": change_pct,
                })
            elif limit_up and change_pct >= 9.9:
                alerts.append({
                    "code": code,
                    "name": name,
                    "type": "limit_up",
                    "level": "info",
                    "message": f"🚀 {name}({code}) 涨停！现价 {price:.2f}",
                    "price": price,
                    "change_pct": change_pct,
                })

        # 成交量异动 (需要历史数据对比，这里简化处理)
        # 实际应比较当前量与过去N天平均量

        return alerts

    def format_alert_message(self, alerts: List[Dict], max_stocks: int = 10) -> str:
        """
        格式化报警消息。

        Args:
            alerts: 报警列表
            max_stocks: 最多显示股票数

        Returns:
            Markdown 格式消息
        """
        if not alerts:
            return ""

        now = datetime.now(_CST).strftime("%Y-%m-%d %H:%M:%S")

        # 分类
        market_alerts = [a for a in alerts if a["type"].startswith("market_")]
        stock_alerts = [a for a in alerts if not a["type"].startswith("market_")]

        lines = [f"## 📊 盯盘报警 ({now})", ""]

        # 大盘异动
        if market_alerts:
            lines.append("### 大盘异动")
            for a in market_alerts:
                lines.append(f"- {a['message']}")
            lines.append("")

        # 个股报警
        if stock_alerts:
            lines.append("### 个股报警")
            for a in stock_alerts[:max_stocks]:
                lines.append(f"- {a['message']}")
            if len(stock_alerts) > max_stocks:
                lines.append(f"- ... 还有 {len(stock_alerts) - max_stocks} 只")
            lines.append("")

        return "\n".join(lines)
