# -*- coding: utf-8 -*-
"""
缠论多级别分析模块

实现日线→15分钟→分时图的递归分析
"""

import pandas as pd
from typing import Dict, List, Optional
from chanlun_core import ChanlunCore, Direction, BuySellType


class MultiLevelAnalyzer:
    """多级别分析器"""

    def __init__(self):
        self.levels = {}

    def analyze(self, daily_df: pd.DataFrame, min15_df: pd.DataFrame = None) -> Dict:
        """
        多级别分析

        Args:
            daily_df: 日线数据
            min15_df: 15分钟数据（可选）

        Returns:
            分析结果
        """
        result = {
            'daily': None,
            'min15': None,
            'signal': None,
            'entry_timing': None,
        }

        # 1. 日线级别分析
        daily_core = ChanlunCore()
        daily_result = daily_core.analyze(daily_df)
        result['daily'] = daily_result

        # 2. 如果有15分钟数据，进行15分钟级别分析
        if min15_df is not None and len(min15_df) > 0:
            min15_core = ChanlunCore()
            min15_result = min15_core.analyze(min15_df)
            result['min15'] = min15_result

        # 3. 判断买入信号
        result['signal'] = self._determine_signal(daily_result, result.get('min15'))

        return result

    def _determine_signal(self, daily_result: Dict, min15_result: Optional[Dict]) -> Dict:
        """
        判断交易信号

        递归逻辑：
        1. 日线级别：判断是否有买点可能
        2. 15分钟级别：确认买点正在形成
        3. 输出信号
        """
        signal = {
            'action': '观望',
            'confidence': 0,
            'reason': '',
            'daily_status': '',
            'min15_status': '',
        }

        # 日线级别分析
        daily_buy_points = daily_result.get('buy_sell_points', [])
        daily_sell_points = [p for p in daily_buy_points if 'sell' in p.type.value]
        daily_buy_points = [p for p in daily_buy_points if 'buy' in p.type.value]

        if daily_buy_points:
            latest_buy = daily_buy_points[-1]
            signal['daily_status'] = f"日线出现{latest_buy.type.value}，价格{latest_buy.price}"
            signal['confidence'] = 50  # 基础置信度

            # 15分钟级别确认
            if min15_result:
                min15_buy_points = min15_result.get('buy_sell_points', [])
                min15_buy = [p for p in min15_buy_points if 'buy' in p.type.value]

                if min15_buy:
                    latest_min15_buy = min15_buy[-1]
                    signal['min15_status'] = f"15分钟确认{latest_min15_buy.type.value}"
                    signal['confidence'] = 80  # 级别确认后提高置信度

                    # 信号确认
                    if latest_min15_buy.index > latest_buy.index:
                        signal['action'] = '买入'
                        signal['reason'] = f"日线{latest_buy.type.value} + 15分钟{latest_min15_buy.type.value}确认"
                        signal['entry_price'] = latest_min15_buy.price
                    else:
                        signal['action'] = '等待'
                        signal['reason'] = "15分钟买点未更新"
                else:
                    signal['min15_status'] = "15分钟无买点"
                    signal['action'] = '等待'
                    signal['reason'] = "等待15分钟级别确认"
            else:
                signal['min15_status'] = "无15分钟数据"
                signal['action'] = '观察'
                signal['reason'] = "仅有日线数据，等待15分钟确认"

        elif daily_sell_points:
            latest_sell = daily_sell_points[-1]
            signal['daily_status'] = f"日线出现{latest_sell.type.value}"
            signal['action'] = '卖出'
            signal['reason'] = f"日线出现{latest_sell.type.value}"
            signal['confidence'] = 70
        else:
            signal['daily_status'] = "日线无买卖点"
            signal['action'] = '观望'
            signal['reason'] = "无明确信号"

        return signal

    def format_report(self, result: Dict) -> str:
        """格式化多级别分析报告"""
        report = []
        report.append("=" * 60)
        report.append("缠论多级别分析报告")
        report.append("=" * 60)
        report.append("")

        # 日线级别
        daily = result.get('daily', {})
        report.append("【日线级别】")
        report.append(f"处理后K线: {daily.get('klines', 0)} 根")
        report.append(f"分型: {daily.get('fractals', 0)} 个")
        report.append(f"笔: {daily.get('bis', 0)} 个")
        report.append(f"中枢: {daily.get('zhong_shus', 0)} 个")
        report.append(f"趋势: {daily.get('trend', '未知')}")
        report.append("")

        # 15分钟级别
        min15 = result.get('min15')
        if min15:
            report.append("【15分钟级别】")
            report.append(f"处理后K线: {min15.get('klines', 0)} 根")
            report.append(f"分型: {min15.get('fractals', 0)} 个")
            report.append(f"笔: {min15.get('bis', 0)} 个")
            report.append(f"中枢: {min15.get('zhong_shus', 0)} 个")
            report.append(f"趋势: {min15.get('trend', '未知')}")
        else:
            report.append("【15分钟级别】无数据")
        report.append("")

        # 信号
        signal = result.get('signal', {})
        report.append("【操作信号】")
        report.append(f"信号: {signal.get('action', '未知')}")
        report.append(f"置信度: {signal.get('confidence', 0)}%")
        report.append(f"原因: {signal.get('reason', '')}")
        report.append(f"日线状态: {signal.get('daily_status', '')}")
        report.append(f"15分钟状态: {signal.get('min15_status', '')}")
        if signal.get('entry_price'):
            report.append(f"入场价: {signal['entry_price']}")
        report.append("")

        return "\n".join(report)
