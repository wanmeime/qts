# -*- coding: utf-8 -*-
"""
多级别联立分析模块

基于用户口述设计文档重写，实现：
1. 日线级别分析
2. 15分钟级别分析
3. 输出当前笔的方向、是否在中枢中、买点/卖点情况

级别递归：
  日线级别 → 15分钟级别 → 分时图

每个级别的分析内容：
  日线：笔、中枢、买点/卖点、趋势
  15分钟：笔、中枢、买点/卖点（用于确认日线信号）
"""

import pandas as pd
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import Enum

from chanlun_core import (
    ChanlunCore, BuySellType, BuySellPoint, Direction, FractalType, ZhongShu, Bi
)


class Level(Enum):
    """分析级别"""
    DAILY = "daily"       # 日线
    MIN15 = "15min"       # 15分钟
    WEEKLY = "weekly"     # 周线（保留接口）
    MONTHLY = "monthly"   # 月线（保留接口）


@dataclass
class LevelAnalysis:
    """
    单级别分析结果

    包含该级别上的完整缠论分析输出。
    """
    level: Level
    # 当前状态
    current_bi_direction: Optional[Direction]  # 当前笔方向
    in_zhong_shu: bool                         # 是否在中枢中
    zhong_shu_high: Optional[float]            # 中枢上沿
    zhong_shu_low: Optional[float]             # 中枢下沿
    # 中继分型
    continuation_count: int                    # 中继分型次数
    # 买卖点
    buy_points: List[BuySellPoint]             # 买点列表
    sell_points: List[BuySellPoint]            # 卖点列表
    latest_buy_point: Optional[BuySellPoint]   # 最近买点
    latest_sell_point: Optional[BuySellPoint]  # 最近卖点
    # 笔信息
    total_bis: int                             # 笔总数
    total_fractals: int                        # 分型总数
    total_zhong_shus: int                      # 中枢总数
    # 原始数据引用
    chanlun_core: Optional[ChanlunCore] = None


@dataclass
class MultiLevelResult:
    """
    多级别联立分析结果

    综合日线和15分钟级别的分析结论。
    """
    stock_code: str
    daily: Optional[LevelAnalysis]      # 日线分析结果
    min15: Optional[LevelAnalysis]      # 15分钟分析结果
    overall_signal: str                 # 综合信号："buy"/"sell"/"hold"/"wait"
    signal_reasons: List[str]           # 信号原因列表
    key_prices: Dict[str, float]        # 关键价位
    summary: str                        # 文本摘要


