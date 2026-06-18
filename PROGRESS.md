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

## 2026-06-15
- 项目初始化提交（仓库重建）
- 修复报告 A 股配色，新闻事件分析增加影响链
- 简化验证信号为明确点位（如 3350/3400 等）
- 情绪分析增加具体证据
- 明确成交量单位为"沪市成交额（亿元）"
- 新增国际半导体/AI 新闻覆盖

## 2026-06-16
- 新增 `generate_html.py` + `report_template.py` → 统一 HTML 报告模板
- 报告模板增加仪表盘图表、情绪/资金流向指标可视化
- 新增 `skills/market_report.py` 模块（报告生成 skill）
- 新增 `skills/feishu_send.py` 模块（飞书消息发送 skill）
- 新增 `skills/feishu_listener.py` → 飞书消息监听（命令处理）
- 新增 `skills/feishu_ws_listener.py` → WebSocket 飞书实时监听，支持私聊
- 清理临时测试/报告文件
- 新增盯盘系统 `50-盯盘/`：watchdog.py、alert_engine.py、realtime_fetcher.py、notifier.py、state_store.py、config.yaml
- 修复缠论分析 bug
- 更新 README.md
