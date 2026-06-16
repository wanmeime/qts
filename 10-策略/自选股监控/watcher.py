#!/usr/bin/env python3
"""
盯盘系统 - 实时监控与告警
==========================

功能：
1. 后台常驻，定时扫描自选股和持仓
2. 缠论分析检测买卖点信号
3. 价格异动告警（涨跌幅、突破等）
4. 飞书消息推送

使用方法：
    python watcher.py                    # 启动盯盘
    python watcher.py --once             # 扫描一次退出
    python watcher.py --interval 60      # 设置扫描间隔（秒）

作者: QTS量化交易系统
日期: 2026-06-14
"""

import os
import sys
import json
import time
import signal
import logging
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Set
from dataclasses import dataclass, field, asdict

# 添加路径
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

from 缠论分析 import analyze, Signal
from signal_generator import score_signals, filter_signals

try:
    import yaml
except ImportError:
    yaml = None

# ============================================================
# 日志配置
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


# ============================================================
# 数据结构
# ============================================================
@dataclass
class AlertRule:
    """告警规则"""
    name: str
    enabled: bool = True
    # 价格条件
    price_above: Optional[float] = None
    price_below: Optional[float] = None
    # 涨跌幅条件
    change_pct_above: Optional[float] = None
    change_pct_below: Optional[float] = None
    # 信号条件
    signal_types: List[str] = field(default_factory=list)  # buy_1, buy_2, sell_1, sell_2
    min_score: float = 60.0


@dataclass
class Alert:
    """告警记录"""
    code: str
    name: str
    alert_type: str  # price, change, signal
    message: str
    price: float
    change_pct: float = 0.0
    timestamp: str = ''
    rule_name: str = ''


@dataclass
class WatchedStock:
    """监控股票"""
    code: str
    name: str = ''
    market: str = ''
    cost_price: float = 0.0  # 持仓成本
    hold_shares: int = 0     # 持仓数量
    is_position: bool = False  # 是否持仓


# ============================================================
# 配置加载
# ============================================================
DEFAULT_CONFIG = {
    'watcher': {
        'interval': 300,  # 扫描间隔（秒）
        'market_hours_only': True,  # 仅交易时段运行
        'market_open': '09:30',
        'market_close': '15:00',
    },
    'data': {
        'watchlist_path': '/home/jiaod/qts/00-研究/自选股/watchlist.json',
        'positions_path': '/home/jiaod/qts/40-执行/持仓/当前持仓.json',
        'kline_cache_dir': '/home/jiaod/qts/00-研究/数据源/缓存/kline_6m',
        'kline_days': 120,
        'adjust': 'qfq',
    },
    'alert': {
        'enabled': True,
        'rules': [
            {
                'name': '大涨告警',
                'change_pct_above': 5.0,
            },
            {
                'name': '大跌告警',
                'change_pct_below': -5.0,
            },
            {
                'name': '买入信号',
                'signal_types': ['buy_1', 'buy_2', 'buy_2_like'],
                'min_score': 60,
            },
            {
                'name': '卖出信号',
                'signal_types': ['sell_1', 'sell_2'],
                'min_score': 60,
            },
        ],
    },
    'chanlun': {
        'macd': {'fast': 12, 'slow': 26, 'signal': 9},
        'divergence_window': 20,
    },
    'signal': {
        'weights': {
            'buy_point': 0.4,
            'macd_confirm': 0.25,
            'volume_confirm': 0.15,
            'trend_score': 0.2,
        },
        'min_score': 50,
    },
}


def load_config(config_path: Optional[str] = None) -> dict:
    """加载配置"""
    cfg = DEFAULT_CONFIG.copy()

    if config_path and os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            if yaml:
                user_cfg = yaml.safe_load(f) or {}
            else:
                user_cfg = json.load(f)

        # 递归合并
        def merge(base, override):
            for k, v in override.items():
                if k in base and isinstance(base[k], dict) and isinstance(v, dict):
                    merge(base[k], v)
                else:
                    base[k] = v

        merge(cfg, user_cfg)

    return cfg


# ============================================================
# 数据加载
# ============================================================
def load_watchlist(path: str) -> List[WatchedStock]:
    """加载自选股"""
    stocks = []
    if not os.path.exists(path):
        logger.warning(f"自选股文件不存在: {path}")
        return stocks

    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    for item in data:
        code = item.get('code', '')
        if not code:
            continue
        # 跳过指数
        if code.startswith('399') or code.startswith('880'):
            continue

        stocks.append(WatchedStock(
            code=code,
            name=item.get('name', ''),
            market=item.get('market', ''),
        ))

    logger.info(f"加载自选股: {len(stocks)} 只")
    return stocks


