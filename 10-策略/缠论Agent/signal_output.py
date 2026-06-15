# -*- coding: utf-8 -*-
"""
缠论信号输出模块

输出操作信号：买入/卖出/持仓/观望
"""

from typing import Dict, List, Optional
from chanlun_core import ChanlunCore, BuySellType, Direction


class SignalOutput:
    """信号输出"""

    def __init__(self, core: ChanlunCore):
        self.core = core

    def generate_signal(self, analysis_result: Dict) -> Dict:
        """
        生成交易信号

        根据缠论分析结果，输出操作信号：
        - 买入：买点出现
        - 卖出：卖点出现 或 止损
        - 持有：没有卖点
        - 观望：没有买点
        """
        buy_sell_points = analysis_result.get('buy_sell_points', [])
        current_bi_direction = analysis_result.get('current_bi_direction')
        in_zhongshu = analysis_result.get('in_zhongshu', False)
        trend = analysis_result.get('trend', '盘整')

        # 分离买点和卖点
        buy_points = [p for p in buy_sell_points if 'buy' in p.type.value]
        sell_points = [p for p in buy_sell_points if 'sell' in p.type.value]

        # 获取最近的买点和卖点
        recent_buy = buy_points[-1] if buy_points else None
        recent_sell = sell_points[-1] if sell_points else None

        # 生成信号
        signal = {
            'action': '观望',
            'reason': '',
            'entry_price': None,
            'stop_loss': None,
            'take_profit': None,
            'recent_buy': recent_buy,
            'recent_sell': recent_sell,
        }

        if recent_buy and not recent_sell:
            signal['action'] = '买入'
            signal['reason'] = f'出现{recent_buy.type.value}'
            signal['entry_price'] = recent_buy.price
            # 止损位：二买低点或一买低点
            signal['stop_loss'] = recent_buy.price * 0.95  # 5%止损
        elif recent_sell and not recent_buy:
            signal['action'] = '卖出'
            signal['reason'] = f'出现{recent_sell.type.value}'
        elif recent_buy and recent_sell:
            # 比较时间，看哪个更新
            if recent_buy.index > recent_sell.index:
                signal['action'] = '买入'
                signal['reason'] = f'最近出现{recent_buy.type.value}'
                signal['entry_price'] = recent_buy.price
                signal['stop_loss'] = recent_buy.price * 0.95
            else:
                signal['action'] = '卖出'
                signal['reason'] = f'最近出现{recent_sell.type.value}'

        return signal

    def format_report(self, analysis_result: Dict, signal: Dict) -> str:
        """格式化输出报告"""
        report = []
        report.append("=" * 60)
        report.append("缠论分析报告")
        report.append("=" * 60)
        report.append("")

        # 基本信息
        report.append("【基本分析】")
        report.append(f"处理后K线: {analysis_result['klines']} 根")
        report.append(f"分型: {analysis_result['fractals']} 个")
        report.append(f"笔: {analysis_result['bis']} 个")
        report.append(f"中枢: {analysis_result['zhong_shus']} 个")
        report.append(f"买卖点: {len(analysis_result['buy_sell_points'])} 个")
        report.append("")

        # 当前状态
        direction = analysis_result.get('current_bi_direction')
        direction_str = "上涨" if direction and direction.value == 1 else "下跌"
        in_zs = "是" if analysis_result.get('in_zhongshu') else "否"
        report.append("【当前状态】")
        report.append(f"当前笔方向: {direction_str}")
        report.append(f"在中枢中: {in_zs}")
        report.append(f"趋势: {analysis_result['trend']}")
        report.append("")

        # 买卖点
        report.append("【买卖点】")
        for p in analysis_result['buy_sell_points']:
            report.append(f"  {p.type.value}: {p.price}")
        report.append("")

        # 操作信号
        report.append("【操作信号】")
        report.append(f"信号: {signal['action']}")
        report.append(f"原因: {signal['reason']}")
        if signal['entry_price']:
            report.append(f"入场价: {signal['entry_price']}")
        if signal['stop_loss']:
            report.append(f"止损价: {signal['stop_loss']}")
        report.append("")

        return "\n".join(report)
