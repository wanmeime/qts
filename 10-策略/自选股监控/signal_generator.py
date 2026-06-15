#!/usr/bin/env python3
"""
信号生成模块
============

基于缠论分析结果，生成标准化的买卖信号。

功能：
1. 信号评分（综合缠论得分、MACD确认、量能确认、趋势得分）
2. 信号过滤（最低分数阈值）
3. 信号排序（按评分降序）
4. 信号输出（CSV + 终端展示）

作者: QTS量化交易系统
日期: 2026-06-07
"""

import os
import pandas as pd
from datetime import date
from typing import List, Dict

from 缠论分析 import Signal


# ============================================================
# 信号评分
# ============================================================

def score_signals(
    signals: List[Signal],
    weights: dict = None,
) -> List[Dict]:
    """
    对缠论信号进行综合评分。

    评分维度：
    1. 买点类型得分 (buy_point): 不同类型买点基础分不同
    2. MACD确认得分 (macd_confirm): MACD背驰确认加分
    3. 量能确认得分 (volume_confirm): 成交量配合加分
    4. 趋势得分 (trend_score): 基于信号在序列中的位置

    返回:
        List[Dict]: 每个信号的评分详情
    """
    if weights is None:
        weights = {
            'buy_point': 0.4,
            'macd_confirm': 0.25,
            'volume_confirm': 0.15,
            'trend_score': 0.2,
        }

    buy_type_scores = {
        'buy_1': 90,     # 一类买点（最安全）
        'buy_2': 80,     # 二类买点（右侧交易）
        'buy_2_like': 75, # 类二买（上涨趋势最佳买点）
        'sell_1': 90,    # 一类卖点
        'sell_2': 75,    # 二类卖点
    }

    scored = []
    for i, signal in enumerate(signals):
        # 1. 买点类型得分
        type_base = buy_type_scores.get(signal.type, 50)

        # 2. MACD确认
        macd_score = 100 if signal.macd_confirm else 30

        # 3. 量能确认
        volume_score = 100 if signal.volume_confirm else 50

        # 4. 趋势得分（越新的信号得分越高）
        total_count = len(signals) if signals else 1
        trend_score = 30 + 70 * (i / max(total_count - 1, 1))

        # 综合评分
        final_score = (
            type_base * weights.get('buy_point', 0.4) +
            macd_score * weights.get('macd_confirm', 0.25) +
            volume_score * weights.get('volume_confirm', 0.15) +
            trend_score * weights.get('trend_score', 0.2)
        )

        scored.append({
            'type': signal.type,
            'date': signal.date,
            'price': signal.price,
            'raw_score': signal.score,
            'final_score': round(final_score, 1),
            'macd_confirm': signal.macd_confirm,
            'volume_confirm': signal.volume_confirm,
            'description': signal.description,
            'type_score': type_base,
            'macd_score': macd_score,
            'volume_score': volume_score,
            'trend_score': round(trend_score, 1),
        })

    # 按综合评分降序
    scored.sort(key=lambda x: x['final_score'], reverse=True)
    return scored


# ============================================================
# 信号过滤与输出
# ============================================================

def filter_signals(scored_signals: List[Dict], min_score: float = 50) -> List[Dict]:
    """过滤低于最低分数的信号"""
    return [s for s in scored_signals if s['final_score'] >= min_score]


def build_signal_dataframe(
    stock_code: str,
    stock_name: str,
    market: str,
    scored_signals: List[Dict],
    current_price: float = None,
) -> pd.DataFrame:
    """将信号列表构建为 DataFrame"""
    rows = []
    for s in scored_signals:
        rows.append({
            '股票代码': stock_code,
            '股票名称': stock_name,
            '市场': market,
            '当前价格': current_price,
            '信号类型': _signal_type_cn(s['type']),
            '信号日期': s['date'],
            '信号价格': s['price'],
            '综合评分': s['final_score'],
            'MACD确认': '是' if s['macd_confirm'] else '否',
            '量能确认': '是' if s['volume_confirm'] else '否',
            '描述': s['description'],
        })
    return pd.DataFrame(rows)


def _signal_type_cn(signal_type: str) -> str:
    """信号类型中文映射"""
    mapping = {
        'buy_1': '一类买点',
        'buy_2': '二类买点',
        'buy_2_like': '类二买',
        'sell_1': '一类卖点',
        'sell_2': '二类卖点',
    }
    return mapping.get(signal_type, signal_type)


# ============================================================
# 信号保存
# ============================================================

def save_signals(
    all_signals_df: pd.DataFrame,
    output_dir: str,
    prefix: str,
    signal_date: str,
) -> str:
    """保存信号到CSV文件"""
    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, f"{prefix}_{signal_date}.csv")

    if not all_signals_df.empty:
        all_signals_df.to_csv(filepath, encoding='utf-8-sig', index=False)
        print(f"信号已保存: {filepath} ({os.path.getsize(filepath)} bytes)")
    else:
        print("无有效信号，未生成文件")

    return filepath


# ============================================================
# 信号展示
# ============================================================

def display_signals(all_signals_df: pd.DataFrame):
    """在终端展示信号摘要"""
    if all_signals_df.empty:
        print("无有效信号")
        return

    buy_signals = all_signals_df[all_signals_df['信号类型'].str.contains('买点')]
    sell_signals = all_signals_df[all_signals_df['信号类型'].str.contains('卖点')]

    print(f"\n{'='*70}")
    print(f"自选股监控 - 信号汇总")
    print(f"{'='*70}")

    if not buy_signals.empty:
        print(f"\n买入信号 ({len(buy_signals)} 个):")
        display_cols = ['股票代码', '股票名称', '信号类型', '信号价格', '综合评分', 'MACD确认']
        available = [c for c in display_cols if c in buy_signals.columns]
        show_df = buy_signals[available].copy()
        show_df['综合评分'] = show_df['综合评分'].apply(lambda x: f"{x:.1f}")
        show_df['信号价格'] = show_df['信号价格'].apply(lambda x: f"{x:.2f}")
        print(show_df.to_string(index=False))

    if not sell_signals.empty:
        print(f"\n卖出信号 ({len(sell_signals)} 个):")
        display_cols = ['股票代码', '股票名称', '信号类型', '信号价格', '综合评分', 'MACD确认']
        available = [c for c in display_cols if c in sell_signals.columns]
        show_df = sell_signals[available].copy()
        show_df['综合评分'] = show_df['综合评分'].apply(lambda x: f"{x:.1f}")
        show_df['信号价格'] = show_df['信号价格'].apply(lambda x: f"{x:.2f}")
        print(show_df.to_string(index=False))

    print(f"\n{'='*70}")


if __name__ == "__main__":
    # 模块测试
    test_signal = Signal(
        type="buy_2",
        date="20260607",
        price=15.50,
        score=75.0,
        description="测试二类买点",
        macd_confirm=True,
    )
    scored = score_signals([test_signal])
    print("评分结果:", scored)