class MultiLevelAnalysis:
    """
    多级别联立分析类

    分析流程：
    1. 日线级别分析 → 确定大方向
    2. 15分钟级别分析 → 确认入场/出场时机
    3. 综合两级给出操作信号
    """

    def __init__(self):
        pass

    def analyze_level(self, df: pd.DataFrame, level: Level) -> LevelAnalysis:
        """
        分析单个级别

        对给定数据执行完整的缠论分析流程。

        参数：
        - df: K线数据
        - level: 分析级别

        返回：
        - LevelAnalysis 分析结果
        """
        chanlun = ChanlunCore()
        chanlun.analyze(df)

        # 获取当前状态
        state = chanlun.get_current_state()

        # 分离买卖点
        buy_points = [p for p in chanlun.buy_sell_points
                      if p.type in (BuySellType.BUY1, BuySellType.BUY2, BuySellType.BUY3)]
        sell_points = [p for p in chanlun.buy_sell_points
                       if p.type in (BuySellType.SELL1, BuySellType.SELL2, BuySellType.SELL3)]

        # 中继分型次数
        cont_count = 0
        if chanlun.continuation_fractals:
            cont_count = chanlun.continuation_fractals.count

        return LevelAnalysis(
            level=level,
            current_bi_direction=state['current_bi_direction'],
            in_zhong_shu=state['in_zhong_shu'],
            zhong_shu_high=state['zhong_shu_info']['high'] if state['zhong_shu_info'] else None,
            zhong_shu_low=state['zhong_shu_info']['low'] if state['zhong_shu_info'] else None,
            continuation_count=cont_count,
            buy_points=buy_points,
            sell_points=sell_points,
            latest_buy_point=state['latest_buy_point'],
            latest_sell_point=state['latest_sell_point'],
            total_bis=len(chanlun.bis),
            total_fractals=len(chanlun.fractals),
            total_zhong_shus=len(chanlun.zhong_shus),
            chanlun_core=chanlun,
        )

    def analyze_multi_level(
        self,
        stock_code: str,
        daily_df: pd.DataFrame,
        min15_df: Optional[pd.DataFrame] = None,
    ) -> MultiLevelResult:
        """
        多级别联立分析

        分析日线和15分钟级别，综合给出操作信号。

        参数：
        - stock_code: 股票代码
        - daily_df: 日线数据
        - min15_df: 15分钟数据（可选）

        返回：
        - MultiLevelResult 综合分析结果
        """
        # 日线分析
        daily = self.analyze_level(daily_df, Level.DAILY)

        # 15分钟分析
        min15 = None
        if min15_df is not None and len(min15_df) > 0:
            min15 = self.analyze_level(min15_df, Level.MIN15)

        # 综合判断
        overall_signal, reasons, key_prices = self._synthesize(daily, min15)

        # 生成摘要
        summary = self._generate_summary(stock_code, daily, min15, overall_signal, reasons)

        return MultiLevelResult(
            stock_code=stock_code,
            daily=daily,
            min15=min15,
            overall_signal=overall_signal,
            signal_reasons=reasons,
            key_prices=key_prices,
            summary=summary,
        )

    def _synthesize(
        self,
        daily: LevelAnalysis,
        min15: Optional[LevelAnalysis],
    ) -> tuple:
        """
        综合日线和15分钟信号

        核心逻辑（基于设计文档）：
        - 日线是基准，权重最高
        - 15分钟用于确认入场/出场时机
        - 两级同向信号最可靠

        返回：
        - (signal_type, reasons, key_prices)
        """
        reasons = []
        key_prices = {}

        # 收集关键价位
        if daily.zhong_shu_high is not None:
            key_prices['daily_zhong_shu_high'] = daily.zhong_shu_high
            key_prices['daily_zhong_shu_low'] = daily.zhong_shu_low

        if min15 and min15.zhong_shu_high is not None:
            key_prices['min15_zhong_shu_high'] = min15.zhong_shu_high
            key_prices['min15_zhong_shu_low'] = min15.zhong_shu_low

        # ---- 日线信号判断 ----
        daily_signal = "hold"
        if daily.latest_buy_point:
            daily_signal = "buy"
            bp = daily.latest_buy_point
            reasons.append(f"日线出现{bp.type.value}，价格={bp.price:.2f}")
            key_prices['buy_point_price'] = bp.price

        if daily.latest_sell_point:
            sp = daily.latest_sell_point
            if daily_signal == "buy":
                # 同时有买卖点，取最新的
                if sp.index > daily.latest_buy_point.index:
                    daily_signal = "sell"
                    reasons.clear()
                    reasons.append(f"日线出现{sp.type.value}，价格={sp.price:.2f}")
                    key_prices['sell_point_price'] = sp.price
                else:
                    reasons.append(f"日线也出现{sp.type.value}，价格={sp.price:.2f}")
            else:
                daily_signal = "sell"
                reasons.append(f"日线出现{sp.type.value}，价格={sp.price:.2f}")
                key_prices['sell_point_price'] = sp.price

        # 日线当前笔方向
        if daily.current_bi_direction == Direction.UP:
            reasons.append("日线上涨一笔中")
        elif daily.current_bi_direction == Direction.DOWN:
            reasons.append("日线下跌一笔中")

        # 中枢状态
        if daily.in_zhong_shu:
            reasons.append(f"日线在中枢中 [{daily.zhong_shu_low:.2f}, {daily.zhong_shu_high:.2f}]")
        else:
            reasons.append("日线不在中枢中")

        # 中继分型
        if daily.continuation_count > 0:
            reasons.append(f"日线中继分型{daily.continuation_count}次")

        # ---- 15分钟确认 ----
        min15_signal = "hold"
        if min15:
            if min15.latest_buy_point:
                min15_signal = "buy"
                bp15 = min15.latest_buy_point
                reasons.append(f"15分钟出现{bp15.type.value}，价格={bp15.price:.2f}")

            if min15.latest_sell_point:
                sp15 = min15.latest_sell_point
                if min15_signal == "buy":
                    if sp15.index > min15.latest_buy_point.index:
                        min15_signal = "sell"
                else:
                    min15_signal = "sell"
                reasons.append(f"15分钟出现{sp15.type.value}，价格={sp15.price:.2f}")

            if min15.current_bi_direction == Direction.UP:
                reasons.append("15分钟上涨一笔中")
            elif min15.current_bi_direction == Direction.DOWN:
                reasons.append("15分钟下跌一笔中")

        # ---- 综合信号 ----
        # 日线为主，15分钟确认
        if daily_signal == "buy" and min15_signal == "buy":
            overall = "buy"
            reasons.append("日线+15分钟共振买入")
        elif daily_signal == "sell" or (daily_signal != "buy" and min15_signal == "sell"):
            overall = "sell"
            if min15_signal == "sell" and daily_signal != "sell":
                reasons.append("15分钟卖出信号（日线无买入信号）")
        elif daily_signal == "buy":
            overall = "buy"
            reasons.append("日线买入信号（等待15分钟确认）")
        else:
            overall = "hold"
            reasons.append("无明确买卖信号，继续观察")

        return overall, reasons, key_prices

    def _generate_summary(
        self,
        stock_code: str,
        daily: LevelAnalysis,
        min15: Optional[LevelAnalysis],
        signal: str,
        reasons: List[str],
    ) -> str:
        """生成文本摘要"""
        lines = []
        lines.append("=" * 60)
        lines.append(f"多级别联立分析 —— {stock_code}")
        lines.append("=" * 60)

        # 日线
        lines.append("")
        lines.append("【日线级别】")
        bi_dir = "上涨" if daily.current_bi_direction == Direction.UP else "下跌" if daily.current_bi_direction == Direction.DOWN else "未知"
        lines.append(f"  当前笔方向: {bi_dir}")
        lines.append(f"  在中枢中: {'是' if daily.in_zhong_shu else '否'}")
        if daily.in_zhong_shu:
            lines.append(f"  中枢区间: [{daily.zhong_shu_low:.2f}, {daily.zhong_shu_high:.2f}]")
        lines.append(f"  中继分型次数: {daily.continuation_count}")
        lines.append(f"  笔数: {daily.total_bis}  分型数: {daily.total_fractals}  中枢数: {daily.total_zhong_shus}")

        if daily.buy_points:
            lines.append(f"  买点({len(daily.buy_points)}个):")
            for bp in daily.buy_points:
                lines.append(f"    {bp.type.value}: {bp.price:.2f} (强度={bp.strength:.2f})")
        if daily.sell_points:
            lines.append(f"  卖点({len(daily.sell_points)}个):")
            for sp in daily.sell_points:
                lines.append(f"    {sp.type.value}: {sp.price:.2f} (强度={sp.strength:.2f})")

        # 15分钟
        if min15:
            lines.append("")
            lines.append("【15分钟级别】")
            bi_dir15 = "上涨" if min15.current_bi_direction == Direction.UP else "下跌" if min15.current_bi_direction == Direction.DOWN else "未知"
            lines.append(f"  当前笔方向: {bi_dir15}")
            lines.append(f"  在中枢中: {'是' if min15.in_zhong_shu else '否'}")
            if min15.in_zhong_shu:
                lines.append(f"  中枢区间: [{min15.zhong_shu_low:.2f}, {min15.zhong_shu_high:.2f}]")
            lines.append(f"  中继分型次数: {min15.continuation_count}")

            if min15.buy_points:
                lines.append(f"  买点({len(min15.buy_points)}个):")
                for bp in min15.buy_points:
                    lines.append(f"    {bp.type.value}: {bp.price:.2f} (强度={bp.strength:.2f})")
            if min15.sell_points:
                lines.append(f"  卖点({len(min15.sell_points)}个):")
                for sp in min15.sell_points:
                    lines.append(f"    {sp.type.value}: {sp.price:.2f} (强度={sp.strength:.2f})")
        else:
            lines.append("")
            lines.append("【15分钟级别】无数据")

        # 综合信号
        lines.append("")
        lines.append("=" * 60)
        signal_cn = {"buy": "买入", "sell": "卖出", "hold": "观望", "wait": "等待"}
        lines.append(f"综合信号: {signal_cn.get(signal, signal)}")
        lines.append("=" * 60)

        if reasons:
            lines.append("")
            lines.append("信号依据:")
            for r in reasons:
                lines.append(f"  - {r}")

        return "\n".join(lines)
