# 缠论分析系统

基于缠论108课理论的股票技术分析系统，支持多级别分析和动态买点确认。

---

## 快速开始

```python
import sys
sys.path.insert(0, '/home/jiaod/qts/10-策略/缠论Agent')
from chanlun_core import ChanlunCore
from multi_level_analyzer import MultiLevelAnalyzer
import akshare as ak
import pandas as pd

# 获取数据
min15_df = ak.stock_zh_a_minute(symbol="sh600186", period="15")
min15_df['day'] = pd.to_datetime(min15_df['day'])
min15_df = min15_df.set_index('day')
min15_df = min15_df[['open', 'high', 'low', 'close']]

# 单级别分析
core = ChanlunCore()
result = core.analyze(min15_df)

# 多级别分析
analyzer = MultiLevelAnalyzer()
daily_df = pd.read_csv('/home/jiaod/qts/00-研究/数据源/缓存/kline_6m/sh600186.csv')
daily_df['date'] = pd.to_datetime(daily_df['date'])
daily_df = daily_df.set_index('date')
daily_df = daily_df[['open', 'close', 'high', 'low']]
result = analyzer.analyze(daily_df, min15_df)
```

---

## 核心功能

### 1. 缠论核心算法（chanlun_core.py）

| 功能 | 方法 | 说明 |
|------|------|------|
| K线包含处理 | `process_klines()` | 上涨取并集，下跌取交集 |
| 分型识别 | `find_fractals()` | 顶分型、底分型 |
| 笔划分 | `find_bis()` | 交替分型、最小间距 |
| 中枢识别 | `find_zhong_shus()` | 3笔共同重叠区间 |
| 买卖点识别 | `find_buy_sell_points()` | 一买/二买/三买 |
| 动态买点确认 | `check_buy_point_validity()` | 检查买点是否被打穿 |

### 2. 多级别分析（multi_level_analyzer.py）

```python
analyzer = MultiLevelAnalyzer()
result = analyzer.analyze(daily_df, min15_df)
```

输出：
- 日线级别分析
- 15分钟级别分析
- 综合操作信号

### 3. 动态买点确认

```python
core = ChanlunCore()
result = core.analyze(df)

# 检查买点是否有效
invalidated = core.update_buy_points(current_price)

if invalidated:
    print(f'发现 {len(invalidated)} 个被打穿的买点:')
    for item in invalidated:
        print(f'  {item["buy_point"].type.value} @ {item["buy_point"].price}元')
        print(f'  原因: {item["reason"]}')
```

---

## 核心原则

1. **不预测**：只描述当前状态，不猜未来
2. **完全分类**：走势只有上涨、下跌、横盘
3. **动态确认**：买点被打穿后推翻结论，触发止损
4. **级别递归**：日线→15分钟→分时图

---

## 文件结构

```
缠论Agent/
├── chanlun_core.py          # 缠论核心算法
├── multi_level_analyzer.py  # 多级别分析
├── signal_output.py         # 信号输出
├── chanlun_agent.py         # Agent主入口
├── knowledge_base.py        # 知识库查询
├── README.md                # 本文件
└── tests/                   # 测试文件
```

---

## 依赖

- pandas
- numpy
- akshare
