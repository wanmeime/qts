# -*- coding: utf-8 -*-
"""
分型、笔、线段完整算法模块

包含：
1. K线包含处理（向上取并集、向下取交集）
2. 分型识别（顶分型、底分型）
3. 笔划分（顶底交替、最小间距）
4. 线段识别（特征序列、线段破坏两种情形）
5. 特征序列包含处理与非包含处理
6. 线段破坏的有缺口/无缺口两种情形

参考章节：第62、65、67、71、77课
"""

import numpy as np
from typing import List, Tuple, Optional
from dataclasses import dataclass, field
from enum import Enum


# ==================== 枚举和数据结构 ====================

class Direction(Enum):
    UP = 1        # 向上
    DOWN = -1     # 向下
    NEUTRAL = 0   # 中性


class FractalType(Enum):
    TOP = "top"       # 顶分型
    BOTTOM = "bottom"  # 底分型


class SegmentBreakType(Enum):
    """线段破坏类型"""
    NO_GAP = "no_gap"          # 第一种情况：无缺口
    WITH_GAP = "with_gap"      # 第二种情况：有缺口
    NOT_BROKEN = "not_broken"  # 未破坏


@dataclass
class Kline:
    """K线数据"""
    index: int
    high: float
    low: float
    open: float
    close: float

    @property
    def mid(self) -> float:
        return (self.high + self.low) / 2

    @property
    def range(self) -> float:
        return self.high - self.low


@dataclass
class ProcessedKline:
    """处理后的K线（经过包含处理）"""
    index: int
    high: float
    low: float
    open: float
    close: float
    raw_indices: List[int] = field(default_factory=list)


@dataclass
class Fractal:
    """分型"""
    index: int
    type: FractalType
    price: float       # 顶分型取high，底分型取low
    kline: ProcessedKline


@dataclass
class Bi:
    """笔"""
    start: Fractal
    end: Fractal
    direction: Direction
    start_index: int
    end_index: int

    @property
    def high(self) -> float:
        return max(self.start.price, self.end.price)

    @property
    def low(self) -> float:
        return min(self.start.price, self.end.price)

    @property
    def length(self) -> float:
        return abs(self.end.price - self.start.price)


@dataclass
class Segment:
    """线段"""
    start_bi_index: int     # 起始笔的索引
    end_bi_index: int       # 结束笔的索引
    start_index: int        # 起始位置
    end_index: int          # 结束位置
    direction: Direction
    high: float             # 线段最高点
    low: float              # 线段最低点
    bis: List[Bi] = field(default_factory=list)  # 组成线段的笔列表

    # 特征序列（第67课）
    # 向上线段的特征序列 = 向下的笔构成的序列
    # 向下线段的特征序列 = 向上的笔构成的序列
    feature_sequence: List[Bi] = field(default_factory=list)

    @property
    def bi_count(self) -> int:
        return len(self.bis)

    @property
    def is_valid(self) -> bool:
        """线段至少由三笔组成"""
        return len(self.bis) >= 3

    def is_up(self) -> bool:
        return self.direction == Direction.UP

    def is_down(self) -> bool:
        return self.direction == Direction.DOWN


# ==================== K线包含处理 ====================

def process_klines(klines: List[Kline]) -> List[ProcessedKline]:
    """
    K线包含处理（第62、65课）

    规则：
    - 向上趋势：取并集（高点取最高，低点取最高）
    - 向下趋势：取交集（高点取最低，低点取最低）

    包含关系：一根K线的高低点全在另一根的范围内

    处理顺序（结合律）：
    1. 先处理第1、2根K线的包含关系，得到新K线
    2. 用新K线与第3根比较
    3. 如有包含关系，继续结合
    4. 如无包含关系，按正常K线处理
    """
    if len(klines) < 3:
        return []

    processed = []
    current_high = klines[0].high
    current_low = klines[0].low
    current_open = klines[0].open
    current_close = klines[0].close
    raw_indices = [klines[0].index]

    # 初始方向判断
    if klines[0].close >= klines[0].open:
        direction = Direction.UP
    else:
        direction = Direction.DOWN

    for i in range(1, len(klines)):
        k = klines[i]

        # 检查是否包含关系
        is_contain = (
            (k.high >= current_high and k.low <= current_low) or
            (k.high <= current_high and k.low >= current_low)
        )

        if is_contain:
            # 包含关系处理
            if direction == Direction.UP:
                # 向上取并集：高点取最高，低点取最高
                current_high = max(current_high, k.high)
                current_low = max(current_low, k.low)
            else:
                # 向下取交集：高点取最低，低点取最低
                current_high = min(current_high, k.high)
                current_low = min(current_low, k.low)
            raw_indices.append(k.index)
        else:
            # 不包含，保存当前K线
            processed.append(ProcessedKline(
                index=len(processed),
                high=current_high,
                low=current_low,
                open=current_open,
                close=current_close,
                raw_indices=raw_indices.copy(),
            ))
            # 更新方向
            direction = Direction.UP if k.high > current_high else Direction.DOWN
            current_high = k.high
            current_low = k.low
            current_open = k.open
            current_close = k.close
            raw_indices = [k.index]

    # 保存最后一根
    processed.append(ProcessedKline(
        index=len(processed),
        high=current_high,
        low=current_low,
        open=current_open,
        close=current_close,
        raw_indices=raw_indices,
    ))

    return processed


