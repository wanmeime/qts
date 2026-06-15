"""
生成市场分析报告的入口脚本
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _build.market_data_collector import MarketDataCollector
from market_multi_agent import analyze_market_with_agents

async def main():
    print("开始采集市场数据...")
    collector = MarketDataCollector()
    market_data = await collector.collect_all()
    
    print("数据采集完成，开始生成分析报告...")
    report = await analyze_market_with_agents(market_data)
    
    # 保存报告
    from datetime import datetime, timezone, timedelta
    cst = timezone(timedelta(hours=8))
    filename = f"市场分析报告_{datetime.now(cst).strftime('%Y%m%d_%H%M%S')}.md"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(report)
    
    print(f"\n报告已保存: {filename}")
    print("\n" + "="*60)
    print(report)

if __name__ == "__main__":
    asyncio.run(main())
