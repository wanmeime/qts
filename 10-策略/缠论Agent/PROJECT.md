# 缠论分析 Agent

基于缠论理论的股票技术分析 Agent，用于识别买点和卖点。

## 功能模块

1. `chanlun_core.py` - 缠论核心算法
2. `macd_analysis.py` - MACD 分析
3. `multi_level.py` - 多级别联立
4. `signal_output.py` - 信号输出
5. `chanlun_agent.py` - Agent 主体

## 使用方法

```python
from chanlun_agent import ChanlunAgent
import akshare as ak

# 获取数据
df = ak.stock_zh_a_hist(symbol="000001", period="daily", start_date="20230101", end_date="20231231")

# 分析
agent = ChanlunAgent()
result = agent.analyze("000001", df)
print(result)
```
