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

# 实时缠论检测
sys.path.insert(0, str(PROJECT_ROOT / "10-策略" / "缠论Agent"))
try:
    from chanlun_core import ChanlunCore, FractalType, Direction
    _HAS_CHANLUN_CORE = True
except ImportError:
    _HAS_CHANLUN_CORE = False
    ChanlunCore = None

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
        tick_interval: float = 5.0,
        divergence_check_interval: float = 60.0,
        fetcher: Optional[Any] = None,
        auto_trade_enabled: bool = False,
        qmt_host: Optional[str] = None,
        auto_trade_config: Optional[Dict] = None,
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
        self._auto_traded_codes: set = set()
        self._auto_trade_enabled = auto_trade_enabled
        self._qmt_host = qmt_host
        self._auto_trade_config = auto_trade_config or {}
        self._auto_traded_codes: set = set()  # 已自动买入的股票代码（防重复买入）

        # 实时底分型检测（盘中不依赖模板）
        self._enable_realtime_detection = True
        self._realtime_scan_counter = 0  # 调试计数
        self._realtime_last_check: Dict[str, float] = {}  # code → last_check_time
        self._realtime_checked_codes: set = set()         # 已检测过的新信号（防重复）
        self._realtime_detected_signals: Dict[str, dict] = {}  # 实时发现的信号模板
        logger.info(f"实时底分型检测: {'已启用' if self._enable_realtime_detection else '未启用'} (ChanlunCore={'可用' if _HAS_CHANLUN_CORE else '不可用'})")

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
        """
        # 实时检测：不依赖模板，盘中直接发现新底分型突破
        if self._enable_realtime_detection and _HAS_CHANLUN_CORE:
            try:
                self._scan_realtime_signals()
            except Exception as e:
                logger.error(f"实时检测异常: {e}")

        # 没有模板信号就不走了（模板检测走下面）
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
                message=f"{code} 底分型{label}突破！当前价 {price:.2f} ≥ third_high {third_high:.2f}",
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
                message=f"{code} 底分型{label}失效，跌破止损 {price:.2f} ≤ {stop_loss:.2f}",
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
                message=f"{code} 顶分型{label}确认！当前价 {price:.2f} ≤ third_low {third_low:.2f}",
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
                message=f"{code} 顶分型{label}失效，涨破止损 {price:.2f} ≥ {stop_loss:.2f}",
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

        # 止损 → 重复通知（5分钟间隔）直到用户点"已收到"
        if stop_loss and price <= stop_loss:
            # 查DB看用户是否已确认
            db_records = self.state_store.load_signal_templates(signal_type="position_risk", stock_code=code)
            for r in db_records:
                if r["id"] == rec["id"] and r["status"] in ("acknowledged", "completed"):
                    self._remove_signal_from_cache("position_risk", rec["id"])
                    return None

            # 去重：5分钟内不重复发
            if self.state_store.was_alerted(code, "stop_loss", 300):
                return None

            self.state_store.update_signal_status(rec["id"], "activated", {
                "triggered_at": datetime.now(_CST).strftime("%Y-%m-%d %H:%M:%S"),
                "triggered_price": price,
            })
            self.state_store.record_alert(code, "stop_loss", f"止损{stop_loss}", price)
            return SignalMatchResult(
                signal_id=rec["id"], stock_code=code,
                stock_name=data.get("stock_name", code),
                signal_type="position_risk", label=None,
                action="stop_loss",
                message=f"🚨 止损！{code} {data.get('stock_name', code)} 现价 {price:.2f}，跌破止损 {stop_loss:.2f}，盈亏 {profit_pct:.1f}%\n\n该信号将每5分钟重复提醒。\n确认已收到，请回复: 确认 {rec['id']}",
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
                message=f"💰 浮盈{profit_pct:.1f}%！{code} {data.get('stock_name', code)} 现价 {price:.2f}，考虑减仓",
                price=price,
            )

        # ±3%波动报警（去重，5分钟内不重复发）
        alert_code = f"alert_{code}"
        if alert_up and price >= alert_up:
            if not self.state_store.was_alerted(code, "alert_up", 300):
                self.state_store.record_alert(code, "alert_up", f"上涨{alert_up}", price)
                return SignalMatchResult(
                    signal_id=rec["id"], stock_code=code,
                    stock_name=data.get("stock_name", code),
                    signal_type="position_risk", label=None,
                    action="alert",
                    message=f"⚡ {code} {data.get('stock_name', code)} 上涨 {profit_pct:.1f}%，现价 {price:.2f}",
                    price=price,
                )

        if alert_down and price <= alert_down:
            if not self.state_store.was_alerted(code, "alert_down", 300):
                self.state_store.record_alert(code, "alert_down", f"下跌{alert_down}", price)
                return SignalMatchResult(
                    signal_id=rec["id"], stock_code=code,
                    stock_name=data.get("stock_name", code),
                    signal_type="position_risk", label=None,
                    action="alert",
                    message=f"⚡ {code} {data.get('stock_name', code)} 下跌 {profit_pct:.1f}%，现价 {price:.2f}",
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

    _FULL_MARKET_CACHE: List[str] = []  # 全市场代码缓存（启动时加载一次）

    @classmethod
    def _get_market_codes(cls) -> List[str]:
        """从 QMT 获取全市场 A 股实际列表（已剔除科创板），缓存到类变量"""
        if cls._FULL_MARKET_CACHE:
            return cls._FULL_MARKET_CACHE
        codes = []
        try:
            import urllib.request as _ureq
            import json as _json
            resp = _ureq.urlopen("http://172.31.144.1:8890/api/stocks/list", timeout=15)
            data = _json.loads(resp.read())
            raw = data.get("stocks", [])
            # 再次过滤确保无科创板
            codes = [c for c in raw if not c.startswith("688")]
            logger.info(f"全市场A股: QMT返回{data.get('count',0)}只, 实际取{len(codes)}只")
        except Exception as e:
            logger.warning(f"从QMT获取股票列表失败: {e}")
        if not codes:
            # 备用号段（实际用到的概率极低）
            for prefix in ['600', '601', '603', '605']:
                for suffix in range(1, 1000):
                    codes.append(f'{prefix}{suffix:03d}.SH')
            for prefix in ['000', '001', '002']:
                for suffix in range(1, 1000):
                    codes.append(f'{prefix}{suffix:03d}.SZ')
            for prefix in ['300', '301']:
                for suffix in range(1, 1000):
                    codes.append(f'{prefix}{suffix:03d}.SZ')
            logger.warning(f"全市场代码: 回退号段 {len(codes)} 只")
        cls._FULL_MARKET_CACHE = codes
        return codes

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
                if result.action in ("buy",):
                    self._try_auto_buy(result)
                elif result.action in ("sell", "stop_loss"):
                    self._try_auto_sell(result)
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

        # 计算买入量（至少1手=100股）
        if strategy == "fixed_amount":
            buy_amount = min(amount, max_amount)
            raw_volume = int(buy_amount / current_price / 100) * 100
        elif strategy == "fixed_volume":
            raw_volume = cfg.get("volume", 100)
        else:
            raw_volume = int(amount / current_price / 100) * 100

        volume = max(raw_volume, 100)  # 至少1手
        if volume * current_price > max_amount:
            volume = int(max_amount / current_price / 100) * 100

        if volume <= 0:
            logger.warning(f"自动买入跳过: {code} 计算股数为0")
            return

        # 发请求到 QMT Bridge
        qmt_host = self._qmt_host
        if not qmt_host:
            logger.warning("自动买入跳过: QMT host 未配置")
            return

        # 取止损位（从实时检测的信号数据中取）
        sl = 0.0
        try:
            sigs = self._signals.get("bottom_fractal", [])
            for s in sigs:
                if s["stock_code"] == code:
                    sl = s.get("data", {}).get("stop_loss", 0)
                    break
        except Exception:
            pass

        try:
            resp = requests.post(
                f"{qmt_host}/api/trade/buy",
                json={
                    "code": code,
                    "price": round(current_price, 2),
                    "volume": volume,
                    "strategy": result.label or "auto",
                    "stop_loss": round(sl, 2) if sl > 0 else 0,
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

    # ============================================================
    # 自动卖出（止损/止盈/顶分型信号）
    # ============================================================

    def _try_auto_sell(self, result: SignalMatchResult):
        """信号触发时自动卖出模拟盘"""
        code = result.stock_code
        price = result.price
        if price <= 0:
            logger.warning(f"自动卖出跳过: {code} 当前价无效 {price}")
            return

        # 获取配置中的止盈规则
        cfg = self._auto_trade_config
        strategy_cfg = None
        try:
            sys.path.insert(0, str(PROJECT_ROOT / "10-策略" / "缠论Agent"))
            from strategy_config import TAKEPROFIT_PCT
            strategy_cfg = {"takeprofit_pct": TAKEPROFIT_PCT}
        except Exception:
            strategy_cfg = {"takeprofit_pct": 0.3}

        # 发送卖出请求
        qmt_host = self._qmt_host
        if not qmt_host:
            logger.warning("自动卖出跳过: QMT host 未配置")
            return

        try:
            # 先查持仓确定可卖数量
            resp = requests.get(f"{qmt_host}/api/trade/positions", timeout=5)
            pos_data = resp.json()
            positions = pos_data.get("positions", []) if pos_data.get("success") else []

            pos = None
            for p in positions:
                p_code = p.get("code", "").replace(".SH", "").replace(".SZ", "")
                if p_code == code:
                    pos = p
                    break

            if not pos:
                logger.info(f"自动卖出跳过: {code} 无持仓")
                return

            total_vol = pos.get("volume", 0)
            available = pos.get("available", 0)
            cost = pos.get("cost", 0)

            if total_vol <= 0:
                return

            # 决定卖出数量
            if result.action == "stop_loss":
                # 止损：全仓卖出
                sell_vol = total_vol
                reason = "止损"
            elif result.label and "sell" in result.label:
                # 一卖/二卖信号：全仓卖出
                sell_vol = total_vol
                reason = f"{result.label}信号"
            elif result.action == "sell":
                # 其他卖出信号（如顶分型跌破）：全仓卖出
                sell_vol = total_vol
                reason = "顶分型跌破"
            else:
                # 默认不做操作
                return

            if sell_vol <= 0:
                logger.warning(f"自动卖出跳过: {code} 可卖数量为0")
                return

            # 调用卖出接口
            resp = requests.post(
                f"{qmt_host}/api/trade/sell",
                json={"code": code, "price": round(price, 2), "volume": sell_vol},
                timeout=5,
            )
            result_data = resp.json()
            if result_data.get("success"):
                logger.info(f"✅ 自动卖出成功: {code} {sell_vol}股 @ {price} ({reason})")
            else:
                logger.warning(f"❌ 自动卖出失败: {code} → {result_data.get('error', '未知')}")
        except requests.exceptions.ConnectionError:
            logger.error(f"自动卖出失败: 无法连接 QMT Bridge ({qmt_host})")
        except Exception as e:
            logger.error(f"自动卖出异常: {e}")

    # ============================================================
    # 实时底分型检测（盘中直接发现新买点）
    # ============================================================

    def _scan_realtime_signals(self):
        """
        盘中扫描所有监控股票，实时检测新形成的底分型。

        不依赖 static_analyzer 盘后生成的信号模板，
        对涨幅 > 2% 的股票运行 ChanlunCore 分析，
        发现新底分型突破 → 直接生成信号并触发自动买入。
        """
        import urllib.request as _ureq
        import json as _json

        # 全市场扫描（剔除科创板），不从自选股列表读取
        codes = self._get_market_codes()
        # 补充持仓（确保持仓股总在监控中，即使退市风险等极端情况）
        pos_codes = list(self._position_codes)
        for c in pos_codes:
            if c not in codes:
                codes.append(c)
        if not codes:
            return

        # 获取实时行情
        quotes = self._fetch_real_time(codes)
        now = time.time()

        # 第一步：筛选异动股（涨幅>2% + 未在冷却期）
        hot_stocks = []
        for code, quote in quotes.items():
            change_pct = abs(quote.get("change_pct", 0))
            price = quote.get("price", 0)

            if change_pct < 2.0:
                continue
            last_check = self._realtime_last_check.get(code, 0)
            if now - last_check < 300:
                continue
            if code in self._realtime_checked_codes:
                continue
            hot_stocks.append((code, quote, price))

        if not hot_stocks:
            self._realtime_scan_counter += 1
            if self._realtime_scan_counter <= 3 or self._realtime_scan_counter % 10 == 0:
                logger.info(f"[实时检测] 第{self._realtime_scan_counter}轮 扫描{len(codes)}只 异动0只 已发现{len(self._realtime_checked_codes)}个信号")
            return

        # 每 tick 最多处理 50 只，防止首轮全量扫描卡死
        # 未处理的会在后续 tick 中继续（5分钟冷却期内会逐一覆盖）
        MAX_PER_TICK = 50
        if len(hot_stocks) > MAX_PER_TICK:
            logger.debug(f"[实时检测] 异动股 {len(hot_stocks)} 只, 本轮仅处理前 {MAX_PER_TICK} 只")
            hot_stocks = hot_stocks[:MAX_PER_TICK]

        # 第二步：并发拉取K线数据（从 QMT 桥接）
        def _fetch_kline(code):
            qmt_code = code if '.' in code else (f"{code}.SH" if code.startswith(('6','9')) else f"{code}.SZ")
            url = f"http://172.31.144.1:8890/api/kline?code={qmt_code}&period=1d&count=90"
            try:
                resp = _ureq.urlopen(url, timeout=10)
                result = _json.loads(resp.read())
                data = result.get('data', [])
                if len(data) < 10:
                    return None
                return (code, data)
            except Exception:
                return None

        import concurrent.futures as _cf
        kline_results = {}
        with _cf.ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(_fetch_kline, code): code for code, _, _ in hot_stocks}
            for future in _cf.as_completed(futures):
                result = future.result()
                if result:
                    code, data = result
                    kline_results[code] = data
                    self._realtime_last_check[code] = now

        # 第三步：逐个分析有K线数据的异动股
        for code, quote, price in hot_stocks:
            if code not in kline_results:
                continue
            data = kline_results[code]

            df = pd.DataFrame(data)
            for col in ['open', 'close', 'high', 'low']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            df['day'] = pd.to_datetime(df['time'], format='%Y%m%d')
            df.index = df['day']

            # 运行缠论
            core = ChanlunCore()
            state = core.analyze(df, level='daily')

            # 查找新的底分型突破（只认昨天及之前完成的，排除当天未收盘的）
            today_str = datetime.now(_CST).strftime("%Y-%m-%d")
            bottoms = [
                f for f in core.fractals
                if f.type == FractalType.BOTTOM and f.third_high > 0
                and not f.timestamp.startswith(today_str)  # 排除今天未收盘的分型
            ]
            if not bottoms:
                # 如果当天新形成了底分型，等明天收盘确认后再检测
                continue

            latest_bottom = bottoms[-1]

            # 检查自底分型形成之后，third_high 是否已被突破（避免追回调）
            th = latest_bottom.third_high
            already_broken = False
            bottom_date_str = latest_bottom.timestamp[:10]
            # 只检查底分型之后的完整K线
            post_bottom_df = df[df.index > bottom_date_str]
            if len(post_bottom_df) >= 1:
                for i in range(len(post_bottom_df)):
                    row = post_bottom_df.iloc[i]
                    # 跳过今天的K线（未收盘）
                    if str(row.name)[:10] == today_str:
                        continue
                    # 收盘价或最高价 >= third_high → 已突破过
                    if row['close'] >= th or row['high'] >= th:
                        already_broken = True
                        break

            # 检查当前价是否突破了 third_high（且之前未被突破）
            if not already_broken and price > th:
                name = quote.get("name", code)
                logger.info(f"【实时检测】{name}({code}) 底分型突破! "
                            f"third_high={th:.2f} 当前={price:.2f}")

                # 防重复
                self._realtime_checked_codes.add(code)

                # 查买卖点标签
                label = ""
                for p in reversed(core.buy_sell_points):
                    if p.type.value.startswith("buy"):
                        label = p.type.value
                        break

                # 生成一个临时信号结果
                fake_signal = {
                    "id": int(now * 1000),
                    "stock_code": code,
                    "signal_type": "bottom_fractal",
                    "data": {
                        "stock_code": code,
                        "stock_name": name,
                        "third_high": latest_bottom.third_high,
                        "fractal_price": latest_bottom.price,
                        "stop_loss": latest_bottom.third_low,
                        "current_price": price,
                        "buy_label": label or "realtime",
                        "status": "pending",
                        "source": "realtime_detection",
                    }
                }

                # 保存到实时信号缓存（假装是模板，供后续tick持续监测）
                if "bottom_fractal" not in self._signals:
                    self._signals["bottom_fractal"] = []
                # 检查是否已有此代码的信号
                existing = [r for r in self._signals["bottom_fractal"] if r["stock_code"] == code]
                if not existing:
                    self._signals["bottom_fractal"].append(fake_signal)
                    logger.info(f"实时信号已加入监测队列: {name}({code})")

                # 立即触发买入
                result = SignalMatchResult(
                    signal_id=fake_signal["id"],
                    stock_code=code,
                    stock_name=name,
                    signal_type="bottom_fractal",
                    label=label,
                    action="buy",
                    message=f"实时检测: {code} {name} 底分型突破 {latest_bottom.third_high:.2f}",
                    price=price,
                )
                self._emit_result(result)

        # 调试日志（每次扫描都输出，首轮多输出便于排查）
        self._realtime_scan_counter += 1
        if self._realtime_scan_counter <= 3 or self._realtime_scan_counter % 10 == 0:
            logger.info(f"[实时检测] 第{self._realtime_scan_counter}轮 扫描{len(codes)}只 异动{len(hot_stocks) if 'hot_stocks' in dir() else '?'}只 已发现{len(self._realtime_checked_codes)}个信号")

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