# ==================== 分型识别 ====================

def find_fractals(klines: List[ProcessedKline]) -> List[Fractal]:
    """
    分型识别（第62课）

    顶分型：中间K线的高点最高，低点也最高
    底分型：中间K线的低点最低，高点也最低

    经过包含处理后的K线，三相邻K线有完全分类：
    1. 上升K线
    2. 顶分型
    3. 下降K线
    4. 底分型
    """
    if len(klines) < 3:
        return []

    fractals = []

    for i in range(1, len(klines) - 1):
        prev = klines[i - 1]
        curr = klines[i]
        next_ = klines[i + 1]

        # 顶分型：中间K线高点最高，低点也最高
        if (curr.high > prev.high and curr.high > next_.high and
                curr.low > prev.low and curr.low > next_.low):
            fractals.append(Fractal(
                index=i,
                type=FractalType.TOP,
                price=curr.high,
                kline=curr,
            ))

        # 底分型：中间K线低点最低，高点也最低
        if (curr.low < prev.low and curr.low < next_.low and
                curr.high < prev.high and curr.high < next_.high):
            fractals.append(Fractal(
                index=i,
                type=FractalType.BOTTOM,
                price=curr.low,
                kline=curr,
            ))

    return fractals


# ==================== 笔划分 ====================

