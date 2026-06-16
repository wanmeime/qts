# 盯盘系统 (Watcher)

实时监控自选股和持仓，检测买卖点信号并推送告警。

## 功能

- **实时监控**: 后台常驻，交易时段自动扫描
- **缠论分析**: 检测一买/二买/类二买/一卖/二卖信号
- **价格告警**: 涨跌幅超阈值、价格突破等
- **飞书推送**: 告警消息实时推送到飞书群
- **持仓联动**: 自动读取持仓，监控持仓盈亏

## 使用方法

```bash
# 启动盯盘（后台运行）
python watcher.py

# 测试模式（不检查交易时段）
python watcher.py --test --once

# 设置扫描间隔
python watcher.py --interval 60

# 指定配置文件
python watcher.py --config watcher_config.yaml
```

## 配置说明

编辑 `watcher_config.yaml`:

```yaml
# 扫描间隔（秒）
watcher:
  interval: 300

# 告警规则
alert:
  rules:
    - name: "大涨告警"
      change_pct_above: 5.0
    - name: "买入信号"
      signal_types: ["buy_1", "buy_2"]
      min_score: 60
```

## 告警类型

| 类型 | 说明 | 配置项 |
|------|------|--------|
| 信号告警 | 缠论买卖点信号 | `signal_types`, `min_score` |
| 涨跌幅告警 | 涨跌幅超阈值 | `change_pct_above/below` |
| 价格告警 | 价格突破/跌破 | `price_above/below` |

## 与其他模块集成

盯盘系统可与以下模块配合使用:

- `10-策略/自选股监控/缠论分析.py` - 缠论分析引擎
- `10-策略/自选股监控/signal_generator.py` - 信号评分
- `40-执行/持仓/持仓管理.py` - 持仓数据
- `skills/feishu_service.py` - 飞书通知

## 文件结构

```
10-策略/自选股监控/
├── watcher.py           # 盯盘主程序
├── watcher_config.yaml  # 配置文件
├── WATCHER.md           # 本文档
├── monitor.py           # 原有监控脚本
├── 缠论分析.py          # 缠论分析引擎
├── signal_generator.py  # 信号生成
└── config.yaml          # 原有配置
```
