#!/usr/bin/env python3
"""
自选股监控 - 主入口
====================

读取自选股列表，调用缠论分析和信号生成，输出监控结果。

核心流程：
1. 加载自选股列表（watchlist.json）
2. 按市场过滤（跳过美股、指数等）
3. 获取K线数据（优先本地缓存，其次AKShare）
4. 缠论分析（分型、笔、中枢、买卖点）
5. 信号评分与过滤
6. 输出分析结果

使用方法:
    /usr/bin/python3 /home/jiaod/qts/10-策略/自选股监控/monitor.py
    /usr/bin/python3 /home/jiaod/qts/10-策略/自选股监控/monitor.py --code 000518
    /usr/bin/python3 /home/jiaod/qts/10-策略/自选股监控/monitor.py --min-score 60
    /usr/bin/python3 /home/jiaod/qts/10-策略/自选股监控/monitor.py --date 20260607

作者: QTS量化交易系统
日期: 2026-06-07
"""

import os
import sys
import json
import time
import argparse
import pandas as pd
from datetime import date, datetime
from pathlib import Path
from typing import List, Dict, Tuple

# 将当前目录加入路径
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

from 缠论分析 import analyze, Signal
from signal_generator import (
    score_signals,
    filter_signals,
    build_signal_dataframe,
    save_signals,
    display_signals,
)

try:
    import yaml
except ImportError:
    yaml = None

try:
    import akshare as ak
except ImportError:
    ak = None


# ============================================================
# 配置加载
# ============================================================

DEFAULT_CONFIG = {
    'data': {
        'watchlist_path': '/home/jiaod/qts/00-研究/自选股/watchlist.json',
        'kline_cache_dir': '/home/jiaod/qts/00-研究/数据源/缓存/kline_6m',
        'kline_days': 120,
        'adjust': 'qfq',
    },
    'market': {
        'enabled_markets': ['上海A股', '深圳A股'],
        'skip_markets': ['美股', '创业板'],
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
        'output_dir': '/home/jiaod/qts/30-信号/',
        'output_prefix': '自选股监控',
    },
    'runtime': {
        'request_delay': 0.3,
        'log_level': 'INFO',
    },
}


def load_config(config_path: str = None) -> dict:
    """加载配置文件"""
    cfg = DEFAULT_CONFIG.copy()

    if config_path and os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            if yaml:
                user_cfg = yaml.safe_load(f) or {}
            else:
                # 简单解析 yaml（无yaml库时）
                user_cfg = {}
        # 简单合并
        for key in user_cfg:
            if key in cfg and isinstance(cfg[key], dict) and isinstance(user_cfg[key], dict):
                cfg[key].update(user_cfg[key])
            else:
                cfg[key] = user_cfg[key]

    return cfg


# ============================================================
# 自选股列表加载
# ============================================================

def load_watchlist(path: str) -> List[Dict]:
    """加载自选股列表"""
    with open(path, 'r', encoding='utf-8') as f:
        watchlist = json.load(f)
    print(f"加载自选股: {len(watchlist)} 只")
    return watchlist


def filter_by_market(watchlist: List[Dict], config: dict) -> List[Dict]:
    """按市场过滤"""
    enabled = set(config['market']['enabled_markets'])
    skip = set(config['market']['skip_markets'])

    filtered = []
    for item in watchlist:
        market = item.get('market', '')
        if market in skip:
            continue
        if enabled and market not in enabled:
            continue
        # 跳过指数（代码以399或880开头）
        code = item.get('code', '')
        if code.startswith('399') or code.startswith('880'):
            continue
        filtered.append(item)

    print(f"市场过滤后: {len(filtered)} 只 (跳过 {len(watchlist) - len(filtered)} 只)")
    return filtered


# ============================================================
# K线数据获取
# ============================================================

def get_kline_from_cache(code: str, cache_dir: str) -> pd.DataFrame:
    """从本地缓存获取K线数据"""
    csv_path = os.path.join(cache_dir, f"{code}.csv")
    if os.path.exists(csv_path):
        df = pd.read_csv(csv_path)
        # 统一列名
        if 'day' in df.columns and 'date' not in df.columns:
            df = df.rename(columns={'day': 'date'})
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
        return df
    return pd.DataFrame()


def get_kline_from_akshare(code: str, days: int = 120, adjust: str = 'qfq') -> pd.DataFrame:
    """通过 AKShare 获取K线数据"""
    if ak is None:
        print(f"  AKShare 未安装，跳过 {code}")
        return pd.DataFrame()

    try:
        end_date = date.today().strftime('%Y%m%d')
        start_date = (date.today() - pd.Timedelta(days=days + 30)).strftime('%Y%m%d')

        df = ak.stock_zh_a_hist(
            symbol=code,
            period='daily',
            start_date=start_date,
            end_date=end_date,
            adjust=adjust,
        )

        if df is None or df.empty:
            return pd.DataFrame()

        # 统一列名
        df = df.rename(columns={
            '日期': 'date',
            '开盘': 'open',
            '收盘': 'close',
            '最高': 'high',
            '最低': 'low',
            '成交量': 'volume',
            '成交额': 'amount',
        })

        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')

        return df

    except Exception as e:
        print(f"  AKShare 获取 {code} 失败: {e}")
        return pd.DataFrame()


