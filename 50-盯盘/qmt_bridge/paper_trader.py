# -*- coding: utf-8 -*-
"""
QMT 模拟交易引擎（独立于 xttrader）

在 QMT Bridge 内部维护一个模拟盘：
- 不需要 MiniQMT 交易连接
- 用内存+SQLite 记录持仓和委托
- 价格取自实时行情（QMT xtdata）
- 与真实模拟盘收益保持一致
"""
import json
import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
from pathlib import Path

logger = logging.getLogger("paper_trader")

_CST = timezone(timedelta(hours=8))

# 模拟盘数据文件（与桥接同目录）
_DATA_DIR = Path(__file__).parent
_POSITIONS_FILE = _DATA_DIR / "paper_positions.json"
_ORDERS_FILE = _DATA_DIR / "paper_orders.json"


def _now() -> str:
    return datetime.now(_CST).strftime("%Y-%m-%d %H:%M:%S")


class PaperTrader:
    """
    模拟交易引擎

    用法：
        trader = PaperTrader()
        trader.init(initial_cash=100000)

        # 买入
        result = trader.buy("300059.SZ", 21.50, 400, "buy1")

        # 卖出
        result = trader.sell("300059.SZ", 22.00, 400)

        # 查询
        positions = trader.get_positions()
        orders = trader.get_orders()
        asset = trader.get_asset()
    """

    def __init__(self):
        self._positions: Dict[str, dict] = {}   # code → position
        self._orders: List[dict] = []            # all orders
        self._cash: float = 0
        self._initial_cash: float = 0
        self._loaded = False

    def init(self, initial_cash: float = 100000):
        """初始化模拟盘（从文件恢复或新建）"""
        self._initial_cash = initial_cash
        self._cash = initial_cash

        # 尝试从文件恢复
        if _POSITIONS_FILE.exists():
            try:
                with open(_POSITIONS_FILE, "r") as f:
                    data = json.load(f)
                    self._positions = {p["code"]: p for p in data.get("positions", [])}
                    self._cash = data.get("cash", initial_cash)
                    self._initial_cash = data.get("initial_cash", initial_cash)
                logger.info(f"模拟盘恢复: {len(self._positions)} 持仓, 现金 {self._cash:.2f}")
            except Exception as e:
                logger.warning(f"模拟盘文件读取失败: {e}")

        if _ORDERS_FILE.exists():
            try:
                with open(_ORDERS_FILE, "r") as f:
                    self._orders = json.load(f)
            except Exception:
                self._orders = []

        self._loaded = True
        logger.info(f"模拟盘初始化完成, 初始资金 {initial_cash}")

    def _save(self):
        """持久化持仓"""
        try:
            with open(_POSITIONS_FILE, "w") as f:
                json.dump({
                    "positions": list(self._positions.values()),
                    "cash": self._cash,
                    "initial_cash": self._initial_cash,
                    "update_time": _now(),
                }, f, ensure_ascii=False, indent=2)
            with open(_ORDERS_FILE, "w") as f:
                json.dump(self._orders[-100:], f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"模拟盘持久化失败: {e}")

    def buy(self, code: str, price: float, volume: int, strategy: str = "", limit_up: float = 0.0) -> dict:
        """模拟买入（limit_up>0 时检查涨停约束）"""
        if volume <= 0 or price <= 0:
            return {"success": False, "error": "参数无效"}

        # 涨停检查（由调用方传入涨停价）
        if limit_up > 0 and price >= limit_up:
            return {"success": False, "error": f"涨停价 {limit_up:.2f}，无法买入"}

        cost = price * volume
        if cost > self._cash:
            return {"success": False, "error": f"现金不足: 需{cost:.2f} 仅{self._cash:.2f}"}

        # 更新持仓（记录买入日期用于 T+1 检查）
        today = datetime.now(_CST).strftime("%Y-%m-%d")
        order_id = f"B{int(time.time()*1000)}"
        if code in self._positions:
            pos = self._positions[code]
            total_cost = pos["cost"] * pos["volume"] + cost
            total_vol = pos["volume"] + volume
            pos["cost"] = round(total_cost / total_vol, 4)
            pos["volume"] = total_vol
            pos["available"] = total_vol
            # 保留最早的买入日期
            if "buy_date" not in pos or pos["buy_date"] > today:
                pos["buy_date"] = pos.get("buy_date", today)
        else:
            self._positions[code] = {
                "code": code,
                "volume": volume,
                "available": volume,
                "cost": price,
                "frozen": 0,
                "buy_date": today,
            }

        self._cash -= cost
        self._orders.append({
            "order_id": order_id,
            "code": code,
            "direction": "buy",
            "price": price,
            "volume": volume,
            "filled": volume,
            "status": "filled",
            "strategy": strategy,
            "time": _now(),
        })
        self._save()
        logger.info(f"模拟买入: {code} {volume}股 @ {price} 策略={strategy} 剩余现金={self._cash:.2f}")
        return {"success": True, "order_id": order_id, "msg": f"买入{code} {volume}股 @ {price}"}

    def sell(self, code: str, price: float, volume: int = 0, limit_down: float = 0.0) -> dict:
        """模拟卖出（volume=0 表示全仓卖）"""
        if code not in self._positions:
            return {"success": False, "error": f"未持仓 {code}"}

        # 跌停检查
        if limit_down > 0 and price <= limit_down:
            return {"success": False, "error": f"跌停价 {limit_down:.2f}，无法卖出"}

        # T+1 检查：当天买入不能当天卖出
        pos = self._positions[code]
        today = datetime.now(_CST).strftime("%Y-%m-%d")
        buy_date = pos.get("buy_date", "")
        if buy_date == today:
            return {"success": False, "error": f"T+1限制: 今日买入{code}，最早明天才能卖出"}

        sell_vol = volume if 0 < volume <= pos["volume"] else pos["volume"]

        revenue = price * sell_vol
        cost_part = pos["cost"] * sell_vol
        pnl = revenue - cost_part
        pnl_pct = (price / pos["cost"] - 1) * 100

        # 更新持仓
        pos["volume"] -= sell_vol
        if pos["volume"] <= 0:
            del self._positions[code]
        else:
            pos["available"] = pos["volume"]

        self._cash += revenue
        order_id = f"S{int(time.time()*1000)}"
        self._orders.append({
            "order_id": order_id,
            "code": code,
            "direction": "sell",
            "price": price,
            "volume": sell_vol,
            "filled": sell_vol,
            "status": "filled",
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "time": _now(),
        })
        self._save()
        logger.info(f"模拟卖出: {code} {sell_vol}股 @ {price} PnL={pnl:.2f}({pnl_pct:.1f}%) 现金={self._cash:.2f}")
        return {"success": True, "order_id": order_id, "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 2)}

    def get_positions(self) -> List[dict]:
        """获取当前持仓（含实时市值）"""
        # 尝试获取实时价格
        result = []
        for code, pos in self._positions.items():
            current_price = self._get_current_price(code)
            pnl = (current_price - pos["cost"]) * pos["volume"] if current_price else 0
            pnl_pct = (current_price / pos["cost"] - 1) * 100 if current_price and pos["cost"] else 0
            result.append({
                "code": code,
                "volume": pos["volume"],
                "available": pos["available"],
                "cost": round(pos["cost"], 4),
                "current": current_price,
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
                "market_value": round(current_price * pos["volume"], 2) if current_price else 0,
            })
        return result

    def get_orders(self) -> List[dict]:
        """获取委托记录"""
        return self._orders[-50:]

    def get_asset(self) -> dict:
        """获取账户资产"""
        positions = self.get_positions()
        market_value = sum(p.get("market_value", 0) for p in positions)
        total = self._cash + market_value
        pnl = total - self._initial_cash
        pnl_pct = (total / self._initial_cash - 1) * 100 if self._initial_cash else 0
        return {
            "cash": round(self._cash, 2),
            "market_value": round(market_value, 2),
            "total": round(total, 2),
            "initial_cash": round(self._initial_cash, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "position_count": len(positions),
        }

    @staticmethod
    def _get_current_price(code: str) -> float:
        """获取实时价格（从 QMT 行情）"""
        try:
            from xtquant.xtdata import get_full_tick
            qmt_code = code if "." in code else (f"{code}.SH" if code.startswith(("6","9")) else f"{code}.SZ")
            tick = get_full_tick([qmt_code])
            if qmt_code in tick:
                return tick[qmt_code].get("lastPrice", 0)
        except Exception:
            pass
        return 0

    def clear_all(self) -> dict:
        """清空所有持仓（以当前市价卖出）"""
        results = []
        codes = list(self._positions.keys())
        for code in codes:
            price = self._get_current_price(code)
            if price > 0:
                r = self.sell(code, price)
                results.append(r)
        return {"success": True, "count": len(results), "results": results}
