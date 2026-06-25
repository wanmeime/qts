#!/usr/bin/env python3
"""
信号监测独立启动脚本

仅启动信号监测系统 + 缠论分析服务（后台线程），
不加载旧的缠论分析模块，实现快速轮询。

用法：
    python3 50-盯盘/run_signal_monitor.py
"""
import sys
import time
import logging
import signal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from state_store import StateStore
from signal_monitor import SignalMonitor
from chanlun_service import ChanlunService
from notifier import Notifier
from realtime_fetcher import RealtimeFetcher, QmtFetcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("signal_monitor")

# 加载配置
import yaml
from watchdog import load_config

config = load_config(str(Path(__file__).parent / "config.yaml"))
tick_interval = config.get("signal_monitor", {}).get("tick_interval", 5.0)
divergence_check_interval = config.get("signal_monitor", {}).get("divergence_check_interval", 60.0)

# 初始化
logger.info("=== 信号监测系统启动 ===")
store = StateStore()
notifier = Notifier(config)

# 优先使用 QMT 行情源，不可用时回退到 HTTP 源
fetcher = QmtFetcher(timeout=config.get("data_source", {}).get("timeout", 10))
try:
    test = fetcher.fetch_batch(["000001"])
    if not test:
        fetcher = RealtimeFetcher(timeout=config.get("data_source", {}).get("timeout", 10))
        logger.warning("QMT 不可用，回退到 HTTP 数据源")
    else:
        logger.info("数据源: QMT (Windows 行情转发)")
except Exception:
    fetcher = RealtimeFetcher(timeout=config.get("data_source", {}).get("timeout", 10))
    logger.warning("QMT 不可用，回退到 HTTP 数据源")

# 缠论后台服务
chanlun_service = ChanlunService()
chanlun_service.start()

# 信号监测回调（通知 + 飞书）
def on_signal_callback(result):
    notif = result.to_notification()
    try:
        notifier.send(notif)
    except Exception as e:
        logger.error(f"发送通知失败: {e}")

# 自动交易配置
auto_trade_cfg = config.get("auto_trade", {})
auto_trade_enabled = auto_trade_cfg.get("enabled", False)
qmt_host = auto_trade_cfg.get("qmt_host", "")
if auto_trade_enabled and qmt_host:
    logger.info(f"自动交易: 已启用 → QMT Bridge ({qmt_host})")
else:
    logger.info("自动交易: 未启用（仅通知模式）")

monitor = SignalMonitor(
    state_store=store,
    chanlun_service=chanlun_service,
    notifier=notifier,
    on_signal=on_signal_callback,
    tick_interval=tick_interval,
    divergence_check_interval=divergence_check_interval,
    fetcher=fetcher,
    auto_trade_enabled=auto_trade_enabled,
    qmt_host=qmt_host if auto_trade_enabled else None,
    auto_trade_config=auto_trade_cfg,
)

# 加载信号
monitor.load_signals()
logger.info(f"加载 {sum(len(v) for v in monitor._signals.values())} 条信号")
logger.info(f"轮询间隔: {tick_interval}s")

# 信号处理
running = True

def handle_signal(sig, frame):
    global running
    running = False

signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)

try:
    while running:
        try:
            monitor.tick()
        except Exception as e:
            logger.exception(f"tick 异常: {e}")
        time.sleep(tick_interval)
finally:
    chanlun_service.stop()
    logger.info("信号监测系统已停止")