def get_kline(code: str, cache_dir: str, days: int = 120, adjust: str = 'qfq') -> pd.DataFrame:
    """获取K线数据（优先缓存，其次AKShare）"""
    # 尝试本地缓存
    df = get_kline_from_cache(code, cache_dir)
    if not df.empty and len(df) >= 30:
        # 取最近N天
        return df.tail(days).reset_index(drop=True)

    # 尝试AKShare
    df = get_kline_from_akshare(code, days, adjust)
    if not df.empty and len(df) >= 30:
        return df.tail(days).reset_index(drop=True)

    return pd.DataFrame()


# ============================================================
# 单股分析
# ============================================================

def analyze_stock(
    code: str,
    market: str,
    config: dict,
) -> Tuple[Dict, List[Dict]]:
    """
    对单只股票进行完整分析。

    返回:
        (stock_info, scored_signals)
    """
    stock_info = {
        'code': code,
        'market': market,
        'name': '',
        'current_price': None,
        'analysis_summary': '',
        'signals': [],
    }

    # 获取K线
    cache_dir = config['data']['kline_cache_dir']
    days = config['data']['kline_days']
    adjust = config['data']['adjust']

    kline_df = get_kline(code, cache_dir, days, adjust)
    if kline_df.empty or len(kline_df) < 30:
        return stock_info, []

    # 获取当前价格
    if 'close' in kline_df.columns:
        stock_info['current_price'] = float(kline_df['close'].iloc[-1])

    # 缠论分析
    try:
        result = analyze(kline_df, config['chanlun'])
    except Exception as e:
        print(f"  分析 {code} 出错: {e}")
        return stock_info, []

    stock_info['analysis_summary'] = result['summary']

    # 信号评分
    if result['signals']:
        scored = score_signals(result['signals'], config['signal']['weights'])
        filtered = filter_signals(scored, config['signal']['min_score'])
        stock_info['signals'] = filtered
        return stock_info, filtered

    return stock_info, []


# ============================================================
# 主函数
# ============================================================

def main():
    parser = argparse.ArgumentParser(description='自选股监控 - 缠论分析')
    parser.add_argument('--config', type=str, default=None, help='配置文件路径')
    parser.add_argument('--code', type=str, default=None, help='只分析指定股票代码')
    parser.add_argument('--min-score', type=float, default=None, help='最低信号分数')
    parser.add_argument('--date', type=str, default=None, help='信号日期')
    parser.add_argument('--verbose', action='store_true', help='显示详细信息')
    args = parser.parse_args()

    # 加载配置
    config_path = args.config or str(current_dir / 'config.yaml')
    config = load_config(config_path)

    if args.min_score is not None:
        config['signal']['min_score'] = args.min_score

    signal_date = args.date or date.today().strftime('%Y%m%d')

    print("=" * 70)
    print("自选股监控 - 缠论分析")
    print(f"日期: {signal_date}")
    print(f"最低分数: {config['signal']['min_score']}")
    print("=" * 70)

    # 加载自选股
    watchlist_path = config['data']['watchlist_path']
    if not os.path.exists(watchlist_path):
        print(f"自选股文件不存在: {watchlist_path}")
        sys.exit(1)

    watchlist = load_watchlist(watchlist_path)
    filtered = filter_by_market(watchlist, config)

    if args.code:
        filtered = [w for w in filtered if w['code'] == args.code]
        if not filtered:
            print(f"股票 {args.code} 不在自选股列表中")
            sys.exit(1)

    # 逐股分析
    all_signals_rows = []
    stock_results = []
    delay = config['runtime']['request_delay']

    for i, item in enumerate(filtered):
        code = item['code']
        market = item.get('market', '')

        print(f"\n[{i+1}/{len(filtered)}] 分析 {code} ({market})...")

        stock_info, signals = analyze_stock(code, market, config)

        # 显示分析摘要
        if stock_info['analysis_summary']:
            print(f"  {stock_info['analysis_summary']}")

        # 显示信号
        if signals:
            for s in signals:
                type_cn = {
                    'buy_1': '一买', 'buy_2': '二买', 'buy_2_like': '类二买',
                    'sell_1': '一卖', 'sell_2': '二卖',
                }.get(s['type'], s['type'])
                macd_mark = '*' if s['macd_confirm'] else ''
                print(f"  => {type_cn} ({s['final_score']:.0f}分{macd_mark}) @ {s['date']} 价格:{s['price']:.2f}")

            # 构建信号DataFrame
            df = build_signal_dataframe(
                stock_code=code,
                stock_name=stock_info.get('name', ''),
                market=market,
                scored_signals=signals,
                current_price=stock_info.get('current_price'),
            )
            all_signals_rows.append(df)
        elif args.verbose:
            print(f"  无有效信号")

        stock_results.append(stock_info)

        # 请求间隔
        if delay > 0 and i < len(filtered) - 1:
            time.sleep(delay)

    # 汇总输出
    print(f"\n{'='*70}")
    print(f"分析完成: 共 {len(filtered)} 只股票")

    if all_signals_rows:
        all_df = pd.concat(all_signals_rows, ignore_index=True)
        display_signals(all_df)

        output_path = save_signals(
            all_df,
            config['signal']['output_dir'],
            config['signal']['output_prefix'],
            signal_date,
        )
    else:
        print("本次扫描无有效信号")

    # 统计有信号的股票
    stocks_with_signals = [s for s in stock_results if s['signals']]
    print(f"有信号的股票: {len(stocks_with_signals)} 只")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
