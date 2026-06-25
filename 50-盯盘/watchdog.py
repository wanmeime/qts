#!/usr/bin/env python3
"""
盯盘系统 - 交易联动版
=====================

与交易系统深度整合：
1. 读取持仓 → 监控持仓盈亏、成本线
2. 对自选股跑缠论分析 → 检测新买点/卖点
3. 结合持仓给出操作建议（加仓/减仓/止损）
4. 飞书实时推送

使用方法:
    python3 watchdog.py                    # 正常运行
    python3 watchdog.py --once             # 扫描一次后退出
    python3 watchdog.py --test             # 测试模式（忽略交易时段）
    python3 watchdog.py --stocks 600519,000858  # 只扫描指定股票
"""
import os
import sys
import json
import time
import signal
import argparse
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

# 添加策略模块路径
sys.path.insert(0, str(Path(__file__).parent.parent / "10-策略" / "自选股监控"))

from realtime_fetcher import RealtimeFetcher, QmtFetcher, is_trading_hours, get_market_status
from state_store import StateStore
from notifier import Notifier

# 信号监测模块
from signal_templates import SignalStatus, BuySellLabel
from signal_monitor import SignalMonitor

# 旧缠论分析模块（缠论分析.py/signal_generator.py）已于 2026-06-24 移除
# 实时分析请使用 static_analyzer.py + signal_monitor.py
HAS_CHANLUN = True  # chanlun_core 始终可用

# 多级别分析模块（旧分析路径，已废弃 — 由 signal_monitor 替代）
HAS_MULTI_LEVEL = False
ChanlunKnowledgeBase = None

try:
    import yaml
except ImportError:
    yaml = None

import pandas as pd
import requests as req_lib

_CST = timezone(timedelta(hours=8))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ============================================================
# 路径常量
# ============================================================
PROJECT_ROOT = Path(__file__).parent.parent
POSITION_FILE = PROJECT_ROOT / "40-执行" / "持仓" / "当前持仓.json"
WATCHLIST_FILE = PROJECT_ROOT / "00-研究" / "自选股" / "watchlist.json"
KLINE_CACHE_DIR = PROJECT_ROOT / "00-研究" / "数据源" / "缓存" / "kline_6m"


# ============================================================
# 配置加载
# ============================================================

def load_config(config_path: str = None) -> dict:
    path = Path(config_path) if config_path else current_dir / "config.yaml"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            if yaml:
                return yaml.safe_load(f) or {}
            return json.load(f)
    return _default_config()


def _default_config() -> dict:
    return {
        "schedule": {"interval_seconds": 60, "run_outside_hours": False},
        "data_source": {"primary": "eastmoney", "timeout": 10},
        "alert_rules": {
            "position_pnl_alert_pct": -5.0,
            "position_pnl_profit_pct": 10.0,
            "signal_min_score": 60,
            "signal_dedup_days": 5,
        },
        "notification": {
            "feishu": {"enabled": True, "chat_id": "oc_d2e8df3c676afa2c352d8ece0a9b6141"},
            "dedup_window_seconds": 300,
        },
        "storage": {"db_path": str(current_dir / "watchdog.db")},
        "signal_monitor": {
            "enabled": False,
            "tick_interval": 5.0,
            "divergence_check_interval": 60.0,
        },
    }


# ============================================================
# 数据加载
# ============================================================

