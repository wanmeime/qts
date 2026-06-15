# -*- coding: utf-8 -*-
"""
缠论核心算法模块（重写版）

严格按照用户口述的设计逻辑实现：
1. 顶底分型识别
2. 包含关系处理
3. 笔的识别
4. 中枢识别
5. 买卖点识别
6. 趋势判断
7. 力度判断
8. 交易信号输出
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import List, Optional
from enum import Enum


class Direction(Enum):
    UP = 1
    DOWN = -1

class FractalType(Enum):
    TOP = "top"
    BOTTOM = "bottom"

class BuySellType(Enum):
    BUY1 = "buy1"
    BUY2 = "buy2"
    BUY3 = "buy3"
    SELL1 = "sell1"
    SELL2 = "sell2"
    SELL3 = "sell3"

@dataclass
class ProcessedKline:
    index: int
    timestamp: str
    high: float
    low: float
    raw_count: int

@dataclass
class Fractal:
    index: int
    timestamp: str
    type: FractalType
    price: float

@dataclass
class Bi:
    start_fractal: Fractal
    end_fractal: Fractal
    direction: Direction
    start_index: int
    end_index: int

    @property
    def high(self):
        return max(self.start_fractal.price, self.end_fractal.price)

    @property
    def low(self):
        return min(self.start_fractal.price, self.end_fractal.price)

@dataclass
class ZhongShu:
    start_bi_index: int
    end_bi_index: int
    high: float
    low: float
    direction: Direction
    bis: List[Bi] = field(default_factory=list)

@dataclass
class BuySellPoint:
    type: BuySellType
    timestamp: str
    price: float
    index: int


class ChanlunCore:
    def __init__(self):
        self.processed_klines = []
        self.fractals = []
        self.bis = []
        self.zhong_shus = []
        self.buy_sell_points = []

    def process_klines(self, df):
        if len(df) < 3:
            return []
        processed = []
        cur_high = float(df['high'].iloc[0])
        cur_low = float(df['low'].iloc[0])
        cur_ts = str(df.index[0])
        raw_count = 1
        direction = Direction.UP if len(df) >= 2 and float(df['high'].iloc[1]) > cur_high else Direction.DOWN

        for i in range(1, len(df)):
            high = float(df['high'].iloc[i])
            low = float(df['low'].iloc[i])
            ts = str(df.index[i])
            is_contain = (high >= cur_high and low <= cur_low) or (high <= cur_high and low >= cur_low)

            if is_contain:
                if direction == Direction.UP:
                    cur_high = max(cur_high, high)
                    cur_low = max(cur_low, low)
                else:
                    cur_high = min(cur_high, high)
                    cur_low = min(cur_low, low)
                raw_count += 1
            else:
                processed.append(ProcessedKline(len(processed), cur_ts, cur_high, cur_low, raw_count))
                if high > cur_high:
                    direction = Direction.UP
                elif high < cur_high:
                    direction = Direction.DOWN
                cur_high, cur_low, cur_ts, raw_count = high, low, ts, 1

        processed.append(ProcessedKline(len(processed), cur_ts, cur_high, cur_low, raw_count))
        self.processed_klines = processed
        return processed

    def find_fractals(self):
        if len(self.processed_klines) < 3:
            return []
        self.fractals = []
        klines = self.processed_klines
        for i in range(1, len(klines) - 1):
            prev, curr, next_ = klines[i-1], klines[i], klines[i+1]
            if curr.high > prev.high and curr.high > next_.high:
                self.fractals.append(Fractal(i, curr.timestamp, FractalType.TOP, curr.high))
            if curr.low < prev.low and curr.low < next_.low:
                self.fractals.append(Fractal(i, curr.timestamp, FractalType.BOTTOM, curr.low))
        return self.fractals

    def find_bis(self, min_gap=4):
        if len(self.fractals) < 2:
            return []
        self.bis = []
        valid = [self.fractals[0]]
        for i in range(1, len(self.fractals)):
            curr, prev = self.fractals[i], valid[-1]
            if curr.type == prev.type:
                if (curr.type == FractalType.TOP and curr.price > prev.price) or \
                   (curr.type == FractalType.BOTTOM and curr.price < prev.price):
                    valid[-1] = curr
                continue
            if abs(curr.index - prev.index) < min_gap - 1:
                continue
            if (prev.type == FractalType.TOP and curr.type == FractalType.BOTTOM and prev.price <= curr.price) or \
               (prev.type == FractalType.BOTTOM and curr.type == FractalType.TOP and prev.price >= curr.price):
                continue
            valid.append(curr)

        for i in range(1, len(valid)):
            s, e = valid[i-1], valid[i]
            if s.type == FractalType.BOTTOM and e.type == FractalType.TOP:
                self.bis.append(Bi(s, e, Direction.UP, s.index, e.index))
            elif s.type == FractalType.TOP and e.type == FractalType.BOTTOM:
                self.bis.append(Bi(s, e, Direction.DOWN, s.index, e.index))
        return self.bis

    def find_zhong_shus(self):
        if len(self.bis) < 3:
            return []
        self.zhong_shus = []
        i = 0
        while i < len(self.bis) - 2:
            b1, b2, b3 = self.bis[i], self.bis[i+1], self.bis[i+2]
            zs_high = min(b1.high, b2.high, b3.high)
            zs_low = max(b1.low, b2.low, b3.low)
            if zs_high > zs_low:
                bis_in = [b1, b2, b3]
                j = i + 3
                while j < len(self.bis):
                    nb = self.bis[j]
                    if nb.low < zs_high and nb.high > zs_low:
                        bis_in.append(nb)
                        zs_high = min(zs_high, nb.high)
                        zs_low = max(zs_low, nb.low)
                        j += 1
                    else:
                        break
                self.zhong_shus.append(ZhongShu(i, j-1, zs_high, zs_low, b1.direction, bis_in))
                i = j
            else:
                i += 1
        return self.zhong_shus

    def find_buy_sell_points(self):
        if len(self.fractals) < 3 or len(self.bis) < 1:
            return []
        self.buy_sell_points = []
        bottoms = [f for f in self.fractals if f.type == FractalType.BOTTOM]
        tops = [f for f in self.fractals if f.type == FractalType.TOP]

        for i, bf in enumerate(bottoms):
            if not self._is_lowest_in_bi(bf):
                continue
            if i >= 2:
                prev_lows = [bottoms[j].price for j in range(max(0, i-2), i)]
                if bf.price < min(prev_lows):
                    self.buy_sell_points.append(BuySellPoint(BuySellType.BUY1, bf.timestamp, bf.price, bf.index))
                    continue
            if i >= 1:
                prev_low = self._find_prev_bi_low(bf)
                if prev_low is not None and bf.price > prev_low:
                    self.buy_sell_points.append(BuySellPoint(BuySellType.BUY2, bf.timestamp, bf.price, bf.index))
                    continue
            zs_high = self._find_prev_zs_high(bf)
            if zs_high is not None and bf.price > zs_high:
                self.buy_sell_points.append(BuySellPoint(BuySellType.BUY3, bf.timestamp, bf.price, bf.index))

        for i, tf in enumerate(tops):
            if not self._is_highest_in_bi(tf):
                continue
            if i >= 2:
                prev_highs = [tops[j].price for j in range(max(0, i-2), i)]
                if tf.price > max(prev_highs):
                    self.buy_sell_points.append(BuySellPoint(BuySellType.SELL1, tf.timestamp, tf.price, tf.index))
                    continue
            if i >= 1:
                prev_high = self._find_prev_bi_high(tf)
                if prev_high is not None and tf.price < prev_high:
                    self.buy_sell_points.append(BuySellPoint(BuySellType.SELL2, tf.timestamp, tf.price, tf.index))
                    continue
            zs_low = self._find_prev_zs_low(tf)
            if zs_low is not None and tf.price < zs_low:
                self.buy_sell_points.append(BuySellPoint(BuySellType.SELL3, tf.timestamp, tf.price, tf.index))
        return self.buy_sell_points

    def _is_lowest_in_bi(self, f):
        for bi in self.bis:
            if bi.start_index <= f.index <= bi.end_index:
                return f.price == bi.low
        return False

    def _is_highest_in_bi(self, f):
        for bi in self.bis:
            if bi.start_index <= f.index <= bi.end_index:
                return f.price == bi.high
        return False

    def _find_prev_bi_low(self, f):
        for bi in reversed(self.bis):
            if bi.end_index < f.index:
                return bi.low
        return None

    def _find_prev_bi_high(self, f):
        for bi in reversed(self.bis):
            if bi.end_index < f.index:
                return bi.high
        return None

    def _find_prev_zs_high(self, f):
        for zs in reversed(self.zhong_shus):
            if zs.end_bi_index * 3 < f.index:
                return zs.high
        return None

    def _find_prev_zs_low(self, f):
        for zs in reversed(self.zhong_shus):
            if zs.end_bi_index * 3 < f.index:
                return zs.low
        return None

    def determine_trend(self):
        if len(self.zhong_shus) < 2:
            return "盘整"
        zs1, zs2 = self.zhong_shus[-2], self.zhong_shus[-1]
        if zs2.low < zs1.high and zs2.high > zs1.low:
            return "盘整"
        if zs2.high < zs1.high and zs2.low < zs1.low:
            return "下跌"
        elif zs2.high > zs1.high and zs2.low > zs1.low:
            return "上涨"
        return "盘整"

    def analyze(self, df):
        self.process_klines(df)
        self.find_fractals()
        self.find_bis()
        self.find_zhong_shus()
        self.find_buy_sell_points()
        current_bi = self.bis[-1] if self.bis else None
        in_zs = False
        if current_bi and self.zhong_shus:
            zs = self.zhong_shus[-1]
            if zs.low <= current_bi.low <= zs.high or zs.low <= current_bi.high <= zs.high:
                in_zs = True
        return {
            "klines": len(self.processed_klines),
            "fractals": len(self.fractals),
            "bis": len(self.bis),
            "zhong_shus": len(self.zhong_shus),
            "buy_sell_points": self.buy_sell_points,
            "current_bi_direction": current_bi.direction if current_bi else None,
            "in_zhongshu": in_zs,
            "trend": self.determine_trend(),
        }

    # ------------------------------------------------------------------
    # 9. 动态买点确认与止损
    # ------------------------------------------------------------------

    def check_buy_point_validity(self, buy_point, current_price):
        """
        检查买点是否仍然有效

        如果当前价格打穿了买点，买点构造失败，需要触发止损

        Args:
            buy_point: 买点对象
            current_price: 当前价格

        Returns:
            dict: {
                'valid': bool,  # 买点是否有效
                'stop_loss': bool,  # 是否触发止损
                'reason': str  # 原因
            }
        """
        # 如果是二买，检查是否被打穿
        if buy_point.type == BuySellType.BUY2:
            # 找到这个二买之前的买点
            prev_buy = self._find_previous_buy(buy_point)
            if prev_buy is not None:
                # 如果当前价格低于二买的最低点，二买构造失败
                if current_price < buy_point.price:
                    return {
                        'valid': False,
                        'stop_loss': True,
                        'reason': f'二买被打穿，当前价格{current_price}低于二买低点{buy_point.price}'
                    }

        # 如果是一买，检查是否被打穿
        if buy_point.type == BuySellType.BUY1:
            # 找到这个一买之前的买点
            prev_buy = self._find_previous_buy(buy_point)
            if prev_buy is not None:
                # 如果当前价格低于一买的最低点，一买构造失败
                if current_price < buy_point.price:
                    return {
                        'valid': False,
                        'stop_loss': True,
                        'reason': f'一买被打穿，当前价格{current_price}低于一买低点{buy_point.price}'
                    }

        return {
            'valid': True,
            'stop_loss': False,
            'reason': '买点有效'
        }

    def _find_previous_buy(self, buy_point):
        """找到当前买点之前的买点"""
        for bp in reversed(self.buy_sell_points):
            if bp.index < buy_point.index and 'buy' in bp.type.value:
                return bp
        return None

    def update_buy_points(self, current_price):
        """
        更新买点状态，检查是否需要推翻或止损

        Args:
            current_price: 当前价格

        Returns:
            list: 需要处理的买点（被打穿的买点）
        """
        invalidated = []

        for bp in self.buy_sell_points:
            if 'buy' in bp.type.value:
                result = self.check_buy_point_validity(bp, current_price)
                if result['stop_loss']:
                    invalidated.append({
                        'buy_point': bp,
                        'reason': result['reason'],
                        'current_price': current_price
                    })

        return invalidated
