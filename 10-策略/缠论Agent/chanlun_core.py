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


class Level(Enum):
    DAILY = "daily"
    MIN15 = "15min"
    WEEKLY = "weekly"

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
    price: float        # 顶分型=high, 底分型=low
    high: float = 0.0   # 分型三K线的最高价
    low: float = 0.0    # 分型三K线的最低价
    third_high: float = 0.0  # 底分型：第三根K线的高点（突破此点确认买入）
    third_low: float = 0.0   # 顶分型：第三根K线的低点（跌破此点确认卖出）

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
    level: str = "daily"


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
            # 顶分型：中间K线最高
            if curr.high > prev.high and curr.high > next_.high:
                f_high = max(prev.high, curr.high, next_.high)
                f_low = min(prev.low, curr.low, next_.low)
                self.fractals.append(Fractal(i, curr.timestamp, FractalType.TOP, curr.high, f_high, f_low,
                    third_high=next_.high, third_low=next_.low))
            # 底分型：中间K线最低
            if curr.low < prev.low and curr.low < next_.low:
                f_high = max(prev.high, curr.high, next_.high)
                f_low = min(prev.low, curr.low, next_.low)
                self.fractals.append(Fractal(i, curr.timestamp, FractalType.BOTTOM, curr.low, f_high, f_low,
                    third_high=next_.high, third_low=next_.low))
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

    # ============================================================
    # MACD 计算与背驰检测
    # ============================================================

    def _calc_macd(self, close_prices):
        """计算MACD指标，并建立到处理后K线的索引映射"""
        ema_fast = close_prices.ewm(span=12, adjust=False).mean()
        ema_slow = close_prices.ewm(span=26, adjust=False).mean()
        dif = ema_fast - ema_slow
        dea = dif.ewm(span=9, adjust=False).mean()
        macd_hist = 2 * (dif - dea)

        # 建立处理后K线索引 → 原始df行号的映射
        # 用raw_count累加来确定每根处理后K线对应原始df的哪一行
        self._kline_to_df = {}
        df_pos = 0
        for pk in self.processed_klines:
            df_pos += pk.raw_count  # 累加原始K线数量
            self._kline_to_df[pk.index] = df_pos - 1  # 最后一个原始行的位置
        
        # 将MACD值映射到处理后K线索引
        self._macd_at_fractal = {}
        for i, pk in enumerate(self.processed_klines):
            df_idx = self._kline_to_df.get(pk.index, i)
            if df_idx < len(macd_hist):
                self._macd_at_fractal[pk.index] = float(macd_hist.iloc[df_idx])
        self._macd_hist = macd_hist

    def _check_divergence(self, curr_bi, prev_bi):
        """
        检查两笔之间的背驰。

        底背驰（curr_bi为下跌笔）：
            curr_bi.low < prev_bi.low 且 MACD柱在curr端 > prev端

        顶背驰（curr_bi为上涨笔）：
            curr_bi.high > prev_bi.high 且 MACD柱在curr端 < prev端

        返回: (is_divergence, macd_curr, macd_prev)
        """
        if not hasattr(self, '_macd_at_fractal'):
            return False, 0, 0

        curr_df_idx = self._kline_to_df.get(curr_bi.end_fractal.index, curr_bi.end_fractal.index)
        prev_df_idx = self._kline_to_df.get(prev_bi.end_fractal.index, prev_bi.end_fractal.index)
        curr_macd = float(self._macd_hist.iloc[curr_df_idx]) if curr_df_idx < len(self._macd_hist) else 0
        prev_macd = float(self._macd_hist.iloc[prev_df_idx]) if prev_df_idx < len(self._macd_hist) else 0

        if curr_bi.direction == Direction.DOWN:
            # 底背驰：价格更低但MACD更高（负值收窄）
            if curr_bi.low < prev_bi.low and curr_macd > prev_macd:
                return True, curr_macd, prev_macd
            # 延伸判断：MACD面积背驰（累加绝对值）
            curr_area = self._bi_macd_area(curr_bi)
            prev_area = self._bi_macd_area(prev_bi)
            if prev_area > 0 and curr_bi.low < prev_bi.low and curr_area < prev_area * 0.85:
                return True, curr_area, prev_area
        else:
            # 顶背驰：价格更高但MACD更低
            if curr_bi.high > prev_bi.high and curr_macd < prev_macd:
                return True, curr_macd, prev_macd
            curr_area = self._bi_macd_area(curr_bi)
            prev_area = self._bi_macd_area(prev_bi)
            if prev_area > 0 and curr_bi.high > prev_bi.high and curr_area < prev_area * 0.85:
                return True, curr_area, prev_area

        return False, 0, 0

    def _bi_macd_area(self, bi):
        """计算一笔的MACD柱面积（绝对值累加），用于面积背驰判断
           使用_kline_to_df映射将处理后K线索引转为原始df行号"""
        if not hasattr(self, '_macd_hist'):
            return 0
        start_df = self._kline_to_df.get(bi.start_fractal.index, bi.start_fractal.index)
        end_df = self._kline_to_df.get(bi.end_fractal.index, bi.end_fractal.index)
        if start_df > end_df:
            start_df, end_df = end_df, start_df
        vals = self._macd_hist.iloc[start_df:end_df+1]
        return float(vals.abs().sum())

    # ============================================================
    # 买卖点识别（严格缠论定义）
    # ============================================================

    def find_buy_sell_points(self, level="daily"):
        """
        严格按缠论定义识别买卖点。

        一买：下跌趋势末端底背驰
            - 至少2个下跌中枢，最后一个向下笔出现MACD底背驰
            - 背驰后底分型确认

        二买：一买后回调不破前低
            - 一买已出现，随后有一笔上涨
            - 回调笔的底分型不低于一买低点

        三买：突破中枢后回踩不进中枢
            - 向上离开中枢，回踩不进入中枢区间

        一卖：上涨趋势末端顶背驰
            - 至少2个上涨中枢，最后一个向上笔出现MACD顶背驰

        二卖：一卖后反弹不破前高
            - 一卖已出现，随后有一笔下跌
            - 反弹笔的顶分型不高于一卖高点
        """
        if len(self.fractals) < 3 or len(self.bis) < 3:
            return []
        self.buy_sell_points = []

        # 分离向上笔和向下笔
        down_bis = [b for b in self.bis if b.direction == Direction.DOWN]
        up_bis = [b for b in self.bis if b.direction == Direction.UP]

        # === 一买：下跌趋势背驰 ===
        for i in range(1, len(down_bis)):
            prev_bi, curr_bi = down_bis[i-1], down_bis[i]
            curr_bottom = curr_bi.end_fractal

            # 条件1：当前笔低点低于前一笔（价格在创新低）
            if curr_bi.low >= prev_bi.low:
                continue

            # 条件2：MACD底背驰
            is_div, _, _ = self._check_divergence(curr_bi, prev_bi)
            if not is_div:
                continue

            # 条件3：至少有一个中枢（下跌趋势结构）
            has_zs = any(
                zs.low <= curr_bi.low <= zs.high or zs.low <= curr_bi.high <= zs.high
                for zs in self.zhong_shus
            )
            if not has_zs:
                continue

            self.buy_sell_points.append(BuySellPoint(
                BuySellType.BUY1, curr_bottom.timestamp,
                curr_bottom.price, curr_bottom.index, level=level
            ))

        # === 一卖：上涨趋势背驰 ===
        for i in range(1, len(up_bis)):
            prev_bi, curr_bi = up_bis[i-1], up_bis[i]
            curr_top = curr_bi.end_fractal

            if curr_bi.high <= prev_bi.high:
                continue

            is_div, _, _ = self._check_divergence(curr_bi, prev_bi)
            if not is_div:
                continue

            has_zs = any(
                zs.low <= curr_bi.low <= zs.high or zs.low <= curr_bi.high <= zs.high
                for zs in self.zhong_shus
            )
            if not has_zs:
                continue

            self.buy_sell_points.append(BuySellPoint(
                BuySellType.SELL1, curr_top.timestamp,
                curr_top.price, curr_top.index, level=level
            ))

        # 获取已经识别到的一买/一卖位置
        buy1_indices = {
            p.index for p in self.buy_sell_points if p.type == BuySellType.BUY1
        }
        sell1_indices = {
            p.index for p in self.buy_sell_points if p.type == BuySellType.SELL1
        }

        # === 二买：一买后回调不破前低 ===
        for bp_idx in sorted(buy1_indices):
            bp_price = next(p.price for p in self.buy_sell_points
                           if p.type == BuySellType.BUY1 and p.index == bp_idx)
            # 在一买之后找下跌笔（回调）
            for bi in self.bis:
                if bi.direction != Direction.DOWN:
                    continue
                if bi.end_fractal.index <= bp_idx:
                    continue
                bottom_f = bi.end_fractal
                # 回调不破一买低点：回调价格必须 > 一买价格
                if bottom_f.price <= bp_price:
                    continue  # 回调破了前低，不是二买
                # 确认中间有上涨笔（一买后的反弹）
                has_up = any(
                    b.direction == Direction.UP
                    and b.start_fractal.index >= bp_idx
                    and b.end_fractal.index <= bi.end_fractal.index
                    for b in self.bis
                )
                if has_up:
                    self.buy_sell_points.append(BuySellPoint(
                        BuySellType.BUY2, bottom_f.timestamp,
                        bottom_f.price, bottom_f.index, level=level
                    ))
                    break

        # === 二卖：一卖后反弹不破前高 ===
        for sp_idx in sorted(sell1_indices):
            sp_price = next(p.price for p in self.buy_sell_points
                           if p.type == BuySellType.SELL1 and p.index == sp_idx)
            for bi in self.bis:
                if bi.direction != Direction.UP:
                    continue
                if bi.end_fractal.index <= sp_idx:
                    continue
                top_f = bi.end_fractal
                # 反弹不破前高：反弹高度必须 < 一卖价格
                if top_f.price >= sp_price:
                    continue  # 反弹突破前高，不是二卖
                has_down = any(
                    b.direction == Direction.DOWN
                    and b.start_fractal.index >= sp_idx
                    and b.end_fractal.index <= bi.end_fractal.index
                    for b in self.bis
                )
                if has_down:
                    self.buy_sell_points.append(BuySellPoint(
                        BuySellType.SELL2, top_f.timestamp,
                        top_f.price, top_f.index, level=level
                    ))
                    break

        # === 三买：突破中枢后回踩不进中枢 ===
        for zs in self.zhong_shus:
            if zs.direction != Direction.UP:
                continue
            # 找中枢后的向上笔
            for bi in self.bis:
                if bi.direction != Direction.UP:
                    continue
                if bi.start_fractal.index < zs.start_bi_index * 2:
                    continue
                # 突破中枢上沿
                if bi.end_fractal.price <= zs.high:
                    continue
                # 找突破后的向下回踩笔
                for cb in self.bis:
                    if cb.direction != Direction.DOWN:
                        continue
                    if cb.start_fractal.index <= bi.end_fractal.index:
                        continue
                    bottom_f = cb.end_fractal
                    # 回踩不进入中枢
                    if bottom_f.price >= zs.high:
                        self.buy_sell_points.append(BuySellPoint(
                            BuySellType.BUY3, bottom_f.timestamp,
                            bottom_f.price, bottom_f.index, level=level
                        ))
                        break
                break

        # === 三卖：跌破中枢后反弹不进中枢 ===
        for zs in self.zhong_shus:
            if zs.direction != Direction.DOWN:
                continue
            for bi in self.bis:
                if bi.direction != Direction.DOWN:
                    continue
                if bi.start_fractal.index < zs.start_bi_index * 2:
                    continue
                if bi.end_fractal.price >= zs.low:
                    continue
                for rb in self.bis:
                    if rb.direction != Direction.UP:
                        continue
                    if rb.start_fractal.index <= bi.end_fractal.index:
                        continue
                    top_f = rb.end_fractal
                    if top_f.price <= zs.low:
                        self.buy_sell_points.append(BuySellPoint(
                            BuySellType.SELL3, top_f.timestamp,
                            top_f.price, top_f.index, level=level
                        ))
                        break
                break

        # === 有效性验证：后续走势破坏了买卖点则剔除 ===
        valid_points = []
        bottoms = [f for f in self.fractals if f.type == FractalType.BOTTOM]
        tops = [f for f in self.fractals if f.type == FractalType.TOP]
        
        for p in self.buy_sell_points:
            if 'buy' in p.type.value:
                # 检查后续是否有更低的底分型（买点被打穿）
                later_lows = [f.price for f in bottoms if f.index > p.index]
                if later_lows and min(later_lows) < p.price - 0.001:
                    continue  # 有更低点，买点无效
                valid_points.append(p)
            elif 'sell' in p.type.value:
                # 检查后续是否有更高的顶分型（卖点被突破）
                later_highs = [f.price for f in tops if f.index > p.index]
                if later_highs and max(later_highs) > p.price + 0.001:
                    continue  # 有更高点，卖点无效
                valid_points.append(p)
            else:
                valid_points.append(p)
        
        self.buy_sell_points = valid_points
        return self.buy_sell_points

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

    def analyze(self, df, level="daily"):
        self.process_klines(df)
        self.find_fractals()
        self.find_bis()
        self.find_zhong_shus()
        self._calc_macd(df['close'])
        self.find_buy_sell_points(level=level)
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
