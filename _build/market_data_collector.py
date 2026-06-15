"""
市场数据采集模块 - 全市场多 Agent 分析所需数据

采集内容：
1. 指数 K 线（上证、深成指、沪深300、创业板指、科创50）
2. 板块数据（行业、概念）
3. 全球市场数据
4. 市场情绪数据（涨停池、热门股）
5. 新闻数据
6. 技术指标计算
"""

from __future__ import annotations

import asyncio
import logging
import traceback
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_CST = timezone(timedelta(hours=8))


class MarketDataCollector:
    """采集全市场分析所需数据的统一入口。"""

    def __init__(self):
        self._cache: Dict[str, Any] = {}
        self._cache_time: Optional[datetime] = None

    async def collect_all(self) -> Dict[str, Any]:
        """并行采集所有市场数据，返回统一数据字典。"""
        now = datetime.now(_CST)
        today_str = now.strftime("%Y-%m-%d")

        # 并行采集所有数据
        results = await asyncio.gather(
            self._fetch_market_overview(),
            self._fetch_board_fund_flow(),
            self._fetch_global_news(today_str, 3, 8),
            self._fetch_zt_pool(today_str),
            self._fetch_hot_stocks(),
            self._fetch_index_klines(),
            return_exceptions=True,
        )

        market_overview = results[0] if isinstance(results[0], dict) else {}
        board_fund_flow = results[1] if isinstance(results[1], str) else ""
        global_news = results[2] if isinstance(results[2], str) else ""
        zt_pool = results[3] if isinstance(results[3], str) else ""
        hot_stocks = results[4] if isinstance(results[4], str) else ""
        index_klines = results[5] if isinstance(results[5], dict) else {}

        # 计算技术指标
        technical_indicators = self._compute_technical_indicators(index_klines)

        return {
            "scan_time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "market_overview": market_overview,
            "board_fund_flow": board_fund_flow,
            "global_news": global_news,
            "zt_pool": zt_pool,
            "hot_stocks": hot_stocks,
            "index_klines": index_klines,
            "technical_indicators": technical_indicators,
        }

    async def _fetch_market_overview(self) -> Dict[str, Any]:
        """获取全市场概览数据（指数+板块）。"""
        try:
            from tradingagents.dataflows.providers.market_scanner import MarketScanner
            loop = asyncio.get_event_loop()
            scanner = MarketScanner()
            return await loop.run_in_executor(None, scanner.scan_all)
        except Exception as e:
            logger.error("获取市场概览失败: %s\n%s", e, traceback.format_exc())
            return {"indices": [], "industry_sectors": {}, "concept_sectors": {}, "global_indices": []}

    async def _fetch_board_fund_flow(self) -> str:
        """获取行业板块资金流向。"""
        try:
            from tradingagents.dataflows.interface import route_to_vendor
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, lambda: route_to_vendor("get_board_fund_flow"))
        except Exception as e:
            logger.warning("获取板块资金流向失败: %s", e)
            return ""

    async def _fetch_global_news(self, date_str: str, days: int = 3, limit: int = 8) -> str:
        """获取全球新闻。"""
        try:
            from tradingagents.dataflows.interface import route_to_vendor
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None, lambda: route_to_vendor("get_global_news", date_str, days, limit)
            )
        except Exception as e:
            logger.warning("获取全球新闻失败: %s", e)
            return ""

    async def _fetch_zt_pool(self, date_str: str) -> str:
        """获取涨停池数据。"""
        try:
            from tradingagents.dataflows.interface import route_to_vendor
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, lambda: route_to_vendor("get_zt_pool", date_str))
        except Exception as e:
            logger.warning("获取涨停池失败: %s", e)
            return ""

    async def _fetch_hot_stocks(self) -> str:
        """获取雪球热门股票。"""
        try:
            from tradingagents.dataflows.interface import route_to_vendor
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, lambda: route_to_vendor("get_hot_stocks_xq"))
        except Exception as e:
            logger.warning("获取热门股票失败: %s", e)
            return ""

    async def _fetch_index_klines(self) -> Dict[str, Any]:
        """获取主要指数K线数据，用于技术指标计算。"""
        try:
            import akshare as ak
            import pandas as pd

            indices = [
                {"code": "000001", "name": "上证指数", "ak_code": "sh000001"},
                {"code": "399001", "name": "深证成指", "ak_code": "sz399001"},
                {"code": "000300", "name": "沪深300", "ak_code": "sh000300"},
                {"code": "399006", "name": "创业板指", "ak_code": "sz399006"},
            ]

            result = {}
            loop = asyncio.get_event_loop()

            for idx in indices:
                try:
                    df = await loop.run_in_executor(
                        None, lambda code=idx["ak_code"]: ak.stock_zh_index_daily(symbol=code)
                    )
                    if df is not None and not df.empty:
                        df = df.tail(60)  # 最近60个交易日
                        result[idx["name"]] = {
                            "code": idx["code"],
                            "data": df.to_dict("records") if hasattr(df, "to_dict") else [],
                            "close": [float(x) for x in df["close"].tolist()] if "close" in df.columns else [],
                            "high": [float(x) for x in df["high"].tolist()] if "high" in df.columns else [],
                            "low": [float(x) for x in df["low"].tolist()] if "low" in df.columns else [],
                            "volume": [float(x) for x in df["volume"].tolist()] if "volume" in df.columns else [],
                        }
                except Exception as e:
                    logger.warning("获取指数 %s K线失败: %s", idx["name"], e)

            return result
        except Exception as e:
            logger.error("获取指数K线失败: %s\n%s", e, traceback.format_exc())
            return {}

    def _compute_technical_indicators(self, index_klines: Dict[str, Any]) -> Dict[str, Any]:
        """计算技术指标（MA/RSI/MACD）。"""
        indicators = {}
        for name, kdata in index_klines.items():
            closes = kdata.get("close", [])
            if len(closes) < 20:
                indicators[name] = {"error": "数据不足"}
                continue

            try:
                # MA 均线
                ma5 = _sma(closes, 5)
                ma10 = _sma(closes, 10)
                ma20 = _sma(closes, 20)
                ma60 = _sma(closes, 60) if len(closes) >= 60 else None

                # RSI
                rsi6 = _rsi(closes, 6)
                rsi12 = _rsi(closes, 12)

                # MACD
                macd_line, signal_line, histogram = _macd(closes)

                indicators[name] = {
                    "latest_close": closes[-1],
                    "ma5": ma5,
                    "ma10": ma10,
                    "ma20": ma20,
                    "ma60": ma60,
                    "rsi6": rsi6,
                    "rsi12": rsi12,
                    "macd_line": macd_line,
                    "macd_signal": signal_line,
                    "macd_histogram": histogram,
                    "trend": _determine_trend(closes, ma5, ma10, ma20),
                    "momentum": _determine_momentum(rsi6, histogram),
                }
            except Exception as e:
                logger.warning("计算 %s 技术指标失败: %s", name, e)
                indicators[name] = {"error": str(e)}

        return indicators


