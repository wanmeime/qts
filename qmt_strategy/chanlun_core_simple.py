# -*- coding: utf-8 -*-
"""
简化版缠论核心算法（专为QMT策略优化）
======================================
只包含交易系统需要的核心功能：
1. 顶底分型识别
2. 笔的识别（简化）
3. 底分型突破检测 → 买入信号
4. 顶分型二卖检测 → 卖出信号

不包含完整缠论的中枢、MACD背驰等（QMT环境运行速度优先）
"""

import numpy as np
import pandas as pd
from typing import List, Optional, Dict


def find_bottom_breakout(df: pd.DataFrame, max_lookback: int = 30) -> Optional[Dict]:
    """
    检测底分型向上突破信号（买入信号）

    逻辑：
    1. 在最近 max_lookback 根K线中找底分型
    2. 底分型：三根K线，中间最低
    3. 检查当前价格是否突破第三根K线的最高点 (third_high)
    4. 如果是，返回买入信号

    Args:
        df: DataFrame(date, open, high, low, close)
        max_lookback: 最多回看多少根K线

    Returns:
        {"third_high": float, "score": int} 或 None
    """
    if df is None or len(df) < 10:
        return None

    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    n = len(closes)

    start = max(0, n - max_lookback)
    current_close = closes[-1]

    for i in range(n - 2, start, -1):
        # 检查：三根K线，中间最低 = 底分型
        if lows[i] < lows[i-1] and lows[i] < lows[i+1]:
            third_high = highs[i+1]  # 第三根K线的高点
            # 突破确认：当前收盘价 > 第三根K线高点
            if current_close > third_high:
                # 评分：检查是否为标准买点附近（简单版：看前面有没有明显的底）
                score = 85
                if i >= 3 and lows[i] < lows[i-2] * 0.95:
                    score = 90  # 明显的底部结构
                return {
                    "third_high": third_high,
                    "index": i,
                    "score": score,
                }
            break  # 最新的底分型都没突破，更老的不看了

    return None


def find_top_erMai(df: pd.DataFrame, min_bars: int = 5) -> Optional[Dict]:
    """
    检测顶分型二卖信号（卖出信号）

    逻辑（用户实战方法）：
    1. 找一个顶部高点 H1
    2. 价格从 H1 回调
    3. 反弹到 H2，但 H2 < H1（反弹失败）
    4. 价格从 H2 再次向下拐头 → 二卖确认

    Args:
        df: DataFrame(date, open, high, low, close)
        min_bars: 两个高点之间的最少K线数

    Returns:
        {"sell_price": float, "score": int} 或 None
    """
    if df is None or len(df) < 20:
        return None

    highs = df["high"].values
    closes = df["close"].values
    n = len(highs)

    # 找最近的两个局部高点（用滑动窗口找峰）
    peaks = []
    window = 5
    for i in range(window, n - window):
        if highs[i] == max(highs[i-window:i+window+1]):
            peaks.append({"index": i, "high": highs[i]})

    if len(peaks) < 2:
        return None

    # 取最近的两个高点
    p2 = peaks[-1]  # 最新的高点
    p1 = peaks[-2]  # 前一个高点

    # 二卖条件：p2 < p1（反弹失败）且间隔足够
    if (p2["high"] < p1["high"] and 
        p2["index"] - p1["index"] >= min_bars):
        
        # 检查当前是否已在回落（拐头向下）
        current_close = closes[-1]
        p2_high_idx = p2["index"]
        p2_after_highs = highs[p2_high_idx:p2_high_idx+5]
        highest_after_p2 = max(p2_after_highs) if len(p2_after_highs) > 0 else p2["high"]
        
        # 如果当前价格已从高点回落超过1% = 拐头向下确认
        if current_close < highest_after_p2 * 0.99:
            return {
                "sell_price": highest_after_p2,
                "p1_high": p1["high"],
                "p2_high": p2["high"],
                "score": 90,
            }

    return None


def analyze_stock(df: pd.DataFrame) -> Dict:
    """
    对单只股票做完整缠论分析（买入+卖出信号）

    Args:
        df: DataFrame(date, open, high, low, close)

    Returns:
        {"buy": {...}, "sell": {...}, "name": str}
    """
    buy_signal = find_bottom_breakout(df)
    sell_signal = find_top_erMai(df)

    return {
        "buy": buy_signal,
        "sell": sell_signal,
    }
