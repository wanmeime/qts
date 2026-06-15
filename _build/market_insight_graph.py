"""
全市场多 Agent 分析模块 - 增强版（含辩论机制 + 增强报告）

流程：
1. MarketDataCollector 并行采集所有市场数据
2. 5 个 Analyst 并行分析（技术面/宏观面/情绪面/新闻面/资金面）
3. Bull vs Bear 辩论（2轮，可配置）
4. Research Manager 综合辩论结果生成增强版报告：
   - 指数详细数据表格
   - 多维度评分表格（每个Agent输出评分）
   - 因果联动分析章节
   - 趋势预判章节（完全分类：反弹上涨/继续下跌/横盘整理）

不依赖 LangGraph，使用纯 Python asyncio 实现流程编排。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import requests
import traceback
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from tradingagents.agents.utils.debate_utils import (
    format_claims_for_prompt,
    format_claim_subset_for_prompt,
    update_debate_state_with_payload,
    default_round_goal,
)

logger = logging.getLogger(__name__)

_CST = timezone(timedelta(hours=8))


# ---------------------------------------------------------------------------
# LLM 调用封装
# ---------------------------------------------------------------------------

def _call_llm(system_prompt: str, user_prompt: str, *, max_tokens: int = 1500) -> str:
    """同步调用 OpenAI 兼容 API，返回文本内容。"""
    api_key = os.environ.get("TA_API_KEY", "")
    base_url = os.environ.get("TA_BASE_URL", "https://api.openai.com/v1")
    model = os.environ.get("TA_LLM_DEEP", "gpt-4o-mini")

    if not api_key:
        raise RuntimeError("TA_API_KEY 未设置")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.7,
        "max_tokens": max_tokens,
    }
    url = f"{base_url.rstrip('/')}/chat/completions"
    resp = requests.post(url, headers=headers, json=payload, timeout=120)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _extract_verdict(text: str) -> Dict[str, Any]:
    """从输出中提取 VERDICT 机读块。"""
    m = re.search(r'<!--\s*VERDICT:\s*(\{.*?\})\s*-->', text or "", re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    return {"direction": "中性", "confidence": "低", "reason": "", "scores": {}}


# ---------------------------------------------------------------------------
# 指数数据表格生成
# ---------------------------------------------------------------------------

def _build_index_table(market_data: Dict[str, Any]) -> str:
    """从 market_data 构建指数数据表格（只含收盘点数和涨跌幅）。"""
    overview = market_data.get("market_overview", market_data)
    indices = overview.get("indices", [])
    global_indices = overview.get("global_indices", [])
    if not indices and not global_indices:
        return ""

    rows = []

    # 国内指数
    for idx in indices:
        if "error" in idx:
            rows.append(f"| {idx.get('name', 'N/A')} | 数据缺失 | - |")
            continue
        name = idx.get("name", "N/A")
        close_price = idx.get("price", "N/A")
        chg_pct = idx.get("change_pct", 0) or 0
        sign = "+" if chg_pct > 0 else ""
        rows.append(f"| {name} | {close_price} | {sign}{chg_pct}% |")

    # 全球指数
    for gi in global_indices:
        if "error" in gi:
            rows.append(f"| {gi.get('market', '')} {gi.get('name', 'N/A')} | 数据缺失 | - |")
            continue
        market = gi.get("market", "")
        name = gi.get("name", "N/A")
        label = f"{market} {name}" if market else name
        close_price = gi.get("price", "N/A")
        chg_pct = gi.get("change_pct", 0) or 0
        sign = "+" if chg_pct > 0 else ""
        rows.append(f"| {label} | {close_price:,.2f} | {sign}{chg_pct}% |")

    header = "| 指数 | 收盘点数 | 涨跌幅 |\n| --- | --- | --- |"
    return header + "\n" + "\n".join(rows)


# ---------------------------------------------------------------------------
# 多维度评分表格生成
# ---------------------------------------------------------------------------

def _build_score_table(verdicts: Dict[str, Dict[str, Any]], analyst_names: List[str]) -> str:
    """从各分析师 VERDICT 中提取 scores，构建评分表格。

    scores 是每个分析师对四个维度的评分（1-5分）。
    最终综合评分取各分析师的平均值。
    """
    dimensions = ["趋势", "动量", "情绪", "政策"]
    all_scores: Dict[str, List[int]] = {d: [] for d in dimensions}

    for name in analyst_names:
        v = verdicts.get(name, {})
        scores = v.get("scores", {})
        for d in dimensions:
            s = scores.get(d)
            if s is not None:
                try:
                    all_scores[d].append(int(s))
                except (ValueError, TypeError):
                    pass

    # 计算各维度的平均分
    avg_scores: Dict[str, str] = {}
    for d in dimensions:
        vals = all_scores[d]
        if vals:
            avg = sum(vals) / len(vals)
            avg_scores[d] = f"{avg:.1f}/5"
        else:
            avg_scores[d] = "N/A"

    # 构建各分析师的评分来源说明
    score_details: Dict[str, List[str]] = {d: [] for d in dimensions}
    for name in analyst_names:
        v = verdicts.get(name, {})
        scores = v.get("scores", {})
        for d in dimensions:
            s = scores.get(d)
            if s is not None:
                score_details[d].append(f"{name}:{s}")

    # 生成表格
    lines = ["| 维度 | 综合评分 | 各分析师评分 |", "| --- | --- | --- |"]
    for d in dimensions:
        detail = ", ".join(score_details[d]) if score_details[d] else "无数据"
        lines.append(f"| {d} | {avg_scores[d]} | {detail} |")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 辩论状态初始化
# ---------------------------------------------------------------------------

def _build_empty_debate_state() -> Dict[str, Any]:
    """构建空的辩论状态。"""
    return {
        "history": "",
        "bull_history": "",
        "bear_history": "",
        "current_speaker": "",
        "current_response": "",
        "count": 0,
        "claims": [],
        "claim_counter": 0,
        "open_claim_ids": [],
        "resolved_claim_ids": [],
        "unresolved_claim_ids": [],
        "focus_claim_ids": [],
        "round_summary": "",
        "round_goal": default_round_goal("investment", 1),
    }


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

class MarketInsightGraph:
    """全市场多 Agent 分析流程编排器（增强版）。

    流程：
    1. 数据采集 -> 2. 5个Analyst并行 -> 3. Bull vs Bear辩论 -> 4. Research Manager综合
    5. 增强报告生成（指数表格 + 评分表格 + 因果分析 + 趋势预判）
    """

    def __init__(self, max_debate_rounds: int = 2):
        """
        Args:
            max_debate_rounds: 辩论最大轮次（每轮 = Bull + Bear 各发言一次）
        """
        self.max_debate_rounds = max_debate_rounds

    async def analyze(self, market_data: Dict[str, Any]) -> str:
        """执行完整的市场洞察分析流程。

        Args:
            market_data: 市场数据字典，由 MarketDataCollector.collect_all() 生成

        Returns:
            Markdown 格式的最终市场洞察报告（增强版）
        """
        from tradingagents.graph.market_data_collector import build_market_context
        from tradingagents.graph.market_insight_analysts import (
            market_tech_analyst,
            market_macro_analyst,
            market_sentiment_analyst,
            market_news_analyst,
            market_smart_money_analyst,
        )
        from tradingagents.prompts.market_insight_prompts import get_market_insight_prompt

        logger.info("[MarketInsight] 开始全市场多 Agent 分析（增强版）")

        # -- Step 1: 构建市场上下文 --
        market_context = build_market_context(market_data)

        # 构建技术指标数据文本
        tech_indicators = market_data.get("technical_indicators", {})
        indicator_text = self._format_indicators(tech_indicators)

        # -- Step 2: 并行调用五个 Analyst --
        logger.info("[MarketInsight] 并行启动 5 个分析师")

        async def _safe_analyst(name: str, coro) -> str:
            try:
                return await coro
            except Exception as e:
                logger.error("[MarketInsight] %s 执行失败: %s\n%s", name, e, traceback.format_exc())
                return f"（{name} 分析失败: {e}）"

        # 构建新闻数据文本
        news_data_parts = []
        global_news = market_data.get("global_news", "")
        if global_news:
            news_data_parts.append(f"【全球重要新闻】\n{global_news}")
        news_text = "\n\n".join(news_data_parts) if news_data_parts else "（无新闻数据）"

        # 构建资金流向数据文本
        fund_flow_parts = []
        board_fund_flow = market_data.get("board_fund_flow", "")
        if board_fund_flow:
            fund_flow_parts.append(f"【行业板块资金流向】\n{board_fund_flow}")
        fund_flow_text = "\n\n".join(fund_flow_parts) if fund_flow_parts else "（无资金流向数据）"

        tech_report, macro_report, sentiment_report, news_report, smart_money_report = await asyncio.gather(
            _safe_analyst("技术分析师", market_tech_analyst(market_context, indicator_text)),
            _safe_analyst("宏观分析师", market_macro_analyst(
                market_context,
                board_fund_flow=market_data.get("board_fund_flow", ""),
                global_news=market_data.get("global_news", ""),
            )),
            _safe_analyst("情绪分析师", market_sentiment_analyst(
                market_context,
                zt_pool=market_data.get("zt_pool", ""),
                hot_stocks=market_data.get("hot_stocks", ""),
            )),
            _safe_analyst("新闻分析师", market_news_analyst(
                market_context,
                news_data=news_text,
            )),
            _safe_analyst("资金分析师", market_smart_money_analyst(
                market_context,
                fund_flow_data=fund_flow_text,
            )),
        )

        logger.info("[MarketInsight] 五位分析师报告完成")

        # 提取各分析师的 VERDICT
        tech_verdict = _extract_verdict(tech_report)
        macro_verdict = _extract_verdict(macro_report)
        sentiment_verdict = _extract_verdict(sentiment_report)
        news_verdict = _extract_verdict(news_report)
        smart_money_verdict = _extract_verdict(smart_money_report)

        verdicts = {
            "技术": tech_verdict,
            "宏观": macro_verdict,
            "情绪": sentiment_verdict,
            "新闻": news_verdict,
            "资金": smart_money_verdict,
        }

        logger.info(
            "[MarketInsight] VERDICT - 技术:%s, 宏观:%s, 情绪:%s, 新闻:%s, 资金:%s",
            tech_verdict.get("direction"),
            macro_verdict.get("direction"),
            sentiment_verdict.get("direction"),
            news_verdict.get("direction"),
            smart_money_verdict.get("direction"),
        )

        # -- Step 3: Bull vs Bear 辩论 --
        logger.info("[MarketInsight] 启动辩论（最多 %d 轮）", self.max_debate_rounds)

        debate_state = _build_empty_debate_state()
        debate_state = await self._run_debate(
            debate_state, tech_report, macro_report, sentiment_report, news_report, smart_money_report
        )

        logger.info("[MarketInsight] 辩论完成，共 %d 轮", debate_state["count"])

        # -- Step 4: Research Manager 综合 --
        logger.info("[MarketInsight] Research Manager 开始综合")

        core_report = await self._research_manager_synthesize(
            debate_state, tech_report, macro_report, sentiment_report, news_report, smart_money_report
        )

        logger.info("[MarketInsight] 核心报告生成完成，长度=%d", len(core_report))

        # -- Step 5: 增强报告生成 --
        logger.info("[MarketInsight] 开始生成增强版报告")

        enhanced_report = self._build_enhanced_report(
            market_data=market_data,
            core_report=core_report,
            verdicts=verdicts,
            analyst_names=["技术", "宏观", "情绪", "新闻", "资金"],
        )

        logger.info("[MarketInsight] 增强版报告生成完成，长度=%d", len(enhanced_report))

        return enhanced_report

    def _build_enhanced_report(
        self,
        market_data: Dict[str, Any],
        core_report: str,
        verdicts: Dict[str, Dict[str, Any]],
        analyst_names: List[str],
    ) -> str:
        """构建增强版报告，包含指数表格、评分表格、因果分析、趋势预判。"""
        parts = []

        # 1. 报告标题和时间
        scan_time = market_data.get("scan_time", datetime.now(_CST).strftime("%Y-%m-%d %H:%M:%S"))
        parts.append(f"# 全市场洞察报告（增强版）\n\n> 数据时间: {scan_time}\n")

        # 2. 指数数据表格（国内+全球，只含收盘和涨跌幅）
        index_table = _build_index_table(market_data)
        if index_table:
            parts.append(f"## 指数数据\n\n{index_table}\n")

        # 3. 多维度评分表格
        score_table = _build_score_table(verdicts, analyst_names)
        if score_table:
            parts.append(f"## 多维度评分\n\n{score_table}\n")

        # 4. 核心分析报告（来自 Research Manager）
        parts.append(f"## 核心分析\n\n{core_report}\n")

        # 5. 因果联动分析
        causal_analysis = self._build_causal_analysis(verdicts, analyst_names)
        if causal_analysis:
            parts.append(f"## 因果联动分析\n\n{causal_analysis}\n")

        # 6. 趋势预判（通过 LLM 生成）
        trend_prediction = self._build_trend_prediction(core_report, verdicts, analyst_names)
        if trend_prediction:
            parts.append(f"## 趋势预判\n\n{trend_prediction}\n")

        return "\n".join(parts)

    def _build_causal_analysis(
        self,
        verdicts: Dict[str, Dict[str, Any]],
        analyst_names: List[str],
    ) -> str:
        """构建因果联动分析文本。

        基于各分析师的方向判断，分析维度之间的联动关系。
        """
        directions = {}
        reasons = {}
        for name in analyst_names:
            v = verdicts.get(name, {})
            directions[name] = v.get("direction", "中性")
            reasons[name] = v.get("reason", "")

        # 构建分析文本
        lines = []

        # 描述各维度状态
        lines.append("### 各维度状态\n")
        for name in analyst_names:
            d = directions[name]
            r = reasons[name]
            lines.append(f"- **{name}面**: {d}" + (f" -- {r}" if r else ""))

        lines.append("")

        # 分析联动关系
        lines.append("### 联动关系\n")

        # 政策 -> 资金 -> 情绪 传导链
        policy_dir = directions.get("政策", directions.get("新闻", "中性"))
        fund_dir = directions.get("资金", "中性")
        emotion_dir = directions.get("情绪", "中性")
        tech_dir = directions.get("技术", "中性")
        macro_dir = directions.get("宏观", "中性")

        # 传导链条分析
        chain_parts = []
        if policy_dir in ("看多", "偏多"):
            chain_parts.append("政策面偏暖 -> 可能带动资金流入 -> 利好市场情绪")
        elif policy_dir in ("看空", "偏空"):
            chain_parts.append("政策面偏冷 -> 可能导致资金流出 -> 打压市场情绪")
        else:
            chain_parts.append("政策面中性 -> 资金面和情绪面更多受市场自身因素驱动")

        if fund_dir in ("看多", "偏多"):
            chain_parts.append("资金面积极 -> 主力资金流入 -> 对技术面形成支撑")
        elif fund_dir in ("看空", "偏空"):
            chain_parts.append("资金面消极 -> 资金持续流出 -> 技术面承压")
        else:
            chain_parts.append("资金面中性 -> 资金流向尚无明确方向")

        if emotion_dir in ("看多", "偏多"):
            chain_parts.append("情绪面积极 -> 市场参与度高 -> 有利于技术面走强")
        elif emotion_dir in ("看空", "偏空"):
            chain_parts.append("情绪面悲观 -> 市场参与度低 -> 技术面缺乏反弹动力")

        for part in chain_parts:
            lines.append(f"1. {part}")

        # 一致性分析
        lines.append("\n### 维度一致性\n")
        bullish_count = sum(1 for d in directions.values() if d in ("看多", "偏多"))
        bearish_count = sum(1 for d in directions.values() if d in ("看空", "偏空"))
        neutral_count = len(directions) - bullish_count - bearish_count

        if bullish_count >= 4:
            lines.append("多维度高度一致看多（{}/5维度看多），信号强烈。".format(bullish_count))
        elif bullish_count >= 3:
            lines.append("多数维度偏多（{}/5维度看多），但存在分歧。".format(bullish_count))
        elif bearish_count >= 4:
            lines.append("多维度高度一致看空（{}/5维度看空），信号强烈。".format(bearish_count))
        elif bearish_count >= 3:
            lines.append("多数维度偏空（{}/5维度看空），但存在分歧。".format(bearish_count))
        else:
            lines.append("各维度分歧较大（看多:{}，看空:{}，中性:{}），市场方向不明朗。".format(
                bullish_count, bearish_count, neutral_count))

        return "\n".join(lines)

    def _build_trend_prediction(
        self,
        core_report: str,
        verdicts: Dict[str, Dict[str, Any]],
        analyst_names: List[str],
    ) -> str:
        """调用 LLM 生成趋势预判章节。"""
        from tradingagents.prompts.market_insight_prompts import get_market_insight_prompt

        # 构建维度评分摘要
        dimensions = ["趋势", "动量", "情绪", "政策"]
        score_lines = []
        for name in analyst_names:
            v = verdicts.get(name, {})
            scores = v.get("scores", {})
            parts = []
            for d in dimensions:
                s = scores.get(d)
                if s is not None:
                    parts.append(f"{d}:{s}")
            if parts:
                score_lines.append(f"- {name}面: {', '.join(parts)}")

        dimension_scores = "\n".join(score_lines) if score_lines else "（评分数据暂不可用）"

        system = (
            "你是资深市场策略师，擅长对市场走势进行情景分析和概率评估。"
            "请用中文输出，逻辑清晰，观点明确。"
        )

        user = get_market_insight_prompt("market_trend_prediction_prompt").format(
            final_judgment=core_report,
            dimension_scores=dimension_scores,
        )

        try:
            result = _call_llm(system, user, max_tokens=4000)
            return result
        except Exception as e:
            logger.error("[MarketInsight] 趋势预判生成失败: %s", e)
            return self._fallback_trend_prediction(verdicts, analyst_names)

    def _fallback_trend_prediction(
        self,
        verdicts: Dict[str, Dict[str, Any]],
        analyst_names: List[str],
    ) -> str:
        """趋势预判的降级方案（不调用LLM）。"""
        # 统计各方向
        bullish = 0
        bearish = 0
        for name in analyst_names:
            d = verdicts.get(name, {}).get("direction", "中性")
            if d in ("看多", "偏多"):
                bullish += 1
            elif d in ("看空", "偏空"):
                bearish += 1

        total = bullish + bearish + (len(analyst_names) - bullish - bearish)
        if total == 0:
            total = 1

        # 根据比例估算概率
        bullish_pct = round(bullish / len(analyst_names) * 100)
        bearish_pct = round(bearish / len(analyst_names) * 100)
        flat_pct = max(0, 100 - bullish_pct - bearish_pct)

        # 调整使得总和为100
        if bullish_pct + bearish_pct + flat_pct != 100:
            flat_pct = 100 - bullish_pct - bearish_pct

        lines = [
            "### 情景A：反弹上涨",
            f"- 触发条件：多维度信号转多，资金面持续流入，情绪面企稳回升",
            f"- 关键观察：涨停家数回升、北向资金净流入、技术指标金叉",
            f"- 概率评估：{'高' if bullish_pct >= 50 else '中' if bullish_pct >= 30 else '低'}（约{bullish_pct}%）",
            "- 目标位：关注前高压力位",
            "",
            "### 情景B：继续下跌",
            f"- 触发条件：空头信号增强，资金面持续流出，情绪面恶化",
            f"- 关键观察：跌停家数增加、北向资金净流出、技术指标死叉",
            f"- 概率评估：{'高' if bearish_pct >= 50 else '中' if bearish_pct >= 30 else '低'}（约{bearish_pct}%）",
            "- 支撑位：关注前期低点支撑",
            "",
            "### 情景C：横盘整理",
            f"- 触发条件：多空分歧加大，市场等待新的催化信号",
            f"- 关键观察：成交量变化、板块轮动速度、政策面动向",
            f"- 概率评估：{'高' if flat_pct >= 50 else '中' if flat_pct >= 30 else '低'}（约{flat_pct}%）",
            "- 震荡区间：在当前价位上下窄幅波动",
        ]

        return "\n".join(lines)

    async def _run_debate(
        self,
        state: Dict[str, Any],
        tech_report: str,
        macro_report: str,
        sentiment_report: str,
        news_report: str = "",
        smart_money_report: str = "",
    ) -> Dict[str, Any]:
        """执行 Bull vs Bear 辩论。"""
        from tradingagents.graph.market_insight_analysts import _call_llm
        from tradingagents.prompts.market_insight_prompts import get_market_insight_prompt

        past_memory_str = ""

        for round_num in range(1, self.max_debate_rounds + 1):
            logger.info("[Debate] === 第 %d 轮 ===", round_num)

            # -- Bull 发言 --
            bull_prompt = get_market_insight_prompt("market_bull_prompt").format(
                tech_report=tech_report,
                macro_report=macro_report,
                sentiment_report=sentiment_report,
                news_report=news_report,
                smart_money_report=smart_money_report,
                history=state.get("history", ""),
                current_response=state.get("current_response", "（辩论刚开始，无对方发言）"),
                past_memory_str=past_memory_str,
            )

            bull_system = (
                "你是看多研究员（Bull Researcher），专注寻找市场上涨的证据。"
                "请用中文输出你的看多论据，结尾附上 DEBATE_STATE 机读块。"
            )

            bull_response = await asyncio.get_event_loop().run_in_executor(
                None, lambda: _call_llm(bull_system, bull_prompt, max_tokens=800)
            )

            state = update_debate_state_with_payload(
                state=state,
                raw_response=bull_response,
                speaker_label="Bull Researcher",
                speaker_key="Bull",
                stance="bullish",
                history_key="bull_history",
                marker="DEBATE_STATE",
                claim_prefix="INV",
                domain="investment",
                speaker_field="current_speaker",
            )

            logger.info("[Debate] Bull 发言完成 (count=%d)", state["count"])

            # -- Bear 发言 --
            bear_prompt = get_market_insight_prompt("market_bear_prompt").format(
                tech_report=tech_report,
                macro_report=macro_report,
                sentiment_report=sentiment_report,
                news_report=news_report,
                smart_money_report=smart_money_report,
                history=state.get("history", ""),
                current_response=state.get("current_response", ""),
                past_memory_str=past_memory_str,
            )

            bear_system = (
                "你是看空研究员（Bear Researcher），专注寻找市场下跌的证据。"
                "请用中文输出你的看空论据，结尾附上 DEBATE_STATE 机读块。"
            )

            bear_response = await asyncio.get_event_loop().run_in_executor(
                None, lambda: _call_llm(bear_system, bear_prompt, max_tokens=800)
            )

            state = update_debate_state_with_payload(
                state=state,
                raw_response=bear_response,
                speaker_label="Bear Researcher",
                speaker_key="Bear",
                stance="bearish",
                history_key="bear_history",
                marker="DEBATE_STATE",
                claim_prefix="INV",
                domain="investment",
                speaker_field="current_speaker",
            )

            logger.info("[Debate] Bear 发言完成 (count=%d)", state["count"])

        return state

    async def _research_manager_synthesize(
        self,
        debate_state: Dict[str, Any],
        tech_report: str,
        macro_report: str,
        sentiment_report: str,
        news_report: str = "",
        smart_money_report: str = "",
    ) -> str:
        """Research Manager 综合辩论结果和分析师报告。"""
        from tradingagents.graph.market_insight_analysts import _call_llm
        from tradingagents.prompts.market_insight_prompts import get_market_insight_prompt

        claims = debate_state.get("claims", [])
        unresolved_claim_ids = debate_state.get("unresolved_claim_ids", [])

        claims_text = format_claims_for_prompt(claims)
        unresolved_claims_text = format_claim_subset_for_prompt(claims, unresolved_claim_ids)
        round_summary = debate_state.get("round_summary", "") or "辩论已完成。"

        system = (
            "你是投资研究部的首席策略师，负责综合辩论双方观点和五位分析师（技术面/宏观面/情绪面/新闻面/资金面）的报告，"
            "给出最终市场判断。请用中文输出，观点鲜明，逻辑清晰。"
        )

        user = get_market_insight_prompt("market_research_manager_prompt").format(
            debate_history=debate_state.get("history", ""),
            claims_text=claims_text,
            unresolved_claims_text=unresolved_claims_text,
            round_summary=round_summary,
            past_memory_str="",
        )

        return await asyncio.get_event_loop().run_in_executor(
            None, lambda: _call_llm(system, user, max_tokens=2000)
        )

    def _format_indicators(self, indicators: Dict[str, Any]) -> str:
        """将技术指标数据格式化为文本。"""
        if not indicators:
            return "（无技术指标数据）"

        lines = ["【指数技术指标汇总】"]
        for name, ind in indicators.items():
            if "error" in ind:
                lines.append(f"  {name}: {ind['error']}")
                continue

            lines.append(f"\n  === {name} ===")
            lines.append(f"  最新收盘: {ind.get('latest_close', 'N/A')}")

            # 均线
            ma_vals = []
            for ma_name in ["ma5", "ma10", "ma20", "ma60"]:
                v = ind.get(ma_name)
                if v is not None:
                    ma_vals.append(f"{ma_name.upper()}={v}")
            if ma_vals:
                lines.append(f"  均线: {', '.join(ma_vals)}")

            # RSI
            rsi6 = ind.get("rsi6")
            rsi12 = ind.get("rsi12")
            if rsi6 is not None or rsi12 is not None:
                lines.append(f"  RSI: RSI6={rsi6}, RSI12={rsi12}")

            # MACD
            macd_l = ind.get("macd_line")
            macd_s = ind.get("macd_signal")
            macd_h = ind.get("macd_histogram")
            if macd_l is not None:
                lines.append(f"  MACD: DIF={macd_l}, DEA={macd_s}, 柱状={macd_h}")

            # 趋势和动量
            lines.append(f"  趋势判断: {ind.get('trend', 'N/A')}")
            lines.append(f"  动量判断: {ind.get('momentum', 'N/A')}")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# 主入口函数（保持向后兼容）
# ---------------------------------------------------------------------------

async def analyze_market_with_agents(market_data: Dict[str, Any]) -> str:
    """全市场多 Agent 分析入口（增强版，含辩论机制 + 增强报告）。

    Args:
        market_data: 市场数据字典

    Returns:
        Markdown 格式的市场洞察报告（增强版）
    """
    graph = MarketInsightGraph(max_debate_rounds=2)
    return await graph.analyze(market_data)
