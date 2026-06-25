# 更新日志

## 2026-06-24

### 清理：旧 watchdog 废弃代码

**文件**: `50-盯盘/watchdog.py`

- 删除 `analyze_stock`、`_analyze_stock_single`、`check_position_alerts`、`check_precise_buy_signals`、`check_signal_alerts`、`build_alert_card`、`format_summary`、`_get_signal_type_cn`、`_get_signal_rule_ref` 共 9 个废弃函数（~600行）
- 删除 `scan_once` 方法体（原 bug 源：`alerts` 未初始化导致崩溃）
- 删除 `_write_notifications`、`_print_summary` 等方法体
- 移除旧 `多级别分析`/`缠论分析` import fallback 代码
- `watchdog.py` 从 1535 行精简至 ~500 行（保留 `load_config`、`fetch_kline`、`Watchdog` 类入口、`main()`）

### 修复：watchdog.py 崩溃 bug

**根因**: `scan_once` 中 `alerts` 列表未初始化就直接 `alerts.append()`
**症状**: watchdog 崩溃 → 飞书推送发不出（不是飞书问题，是根本没跑到推送）
**修复**: 清理废弃代码，崩溃路径已消除。信号监测走 `run_signal_monitor.py` 独立进程，不受影响。

### 修复：信号监测行情源

- 从容易断连的东方财富 HTTP 源改为 **QMT 行情转发**（Windows 端）
- SignalMonitor 新增 `fetcher` 参数，支持 QMT/HTTP 切换
- run_signal_monitor.py 自动探测 QMT 可用性，不可用时回退 HTTP

### 新增
- 持仓：**迦南科技** 300412（2800股 × 5.126，止损 4.68）
- 自选股：迦南科技 300412 加入 watchlist.json
- 持仓风控信号优先读取持仓文件手动设置的止损价

## 2026-06-23

### 修复：缠论引擎一买/二买逻辑缺陷

**文件**: `10-策略/缠论Agent/chanlun_core.py`

**Bug 1 — 一买被删导致孤儿二买（中兴通讯6/15场景）**
- 旧逻辑：有效性验证直接 `continue` 删除被后续低点打穿的一买
- 修复：改为**重定位**到后续最低底分型，一买前移而非删除

**Bug 2 — 小转大一买漏标**
- 旧逻辑：只依赖背驰检测，无背驰就不出一买
- 修复：新增小转大检测——有下跌中枢+离开笔创新低→标记一买

**Bug 3 — 二买基于未验证的一买快照**
- 旧逻辑：二买基于预处理的一买快照，一买被删后二买成孤儿
- 修复：重定位→基于最终一买生成二买，杜绝孤儿二买

### 新增：实时信号监测系统

**文件**:
- `50-盯盘/signal_templates.py` — 4类信号模板数据结构
- `50-盯盘/static_analyzer.py` — 盘后静态分析→信号模板
- `50-盯盘/chanlun_service.py` — 盘中缠论分析后台服务
- `50-盯盘/signal_monitor.py` — 实时匹配引擎
- `50-盯盘/run_signal_monitor.py` — 独立启动脚本

**设计思想**（完全分类）：
- 静态分析（盘后）：缠论引擎→提取昨日第三根K线的分型→成交量过滤→生成信号模板→写DB
- 实时匹配（盘中）：每5秒轮询行情→阈值匹配→输出带买卖点标签的通知
- 盘中缠论服务（后台线程）：接收请求→跑ChanlunCore→返回背驰段判断
- 缠论引擎保持纯净（回测/盯盘共享），不掺实时逻辑

**过滤条件**：
- 只监控最新完成的K线形成的分型（昨日第三根K线）
- 买点信号需要成交量 > 近5日均量 × 1.5
- 卖点信号只对持仓股生成（非持仓忽略）

### 新增：飞书交互卡片通知

**文件**: `50-盯盘/notifier.py`

- 买入信号 → 🟢 绿色卡片
- 卖出信号 → 🔴 红色卡片
- 止损提醒 → 🚨 红色卡片 + **「已止损」按钮**（点击自动移除持仓）
- 信号失效 → ❌ 灰色卡片
- 止盈提醒 → 💰 黄色卡片
- 波动报警 → ⚡ 橙色卡片

### 新增：持仓一键移除 API

**文件**: `50-盯盘/dashboard_server.py`
- `POST /api/position/remove/{code}` — 飞书卡片按钮回调接口

### 数据基础设施

- `tools/download_minute_kline.py` — 全市场分钟K线下载脚本（备用新浪接口）
- `50-盯盘/qmt_bridge/download_minute.py` — QMT xtquant 分钟线下载脚本（Windows端）

## 2026-06-16

### 新增：盯盘系统 (交易联动版)

- 创建 `10-策略/自选股监控/watcher.py` — 盯盘主程序
- 创建 `10-策略/自选股监控/watcher_config.yaml` — 配置文件
- 创建 `10-策略/自选股监控/WATCHER.md` — 使用说明

**功能**：
- 自动加载自选股 + 持仓，合并监控
- 定时扫描（默认5分钟），交易时段运行
- 缠论分析检测买卖点信号（一买/二买/类二买/一卖/二卖）
- 涨跌幅/价格突破告警
- 飞书 Markdown 消息推送（富文本格式）
- 告警去重（同一股票同一规则5分钟内不重复推送）
- 从新浪接口获取股票名称，告警消息显示完整名称

**告警分类**：
- 🟢 大涨告警 — 涨幅超阈值
- 🔴 大跌告警 — 跌幅超阈值
- 🟢 买入信号 — 缠论买点
- 🔴 卖出信号 — 缠论卖点
- ⚡ 价格突破 — 价格突破指定价位
- 📋 持仓摘要 — 显示持仓股票信息

### 修复：缠论分析模块 Bug

**文件**: `10-策略/自选股监控/缠论分析.py`

**Bug 1** (第487行): `prev_top = b` → `prev_top = b.end`
- Bi 对象没有 `.price` 属性，应存储 Fractal 对象

**Bug 2** (第499行): `prev_top.end.index` → `prev_top.index`
- Fractal 对象本身就是端点，没有 `.end` 属性

**效果**: 分析成功率从 65% → 94%，0报错
