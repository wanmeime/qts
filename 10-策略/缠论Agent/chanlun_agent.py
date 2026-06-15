# -*- coding: utf-8 -*-
"""
缠论分析 Agent 主入口

整合所有模块，提供统一接口：

    agent = ChanlunAgent()
    result = agent.analyze(stock_code, daily_data, min15_data)

输出：当前状态、买点/卖点、操作信号

模块依赖：
- chanlun_core: 缠论核心算法（包含关系、分型、笔、中枢、买卖点）
- multi_level: 多级别联立分析（日线+15分钟）
- signal_output: 信号输出（买入/卖出/止损/观望）
- knowledge_base: 缠论知识库（可选，查询理论知识）
- macd_analysis: MACD分析（可选，辅助判断）
"""

import pandas as pd
from typing import Dict, Optional

from chanlun_core import ChanlunCore, Direction, BuySellType
from multi_level import MultiLevelAnalysis, MultiLevelResult
from signal_output import SignalOutput, Signal
from knowledge_base import ChanlunKnowledgeBase


class ChanlunAgent:
    """
    缠论分析 Agent

    统一接口，整合：
    - 缠论核心算法
    - 多级别联立分析
    - 信号输出（含止损规则）
    - 知识库增强（可选）

    使用方式：
        agent = ChanlunAgent()
        result = agent.analyze(stock_code, daily_df, min15_df)
    """

    def __init__(self):
        self.chanlun_core = ChanlunCore()
        self.multi_level = MultiLevelAnalysis()
        self.signal_output = SignalOutput()
        self.knowledge_base = ChanlunKnowledgeBase()

    def analyze(
        self,
        stock_code: str,
        daily_data: pd.DataFrame,
        min15_data: Optional[pd.DataFrame] = None,
    ) -> Dict:
        """
        分析股票（主入口）

        参数：
        - stock_code: 股票代码（如 "600186"）
        - daily_data: 日线K线数据，必须包含 open, high, low, close 列
        - min15_data: 15分钟K线数据（可选），同样需要 open, high, low, close 列

        返回：
        分析结果字典，包含：
        - stock_code: 股票代码
        - chanlun: 缠论核心分析结果（processed_klines, fractals, bis, zhong_shus, buy_sell_points）
        - multi_level: 多级别联立分析结果
        - signal: 交易信号（Signal对象）
        - report: 完整文本报告
        """
        # 验证输入
        if not self._validate_data(daily_data):
            return self._error_result(stock_code, "日线数据格式不正确，必须包含 open, high, low, close 列")

        # ---- 1. 缠论核心分析（日线） ----
        chanlun_result = self.chanlun_core.analyze(daily_data)

        # ---- 2. 获取当前价格 ----
        current_price = self._get_current_price(daily_data)

        # ---- 3. 多级别联立分析 ----
        multi_level_result = None
        if min15_data is not None and self._validate_data(min15_data):
            multi_level_result = self.multi_level.analyze_multi_level(
                stock_code, daily_data, min15_data
            )
        else:
            # 仅日线分析
            multi_level_result = self.multi_level.analyze_multi_level(
                stock_code, daily_data, None
            )

        # ---- 4. 生成交易信号 ----
        signal = self.signal_output.generate_signal(
            chanlun_result, multi_level_result, current_price
        )

        # ---- 5. 知识库增强（可选） ----
        kb_content = self._query_knowledge_base(chanlun_result, signal)

        # ---- 6. 生成完整报告 ----
        report = self.signal_output.generate_full_report(
            stock_code, chanlun_result, multi_level_result, signal
        )

        # 追加知识库内容
        if kb_content:
            report += "\n\n" + kb_content

        return {
            'stock_code': stock_code,
            'chanlun': chanlun_result,
            'multi_level': multi_level_result,
            'signal': signal,
            'report': report,
        }

    def quick_analyze(self, stock_code: str, kline_data: pd.DataFrame) -> str:
        """
        快速分析，只返回文本报告

        不做多级别分析，适合快速查看。
        """
        result = self.analyze(stock_code, kline_data)
        return result['report']

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _validate_data(self, df: pd.DataFrame) -> bool:
        """验证输入数据格式"""
        if df is None or len(df) == 0:
            return False
        required_columns = ['open', 'high', 'low', 'close']
        return all(col in df.columns for col in required_columns)

    def _get_current_price(self, df: pd.DataFrame) -> float:
        """获取当前价格（最后一根K线的收盘价）"""
        if df is not None and len(df) > 0:
            return float(df['close'].iloc[-1])
        return None

    def _query_knowledge_base(self, chanlun_result: dict, signal: Signal) -> str:
        """
        查询知识库，生成增强内容

        根据分析中发现的买卖点和中枢，查询相关缠论理论知识。
        """
        if not self.knowledge_base.is_available():
            return ""

        sections = []

        # 买卖点相关知识
        if chanlun_result.get('buy_sell_points'):
            point_types = set()
            for p in chanlun_result['buy_sell_points']:
                point_types.add(p.type.value)

            for pt in sorted(point_types):
                rules = self.knowledge_base.get_buy_sell_rules(pt)
                if rules.get('found'):
                    sections.append(
                        f"【{rules.get('cn_name', pt)}规则参考】\n{rules['content']}"
                    )

        # 中枢相关知识
        if chanlun_result.get('zhong_shus'):
            zs_info = self.knowledge_base.get_zhong_shu_rules()
            if zs_info.get('found'):
                sections.append(f"【中枢规则参考】\n{zs_info['content']}")

        # 基于信号的语义搜索
        if signal.signal_type in ('buy', 'sell') and signal.reasons:
            context = " ".join(signal.reasons)
            enhancement = self.knowledge_base.enhance_analysis(context, top_k=2)
            if enhancement.get('enhanced'):
                refs = []
                for ref in enhancement['references']:
                    refs.append(f"  [{ref['score']:.2f}] {ref['source']}")
                sections.append("【相关知识参考】\n" + "\n".join(refs))

        if not sections:
            return ""

        lines = ["=" * 60]
        lines.append("知识库参考")
        lines.append("=" * 60)
        lines.append("")
        lines.append("\n\n".join(sections))
        lines.append("")

        return "\n".join(lines)

    def _error_result(self, stock_code: str, message: str) -> Dict:
        """生成错误结果"""
        return {
            'stock_code': stock_code,
            'chanlun': {},
            'multi_level': None,
            'signal': Signal(
                timestamp="",
                signal_type="error",
                strength=0,
                reasons=[message],
            ),
            'report': f"分析失败: {message}",
        }
