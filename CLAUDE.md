# 交易量化系统 (qts)

## Context Management
- **DO NOT** read PDF files or large binary documents
- **DO NOT** scan entire project directories - only read files that are explicitly needed
- **DO NOT** load more than 10 files at once
- Keep context minimal - only include relevant files in responses
- When working with historical data or backtest results, reference files by path without reading full content

## Project Structure
- `00-研究/` - Research and analysis
- `10-策略/` - Trading strategies  
- `20-回测/` - Backtesting systems
- `30-信号/` - Signal generation
- `40-执行/` - Execution systems
- `90-复盘/` - Post-trade review
- `_build/` - Market insight pipeline (market_insight_graph.py, market_insight_prompts.py)

## Important
- The PDF "缠中说禅108课" was moved to ~/Documents/ - DO NOT try to read it
- Focus on Python code, not documentation files

## Tool Invocation

| 用户指令 | 调用方式 | Skill |
|----------|----------|-------|
| 大盘分析、市场趋势、板块轮动、宏观研判 | 全市场分析 | `tradingagents-market-scan` |
| 个股技术分析、买点卖点、缠论结构 | 缠论个股分析 | `chanlun-analysis` |

## Prompt Fix
- `_build/market_insight_prompts.py` 中 VERDICT 已要求输出 `scores`（趋势/动量/情绪/政策，1-5分）
- 报告"多维度评分"表格现在会正确显示数据
