# -*- coding: utf-8 -*-
"""
实时盯盘信号监测模块

职责：
  1. 开机加载 DB 中的信号模板
  2. 获取实时行情，与信号模板阈值做比较
  3. 日线信号：直接比较当前价格 → 突破/跌破/失效
  4. 15分钟背驰段信号：K线完成时发请求给 chanlun_service
  5. 持仓风控信号：监测涨跌幅/止损/止盈
  6. 命中信号时 → 更新 DB 状态 + 输出通知

设计原则：
  - 不做任何缠论计算（由 chanlun_service 处理）
  - 只做数值比较 + 状态管理
  - 带买卖点标签传递
"""
import sys
import json
import logging
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Callable, Any

import requests
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "50-盯盘"))

from signal_templates import (
    BottomFractalSignal, TopFractalSignal,
    DivergenceZoneSignal, PositionRiskSignal,
    SignalStatus, DivergenceStatus, RiskLevel,
    BuySellLabel,
)
from state_store import StateStore
from realtime_fetcher import RealtimeFetcher
from chanlun_service import ChanlunService, AnalysisRequest

from notifier import Notifier

logger = logging.getLogger(__name__)

_CST = timezone(timedelta(hours=8))

# 信号类型 DB 名称
SIGNAL_TYPE_MAP = {
    "bottom_fractal": BottomFractalSignal,
    "top_fractal": TopFractalSignal,
    "divergence_zone": DivergenceZoneSignal,
    "position_risk": PositionRiskSignal,
}


class SignalMatchResult:
    """信号匹配结果"""

    def __init__(
        self,
        signal_id: int,
        stock_code: str,
        stock_name: str,
        signal_type: str,
        label: Optional[str],       # buy1/sell2/ 等买卖点标签
        action: str,                # buy / sell / alert / stop_loss / invalidated
        message: str,
        price: float,
    ):
        self.signal_id = signal_id
        self.stock_code = stock_code
        self.stock_name = stock_name
        self.signal_type = signal_type
        self.label = label
        self.action = action
        self.message = message
        self.price = price

    def to_dict(self) -> Dict:
        return {
            "signal_id": self.signal_id,
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "signal_type": self.signal_type,
            "label": self.label,
            "action": self.action,
            "message": self.message,
            "price": self.price,
        }

    def to_notification(self) -> Dict:
        """转为通知格式"""
        emoji_map = {
            "buy": "🟢",
            "sell": "🔴",
            "alert": "⚡",
            "stop_loss": "🚨",
            "invalidated": "❌",
        }
        emoji = emoji_map.get(self.action, "📌")

        # 带标签的通知标题
        label_str = f"[{self.label.upper()}] " if self.label else ""

        return {
            "code": self.stock_code,
            "name": self.stock_name,
            "type": f"signal_{self.action}",
            "level": "warning" if self.action in ("sell", "stop_loss") else "info",
            "title": f"{emoji} {label_str}{self.stock_name}({self.stock_code})",
            "message": self.message,
            "price": self.price,
        }