def load_positions() -> List[Dict]:
    """加载当前持仓"""
    if not POSITION_FILE.exists():
        logger.warning(f"持仓文件不存在: {POSITION_FILE}")
        return []
    try:
        with open(POSITION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        positions = data.get("持仓明细", [])
        logger.info(f"加载持仓: {len(positions)} 只")
        return positions
    except Exception as e:
        logger.error(f"加载持仓失败: {e}")
        return []


def load_watchlist_codes() -> List[str]:
    """加载自选股代码列表"""
    if not WATCHLIST_FILE.exists():
        return []
    try:
        with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        codes = []
        for item in data:
            if isinstance(item, dict):
                code = item.get("code", "")
                market = item.get("market", "")
                # 跳过指数
                if code.startswith("399") or code.startswith("880"):
                    continue
                # 只保留A股
                if "A股" in market or "创业板" in market:
                    codes.append(code)
            elif isinstance(item, str):
                codes.append(item)
        logger.info(f"加载自选股: {len(codes)} 只")
        return codes
    except Exception as e:
        logger.error(f"加载自选股失败: {e}")
        return []


def fetch_kline(code: str, days: int = 120, scale: int = 240) -> pd.DataFrame:
    """
    获取K线数据（优先同花顺本地数据 → 缓存 → 新浪）
    
    Args:
        code: 股票代码
        days: 获取天数
        scale: K线周期（分钟），240=日线，15=15分钟
    """
    # 仅日线支持本地数据源
    if scale == 240:
        # 1. 优先同花顺本地数据
        ths_df = None
        try:
            from qmt_bridge.hexin_reader import get_hexin_kline, has_hexin_data
            if has_hexin_data(code):
                ths_df = get_hexin_kline(code, days=days + 60)
        except Exception:
            pass

        # 2. 缓存（仅当无同花顺数据时）
        csv_df = None
        if ths_df is None or len(ths_df) < 30:
            csv_path = KLINE_CACHE_DIR / f"{code}.csv"
            if csv_path.exists():
                try:
                    csv_df = pd.read_csv(csv_path)
                    if "day" in csv_df.columns and "date" not in csv_df.columns:
                        csv_df = csv_df.rename(columns={"day": "date"})
                    if len(csv_df) >= 30:
                        csv_df = csv_df.set_index("date")
                        csv_df.index = pd.to_datetime(csv_df.index)
                except Exception:
                    pass

        # 3. 新浪接口（获取完整数据，用于填补空缺）
        sina_df = None
        try:
            if code.startswith("6") or code.startswith("9"):
                symbol = f"sh{code}"
            else:
                symbol = f"sz{code}"
            url = f"https://quotes.sina.cn/cn/api/jsonp.php/=/CN_MarketDataService.getKLineData?symbol={symbol}&scale={scale}&ma=no&datalen={days + 60}"
            resp = req_lib.get(url, timeout=10)
            text = resp.text
            start = text.index("[")
            end = text.rindex("]") + 1
            data = json.loads(text[start:end])
            if data:
                sina_df = pd.DataFrame(data)
                sina_df = sina_df.rename(columns={"day": "date"})
                for col in ["open", "close", "high", "low", "volume"]:
                    if col in sina_df.columns:
                        sina_df[col] = pd.to_numeric(sina_df[col], errors="coerce")
                sina_df["date"] = pd.to_datetime(sina_df["date"])
                sina_df = sina_df.set_index("date")
        except Exception:
            pass

        # 设置日期索引（确保后续缠论分析能用正确日期）
        def _set_date_index(df):
            if "date" in df.columns:
                df = df.set_index(pd.to_datetime(df["date"]))
            return df

        # 4. 合并数据：优先同花顺，空缺用新浪补（用同花顺价格计算修正系数）
        if ths_df is not None and len(ths_df) >= 30 and sina_df is not None and len(sina_df) >= 30:
            # 计算复权系数（用同时有数据的日期）
            common_dates = ths_df.index.intersection(sina_df.index)
            if len(common_dates) > 5:
                ratios = (ths_df.loc[common_dates, "close"] / sina_df.loc[common_dates, "close"]).values
                ratio = sum(ratios) / len(ratios)
            else:
                ratio = 1.0
            
            # 用同花顺数据，缺失日期用新浪×系数填补
            all_dates = sina_df.index.union(ths_df.index).sort_values()
            merged = pd.DataFrame(index=all_dates)
            # 同花顺列
            for col in ["open", "high", "low", "close", "volume"]:
                if col in ths_df.columns:
                    merged[f"ths_{col}"] = ths_df[col]
                    merged[f"sina_{col}"] = sina_df[col] * ratio
            
            # 填值：优先同花顺，没有的用新浪修正值
            for col in ["open", "high", "low", "close"]:
                merged[col] = merged[f"ths_{col}"].fillna(merged[f"sina_{col}"])
            merged["volume"] = merged["ths_volume"].fillna(merged["sina_volume"]).fillna(0).astype(int)
            
            merged = merged.drop(columns=[c for c in merged.columns if c.startswith("ths_") or c.startswith("sina_")])
            merged = merged.dropna(subset=["close"])
            
            if len(merged) >= 30:
                return merged.tail(days).reset_index(drop=False).rename(columns={"index": "date"})
        
        # 5. 仅同花顺（无新浪）
        if ths_df is not None and len(ths_df) >= 30:
            return ths_df.reset_index().tail(days).reset_index(drop=True)
        
        # 6. 仅缓存
        if csv_df is not None and len(csv_df) >= 30:
            return csv_df.tail(days).reset_index(drop=True)

    # 7. 仅有新浪（或非日线）
    try:
        if sina_df is not None and len(sina_df) >= 30:
            return sina_df.tail(days).reset_index(drop=False).rename(columns={"index": "date"})
        
        # 重新从新浪拉
        if code.startswith("6") or code.startswith("9"):
            symbol = f"sh{code}"
        else:
            symbol = f"sz{code}"
        url = f"https://quotes.sina.cn/cn/api/jsonp.php/=/CN_MarketDataService.getKLineData?symbol={symbol}&scale={scale}&ma=no&datalen={days + 30}"
        resp = req_lib.get(url, timeout=10)
        text = resp.text
        start = text.index("[")
        end = text.rindex("]") + 1
        data = json.loads(text[start:end])
        if not data:
            return pd.DataFrame()
        df = pd.DataFrame(data)
        df = df.rename(columns={"day": "date"})
        for col in ["open", "close", "high", "low", "volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df.tail(days).reset_index(drop=True)
    except Exception as e:
        logger.debug(f"获取 {code} K线(scale={scale})失败: {e}")
        return pd.DataFrame()


# ============================================================
# 旧缠论分析函数 — 已于 2026-06-24 全部移除
# 实时监控请用 run_signal_monitor.py
# ============================================================


# ============================================================
# 主调度器
# ============================================================

class Watchdog:
    def __init__(self, config: dict):
        self.config = config
        # 优先使用 QMT 数据源，不可用时回退到 HTTP 源
        qmt_fetcher = QmtFetcher(timeout=config.get("data_source", {}).get("timeout", 10))
        if qmt_fetcher.fetch_batch(["000001"]):
            self.fetcher = qmt_fetcher
            logger.info("数据源: QMT (Windows 行情转发)")
        else:
            self.fetcher = RealtimeFetcher(timeout=config.get("data_source", {}).get("timeout", 10))
            logger.warning("QMT 不可用，回退到东方财富 HTTP 数据源")
        self.store = StateStore(config.get("storage", {}).get("db_path", str(current_dir / "watchdog.db")))
        self.notifier = Notifier(config)

        # 信号监测系统
        self.chanlun_service = None
        self.signal_monitor = None
        self.signal_monitor_enabled = config.get("signal_monitor", {}).get("enabled", False)

        self.running = True
        self.start_time = datetime.now(_CST)
        self.scan_count = 0

        # 加载数据
        self.positions = load_positions()
        self.watchlist_codes = load_watchlist_codes()

        # 合并监控列表：持仓 + 自选股
        position_codes = [p.get("股票代码") for p in self.positions if p.get("股票代码")]
        self.all_codes = list(set(position_codes + self.watchlist_codes))

        self.index_codes = {
            "000001": "上证指数",
            "399001": "深证成指",
            "000300": "沪深300",
            "399006": "创业板指",
        }

        self.dedup_window = config.get("notification", {}).get("dedup_window_seconds", 300)

        # 初始化缠论知识库（Qdrant）
        self.knowledge_base = None
        if ChanlunKnowledgeBase is not None:
            try:
                kb = ChanlunKnowledgeBase()
                if kb.is_available():
                    self.knowledge_base = kb
                    logger.info("缠论知识库已连接 (Qdrant)")
                else:
                    logger.info("缠论知识库服务未运行，跳过")
            except Exception as e:
                logger.warning(f"缠论知识库连接失败: {e}")

        # 信号监测初始化（懒加载，run_forever 中启动）
        self._signal_initialized = False

    def _init_signal_monitor(self):
        """初始化信号监测系统"""
        if self._signal_initialized:
            return
        self._signal_initialized = True

        try:
            from chanlun_service import ChanlunService

            self.chanlun_service = ChanlunService()
            self.chanlun_service.start()

            def on_signal_result(result):
                """信号命中回调"""
                notification = result.to_notification()
                self.notifier.send(notification)

            self.signal_monitor = SignalMonitor(
                state_store=self.store,
                chanlun_service=self.chanlun_service,
                notifier=self.notifier,
                on_signal=on_signal_result,
                tick_interval=self.config.get("signal_monitor", {}).get("tick_interval", 5.0),
                divergence_check_interval=self.config.get("signal_monitor", {}).get(
                    "divergence_check_interval", 60.0),
            )
            self.signal_monitor.load_signals()
            logger.info(f"信号监测已初始化，{sum(len(v) for v in self.signal_monitor._signals.values())} 条信号")

        except Exception as e:
            logger.error(f"信号监测初始化失败: {e}")
            self.chanlun_service = None
            self.signal_monitor = None

    def scan_once(self, specific_codes: List[str] = None) -> List[Dict]:
        """执行一次扫描（已废弃 — 由 signal_monitor.tick() 替代）"""
        return []

    def _write_notifications(self, alerts: List[Dict], index_data: Dict):
        """（已废弃 — 旧通知写入逻辑）"""
        try:
            now = datetime.now(_CST)
            notif_path = current_dir / "notifications.json"
            max_alerts = 200

            # 读取已有记录
            existing = []
            if notif_path.exists():
                try:
                    with open(notif_path, "r", encoding="utf-8") as f:
                        old = json.load(f)
                    existing = old.get("alerts", [])
                except:
                    existing = []

            # 为每条报警加上时间和级别中文
            level_cn = {"daily": "日线", "15min": "15分钟"}

            # 大盘概要
            index_summary = {}
            if index_data:
                for code, data in index_data.items():
                    name = data.get("name", code)
                    change = data.get("change_pct", 0)
                    sign = "+" if change > 0 else ""
                    index_summary[name] = f"{sign}{change:.2f}%"

            new_entries = []
            for a in alerts:
                sig_level = a.get("signal_level", "")
                level_label = level_cn.get(sig_level, "")
                new_entries.append({
                    "code": a.get("code", ""),
                    "name": a.get("name", ""),
                    "type": a.get("type", ""),
                    "level": a.get("level", "info"),
                    "message": a.get("message", ""),
                    "price": a.get("price", 0),
                    "score": a.get("score", 0),
                    "signal_level": sig_level,
                    "signal_level_cn": level_label,
                    "action": a.get("action", ""),
                    "time": now.strftime("%H:%M:%S"),
                    "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
                })

            # 合并：新报警放前面
            all_alerts = new_entries + existing
            all_alerts = all_alerts[:max_alerts]

            data = {
                "updated_at": now.strftime("%H:%M:%S"),
                "update_time": now.strftime("%Y-%m-%d %H:%M:%S"),
                "indices": index_summary,
                "alert_count": len(new_entries),
                "total_alerts": len(all_alerts),
                "alerts": all_alerts,
            }

            with open(notif_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

        except Exception as e:
            logger.warning(f"写入通知文件失败: {e}")

    def _print_summary(self, realtime_data, index_data, analyses):
        """打印扫描摘要"""
        if index_data:
            parts = []
            for code, data in index_data.items():
                name = data.get("name", code)
                change = data.get("change_pct", 0)
                sign = "+" if change > 0 else ""
                parts.append(f"{name} {sign}{change:.2f}%")
            logger.info(f"大盘: {' | '.join(parts)}")

        # 持仓盈亏
        total_pnl = 0
        for pos in self.positions:
            code = pos.get("股票代码", "")
            cost = pos.get("成本价", 0)
            shares = pos.get("持股数量", 0)
            rt = realtime_data.get(code, {})
            price = rt.get("price", 0)
            if price and cost:
                total_pnl += (price - cost) * shares
        logger.info(f"持仓总盈亏: {total_pnl:,.0f}元")

        # 缠论信号
        buy_count = sum(1 for a in analyses.values() if a.get("chanlun") and a["chanlun"].get("signals"))
        logger.info(f"有信号的股票: {buy_count} 只")

    def run_forever(self, specific_codes: List[str] = None):
        interval = self.config.get("schedule", {}).get("interval_seconds", 60)
        run_outside = self.config.get("schedule", {}).get("run_outside_hours", False)

        logger.info("=" * 50)
        logger.info("盯盘系统启动（交易联动版）")
        logger.info(f"持仓股票: {len(self.positions)} 只")
        logger.info(f"自选股: {len(self.watchlist_codes)} 只")
        logger.info(f"总计监控: {len(self.all_codes)} 只")
        logger.info(f"扫描间隔: {interval} 秒")
        chanlun_status = "不可用"
        if HAS_CHANLUN:
            chanlun_status = "多级别联立分析" if HAS_MULTI_LEVEL else "单级别分析"
        logger.info(f"缠论分析: {chanlun_status}")
        logger.info("=" * 50)

        # 启动通知
        pos_summary = f"持仓{len(self.positions)}只 | 自选{len(self.watchlist_codes)}只"
        self.notifier.send_text(f"🟢 盯盘系统已启动\n\n{pos_summary}\n扫描间隔: {interval}秒")

        # 初始化信号监测系统（盘中可用时）
        if self.signal_monitor_enabled:
            self._init_signal_monitor()

        while self.running:
            try:
                if is_trading_hours() or run_outside:
                    self.scan_once(specific_codes)

                    # 信号监测 tick
                    if self.signal_monitor:
                        self.signal_monitor.tick()
                else:
                    status = get_market_status()
                    logger.info(f"非交易时段 ({status})，等待...")

                time.sleep(interval)
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"扫描异常: {e}", exc_info=True)
                time.sleep(interval)

        # 停止信号监测
        if self.chanlun_service:
            self.chanlun_service.stop()

        self.notifier.send_text("🔴 盯盘系统已停止")
        logger.info("盯盘系统已停止")

    def get_status(self) -> Dict:
        uptime = datetime.now(_CST) - self.start_time
        hours, remainder = divmod(int(uptime.total_seconds()), 3600)
        minutes, _ = divmod(remainder, 60)

        return {
            "state": "运行中" if self.running else "已停止",
            "market_status": get_market_status(),
            "position_count": len(self.positions),
            "watchlist_count": len(self.watchlist_codes),
            "total_count": len(self.all_codes),
            "scan_count": self.scan_count,
            "uptime": f"{hours}小时{minutes}分",
            "chanlun": "多级别联立分析" if HAS_MULTI_LEVEL else ("单级别分析" if HAS_CHANLUN else "不可用"),
        }


def main():
    parser = argparse.ArgumentParser(description="盯盘系统（交易联动版）")
    parser.add_argument("--config", type=str, help="配置文件路径")
    parser.add_argument("--once", action="store_true", help="扫描一次后退出")
    parser.add_argument("--test", action="store_true", help="测试模式")
    parser.add_argument("--status", action="store_true", help="查看状态")
    parser.add_argument("--stocks", type=str, help="只扫描指定股票，逗号分隔")
    args = parser.parse_args()

    config = load_config(args.config)
    if args.test:
        config.setdefault("schedule", {})["run_outside_hours"] = True

    dog = Watchdog(config)

    if args.status:
        print(json.dumps(dog.get_status(), ensure_ascii=False, indent=2))
        return

    def signal_handler(sig, frame):
        dog.running = False

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    specific = args.stocks.split(",") if args.stocks else None

    if args.once:
        dog.scan_once(specific)
    else:
        dog.run_forever(specific)


if __name__ == "__main__":
    main()