# ── 技术指标计算辅助函数 ──────────────────────────────────────

def _sma(data: list, period: int) -> Optional[float]:
    """简单移动平均。"""
    if len(data) < period:
        return None
    return round(sum(data[-period:]) / period, 4)


def _ema(data: list, period: int) -> float:
    """指数移动平均。"""
    if not data:
        return 0.0
    multiplier = 2.0 / (period + 1)
    ema_val = data[0]
    for price in data[1:]:
        ema_val = (price - ema_val) * multiplier + ema_val
    return round(ema_val, 4)


def _rsi(closes: list, period: int = 14) -> Optional[float]:
    """相对强弱指标。"""
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]

    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def _macd(closes: list, fast: int = 12, slow: int = 26, signal: int = 9):
    """MACD 指标。返回 (macd_line, signal_line, histogram)。"""
    if len(closes) < slow:
        return None, None, None

    ema_fast = _ema_series(closes, fast)
    ema_slow = _ema_series(closes, slow)

    macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
    signal_line = _ema_series(macd_line, signal)
    histogram = [m - s for m, s in zip(macd_line, signal_line)]

    return (
        round(macd_line[-1], 4) if macd_line else None,
        round(signal_line[-1], 4) if signal_line else None,
        round(histogram[-1], 4) if histogram else None,
    )


