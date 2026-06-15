# PROGRESS

## 2026-06-03
- 新增 `requirements.txt`
- 新增 `tools/check_env.py`
- 让动量/多因子回测优先读取本地 K 线数据
- 把动量因子从单日涨跌幅改为真实多周期动量
- 让 `90-复盘/每日复盘.py` 成功生成首份日报
- 新增最小单元测试 `tests/test_qts_data.py`
- 新增 `AGENT-ROUTES.md`

## 2026-06-03 会话记录
- 讨论了 TradingAgents (ashare/astock) 集成方案
- 分析了现有两个选股策略的因子和权重
- 确定暂不集成 AI，等选股策略细化后再考虑
- 详细记录见 SESSION-20260603.md