def load_positions(config: dict) -> Dict[str, WatchedStock]:
    """加载手动配置的持仓"""
    positions = {}
    pos_cfg = config.get('positions', {})
    
    for code, info in pos_cfg.items():
        if isinstance(info, dict):
            positions[code] = WatchedStock(
                code=code,
                name=info.get('name', ''),
                cost_price=info.get('cost', 0),
                hold_shares=info.get('shares', 0),
                is_position=True,
            )
        else:
            # 简单格式：code: "名称,成本,数量"
            parts = str(info).split(',')
            if len(parts) >= 3:
                positions[code] = WatchedStock(
                    code=code,
                    name=parts[0].strip(),
                    cost_price=float(parts[1].strip()),
                    hold_shares=int(parts[2].strip()),
                    is_position=True,
                )
    
    logger.info(f"加载持仓: {len(positions)} 只")
    return positions


def get_kline(code: str, cache_dir: str, days: int = 120, adjust: str = 'qfq') -> 'pd.DataFrame':
    """获取K线数据"""
    import pandas as pd

    # 优先本地缓存 - 尝试多种文件名格式
    csv_path = None
    for name in [f"{code}.csv", f"sh{code}.csv", f"sz{code}.csv"]:
        candidate = os.path.join(cache_dir, name)
        if os.path.exists(candidate):
            csv_path = candidate
            break

    if csv_path:
        try:
            df = pd.read_csv(csv_path)
            if 'day' in df.columns and 'date' not in df.columns:
                df = df.rename(columns={'day': 'date'})
            if 'date' in df.columns:
                df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
            if len(df) >= 30:
                return df.tail(days).reset_index(drop=True)
        except Exception as e:
            logger.debug(f"读取缓存{csv_path}失败: {e}")

    # AKShare
    try:
        import akshare as ak
        from datetime import date
        end_date = date.today().strftime('%Y%m%d')
        start_date = (date.today() - pd.Timedelta(days=days + 30)).strftime('%Y%m%d')

        df = ak.stock_zh_a_hist(
            symbol=code, period='daily',
            start_date=start_date, end_date=end_date, adjust=adjust
        )
        if df is None or df.empty:
            return pd.DataFrame()

        df = df.rename(columns={
            '日期': 'date', '开盘': 'open', '收盘': 'close',
            '最高': 'high', '最低': 'low', '成交量': 'volume', '成交额': 'amount',
        })
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
        return df.tail(days).reset_index(drop=True)
    except Exception as e:
        logger.debug(f"AKShare获取{code}失败: {e}")
        return pd.DataFrame()


# ============================================================
# 告警引擎
# ============================================================
class AlertEngine:
    """告警引擎"""

    def __init__(self, config: dict):
        self.rules = []
        for rule_cfg in config.get('alert', {}).get('rules', []):
            self.rules.append(AlertRule(
                name=rule_cfg.get('name', ''),
                enabled=rule_cfg.get('enabled', True),
                price_above=rule_cfg.get('price_above'),
                price_below=rule_cfg.get('price_below'),
                change_pct_above=rule_cfg.get('change_pct_above'),
                change_pct_below=rule_cfg.get('change_pct_below'),
                signal_types=rule_cfg.get('signal_types', []),
                min_score=rule_cfg.get('min_score', 60),
            ))

    def check_signals(self, code: str, name: str, signals: List[Dict], price: float) -> List[Alert]:
        """检查信号告警"""
        alerts = []
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        for rule in self.rules:
            if not rule.enabled or not rule.signal_types:
                continue

            for sig in signals:
                sig_type = sig.get('type', '')
                sig_score = sig.get('final_score', 0)

                if sig_type in rule.signal_types and sig_score >= rule.min_score:
                    type_cn = {
                        'buy_1': '一买', 'buy_2': '二买', 'buy_2_like': '类二买',
                        'sell_1': '一卖', 'sell_2': '二卖',
                    }.get(sig_type, sig_type)

                    alerts.append(Alert(
                        code=code,
                        name=name,
                        alert_type='signal',
                        message=f"【{type_cn}信号】{name}({code}) {type_cn}，评分{sig_score:.0f}分，价格{price:.2f}",
                        price=price,
                        timestamp=now,
                        rule_name=rule.name,
                    ))

        return alerts

    def check_price(self, code: str, name: str, price: float, change_pct: float) -> List[Alert]:
        """检查价格/涨跌幅告警"""
        alerts = []
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        for rule in self.rules:
            if not rule.enabled:
                continue

            # 涨跌幅告警
            if rule.change_pct_above is not None and change_pct >= rule.change_pct_above:
                alerts.append(Alert(
                    code=code, name=name, alert_type='change',
                    message=f"涨幅{change_pct:+.2f}%，价格{price:.2f}",
                    price=price, change_pct=change_pct,
                    timestamp=now, rule_name=rule.name,
                ))

            if rule.change_pct_below is not None and change_pct <= rule.change_pct_below:
                alerts.append(Alert(
                    code=code, name=name, alert_type='change',
                    message=f"跌幅{change_pct:+.2f}%，价格{price:.2f}",
                    price=price, change_pct=change_pct,
                    timestamp=now, rule_name=rule.name,
                ))

            # 价格告警
            if rule.price_above is not None and price >= rule.price_above:
                alerts.append(Alert(
                    code=code, name=name, alert_type='price',
                    message=f"【{rule.name}】{name}({code}) 突破{rule.price_above}，当前{price:.2f}",
                    price=price, timestamp=now, rule_name=rule.name,
                ))

            if rule.price_below is not None and price <= rule.price_below:
                alerts.append(Alert(
                    code=code, name=name, alert_type='price',
                    message=f"【{rule.name}】{name}({code}) 跌破{rule.price_below}，当前{price:.2f}",
                    price=price, timestamp=now, rule_name=rule.name,
                ))

        return alerts


