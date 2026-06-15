"""
全市场多 Agent 分析模块 - 简化版

每个 Agent 调用独立函数分析不同维度，Research Manager 综合生成最终报告。
不依赖 LangGraph，直接调用 LLM API + 现有数据接口。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import traceback
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import requests

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


# ---------------------------------------------------------------------------
# 数据获取辅助
# ---------------------------------------------------------------------------

def _fetch_zt_pool(date_str: str) -> str:
    """获取涨停池数据，失败返回空串。"""
    try:
        from tradingagents.dataflows.interface import route_to_vendor
        return route_to_vendor("get_zt_pool", date_str)
    except Exception as e:
        logger.warning("get_zt_pool 失败: %s", e)
        return ""


def _fetch_hot_stocks() -> str:
    """获取雪球热门股票，失败返回空串。"""
    try:
        from tradingagents.dataflows.interface import route_to_vendor
        return route_to_vendor("get_hot_stocks_xq")
    except Exception as e:
        logger.warning("get_hot_stocks_xq 失败: %s", e)
        return ""


def _fetch_board_fund_flow() -> str:
    """获取行业板块资金流向，失败返回空串。"""
    try:
        from tradingagents.dataflows.interface import route_to_vendor
        return route_to_vendor("get_board_fund_flow")
    except Exception as e:
        logger.warning("get_board_fund_flow 失败: %s", e)
        return ""


def _fetch_global_news(date_str: str, days: int = 3, limit: int = 8) -> str:
    """获取全球新闻，失败返回空串。"""
    try:
        from tradingagents.dataflows.interface import route_to_vendor
        return route_to_vendor("get_global_news", date_str, days, limit)
    except Exception as e:
        logger.warning("get_global_news 失败: %s", e)
        return ""


# ---------------------------------------------------------------------------
# 市场上下文构建
# ---------------------------------------------------------------------------

def build_market_context(market_data: Dict[str, Any]) -> str:
    """将 /v1/market/overview 返回的原始数据转换为文本摘要。"""
    lines: List[str] = []
    scan_time = market_data.get("scan_time", datetime.now(_CST).strftime("%Y-%m-%d %H:%M:%S"))
    lines.append(f"数据时间: {scan_time}")

    # 指数
    lines.append("\n【大盘指数】")
    for idx in market_data.get("indices", []):
        if "error" in idx:
            lines.append(f"  {idx['name']}: 数据缺失")
            continue
        price = idx.get("price", 0)
        chg = idx.get("change_pct", 0) or 0
        sign = "+" if chg > 0 else ""
        lines.append(f"  {idx['name']}: {price}, 涨跌幅 {sign}{chg}%")

    # 行业板块
    ind = market_data.get("industry_sectors", {})
    if not ind.get("error"):
        lines.append("\n【领涨行业 TOP5】")
        for s in ind.get("gainers", []):
            chg = s.get("change_pct", 0) or 0
            sign = "+" if chg > 0 else ""
            lines.append(f"  {s.get('name','')}: {sign}{chg}%, 领涨 {s.get('leader','')}(+{s.get('leader_change_pct',0)}%)")
        lines.append("\n【领跌行业 TOP5】")
        for s in ind.get("losers", []):
            chg = s.get("change_pct", 0) or 0
            sign = "+" if chg > 0 else ""
            lines.append(f"  {s.get('name','')}: {sign}{chg}%, 领涨 {s.get('leader','')}({s.get('leader_change_pct',0)}%)")

    # 概念板块
    con = market_data.get("concept_sectors", {})
    if not con.get("error"):
        lines.append("\n【热门概念 TOP10】")
        for s in con.get("hot", []):
            chg = s.get("change_pct", 0) or 0
            sign = "+" if chg > 0 else ""
            leader = s.get("leader", "")
            leader_info = f", 领涨 {leader}({s.get('leader_change_pct',0)}%)" if leader else ""
            lines.append(f"  {s.get('name','')}: {sign}{chg}%{leader_info}")

    # 全球市场
    global_idx = market_data.get("global_indices", [])
    if global_idx:
        lines.append("\n【全球市场】")
        for gi in global_idx:
            price = gi.get("price", 0)
            chg = gi.get("change_pct", 0) or 0
            sign = "+" if chg > 0 else ""
            lines.append(f"  {gi.get('market','')}-{gi.get('name','')}: {price:,.2f}, 涨跌幅 {sign}{chg}%")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Agent 1: 宏观分析师
# ---------------------------------------------------------------------------

async def macro_analyst(context: str, extra_data: Dict[str, str] | None = None) -> str:
    """分析板块轮动、资金流向、全球市场对 A 股的影响。"""
    extra = ""
    if extra_data:
        if extra_data.get("board_fund_flow"):
            extra += f"\n\n【行业板块资金流向】\n{extra_data['board_fund_flow']}"
        if extra_data.get("global_news"):
            extra += f"\n\n【全球重要新闻】\n{extra_data['global_news']}"

    system = (
        "你是一位资深宏观策略分析师，擅长从板块轮动、资金流向、全球市场联动等"
        "维度分析 A 股市场。请用中文输出，观点明确，分析有深度。"
    )
    user = (
        f"以下是当前 A 股市场数据：\n\n{context}{extra}\n\n"
        "请从以下角度进行宏观分析：\n"
        "1. 板块轮动信号：领涨/领跌板块反映了什么样的市场逻辑？资金在往哪个方向流？\n"
        "2. 全球市场联动：美股、港股等外围市场对 A 股有何影响？\n"
        "3. 大盘趋势判断：综合指数表现，当前大盘处于什么阶段？\n"
        "4. 宏观风险提示：需要关注哪些系统性风险？\n\n"
        "输出 Markdown 格式，标题用 ##，控制在 400-600 字。"
    )

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: _call_llm(system, user, max_tokens=1000))


# ---------------------------------------------------------------------------
# Agent 2: 新闻分析师
# ---------------------------------------------------------------------------

async def news_analyst(context: str, extra_data: Dict[str, str] | None = None) -> str:
    """关联新闻事件、政策面分析。"""
    extra = ""
    if extra_data:
        if extra_data.get("global_news"):
            extra += f"\n\n【全球与国内重要新闻】\n{extra_data['global_news']}"

    system = (
        "你是一位专业财经新闻分析师，擅长从新闻事件中提炼对市场的影响。"
        "请用中文输出，观点明确，不是简单复述新闻，而是分析其市场含义。"
    )
    user = (
        f"以下是当前 A 股市场数据：\n\n{context}{extra}\n\n"
        "请从以下角度进行新闻面分析：\n"
        "1. 政策面：当前有哪些重要政策/监管动态？对市场有何影响？\n"
        "2. 行业新闻：哪些行业有重大新闻事件？如何影响相关板块？\n"
        "3. 外部事件：国际事件（如关税、地缘政治）对 A 股的影响\n"
        "4. 需要重点关注的后续事件\n\n"
        "输出 Markdown 格式，标题用 ##，控制在 400-600 字。"
    )

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: _call_llm(system, user, max_tokens=1000))


# ---------------------------------------------------------------------------
# Agent 3: 情绪分析师
# ---------------------------------------------------------------------------

async def sentiment_analyst(context: str, extra_data: Dict[str, str] | None = None) -> str:
    """市场情绪、涨停池、热门股分析。"""
    extra = ""
    if extra_data:
        if extra_data.get("zt_pool"):
            extra += f"\n\n【今日涨停池数据】\n{extra_data['zt_pool']}"
        if extra_data.get("hot_stocks"):
            extra += f"\n\n【雪球热门股票】\n{extra_data['hot_stocks']}"

    system = (
        "你是一位市场情绪分析专家，擅长从涨停板、热门股、成交量等数据"
        "判断市场情绪温度和短线机会。请用中文输出，观点明确。"
    )
    user = (
        f"以下是当前 A 股市场数据：\n\n{context}{extra}\n\n"
        "请从以下角度进行情绪面分析：\n"
        "1. 市场情绪温度：当前市场情绪是亢奋、温和还是恐慌？依据是什么？\n"
        "2. 涨停板分析：涨停家数、连板情况、涨停原因分类，反映什么信号？\n"
        "3. 热门股解读：雪球热搜股票有哪些特征？散户关注什么方向？\n"
        "4. 短线机会与风险：基于情绪面，短期有哪些值得关注的机会或风险？\n\n"
        "输出 Markdown 格式，标题用 ##，控制在 400-600 字。"
    )

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: _call_llm(system, user, max_tokens=1000))


# ---------------------------------------------------------------------------
# Research Manager: 综合所有 Agent 报告
# ---------------------------------------------------------------------------

async def research_manager(reports: List[str], context: str) -> str:
    """综合所有 Agent 报告，生成最终市场洞察。"""
    combined = ""
    labels = ["宏观分析师报告", "新闻分析师报告", "情绪分析师报告"]
    for label, report in zip(labels, reports):
        combined += f"\n\n### {label}\n{report}"

    system = (
        "你是投资研究部的首席策略师，负责综合多位分析师的报告，提炼核心观点，"
        "给出最终的市场判断和操作建议。请用中文输出，观点鲜明，逻辑清晰。"
    )
    user = (
        f"以下是当前市场数据概要：\n{context}\n\n"
        f"以下是三位分析师的独立报告：{combined}\n\n"
        "请综合以上所有信息，生成最终市场洞察报告：\n"
        "1. 市场总览（一句话概括今天市场）\n"
        "2. 核心观点（综合三位分析师的共识和分歧，给出你的判断）\n"
        "3. 板块建议：明确推荐关注的板块（附理由）和需要回避的板块\n"
        "4. 操作策略：仓位建议、投资方向\n"
        "5. 风险提示：综合各维度的主要风险\n\n"
        "要求：\n"
        "- 输出 Markdown 格式，标题用 ##\n"
        "- 总结各分析师的观点时要引用来源（宏观/新闻/情绪）\n"
        "- 控制在 600-800 字\n"
        "- 给出明确的操作建议，不要模棱两可"
    )

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: _call_llm(system, user, max_tokens=1500))


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

async def analyze_market_with_agents(market_data: Dict[str, Any]) -> str:
    """
    全市场多 Agent 分析入口。

    1. 构造市场上下文
    2. 并行获取额外数据 + 调用三个 Agent
    3. 收集报告，由 Research Manager 综合
    4. 返回最终报告
    """
    # 1. 构造市场上下文
    context = build_market_context(market_data)

    today_str = datetime.now(_CST).strftime("%Y-%m-%d")

    # 2. 并行获取额外数据（这些是 I/O 密集型，单独跑）
    extra_results = await asyncio.gather(
        asyncio.to_thread(_fetch_board_fund_flow),
        asyncio.to_thread(_fetch_global_news, today_str, 3, 8),
        asyncio.to_thread(_fetch_zt_pool, today_str),
        asyncio.to_thread(_fetch_hot_stocks),
        return_exceptions=True,
    )

    board_fund_flow = extra_results[0] if isinstance(extra_results[0], str) else ""
    global_news = extra_results[1] if isinstance(extra_results[1], str) else ""
    zt_pool = extra_results[2] if isinstance(extra_results[2], str) else ""
    hot_stocks = extra_results[3] if isinstance(extra_results[3], str) else ""

    macro_extra = {"board_fund_flow": board_fund_flow, "global_news": global_news}
    news_extra = {"global_news": global_news}
    sentiment_extra = {"zt_pool": zt_pool, "hot_stocks": hot_stocks}

    # 3. 并行调用三个 Agent（容错：单个失败不影响其他）
    async def _safe_agent(name: str, coro) -> str:
        try:
            return await coro
        except Exception as e:
            logger.error("[MultiAgent] %s 执行失败: %s\n%s", name, e, traceback.format_exc())
            return f"（{name} 分析失败: {e}）"

    reports = await asyncio.gather(
        _safe_agent("宏观分析师", macro_analyst(context, macro_extra)),
        _safe_agent("新闻分析师", news_analyst(context, news_extra)),
        _safe_agent("情绪分析师", sentiment_analyst(context, sentiment_extra)),
    )

    # 4. Research Manager 综合
    try:
        final = await research_manager(list(reports), context)
    except Exception as e:
        logger.error("[MultiAgent] Research Manager 失败: %s\n%s", e, traceback.format_exc())
        # 降级：直接拼接各报告
        final = _fallback_report(reports, context)

    return final


def _fallback_report(reports: List[str], context: str) -> str:
    """当 Research Manager 失败时的降级报告。"""
    labels = ["宏观分析", "新闻分析", "情绪分析"]
    parts = ["# 市场洞察报告（部分降级）\n"]
    parts.append(f"**数据概要**\n{context}\n")
    for label, report in zip(labels, reports):
        parts.append(f"\n---\n\n## {label}\n{report}")
    return "\n".join(parts)
