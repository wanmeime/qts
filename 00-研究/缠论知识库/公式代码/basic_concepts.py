# -*- coding: utf-8 -*-
"""
缠论基础概念模块

包含：
1. K线包含处理
2. 分型识别（顶分型、底分型）
3. 笔划分（交替分型、最小间距）

参考章节：第62课、第65课
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import List, Tuple, Optional
from enum import Enum


# ==================== 枚举和数据结构 ====================

class Direction(Enum):
    """方向"""
    UP = 1
    DOWN = -1
    NEUTRAL = 0


class FractalType(Enum):
    """分型类型"""
    TOP = "top"       # 顶分型
    BOTTOM = "bottom"  # 底分型


@dataclass
class RawKline:
    """原始K线"""
    index: int
    timestamp: str
    open: float
    high: float
    low: float
    close: float


@dataclass
class ProcessedKline:
    """处理后的K线（经过包含处理）"""
    index: int
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    raw_indices: List[int] = field(default_factory=list)  # 对应的原始K线索引

    @property
    def mid(self) -> float:
        return (self.high + self.low) / 2


@dataclass
class Fractal:
    """分型"""
    index: int           # 在处理后K线中的位置
    timestamp: str
    type: FractalType
    price: float         # 顶分型取high，底分型取low
    kline: ProcessedKline


@dataclass
class Bi:
    """笔"""
    start_fractal: Fractal
    end_fractal: Fractal
    direction: Direction
    start_index: int
    end_index: int

    @property
    def high(self) -> float:
        return max(self.start_fractal.price, self.end_fractal.price)

    @property
    def low(self) -> float:
        return min(self.start_fractal.price, self.end_fractal.price)

    @property
    def length(self) -> float:
        """笔的幅度"""
        return abs(self.end_fractal.price - self.start_fractal.price)


# ==================== K线包含处理 ====================

def process_klines(df: pd.DataFrame) -> List[ProcessedKline]:
    """
    K线包含处理

    规则（第62、65课）：
    - 向上趋势：取并集（高点取最高，低点取最高）
    - 向下趋势：取交集（高点取最低，低点取最低）

    包含关系：一根K线的高低点全在另一根的范围内

    参数：
        df: 包含 open, high, low, close 列的DataFrame

    返回：
        处理后的K线列表
    """
    if len(df) < 3:
        return []

    processed = []
    current_high = df['high'].iloc[0]
    current_low = df['low'].iloc[0]
    current_open = df['open'].iloc[0]
    current_close = df['close'].iloc[0]
    raw_indices = [0]

    # 初始方向判断
    if df['close'].iloc[0] >= df['open'].iloc[0]:
        direction = Direction.UP
    else:
        direction = Direction.DOWN

    for i in range(1, len(df)):
        high = df['high'].iloc[i]
        low = df['low'].iloc[i]

        # 检查是否包含关系
        is_contain = (high >= current_high and low <= current_low) or \
                     (high <= current_high and low >= current_low)

        if is_contain:
            # 包含关系处理
            if direction == Direction.UP:
                # 向上取并集
                current_high = max(current_high, high)
                current_low = max(current_low, low)
            else:
                # 向下取交集
                current_high = min(current_high, high)
                current_low = min(current_low, low)
            raw_indices.append(i)
        else:
            # 不包含，保存当前K线
            timestamp = str(df.index[i]) if hasattr(df.index[i], 'strftime') else str(df.index[i])
            processed.append(ProcessedKline(
                index=len(processed),
                timestamp=timestamp,
                open=current_open,
                high=current_high,
                low=current_low,
                close=current_close,
                raw_indices=raw_indices.copy()
            ))
            # 更新方向
            if high > current_high:
                direction = Direction.UP
            else:
                direction = Direction.DOWN
            current_high = high
            current_low = low
            current_open = df['open'].iloc[i]
            current_close = df['close'].iloc[i]
            raw_indices = [i]

    # 保存最后一根
    timestamp = str(df.index[-1]) if hasattr(df.index[-1], 'strftime') else str(df.index[-1])
    processed.append(ProcessedKline(
        index=len(processed),
        timestamp=timestamp,
        open=current_open,
        high=current_high,
        low=current_low,
        close=current_close,
        raw_indices=raw_indices
    ))

    return processed


# ==================== 分型识别 ====================

def find_fractals(klines: List[ProcessedKline]) -> List[Fractal]:
    """
    分型识别

    顶分型：中间K线的高点最高，低点也最高（第62课图1）
    底分型：中间K线的低点最低，高点也最低（第62课图2）

    参数：
        klines: 经过包含处理的K线列表

    返回：
        分型列表
    """
    if len(klines) < 3:
        return []

    fractals = []

    for i in range(1, len(klines) - 1):
        prev = klines[i - 1]
        curr = klines[i]
        next_ = klines[i + 1]

        # 顶分型：中间K线高点最高，低点也最高
        if curr.high > prev.high and curr.high > next_.high and \
           curr.low > prev.low and curr.low > next_.low:
            fractals.append(Fractal(
                index=i,
                timestamp=curr.timestamp,
                type=FractalType.TOP,
                price=curr.high,
                kline=curr
            ))

        # 底分型：中间K线低点最低，高点也最低
        if curr.low < prev.low and curr.low < next_.low and \
           curr.high < prev.high and curr.high < next_.high:
            fractals.append(Fractal(
                index=i,
                timestamp=curr.timestamp,
                type=FractalType.BOTTOM,
                price=curr.low,
                kline=curr
            ))

    return fractals


# ==================== 笔划分 ====================

def find_bis(fractals: List[Fractal], min_gap: int = 4) -> List[Bi]:
    """
    笔划分

    规则（第62、65课）：
    1. 分型必须交替（顶-底-顶-底）
    2. 相邻分型之间至少有 min_gap 根处理后K线
    3. 顶分型的高点高于底分型的低点
    4. 顶和底之间必须至少有一根独立K线

    参数：
        fractals: 分型列表
        min_gap: 相邻分型之间的最小K线间距（默认4）

    返回：
        笔列表
    """
    if len(fractals) < 2:
        return []

    # 第一步：筛选有效分型，确保交替
    valid_fractals = [fractals[0]]

    for i in range(1, len(fractals)):
        curr = fractals[i]
        prev = valid_fractals[-1]

        # 同类型分型，取更极端的
        if curr.type == prev.type:
            if curr.type == FractalType.TOP:
                if curr.price > prev.price:
                    valid_fractals[-1] = curr
            else:  # BOTTOM
                if curr.price < prev.price:
                    valid_fractals[-1] = curr
            continue

        # 检查最小间距
        gap = abs(curr.index - prev.index)
        if gap < min_gap:
            continue

        valid_fractals.append(curr)

    # 第二步：构建笔
    bis = []
    for i in range(1, len(valid_fractals)):
        start = valid_fractals[i - 1]
        end = valid_fractals[i]

        if start.type == FractalType.BOTTOM and end.type == FractalType.TOP:
            direction = Direction.UP
        elif start.type == FractalType.TOP and end.type == FractalType.BOTTOM:
            direction = Direction.DOWN
        else:
            continue

        bis.append(Bi(
            start_fractal=start,
            end_fractal=end,
            direction=direction,
            start_index=start.index,
            end_index=end.index
        ))

    return bis


# ==================== 完整分析 ====================

def analyze_basic(df: pd.DataFrame, min_gap: int = 4) -> dict:
    """
    基础分析：K线包含处理 -> 分型识别 -> 笔划分

    参数：
        df: 包含 open, high, low, close 列的DataFrame
        min_gap: 笔的最小间距

    返回：
        包含 processed_klines, fractals, bis 的字典
    """
    processed_klines = process_klines(df)
    fractals = find_fractals(processed_klines)
    bis = find_bis(fractals, min_gap=min_gap)

    return {
        'processed_klines': processed_klines,
        'fractals': fractals,
        'bis': bis
    }


# ==================== 工具函数 ====================

def bi_high(bi: Bi) -> float:
    """获取笔的最高点"""
    return max(bi.start_fractal.price, bi.end_fractal.price)


def bi_low(bi: Bi) -> float:
    """获取笔的最低点"""
    return min(bi.start_fractal.price, bi.end_fractal.price)


def bi_direction(bi: Bi) -> Direction:
    """获取笔的方向"""
    return bi.direction


def get_up_bis(bis: List[Bi]) -> List[Bi]:
    """获取所有向上笔"""
    return [bi for bi in bis if bi.direction == Direction.UP]


def get_down_bis(bis: List[Bi]) -> List[Bi]:
    """获取所有向下笔"""
    return [bi for bi in bis if bi.direction == Direction.DOWN]


if __name__ == "__main__":
    # 示例用法
    import pandas as pd

    # 创建示例数据
    dates = pd.date_range('2024-01-01', periods=50, freq='D')
    np.random.seed(42)
    close = 100 + np.cumsum(np.random.randn(50) * 2)
    high = close + np.abs(np.random.randn(50))
    low = close - np.abs(np.random.randn(50))
    open_ = close + np.random.randn(50) * 0.5

    df = pd.DataFrame({
        'open': open_,
        'high': high,
        'low': low,
        'close': close
    }, index=dates)

    result = analyze_basic(df)

    print(f"处理后K线数: {len(result['processed_klines'])}")
    print(f"分型数: {len(result['fractals'])}")
    print(f"笔数: {len(result['bis'])}")

    for bi in result['bis']:
        print(f"  {bi.direction.name}: {bi.start_fractal.price:.2f} -> {bi.end_fractal.price:.2f}")