# ============================================================
# 通知器
# ============================================================
class Notifier:
    """通知发送"""

    def __init__(self, feishu_chat_id: str = 'oc_d2e8df3c676afa2c352d8ece0a9b6141'):
        self.feishu_chat_id = feishu_chat_id
        self.lark_cli = '/home/jiaod/.npm-global/bin/lark-cli'

    def send_feishu(self, message: str) -> bool:
        """发送飞书消息"""
        import subprocess
        try:
            result = subprocess.run(
                [self.lark_cli, 'im', '+messages-send',
                 '--chat-id', self.feishu_chat_id,
                 '--markdown', message,
                 '--as', 'bot'],
                capture_output=True, text=True, timeout=30,
                cwd='/home/jiaod/qts'
            )
            if result.returncode == 0:
                import json
                data = json.loads(result.stdout)
                return data.get('ok', False)
        except Exception as e:
            logger.error(f"飞书发送失败: {e}")
        return False

    def notify_alerts(self, alerts: List[Alert], positions: Dict[str, WatchedStock]):
        """发送告警通知 - 飞书Markdown消息"""
        if not alerts:
            return

        now = datetime.now().strftime('%Y-%m-%d %H:%M')

        # 按类型分组
        big_rise = [a for a in alerts if a.alert_type == 'change' and a.rule_name == '大涨告警']
        big_drop = [a for a in alerts if a.alert_type == 'change' and a.rule_name == '大跌告警']
        buy_sig = [a for a in alerts if a.alert_type == 'signal' and 'buy' in a.rule_name]
        sell_sig = [a for a in alerts if a.alert_type == 'signal' and 'sell' in a.rule_name]
        price_alerts = [a for a in alerts if a.alert_type == 'price']

        # 构建Markdown消息
        lines = [f"## 📊 盯盘告警 ({now})", ""]

        # 大涨
        if big_rise:
            lines.append(f"### 🟢 大涨告警 ({len(big_rise)}只)")
            for a in big_rise:
                lines.append(f"- **{a.name}**({a.code}) 涨幅+{a.change_pct:.2f}%，现价{a.price:.2f}")
            lines.append("")

        # 大跌
        if big_drop:
            lines.append(f"### 🔴 大跌告警 ({len(big_drop)}只)")
            for a in big_drop:
                lines.append(f"- **{a.name}**({a.code}) 跌幅{a.change_pct:.2f}%，现价{a.price:.2f}")
            lines.append("")

        # 买入信号
        if buy_sig:
            lines.append(f"### 🟢 买入信号 ({len(buy_sig)}个)")
            for a in buy_sig:
                lines.append(f"- **{a.name}**({a.code}) {a.message}")
            lines.append("")

        # 卖出信号
        if sell_sig:
            lines.append(f"### 🔴 卖出信号 ({len(sell_sig)}个)")
            for a in sell_sig:
                lines.append(f"- **{a.name}**({a.code}) {a.message}")
            lines.append("")

        # 价格突破
        if price_alerts:
            lines.append(f"### ⚡ 价格突破 ({len(price_alerts)}个)")
            for a in price_alerts:
                lines.append(f"- **{a.name}**({a.code}) {a.message}")
            lines.append("")

        # 持仓摘要
        if positions:
            lines.append("### 📋 持仓摘要")
            for code, pos in positions.items():
                lines.append(f"- **{pos.name}**({code}) 成本{pos.cost_price:.2f} 持仓{pos.hold_shares}股")
            lines.append("")

        message = "\n".join(lines)
        self.send_feishu_markdown(message)

    def send_feishu_markdown(self, markdown: str) -> bool:
        """发送飞书Markdown消息"""
        import subprocess
        try:
            result = subprocess.run(
                [self.lark_cli, 'im', '+messages-send',
                 '--chat-id', self.feishu_chat_id,
                 '--markdown', markdown,
                 '--as', 'bot'],
                capture_output=True, text=True, timeout=30,
                cwd='/home/jiaod/qts'
            )
            if result.returncode == 0:
                import json
                data = json.loads(result.stdout)
                return data.get('ok', False)
        except Exception as e:
            logger.error(f"飞书Markdown发送失败: {e}")
        return False

    def notify_startup(self, stock_count: int, position_count: int):
        """发送启动通知"""
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        message = f"""# 🟢 盯盘系统已启动

- **监控股票**: {stock_count} 只
- **持仓股票**: {position_count} 只
- **启动时间**: {now}
"""
        self.send_feishu_markdown(message)

    def notify_shutdown(self):
        """发送停止通知"""
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        message = f"""# 🔴 盯盘系统已停止

- **停止时间**: {now}
"""
        self.send_feishu_markdown(message)


