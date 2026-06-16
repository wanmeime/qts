#!/usr/bin/env python3
"""
缠论分析模块
============

实现缠论基础分析功能：
- K线包含处理
- 分型识别（顶分型、底分型）
- 笔的划分
- 中枢识别
- 买点/卖点识别（一买、二买、类二买、一卖、二卖）
- MACD 辅助判断（背驰检测）

数据输入:
    pandas DataFrame，包含 date, open, close, high, low, amount 列

作者: QTS量化交易系统
日期: 2026-06-07
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


# ============================================================
# 数据结构
# ============================================================

@dataclass
class Kline:
    """处理后的K线（经过包含处理）"""
    index: int
    date: str
    high: float
    low: float
    open: float
    close: float
    direction: int = 0  # 1=向上, -1=向下, 0=未定


@dataclass
class Fractal:
    """分型"""
    index: int          # 在处理后K线序列中的位置
    date: str
    price: float        # 顶分型取high, 底分型取low
    type: str           # "top" 或 "bottom"
    kline_left: Kline = None
    kline_mid: Kline = None
    kline_right: Kline = None


@dataclass
class Bi:
    """笔"""
    start: Fractal
    end: Fractal
    direction: int      # 1=向上笔, -1=向下笔
    kline_count: int    # 包含的K线数量


@dataclass
class ZhongShu:
    """中枢"""
    start_index: int
    end_index: int
    high: float         # 中枢上沿
    low: float          # 中枢下沿
    bi_list: List[Bi] = field(default_factory=list)
    level: int = 1      # 中枢级别


@dataclass
class Signal:
    """买卖信号"""
    type: str           # "buy_1", "buy_2", "buy_2_like", "sell_1", "sell_2"
    date: str
    price: float
    score: float        # 信号强度 0-100
    description: str
    macd_confirm: bool = False
    volume_confirm: bool = False


# ============================================================
# MACD 计算
# ============================================================

def calc_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """计算 MACD 指标"""
    close = df['close'].astype(float)
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    macd_hist = 2 * (dif - dea)

    result = df.copy()
    result['dif'] = dif
    result['dea'] = dea
    result['macd'] = macd_hist
    return result


def macd_area(macd_hist: pd.Series, start: int, end: int) -> float:
    """计算两个索引之间的 MACD 柱状图面积（绝对值之和）"""
    segment = macd_hist.iloc[start:end + 1]
    return float(segment.abs().sum())


# ============================================================
# K线包含处理
# ============================================================

def merge_klines(df: pd.DataFrame) -> List[Kline]:
    """
    K线包含处理。

    包含关系定义：
    - K1 包含 K2：K1.high >= K2.high 且 K1.low <= K2.low
    - K2 包含 K1：K2.high >= K1.high 且 K2.low <= K1.low

    处理方式：
    - 向上趋势中取并集（高取高，低取高）
    - 向下趋势中取交集（高取低，低取低）
    """
    if len(df) < 3:
        return []

    klines = []
    for i, row in df.iterrows():
        klines.append(Kline(
            index=i,
            date=str(row['date']),
            high=float(row['high']),
            low=float(row['low']),
            open=float(row['open']),
            close=float(row['close']),
        ))

    merged = [klines[0]]
    for k in klines[1:]:
        prev = merged[-1]

        # 判断包含关系
        is_inclusion = (
            (prev.high >= k.high and prev.low <= k.low) or
            (k.high >= prev.high and k.low <= prev.low)
        )

        if is_inclusion:
            # 确定方向
            if len(merged) >= 2:
                direction = 1 if merged[-1].high > merged[-2].high else -1
            else:
                direction = 1 if k.close > k.open else -1

            if direction == 1:  # 向上：取并集
                prev.high = max(prev.high, k.high)
                prev.low = max(prev.low, k.low)
            else:  # 向下：取交集
                prev.high = min(prev.high, k.high)
                prev.low = min(prev.low, k.low)
        else:
            klines_merged = [m for m in merged[-3:]] + [k]
            if len(klines_merged) >= 2:
                if klines_merged[-1].high > klines_merged[-2].high:
                    k.direction = 1
                else:
                    k.direction = -1
            merged.append(k)

    # 重新编号
    for i, k in enumerate(merged):
        k.index = i

    return merged


# ============================================================
# 分型识别
# ============================================================

def find_fractals(klines: List[Kline]) -> List[Fractal]:
    """
    识别顶分型和底分型。

    顶分型：中间K线的高点是三根中最高的
    底分型：中间K线的低点是三根中最低的
    """
    if len(klines) < 3:
        return []

    fractals = []
    for i in range(1, len(klines) - 1):
        left, mid, right = klines[i - 1], klines[i], klines[i + 1]

        # 顶分型
        if mid.high > left.high and mid.high > right.high:
            fractals.append(Fractal(
                index=i,
                date=mid.date,
                price=mid.high,
                type="top",
                kline_left=left,
                kline_mid=mid,
                kline_right=right,
            ))

        # 底分型
        elif mid.low < left.low and mid.low < right.low:
            fractals.append(Fractal(
                index=i,
                date=mid.date,
                price=mid.low,
                type="bottom",
                kline_left=left,
                kline_mid=mid,
                kline_right=right,
            ))

    return fractals


# ============================================================
# 笔的划分
# ============================================================

def build_bi_list(fractals: List[Fractal], min_kline_count: int = 4) -> List[Bi]:
    """
    根据分型序列构建笔。

    规则：
    - 顶分型和底分型必须交替出现
    - 两个分型之间至少有 min_kline_count 根K线
    - 向上笔：底分型 -> 顶分型
    - 向下笔：顶分型 -> 底分型
    """
    if len(fractals) < 2:
        return []

    # 确保分型交替
    filtered = [fractals[0]]
    for f in fractals[1:]:
        if f.type != filtered[-1].type:
            # 检查距离
            if f.index - filtered[-1].index >= min_kline_count:
                filtered.append(f)
            else:
                # 距离不够，看是否能替换
                if f.type == "top" and f.price > filtered[-1].price:
                    filtered[-1] = f
                elif f.type == "bottom" and f.price < filtered[-1].price:
                    filtered[-1] = f
        else:
            # 同类型，保留更极端的
            if f.type == "top" and f.price > filtered[-1].price:
                filtered[-1] = f
            elif f.type == "bottom" and f.price < filtered[-1].price:
                filtered[-1] = f

    # 构建笔
    bis = []
    for i in range(len(filtered) - 1):
        start = filtered[i]
        end = filtered[i + 1]
        direction = 1 if end.type == "top" else -1
        kline_count = end.index - start.index
        bis.append(Bi(start=start, end=end, direction=direction, kline_count=kline_count))

    return bis


# ============================================================
# 中枢识别
# ============================================================

def find_zhongshu(bis: List[Bi], min_bi_count: int = 3) -> List[ZhongShu]:
    """
    识别中枢。

    中枢定义：至少三笔有重叠区间。
    中枢区间 = 三笔重叠部分 [max(各笔低点), min(各笔高点)]
    """
    if len(bis) < min_bi_count:
        return []

    zhongshus = []
    i = 0
    while i <= len(bis) - min_bi_count:
        bi1, bi2, bi3 = bis[i], bis[i + 1], bis[i + 2]

        # 计算三笔的高低点
        highs = [max(b.start.price, b.end.price) for b in [bi1, bi2, bi3]]
        lows = [min(b.start.price, b.end.price) for b in [bi1, bi2, bi3]]

        zs_high = min(highs)  # 中枢上沿
        zs_low = max(lows)    # 中枢下沿

        if zs_high > zs_low:
            # 有效中枢
            included_bis = [bi1, bi2, bi3]

            # 尝试扩展中枢
            j = i + min_bi_count
            while j < len(bis):
                next_bi = bis[j]
                next_high = max(next_bi.start.price, next_bi.end.price)
                next_low = min(next_bi.start.price, next_bi.end.price)

                # 下一笔与中枢有重叠
                if next_low < zs_high and next_high > zs_low:
                    included_bis.append(next_bi)
                    j += 1
                else:
                    break

            zhongshus.append(ZhongShu(
                start_index=included_bis[0].start.index,
                end_index=included_bis[-1].end.index,
                high=zs_high,
                low=zs_low,
                bi_list=included_bis,
            ))
            i = j
        else:
            i += 1

    return zhongshus


# ============================================================
# 买卖点识别
# ============================================================

def find_buy_sell_signals(
    klines: List[Kline],
    fractals: List[Fractal],
    bis: List[Bi],
    zhongshus: List[ZhongShu],
    macd_df: pd.DataFrame,
    divergence_window: int = 20,
) -> List[Signal]:
    """
    识别买卖信号。

    重点识别：
    - 二类买点（二买）：一买后的回调低点
    - 类二买：上涨趋势中第一个上涨中枢的横盘突破
    - 二类卖点（二卖）
    """
    signals = []
    if len(bis) < 3 or len(zhongshus) < 1:
        return signals

    macd_hist = macd_df['macd'].values
    dif = macd_df['dif'].values

    for zs_idx, zs in enumerate(zhongshus):
        zs_bis = zs.bi_list
        if len(zs_bis) < 3:
            continue

        # === 二买识别 ===
        # 条件：中枢前有一个明显的下跌笔（一买区域），中枢内出现回调不破前低
        if zs_idx > 0 and zs_idx < len(zhongshus):
            pre_zs = zhongshus[zs_idx - 1] if zs_idx > 0 else None

            for bi in zs_bis:
                if bi.direction == -1:  # 下跌笔
                    # 检查是否在一买之后
                    bottom_fractal = bi.end
                    if bottom_fractal.type != "bottom":
                        continue

                    # 检查MACD底背驰
                    bi_end_idx = bottom_fractal.index
                    if bi_end_idx >= len(macd_hist):
                        continue

                    macd_confirmed = False
                    if bi_end_idx >= divergence_window:
                        recent_macd_area = macd_area(
                            pd.Series(macd_hist),
                            bi_end_idx - divergence_window,
                            bi_end_idx
                        )
                        prev_bi = None
                        for b in zs_bis:
                            if b.direction == -1 and b.end.index < bi.start.index:
                                prev_bi = b
                        if prev_bi:
                            prev_end = prev_bi.end.index
                            if prev_end >= divergence_window:
                                prev_macd_area = macd_area(
                                    pd.Series(macd_hist),
                                    prev_end - divergence_window,
                                    prev_end
                                )
                                if recent_macd_area < prev_macd_area * 0.8:
                                    macd_confirmed = True

                    # 二买条件：回调不破前低
                    score = 50.0
                    if macd_confirmed:
                        score += 20

                    # 检查是否有底分型确认
                    if bi_end_idx + 1 < len(klines):
                        k = klines[bi_end_idx + 1] if bi_end_idx + 1 < len(klines) else None
                        if k and k.high > klines[bi_end_idx].high:
                            score += 15

                    if score >= 50:
                        signals.append(Signal(
                            type="buy_2",
                            date=bottom_fractal.date,
                            price=bottom_fractal.price,
                            score=min(score, 100),
                            description=f"二类买点: 回调不破前低，MACD{'确认' if macd_confirmed else '未确认'}",
                            macd_confirm=macd_confirmed,
                        ))

        # === 类二买识别 ===
        # 条件：上涨中枢（上下上结构），中枢内横盘后向上突破
        if len(zs_bis) >= 3:
            first_three = zs_bis[:3]
            # 上下上结构
            if (first_three[0].direction == 1 and
                first_three[1].direction == -1 and
                first_three[2].direction == 1):

                # 检查中枢内横盘
                zs_range = zs.high - zs.low
                avg_price = (zs.high + zs.low) / 2
                if avg_price > 0 and zs_range / avg_price < 0.15:  # 振幅<15%
                    # 横盘形态，寻找突破
                    last_bi = zs_bis[-1]
                    if last_bi.direction == 1 and last_bi.end.price > zs.high:
                        score = 60.0

                        # MACD确认
                        macd_confirmed = False
                        bi_end_idx = last_bi.end.index
                        if bi_end_idx < len(dif) and bi_end_idx > 0:
                            if dif[bi_end_idx] > dif[bi_end_idx - 1]:
                                macd_confirmed = True
                                score += 15

                        # 量能确认（简化判断）
                        volume_confirmed = False
                        if bi_end_idx < len(klines) and bi_end_idx > 5:
                            recent_vol = np.mean([klines[bi_end_idx - j].high - klines[bi_end_idx - j].low
                                                   for j in range(3)])
                            prev_vol = np.mean([klines[bi_end_idx - j - 3].high - klines[bi_end_idx - j - 3].low
                                                for j in range(3)])
                            if prev_vol > 0 and recent_vol > prev_vol * 1.2:
                                volume_confirmed = True
                                score += 10

                        signals.append(Signal(
                            type="buy_2_like",
                            date=last_bi.end.date,
                            price=last_bi.end.price,
                            score=min(score, 100),
                            description=f"类二买: 上涨中枢横盘突破，MACD{'确认' if macd_confirmed else '未确认'}",
                            macd_confirm=macd_confirmed,
                            volume_confirm=volume_confirmed,
                        ))

        # === 二卖识别 ===
        # 条件：中枢后出现反弹但未突破前高
        if len(zs_bis) >= 3:
            for bi in zs_bis:
                if bi.direction == 1:  # 上涨笔
                    top_fractal = bi.end
                    if top_fractal.type != "top":
                        continue

                    # 检查是否未突破前高
                    prev_top = None
                    for b in zs_bis:
                        if b.direction == 1 and b.end.index < bi.start.index:
                            if prev_top is None or b.end.price > prev_top.price:
                                prev_top = b.end

                    if prev_top and top_fractal.price < prev_top.price:
                        # MACD顶背驰检查
                        macd_confirmed = False
                        bi_end_idx = top_fractal.index
                        if bi_end_idx >= divergence_window and bi_end_idx < len(macd_hist):
                            recent_area = macd_area(
                                pd.Series(macd_hist),
                                bi_end_idx - divergence_window,
                                bi_end_idx
                            )
                            prev_end = prev_top.index
                            if prev_end >= divergence_window and prev_end < len(macd_hist):
                                prev_area = macd_area(
                                    pd.Series(macd_hist),
                                    prev_end - divergence_window,
                                    prev_end
                                )
                                if recent_area < prev_area * 0.8:
                                    macd_confirmed = True

                        score = 55.0
                        if macd_confirmed:
                            score += 20

                        signals.append(Signal(
                            type="sell_2",
                            date=top_fractal.date,
                            price=top_fractal.price,
                            score=min(score, 100),
                            description=f"二类卖点: 反弹未破前高，MACD{'确认' if macd_confirmed else '未确认'}",
                            macd_confirm=macd_confirmed,
                        ))

    return signals


# ============================================================
# 主分析入口
# ============================================================

def analyze(df: pd.DataFrame, config: dict = None) -> dict:
    """
    对单只股票进行缠论分析。

    参数:
        df: K线数据，包含 date, open, close, high, low, amount 列
        config: 缠论分析配置（可选）

    返回:
        dict: {
            'klines': List[Kline],      # 处理后K线
            'fractals': List[Fractal],  # 分型列表
            'bis': List[Bi],            # 笔列表
            'zhongshus': List[ZhongShu],# 中枢列表
            'signals': List[Signal],    # 买卖信号
            'macd': DataFrame,          # MACD数据
            'summary': str,             # 分析摘要
        }
    """
    if config is None:
        config = {}

    macd_cfg = config.get('macd', {})
    fast = macd_cfg.get('fast', 12)
    slow = macd_cfg.get('slow', 26)
    sig = macd_cfg.get('signal', 9)
    divergence_window = config.get('divergence_window', 20)

    # 数据预处理
    df = df.copy()
    df = df.reset_index(drop=True)

    # 计算MACD
    macd_df = calc_macd(df, fast, slow, sig)

    # K线包含处理
    merged_klines = merge_klines(df)

    # 分型识别
    fractals = find_fractals(merged_klines)

    # 笔划分
    bis = build_bi_list(fractals)

    # 中枢识别
    zhongshus = find_zhongshu(bis)

    # 买卖信号
    signals = find_buy_sell_signals(
        merged_klines, fractals, bis, zhongshus, macd_df, divergence_window
    )

    # 生成摘要
    summary = _build_summary(fractals, bis, zhongshus, signals)

    return {
        'klines': merged_klines,
        'fractals': fractals,
        'bis': bis,
        'zhongshus': zhongshus,
        'signals': signals,
        'macd': macd_df,
        'summary': summary,
    }


def _build_summary(fractals, bis, zhongshus, signals) -> str:
    """生成分析摘要"""
    parts = []
    parts.append(f"分型: {len(fractals)}个 (顶{sum(1 for f in fractals if f.type=='top')} 底{sum(1 for f in fractals if f.type=='bottom')})")
    parts.append(f"笔: {len(bis)}条 (上{sum(1 for b in bis if b.direction==1)} 下{sum(1 for b in bis if b.direction==-1)})")
    parts.append(f"中枢: {len(zhongshus)}个")

    buy_signals = [s for s in signals if 'buy' in s.type]
    sell_signals = [s for s in signals if 'sell' in s.type]
    parts.append(f"信号: 买{len(buy_signals)} 卖{len(sell_signals)}")

    if signals:
        best = max(signals, key=lambda s: s.score)
        parts.append(f"最强信号: {best.type} ({best.score:.0f}分)")

    return " | ".join(parts)


if __name__ == "__main__":
    # 简单测试
    import sys
    if len(sys.argv) > 1:
        csv_path = sys.argv[1]
        test_df = pd.read_csv(csv_path)
        result = analyze(test_df)
        print(f"分析摘要: {result['summary']}")
        for s in result['signals']:
            print(f"  {s.type}: {s.date} @ {s.price:.2f} ({s.score:.0f}分) - {s.description}")
    else:
        print("用法: python 缠论分析.py <kline_csv_path>")