class SignalMonitor:
    """
    实时信号监测器

    用法：
        monitor = SignalMonitor(state_store, chanlun_service, on_signal=my_callback)
        monitor.load_signals()
        monitor.run()       # 阻塞主循环
        # 或在已有事件循环中调用 monitor.tick()
    """

    def __init__(
        self,
        state_store: StateStore,
        chanlun_service: Optional[ChanlunService] = None,
        notifier: Optional[Notifier] = None,
        on_signal: Optional[Callable] = None,
        tick_interval: float = 5.0,       # 主循环间隔（秒）
        divergence_check_interval: float = 60.0,  # 背驰段检查间隔
        fetcher: Optional[Any] = None,    # 行情源（默认 RealtimeFetcher）
    ):
        self.state_store = state_store
        self.chanlun_service = chanlun_service
        self.notifier = notifier
        self.on_signal = on_signal
        self.tick_interval = tick_interval
        self.divergence_check_interval = divergence_check_interval
        self._running = False

        # 自动交易参数
        self._auto_trade_enabled = auto_trade_enabled
        self._qmt_host = qmt_host
        self._auto_trade_config = auto_trade_config or {}
        self._auto_traded_codes: set = set()  # 已自动买入的股票代码（防重复买入）

        # 缓存的信号模板（加载后全量缓存在内存）
        self._signals: Dict[str, List[Dict]] = {}  # signal_type → [signal_dicts]
        self._position_codes: set = set()          # 持仓代码集合

        # 背驰段检查计时
        self._last_divergence_check: Dict[str, float] = {}

        # 实时数据抓取（优先使用外部传入的 fetcher，否则用默认）
        if fetcher is not None:
            self._fetcher = fetcher
        else:
            from realtime_fetcher import RealtimeFetcher
            self._fetcher = RealtimeFetcher()

    # ============================================================
    # 信号加载
    # ============================================================

    def load_signals(self):
        """从 DB 加载所有 PENDING 信号"""
        self._signals = {}
        for sig_type in SIGNAL_TYPE_MAP:
            records = self.state_store.load_signal_templates(
                signal_type=sig_type, status="pending"
            )
            self._signals[sig_type] = records
            logger.info(f"加载 {sig_type}: {len(records)} 条")

        # 加载持仓代码（从 PositionRiskSignal 中提取）
        pos_records = self.state_store.load_signal_templates(
            signal_type="position_risk"
        )
        self._position_codes = {r["stock_code"] for r in pos_records}
        logger.info(f"持仓: {len(self._position_codes)} 只")

    def reload_signals(self):
        """重新加载信号（每日盘前调用）"""
        self.load_signals()
        self._last_divergence_check = {}

    # ============================================================
    # 主循环
    # ============================================================

    def run(self):
        """主循环（阻塞）"""
        self._running = True
        logger.info(f"信号监测启动，tick={self.tick_interval}s")

        while self._running:
            try:
                self.tick()
            except Exception as e:
                logger.exception(f"tick 异常: {e}")
            time.sleep(self.tick_interval)

        logger.info("信号监测停止")

    def stop(self):
        """停止主循环"""
        self._running = False

    def tick(self):
        """
        单次扫描（供外部事件循环调用）

        如果 run() 阻塞模式不适合，外部可在自己的循环中调用 tick()
        """
        if not self._signals:
            return

        # 1. 获取实时行情（所有信号涉及的股票）
        codes = self._get_all_codes()
        if not codes:
            return

        quotes = self._fetch_real_time(codes)

        # 2. 逐类处理信号
        results = []

        # 日线底分型信号
        for rec in self._signals.get("bottom_fractal", []):
            result = self._check_bottom_fractal(rec, quotes)
            if result:
                results.append(result)

        # 日线顶分型信号
        for rec in self._signals.get("top_fractal", []):
            result = self._check_top_fractal(rec, quotes)
            if result:
                results.append(result)

        # 持仓风控信号
        for rec in self._signals.get("position_risk", []):
            result = self._check_position_risk(rec, quotes)
            if result:
                results.append(result)

        # 3. 处理背驰段（定时检查）
        self._check_divergence_zone_signals()

        # 4. 输出结果
        for result in results:
            self._emit_result(result)

    # ============================================================
    # 信号检查逻辑
    # ============================================================

    def _check_bottom_fractal(self, rec: Dict, quotes: Dict) -> Optional[SignalMatchResult]:
        """
        检查底分型信号

        完全分类：
          - 当前价 >= third_high  → 买入确认 (activated)
          - 当前价 <= stop_loss  → 分型失效 (invalidated)
          - 在中间               → 继续观察 (pending)
        """
        code = rec["stock_code"]
        quote = quotes.get(code)
        if not quote:
            return None

        price = quote.get("price", 0)
        data = rec["data"]
        third_high = data.get("third_high", 0)
        stop_loss = data.get("stop_loss", 0)
        label = data.get("buy_label", "")

        if price <= 0:
            return None

        if price >= third_high:
            # 突破 → 买入信号
            self.state_store.update_signal_status(rec["id"], "activated", {
                "triggered_at": datetime.now(_CST).strftime("%Y-%m-%d %H:%M:%S"),
                "triggered_price": price,
            })
            # 从缓存中移除
            self._remove_signal_from_cache("bottom_fractal", rec["id"])

            return SignalMatchResult(
                signal_id=rec["id"],
                stock_code=code,
                stock_name=data.get("stock_name", code),
                signal_type="bottom_fractal",
                label=label,
                action="buy",
                message=f"底分型{label}突破！当前价 {price:.2f} ≥ third_high {third_high:.2f}",
                price=price,
            )

        elif price <= stop_loss:
            # 跌破 → 分型失效
            self.state_store.update_signal_status(rec["id"], "invalidated", {
                "triggered_at": datetime.now(_CST).strftime("%Y-%m-%d %H:%M:%S"),
                "triggered_price": price,
            })
            self._remove_signal_from_cache("bottom_fractal", rec["id"])

            return SignalMatchResult(
                signal_id=rec["id"],
                stock_code=code,
                stock_name=data.get("stock_name", code),
                signal_type="bottom_fractal",
                label=label,
                action="invalidated",
                message=f"底分型{label}失效，跌破止损 {price:.2f} ≤ {stop_loss:.2f}",
                price=price,
            )

        return None  # 继续观察

    def _check_top_fractal(self, rec: Dict, quotes: Dict) -> Optional[SignalMatchResult]:
        """
        检查顶分型信号

        完全分类：
          - 当前价 <= third_low  → 卖出确认 (activated)
          - 当前价 >= stop_loss  → 分型失效 (invalidated)
          - 在中间               → 继续观察 (pending)
        """
        code = rec["stock_code"]
        quote = quotes.get(code)
        if not quote:
            return None

        price = quote.get("price", 0)
        data = rec["data"]
        third_low = data.get("third_low", 0)
        stop_loss = data.get("stop_loss", 0)
        label = data.get("sell_label", "")

        if price <= 0:
            return None

        if price <= third_low:
            self.state_store.update_signal_status(rec["id"], "activated", {
                "triggered_at": datetime.now(_CST).strftime("%Y-%m-%d %H:%M:%S"),
                "triggered_price": price,
            })
            self._remove_signal_from_cache("top_fractal", rec["id"])

            return SignalMatchResult(
                signal_id=rec["id"],
                stock_code=code,
                stock_name=data.get("stock_name", code),
                signal_type="top_fractal",
                label=label,
                action="sell",
                message=f"顶分型{label}确认！当前价 {price:.2f} ≤ third_low {third_low:.2f}",
                price=price,
            )

        elif price >= stop_loss:
            self.state_store.update_signal_status(rec["id"], "invalidated", {
                "triggered_at": datetime.now(_CST).strftime("%Y-%m-%d %H:%M:%S"),
                "triggered_price": price,
            })
            self._remove_signal_from_cache("top_fractal", rec["id"])

            return SignalMatchResult(
                signal_id=rec["id"],
                stock_code=code,
                stock_name=data.get("stock_name", code),
                signal_type="top_fractal",
                label=label,
                action="invalidated",
                message=f"顶分型{label}失效，涨破止损 {price:.2f} ≥ {stop_loss:.2f}",
                price=price,
            )

        return None  # 继续观察

    def _check_position_risk(self, rec: Dict, quotes: Dict) -> Optional[SignalMatchResult]:
        """
        检查持仓风控信号

        完全分类：
          - 价格 <= stop_loss_price  → 止损 (stop_loss)
          - 价格 >= profit_30pct     → 减仓 (take_profit)
          - 涨跌幅 > 3%             → 报警 (alert)
          - 正常                   → 继续观察
        """
        code = rec["stock_code"]
        quote = quotes.get(code)
        if not quote:
            return None

        price = quote.get("price", 0)
        data = rec["data"]
        cost = data.get("cost_price", 0)
        stop_loss = data.get("stop_loss_price")
        profit_30 = data.get("profit_30pct_price")
        alert_up = data.get("alert_3pct_up")
        alert_down = data.get("alert_3pct_down")

        if price <= 0 or cost <= 0:
            return None

        profit_pct = (price - cost) / cost * 100

        # 止损
        if stop_loss and price <= stop_loss:
            self.state_store.update_signal_status(rec["id"], "activated", {
                "triggered_at": datetime.now(_CST).strftime("%Y-%m-%d %H:%M:%S"),
                "triggered_price": price,
            })
            return SignalMatchResult(
                signal_id=rec["id"], stock_code=code,
                stock_name=data.get("stock_name", code),
                signal_type="position_risk", label=None,
                action="stop_loss",
                message=f"🚨 止损！{data.get('stock_name', code)} 现价 {price:.2f}，跌破止损 {stop_loss:.2f}，盈亏 {profit_pct:.1f}%",
                price=price,
            )

        # 浮盈30%减仓
        if profit_30 and price >= profit_30:
            self.state_store.update_signal_status(rec["id"], "activated", {
                "triggered_at": datetime.now(_CST).strftime("%Y-%m-%d %H:%M:%S"),
                "triggered_price": price,
            })
            self._remove_signal_from_cache("position_risk", rec["id"])
            return SignalMatchResult(
                signal_id=rec["id"], stock_code=code,
                stock_name=data.get("stock_name", code),
                signal_type="position_risk", label=None,
                action="take_profit",
                message=f"💰 浮盈{profit_pct:.1f}%！{data.get('stock_name', code)} 现价 {price:.2f}，考虑减仓",
                price=price,
            )

        # ±3%波动报警（不改变信号状态，仅通知）
        if alert_up and price >= alert_up:
            return SignalMatchResult(
                signal_id=rec["id"], stock_code=code,
                stock_name=data.get("stock_name", code),
                signal_type="position_risk", label=None,
                action="alert",
                message=f"⚡ {data.get('stock_name', code)} 上涨 {profit_pct:.1f}%，现价 {price:.2f}",
                price=price,
            )

        if alert_down and price <= alert_down:
            return SignalMatchResult(
                signal_id=rec["id"], stock_code=code,
                stock_name=data.get("stock_name", code),
                signal_type="position_risk", label=None,
                action="alert",
                message=f"⚡ {data.get('stock_name', code)} 下跌 {profit_pct:.1f}%，现价 {price:.2f}",
                price=price,
            )

        return None

    # ============================================================
    # 背驰段检查
    # ============================================================

    def _check_divergence_zone_signals(self):
        """定时检查背驰段信号"""
        if not self.chanlun_service:
            return

        now = time.time()
        div_signals = self._signals.get("divergence_zone", [])

        for rec in div_signals:
            code = rec["stock_code"]
            data = rec["data"]
            last_check = self._last_divergence_check.get(code, 0)

            # 检查间隔控制
            if now - last_check < self.divergence_check_interval:
                continue

            self._last_divergence_check[code] = now

            # 发请求给缠论服务
            req = AnalysisRequest(
                request_type="check_divergence_zone",
                stock_code=code,
                stock_name=data.get("stock_name", code),
            )
            self.chanlun_service.request_queue.put(req)

    # ============================================================
    # 工具方法
    # ============================================================

    def _get_all_codes(self) -> List[str]:
        """获取所有信号涉及的股票代码"""
        codes = set()
        for sig_type, records in self._signals.items():
            for rec in records:
                codes.add(rec["stock_code"])
        return list(codes)

    def _fetch_real_time(self, codes: List[str]) -> Dict[str, Dict]:
        """获取实时行情，并统一返回的 code 为裸代码格式"""
        try:
            raw = self._fetcher.fetch_batch(codes)
        except Exception as e:
            logger.warning(f"获取实时行情失败: {e}")
            return {}

        # 统一 key 为裸代码（去除 .SH/.SZ 后缀）
        normalized = {}
        for code, data in raw.items():
            bare_code = code.replace(".SH", "").replace(".SZ", "")
            normalized[bare_code] = data
        return normalized

    def _remove_signal_from_cache(self, sig_type: str, signal_id: int):
        """从缓存中移除已处理的信号"""
        if sig_type in self._signals:
            self._signals[sig_type] = [
                r for r in self._signals[sig_type] if r["id"] != signal_id
            ]

    def _emit_result(self, result: SignalMatchResult):
        """输出信号结果"""
        notification = result.to_notification()

        # 回调
        if self.on_signal:
            try:
                self.on_signal(result)
            except Exception as e:
                logger.error(f"信号回调异常: {e}")

        # 通知
        if self.notifier:
            try:
                self.notifier.send(notification)
            except Exception as e:
                logger.error(f"发送通知异常: {e}")

        # 自动交易
        if self._auto_trade_enabled:
            try:
                self._try_auto_buy(result)
            except Exception as e:
                logger.error(f"自动交易异常: {e}")

        # 日志
        logger.info(f"[信号] {notification.get('title', '')}: {result.message}")

    # ============================================================
    # 自动交易（模拟盘）
    # ============================================================

    def _try_auto_buy(self, result: SignalMatchResult):
        """
        信号触发时自动买入模拟盘。
        只对底分型突破信号（bottom_fractal）触发买入。
        """
        # 只对买入信号操作
        if result.action not in ("buy",):
            return
        if result.signal_type not in ("bottom_fractal",):
            return

        code = result.stock_code

        # 防重复买入（同一只股票一天内只买一次）
        if code in self._auto_traded_codes:
            return

        # 获取配置
        cfg = self._auto_trade_config
        allowed = cfg.get("allowed_signals", ["bottom_fractal"])
        if result.signal_type not in allowed:
            return

        # 计算买入数量和价格
        current_price = result.price
        if current_price <= 0:
            logger.warning(f"自动买入跳过: {code} 当前价无效 {current_price}")
            return

        strategy = cfg.get("strategy", "fixed_amount")
        amount = cfg.get("amount_per_trade", 10000)
        max_amount = cfg.get("max_single_amount", 50000)
        price_deviation = cfg.get("price_deviation", 3.0)

        # 获取信号模板中的 third_high（突破确认价）
        matched_data = getattr(result, "matched_signal", None) or {}
        third_high = 0
        if isinstance(matched_data, dict):
            third_high = matched_data.get("data", {}).get("third_high", 0)

        # 当前价偏离 third_high 超过阈值 → 不追
        if third_high > 0:
            deviation = (current_price - third_high) / third_high * 100
            if deviation > price_deviation:
                logger.info(f"自动买入跳过: {code} 偏离{deviation:.1f}% > {price_deviation}%（不追高）")
                return

        # 计算买入量
        if strategy == "fixed_amount":
            buy_amount = min(amount, max_amount)
            volume = int(buy_amount / current_price / 100) * 100  # 整百股
        elif strategy == "fixed_volume":
            volume = cfg.get("volume", 100)
        else:
            volume = int(amount / current_price / 100) * 100

        if volume <= 0:
            logger.warning(f"自动买入跳过: {code} 计算股数为0")
            return

        # 发请求到 QMT Bridge
        qmt_host = self._qmt_host
        if not qmt_host:
            logger.warning("自动买入跳过: QMT host 未配置")
            return

        try:
            resp = requests.post(
                f"{qmt_host}/api/trade/buy",
                json={
                    "code": code,
                    "price": round(current_price, 2),
                    "volume": volume,
                    "strategy": result.label or "auto",
                },
                timeout=5,
            )
            result_data = resp.json()
            if result_data.get("success"):
                self._auto_traded_codes.add(code)
                logger.info(f"✅ 自动买入成功: {code} {volume}股 @ {current_price}")
            else:
                logger.warning(f"❌ 自动买入失败: {code} → {result_data.get('error', '未知')}")
        except requests.exceptions.ConnectionError:
            logger.error(f"自动买入失败: 无法连接 QMT Bridge ({qmt_host})")
        except Exception as e:
            logger.error(f"自动买入异常: {e}")

    def get_current_signals(self) -> Dict:
        """获取当前信号状态（供 dashboard 调用）"""
        result = {}
        for sig_type, records in self._signals.items():
            result[sig_type] = [
                {
                    "id": r["id"],
                    "code": r["stock_code"],
                    "type": sig_type,
                    "data": r["data"],
                }
                for r in records
            ]
        return result