# ============================================================
# 盯盘主类
# ============================================================
class Watcher:
    """盯盘系统"""

    def __init__(self, config: dict):
        self.config = config
        self.alert_engine = AlertEngine(config)
        self.notifier = Notifier()
        self.running = True

        # 加载数据
        self.watchlist = load_watchlist(config['data']['watchlist_path'])
        self.positions = load_positions(config)

        # 合并监控列表（自选股 + 持仓）
        self.all_stocks: Dict[str, WatchedStock] = {}
        for s in self.watchlist:
            self.all_stocks[s.code] = s
        for code, pos in self.positions.items():
            if code in self.all_stocks:
                # 合并持仓信息
                self.all_stocks[code].cost_price = pos.cost_price
                self.all_stocks[code].hold_shares = pos.hold_shares
                self.all_stocks[code].is_position = True
            else:
                self.all_stocks[code] = pos

        # 已告警记录（避免重复）
        self.alerted: Set[str] = set()

    def is_market_hours(self) -> bool:
        """是否交易时段"""
        if not self.config['watcher']['market_hours_only']:
            return True

        now = datetime.now()
        # 周末不交易
        if now.weekday() >= 5:
            return False

        open_time = self.config['watcher']['market_open']
        close_time = self.config['watcher']['market_close']

        current = now.strftime('%H:%M')
        return open_time <= current <= close_time

    def scan_once(self):
        """执行一次扫描"""
        logger.info("=" * 50)
        logger.info(f"开始扫描 {len(self.all_stocks)} 只股票")

        # 先获取实时行情填充名称
        all_codes = list(self.all_stocks.keys())
        logger.info("获取实时行情...")
        realtime_data = {}
        
        # 用新浪接口获取名称和实时价格
        try:
            import requests as req_lib
            symbols = []
            code_to_symbol = {}
            for code in all_codes:
                if code.startswith('6') or code.startswith('9'):
                    sym = f"sh{code}"
                else:
                    sym = f"sz{code}"
                symbols.append(sym)
                code_to_symbol[sym] = code
            
            url = f"https://hq.sinajs.cn/list={','.join(symbols[:80])}"
            headers = {"Referer": "https://finance.sina.com.cn"}
            resp = req_lib.get(url, headers=headers, timeout=10)
            resp.encoding = "gbk"
            
            import re
            for line in resp.text.strip().split("\n"):
                match = re.search(r'var hq_str_(\w+)="(.*)"', line)
                if not match:
                    continue
                symbol = match.group(1)
                data = match.group(2)
                if not data:
                    continue
                parts = data.split(",")
                if len(parts) < 10:
                    continue
                code = code_to_symbol.get(symbol, symbol)
                try:
                    realtime_data[code] = {
                        "name": parts[0],
                        "price": float(parts[3]),
                        "change_pct": round((float(parts[3]) - float(parts[2])) / float(parts[2]) * 100, 2),
                    }
                except (ValueError, IndexError):
                    pass
        except Exception as e:
            logger.warning(f"获取新浪实时行情失败: {e}")
        
        # 填充名称
        for code, stock in self.all_stocks.items():
            if not stock.name and code in realtime_data:
                stock.name = realtime_data[code]["name"]
        
        logger.info(f"获取到 {len(realtime_data)} 只股票行情")

        all_alerts = []
        analyzed = 0
        signals_found = 0

        for code, stock in self.all_stocks.items():
            try:
                # 获取K线
                kline = get_kline(
                    code,
                    self.config['data']['kline_cache_dir'],
                    self.config['data']['kline_days'],
                    self.config['data']['adjust']
                )

                if kline.empty or len(kline) < 30:
                    continue

                # 获取当前价格和涨跌幅
                current_price = float(kline['close'].iloc[-1])
                if len(kline) >= 2:
                    prev_close = float(kline['close'].iloc[-2])
                    change_pct = (current_price - prev_close) / prev_close * 100 if prev_close > 0 else 0
                else:
                    change_pct = 0

                # 缠论分析
                result = analyze(kline, self.config.get('chanlun', {}))
                signals = result.get('signals', [])

                # 信号评分
                if signals:
                    scored = score_signals(signals, self.config['signal']['weights'])
                    filtered = filter_signals(scored, self.config['signal']['min_score'])
                else:
                    filtered = []

                # 检查告警
                # 信号告警
                signal_alerts = self.alert_engine.check_signals(
                    code, stock.name, filtered, current_price
                )
                all_alerts.extend(signal_alerts)

                # 价格告警 - 使用实时行情数据
                rt_data = realtime_data.get(code, {})
                rt_price = rt_data.get("price", current_price)
                rt_change = rt_data.get("change_pct", change_pct)
                
                price_alerts = self.alert_engine.check_price(
                    code, stock.name, rt_price, rt_change
                )
                all_alerts.extend(price_alerts)

                if filtered:
                    signals_found += 1
                    for sig in filtered:
                        type_cn = {
                            'buy_1': '一买', 'buy_2': '二买', 'buy_2_like': '类二买',
                            'sell_1': '一卖', 'sell_2': '二卖',
                        }.get(sig['type'], sig['type'])
                        logger.info(f"  {stock.name}({code}) {type_cn} 评分{sig['final_score']:.0f}")

                analyzed += 1
                time.sleep(0.3)  # 请求间隔

            except Exception as e:
                logger.error(f"分析{code}失败: {e}")

        # 过滤已告警的
        new_alerts = []
        for alert in all_alerts:
            alert_key = f"{alert.code}_{alert.alert_type}_{alert.rule_name}"
            if alert_key not in self.alerted:
                new_alerts.append(alert)
                self.alerted.add(alert_key)

        logger.info(f"扫描完成: 分析{analyzed}只, 信号{signals_found}只, 新告警{len(new_alerts)}条")

        # 发送通知
        if new_alerts:
            self.notifier.notify_alerts(new_alerts, self.positions)

        return new_alerts

    def run(self, interval: int = None):
        """持续运行"""
        interval = interval or self.config['watcher']['interval']

        logger.info(f"盯盘系统启动，扫描间隔: {interval}秒")
        self.notifier.notify_startup(len(self.all_stocks), len(self.positions))

        # 信号处理
        def handle_signal(sig, frame):
            logger.info("收到停止信号")
            self.running = False

        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

        while self.running:
            try:
                if self.is_market_hours():
                    self.scan_once()
                else:
                    logger.debug("非交易时段，跳过扫描")

                # 等待下次扫描
                for _ in range(interval):
                    if not self.running:
                        break
                    time.sleep(1)

            except Exception as e:
                logger.error(f"扫描异常: {e}")
                time.sleep(10)

        self.notifier.notify_shutdown()
        logger.info("盯盘系统已停止")


# ============================================================
# 主函数
# ============================================================
def main():
    parser = argparse.ArgumentParser(description='盯盘系统')
    parser.add_argument('--config', type=str, help='配置文件路径')
    parser.add_argument('--once', action='store_true', help='扫描一次后退出')
    parser.add_argument('--interval', type=int, help='扫描间隔（秒）')
    parser.add_argument('--test', action='store_true', help='测试模式（不检查交易时段）')
    args = parser.parse_args()

    config = load_config(args.config)

    if args.test:
        config['watcher']['market_hours_only'] = False

    watcher = Watcher(config)

    if args.once:
        watcher.scan_once()
    else:
        watcher.run(args.interval)


if __name__ == '__main__':
    main()
