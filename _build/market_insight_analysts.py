"""
市场洞察多 Agent 系统 - 分析师模块

包含三位并行分析师：
1. market_tech_analyst: 技术面分析（MA/RSI/MACD）
2. market_macro_analyst: 宏观面分析（板块轮动、资金流向、全球影响）
3. market_sentiment_analyst: 情绪面分析（涨停池、热门股）
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import requests
import traceback
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


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
# VERDICT 提取
# ---------------------------------------------------------------------------

def extract_verdict(text: str) -> Dict[str, Any]:
    """从分析师输出中提取 VERDICT 机读块。"""
    m = re.search(r'<!--\s*VERDICT:\s*(\{.*?\})\s*-->', text or "", re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    return {"direction": "中性", "confidence": "低", "reason": ""}


# ---------------------------------------------------------------------------
# Agent 1: 市场技术分析师
# ---------------------------------------------------------------------------

async def market_tech_analyst(market_context: str, indicator_data: str) -> str:
    """分析指数技术面（MA/RSI/MACD）。"""
    from tradingagents.prompts.market_insight_prompts import get_market_insight_prompt

    system = get_market_insight_prompt("market_tech_analyst_system")
    user = get_market_insight_prompt("market_tech_analyst_user").format(
        market_context=market_context,
        indicator_data=indicator_data,
    )

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: _call_llm(system, user, max_tokens=1000))


# ---------------------------------------------------------------------------
# Agent 2: 宏观策略分析师
# ---------------------------------------------------------------------------

async def market_macro_analyst(
    market_context: str,
    board_fund_flow: str = "",
    global_news: str = "",
) -> str:
    """分析板块轮动、资金流向、全球影响。"""
    from tradingagents.prompts.market_insight_prompts import get_market_insight_prompt

    extra_parts = []
    if board_fund_flow:
        extra_parts.append(f"【行业板块资金流向】\n{board_fund_flow}")
    if global_news:
        extra_parts.append(f"【全球重要新闻】\n{global_news}")
    extra_data = "\n\n".join(extra_parts) if extra_parts else "（无额外数据）"

    system = get_market_insight_prompt("market_macro_analyst_system")
    user = get_market_insight_prompt("market_macro_analyst_user").format(
        market_context=market_context,
        extra_data=extra_data,
    )

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: _call_llm(system, user, max_tokens=1000))


# ---------------------------------------------------------------------------
# Agent 3: 市场情绪分析师
# ---------------------------------------------------------------------------

async def market_sentiment_analyst(
    market_context: str,
    zt_pool: str = "",
    hot_stocks: str = "",
) -> str:
    """分析市场情绪、涨停池、热门股。"""
    from tradingagents.prompts.market_insight_prompts import get_market_insight_prompt

    extra_parts = []
    if zt_pool:
        extra_parts.append(f"【今日涨停池数据】\n{zt_pool}")
    if hot_stocks:
        extra_parts.append(f"【雪球热门股票】\n{hot_stocks}")
    extra_data = "\n\n".join(extra_parts) if extra_parts else "（无额外数据）"

    system = get_market_insight_prompt("market_sentiment_analyst_system")
    user = get_market_insight_prompt("market_sentiment_analyst_user").format(
        market_context=market_context,
        extra_data=extra_data,
    )

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: _call_llm(system, user, max_tokens=1000))


# ---------------------------------------------------------------------------
# Agent 4: 新闻分析师
# ---------------------------------------------------------------------------

async def market_news_analyst(
    market_context: str,
    news_data: str = "",
) -> str:
    """分析新闻事件对市场的影响。"""
    from tradingagents.prompts.market_insight_prompts import get_market_insight_prompt

    system = get_market_insight_prompt("market_news_analyst_system")
    user = get_market_insight_prompt("market_news_analyst_user").format(
        market_context=market_context,
        news_data=news_data if news_data else "（无新闻数据）",
    )

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: _call_llm(system, user, max_tokens=1000))


# ---------------------------------------------------------------------------
# Agent 5: 资金分析师（聪明钱）
# ---------------------------------------------------------------------------

async def market_smart_money_analyst(
    market_context: str,
    fund_flow_data: str = "",
) -> str:
    """分析主力资金流向和聪明钱动向。"""
    from tradingagents.prompts.market_insight_prompts import get_market_insight_prompt

    system = get_market_insight_prompt("market_smart_money_analyst_system")
    user = get_market_insight_prompt("market_smart_money_analyst_user").format(
        market_context=market_context,
        fund_flow_data=fund_flow_data if fund_flow_data else "（无资金流向数据）",
    )

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: _call_llm(system, user, max_tokens=1000))