def find_bis(
    fractals: List[Fractal],
    min_gap: int = 4
) -> List[Bi]:
    """
    笔划分（第62、65课）

    规则：
    1. 分型必须交替（顶-底-顶-底）
    2. 相邻分型之间至少有 min_gap 根处理后K线
    3. 同类型分型相邻时，取更极端的
    4. 顶和底之间必须至少有一根独立K线
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

        # 检查最小间距（顶和底之间必须至少有一根独立K线）
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
            start=start,
            end=end,
            direction=direction,
            start_index=start.index,
            end_index=end.index,
        ))

    return bis


# ==================== 特征序列处理 ====================

def build_feature_sequence(segment_bis: List[Bi]) -> List[Bi]:
    """
    构建线段的特征序列（第67课）

    以向上笔开始的线段：特征序列 = 向下的笔构成的序列 X1X2...Xn
    以向下笔开始的线段：特征序列 = 向上的笔构成的序列 S1S2...Sn

    特征序列的元素方向与线段方向相反。

    参数：
        segment_bis: 构成线段的笔列表

    返回：
        特征序列（Bi列表）
    """
    if len(segment_bis) < 2:
        return []

    # 确定线段方向
    first_bi = segment_bis[0]
    segment_dir = first_bi.direction

    # 特征序列元素 = 与线段方向相反的笔
    feature_seq = []
    for bi in segment_bis:
        if bi.direction != segment_dir:
            feature_seq.append(bi)

    return feature_seq


def process_feature_contain(
    feature_seq: List[Bi]
) -> List[Bi]:
    """
    特征序列的包含处理（第67课）

    把特征序列的每一个元素看成一根K线，
    （以上涨线段为例，特征序列是向下的笔）
    以笔的起点和终点作为"高低点"，
    按照普通K线包含处理规则进行非包含处理。

    注意：特征序列元素的包含关系前提是必须在同一特征序列里。
    不同特征序列之间的元素讨论包含关系没有意义。
    """
    if len(feature_seq) < 2:
        return feature_seq

    result = [feature_seq[0]]

    for i in range(1, len(feature_seq)):
        prev = result[-1]
        curr = feature_seq[i]

        # 以笔的起点和终点构造"K线"的高点和低点
        prev_high = max(prev.start.price, prev.end.price)
        prev_low = min(prev.start.price, prev.end.price)
        curr_high = max(curr.start.price, curr.end.price)
        curr_low = min(curr.start.price, curr.end.price)

        # 检查是否包含
        is_contain = (
            (curr_high >= prev_high and curr_low <= prev_low) or
            (curr_high <= prev_high and curr_low >= prev_low)
        )

        if is_contain:
            # 确定方向（用前一个非包含元素判断）
            if len(result) >= 2:
                prev2 = result[-2]
                p2_high = max(prev2.start.price, prev2.end.price)
                p2_low = min(prev2.start.price, prev2.end.price)
                if prev_high > p2_high:
                    # 向上：取并集
                    merged = prev
                    merged.end = curr.end if abs(curr.end.price) > abs(prev.end.price) else prev.end
                    result[-1] = merged
                else:
                    # 向下：取交集
                    if abs(curr.end.price) < abs(prev.end.price):
                        result[-1] = curr
            else:
                # 只有两个元素时，保留更极端的
                result[-1] = curr
        else:
            result.append(curr)

    return result


# ==================== 线段识别 ====================

def find_fractal_on_feature(
    feature_seq: List[Bi],
    segment_dir: Direction
) -> Tuple[bool, int, SegmentBreakType, bool]:
    """
    在特征序列上寻找分型，判断线段是否结束（第67课）

    参照一般K线图关于顶分型与底分型的定义：
    - 以向上笔开始的线段，只考察顶分型
    - 以向下笔开始的线段，只考察底分型

    两种情况：
    1. 无缺口：第一和第二元素间不存在特征序列的缺口
    2. 有缺口：第一和第二元素间存在特征序列的缺口

    返回：
        (是否结束, 结束位置索引, 破坏类型, 是否有缺口)
    """
    if len(feature_seq) < 3:
        return False, -1, SegmentBreakType.NOT_BROKEN, False

    for i in range(1, len(feature_seq) - 1):
        prev = feature_seq[i - 1]
        curr = feature_seq[i]
        next_ = feature_seq[i + 1]

        # 计算每个特征序列元素的"高低点"
        prev_high = max(prev.start.price, prev.end.price)
        prev_low = min(prev.start.price, prev.end.price)
        curr_high = max(curr.start.price, curr.end.price)
        curr_low = min(curr.start.price, curr.end.price)
        next_high = max(next_.start.price, next_.end.price)
        next_low = min(next_.start.price, next_.end.price)

        # 检查是否有缺口（第一和第二元素间无重合区间）
        has_gap = (prev_low > curr_high)

        if segment_dir == Direction.UP:
            # 向上一笔开始的线段：找特征序列顶分型
            is_top = (
                curr_high > prev_high and curr_high > next_high and
                curr_low > prev_low and curr_low > next_low
            )
            if is_top:
                if not has_gap:
                    # 第一种情况：无缺口，线段在顶分型高点处结束
                    return True, i, SegmentBreakType.NO_GAP, False
                else:
                    # 第二种情况：有缺口
                    # 需要从该分型最高点后的向下笔开始，
                    # 其后的特征序列出现底分型才能确认
                    return True, i, SegmentBreakType.WITH_GAP, True
        else:
            # 向下一笔开始的线段：找特征序列底分型
            is_bottom = (
                curr_low < prev_low and curr_low < next_low and
                curr_high < prev_high and curr_high < next_high
            )
            if is_bottom:
                if not has_gap:
                    return True, i, SegmentBreakType.NO_GAP, False
                else:
                    return True, i, SegmentBreakType.WITH_GAP, True

    return False, -1, SegmentBreakType.NOT_BROKEN, False


def find_segments(bis: List[Bi]) -> List[Segment]:
    """
    从笔序列中识别线段（第62、67、71课）

    规则：
    1. 线段至少由三笔组成
    2. 线段必须被线段破坏才算结束
    3. 线段开始的那三笔必须有重合
    4. 线段中包含笔的数目都是单数的
    5. 线段被线段破坏必须是被不同性质的线段破坏

    返回：
        线段列表
    """
    if len(bis) < 3:
        return []

    segments = []
    current_bis: List[Bi] = [bis[0]]
    current_dir = bis[0].direction

    for i in range(1, len(bis)):
        bi = bis[i]
        current_bis.append(bi)

        if len(current_bis) < 3:
            continue

        # 检查前三笔是否有重合
        if len(current_bis) == 3:
            highs = [b.high for b in current_bis]
            lows = [b.low for b in current_bis]
            if max(lows) >= min(highs):
                # 三笔有重合，形成线段基础
                continue
            else:
                # 前三笔无重合，不能构成线段
                current_bis = [bis[i - 1], bis[i]]
                current_dir = bis[i].direction
                continue  # 实际上是标准答案的笔合并情况

        # 检查方向是否一致（线段中的笔方向交替）
        if bi.direction == current_dir:
            # 同向笔连续 — 延伸线段
            continue

        # 方向改变 → 检查是否形成新线段
        # 构建特征序列判断
        feature_seq = build_feature_sequence(current_bis)
        if len(feature_seq) < 3:
            continue

        # 处理后特征序列（去除包含关系）
        processed_seq = process_feature_contain(feature_seq)

        # 在特征序列上找分型
        is_ended, end_pos, break_type, has_gap = find_fractal_on_feature(
            processed_seq, current_dir
        )

        if is_ended:
            # 当前线段结束
            end_bi_idx = len(current_bis) - 1  # 简化处理

            seg_high = max(b.high for b in current_bis)
            seg_low = min(b.low for b in current_bis)

            seg = Segment(
                start_bi_index=len(segments),  # 近似
                end_bi_index=end_bi_idx,
                start_index=current_bis[0].start_index,
                end_index=current_bis[-1].end_index,
                direction=current_dir,
                high=seg_high,
                low=seg_low,
                bis=current_bis.copy(),
                feature_sequence=feature_seq,
            )

            if seg.is_valid:
                segments.append(seg)

            # 开始新线段
            # 从破坏笔开始
            remaining = current_bis[-2:] if len(current_bis) >= 2 else [current_bis[-1]]
            current_bis = remaining
            current_dir = bis[i - 1].direction if len(remaining) >= 2 else bi.direction
        else:
            # 线段尚未结束，继续延伸
            continue

    # 处理最后的未完成线段
    if len(current_bis) >= 3:
        seg_high = max(b.high for b in current_bis)
        seg_low = min(b.low for b in current_bis)
        seg = Segment(
            start_bi_index=len(segments),
            end_bi_index=len(bis) - 1,
            start_index=current_bis[0].start_index,
            end_index=current_bis[-1].end_index,
            direction=current_dir,
            high=seg_high,
            low=seg_low,
            bis=current_bis,
        )
        if seg.is_valid:
            segments.append(seg)

    return segments


# ==================== 完整分析 ====================

def analyze_full(klines: List[Kline], min_bi_gap: int = 4) -> dict:
    """
    完整分析流程：K线包含处理 → 分型识别 → 笔划分 → 线段识别

    参数：
        klines: K线列表
        min_bi_gap: 笔的最小K线间距

    返回：
        包含 processed_klines, fractals, bis, segments 的字典
    """
    processed_klines = process_klines(klines)
    fractals = find_fractals(processed_klines)
    bis = find_bis(fractals, min_gap=min_bi_gap)
    segments = find_segments(bis)

    return {
        "processed_klines": processed_klines,
        "fractals": fractals,
        "bis": bis,
        "segments": segments,
    }


def analyze_summary(result: dict) -> str:
    """生成分析摘要"""
    lines = ["=== 分型-笔-线段分析结果 ==="]
    lines.append(f"处理后K线: {len(result['processed_klines'])} 根")
    lines.append(f"分型: {len(result['fractals'])} 个")

    top_count = sum(1 for f in result['fractals'] if f.type == FractalType.TOP)
    bot_count = sum(1 for f in result['fractals'] if f.type == FractalType.BOTTOM)
    lines.append(f"  顶分型: {top_count} | 底分型: {bot_count}")

    lines.append(f"笔: {len(result['bis'])} 条")
    up_bis = sum(1 for b in result['bis'] if b.direction == Direction.UP)
    down_bis = sum(1 for b in result['bis'] if b.direction == Direction.DOWN)
    lines.append(f"  向上笔: {up_bis} | 向下笔: {down_bis}")

    lines.append(f"线段: {len(result['segments'])} 条")
    for i, seg in enumerate(result['segments']):
        dir_label = "↑" if seg.direction == Direction.UP else "↓"
        lines.append(
            f"  [{i}] {dir_label} 笔数:{seg.bi_count} "
            f"区间:[{seg.low:.2f}, {seg.high:.2f}]"
        )

    return "\n".join(lines)


if __name__ == "__main__":
    print("分型-笔-线段分析模块加载成功")
    print("功能:")
    print("  1. K线包含处理")
    print("  2. 分型识别（顶分型/底分型）")
    print("  3. 笔划分")
    print("  4. 线段识别（特征序列+两种情况）")
    print(f"\n示例: {analyze_full.__doc__}")