def _ema_series(data: list, period: int) -> list:
    """计算 EMA 序列。"""
    if len(data) < period:
        return []
    multiplier = 2.0 / (period + 1)
    ema_values = [sum(data[:period]) / period]
    for price in data[period:]:
        ema_values.append((price - ema_values[-1]) * multiplier + ema_values[-1])
    return ema_values


def _determine_trend(closes: list, ma5, ma10, ma20) -> str:
    """判断趋势。"""
    if ma5 is None or ma10 is None or ma20 is None:
        return "数据不足"
    latest = closes[-1]
    if latest > ma5 > ma10 > ma20:
        return "强势上涨"
    elif latest > ma10 > ma20:
        return "上涨趋势"
    elif latest < ma5 < ma10 < ma20:
        return "强势下跌"
    elif latest < ma10 < ma20:
        return "下跌趋势"
    else:
        return "震荡整理"


def _determine_momentum(rsi, histogram) -> str:
    """判断动量。"""
    if rsi is None:
        return "数据不足"
    if rsi > 70:
        return "超买" if histogram and histogram < 0 else "强势超买"
    elif rsi < 30:
        return "超卖" if histogram and histogram > 0 else "弱势超卖"
    elif rsi > 50:
        return "偏强"
    else:
        return "偏弱"


def build_market_context(data: Dict[str, Any]) -> str:
    """将采集到的数据转换为文本上下文，供分析师使用。"""
    lines: List[str] = []
    lines.append(f"数据时间: {data.get('scan_time', 'N/A')}")

    # 市场概览
    overview = data.get("market_overview", {})

    # 指数
    lines.append("\n【大盘指数】")
    for idx in overview.get("indices", []):
        if "error" in idx:
            lines.append(f"  {idx['name']}: 数据缺失")
            continue
        price = idx.get("price", 0)
        chg = idx.get("change_pct", 0) or 0
        sign = "+" if chg > 0 else ""
        lines.append(f"  {idx['name']}: {price}, 涨跌幅 {sign}{chg}%")

    # 行业板块
    ind = overview.get("industry_sectors", {})
    if not ind.get("error"):
        lines.append("\n【领涨行业 TOP5】")
        for s in ind.get("gainers", []):
            chg = s.get("change_pct", 0) or 0
            sign = "+" if chg > 0 else ""
            lines.append(f"  {s.get('name','')}: {sign}{chg}%, 领涨 {s.get('leader','')}({s.get('leader_change_pct',0)}%)")
        lines.append("\n【领跌行业 TOP5】")
        for s in ind.get("losers", []):
            chg = s.get("change_pct", 0) or 0
            sign = "+" if chg > 0 else ""
            lines.append(f"  {s.get('name','')}: {sign}{chg}%, 领涨 {s.get('leader','')}({s.get('leader_change_pct',0)}%)")

    # 概念板块
    con = overview.get("concept_sectors", {})
    if not con.get("error"):
        lines.append("\n【热门概念 TOP10】")
        for s in con.get("hot", []):
            chg = s.get("change_pct", 0) or 0
            sign = "+" if chg > 0 else ""
            leader = s.get("leader", "")
            leader_info = f", 领涨 {leader}({s.get('leader_change_pct',0)}%)" if leader else ""
            lines.append(f"  {s.get('name','')}: {sign}{chg}%{leader_info}")

    # 全球市场
    global_idx = overview.get("global_indices", [])
    if global_idx:
        lines.append("\n【全球市场】")
        for gi in global_idx:
            price = gi.get("price", 0)
            chg = gi.get("change_pct", 0) or 0
            sign = "+" if chg > 0 else ""
            lines.append(f"  {gi.get('market','')}-{gi.get('name','')}: {price:,.2f}, 涨跌幅 {sign}{chg}%")

    return "\n".join(lines)


from typing import List
