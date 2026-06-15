#!/usr/bin/env python3
"""
多因子选股策略回测
==================
1. 用curl从新浪拉取Top20股票最近250个交易日K线
2. 用backtrader回测：月初调仓，买入多因子Top10，等权配置
3. 计算年化收益率、夏普比率、最大回撤、胜率
4. 生成回测报告
"""

import subprocess
import json
import re
import os
import sys
import math
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
import backtrader as bt

# 将 qts_data 加入路径，优先复用本地 K 线数据
sys.path.insert(0, str(Path('/home/jiaod/qts')))
try:
    import qts_data as qd
except Exception:
    qd = None

GLOBAL_KLINE_DIR = str(Path('/home/jiaod/qts/00-研究/数据源/缓存/kline_6m'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

# 设置中文字体
_cjk_fonts = ['WenQuanYi Micro Hei', 'Noto Sans CJK SC', 'SimHei', 'Microsoft YaHei']
for _f in _cjk_fonts:
    try:
        fm.findfont(_f, fallback_to_default=False)
        plt.rcParams['font.sans-serif'] = [_f] + plt.rcParams['font.sans-serif']
        plt.rcParams['axes.unicode_minus'] = False
        break
    except Exception:
        continue

# ============================================================
# 配置
# ============================================================
STRATEGY_DIR = Path("/home/jiaod/qts/10-策略/多因子选股策略")
REPORT_DIR = Path("/home/jiaod/qts/20-回测/多因子选股策略/20260602-v1")
REPORT_DIR.mkdir(parents=True, exist_ok=True)

# Top20股票（从信号生成结果中获取）
TOP20_STOCKS = [
    {"symbol": "sz300750", "name": "宁德时代", "score": 86.27},
    {"symbol": "sh601138", "name": "工业富联", "score": 85.53},
    {"symbol": "sh601398", "name": "工商银行", "score": 85.40},
    {"symbol": "sh601939", "name": "建设银行", "score": 85.29},
    {"symbol": "sz300308", "name": "中际旭创", "score": 85.18},
    {"symbol": "sh601288", "name": "农业银行", "score": 82.58},
    {"symbol": "sh600941", "name": "中国移动", "score": 81.44},
    {"symbol": "sh601857", "name": "中国石油", "score": 80.35},
    {"symbol": "sh601988", "name": "中国银行", "score": 80.04},
    {"symbol": "sh600519", "name": "贵州茅台", "score": 78.69},
    {"symbol": "sh600938", "name": "中国海油", "score": 77.95},
    {"symbol": "sh688981", "name": "中芯国际", "score": 77.12},
    {"symbol": "sz300502", "name": "新易盛", "score": 75.10},
    {"symbol": "sh603986", "name": "兆易创新", "score": 74.84},
    {"symbol": "sz002475", "name": "立讯精密", "score": 74.67},
    {"symbol": "sh601899", "name": "紫金矿业", "score": 74.35},
    {"symbol": "sh600036", "name": "招商银行", "score": 74.16},
    {"symbol": "sh601318", "name": "中国平安", "score": 74.03},
    {"symbol": "sh601088", "name": "中国神华", "score": 73.58},
    {"symbol": "sz002594", "name": "比亚迪", "score": 73.01},
]

TOP_N = 10  # 回测买入前N只


# ============================================================
# 数据拉取（用curl，不走requests）
# ============================================================
def fetch_kline_sina(symbol: str, datalen: int = 250) -> pd.DataFrame:
    """
    用curl从新浪接口拉取日K线数据

    参数:
        symbol: 股票代码，如 sh600519
        datalen: 拉取天数
    返回:
        DataFrame(date, open, high, low, close, volume)
    """
    url = (
        f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_{symbol}=/"
        f"CN_MarketDataService.getKLineData?"
        f"symbol={symbol}&scale=240&ma=no&datalen={datalen}"
    )

    try:
        result = subprocess.run(
            ["curl", "-s", "-m", "10", url],
            capture_output=True, text=True, timeout=15
        )
        raw = result.stdout.strip()

        if not raw:
            print(f"  ⚠️ {symbol}: 返回空数据")
            return pd.DataFrame()

        # 解析JSONP: var _sz300750=([...]);
        match = re.search(r'\((\[.*\])\)', raw, re.DOTALL)
        if not match:
            print(f"  ⚠️ {symbol}: JSONP解析失败")
            return pd.DataFrame()

        data = json.loads(match.group(1))

        if not data:
            print(f"  ⚠️ {symbol}: 数据为空列表")
            return pd.DataFrame()

        df = pd.DataFrame(data)

        # 标准化列名
        col_map = {}
        for col in df.columns:
            col_lower = col.lower()
            if col_lower == 'day' or col_lower == 'date':
                col_map[col] = 'date'
            elif col_lower == 'open':
                col_map[col] = 'open'
            elif col_lower == 'high':
                col_map[col] = 'high'
            elif col_lower == 'low':
                col_map[col] = 'low'
            elif col_lower == 'close':
                col_map[col] = 'close'
            elif col_lower == 'volume':
                col_map[col] = 'volume'

        df = df.rename(columns=col_map)

        # 转换数值类型
        for c in ['open', 'high', 'low', 'close', 'volume']:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors='coerce')

        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])

        df = df.dropna(subset=['close'])
        df = df.sort_values('date').reset_index(drop=True)

        print(f"  ✅ {symbol}: 拉取 {len(df)} 条K线")
        return df

    except Exception as e:
        print(f"  ❌ {symbol}: 拉取失败 - {e}")
        return pd.DataFrame()


def fetch_all_klines(stocks: list, datalen: int = 250) -> dict:
    """批量准备所有股票K线，优先使用本地数据"""
    print("\n📡 准备历史K线数据（本地优先）...")
    klines = {}
    for stock in stocks:
        sym = stock["symbol"]
        loaded = False

        # 1) 已有子目录缓存
        local = REPORT_DIR / "data" / f"{sym}.csv"
        if local.exists():
            df = pd.read_csv(local)
            date_col = "date" if "date" in df.columns else "day"
            df = df.rename(columns={date_col: "date"})
            df["date"] = pd.to_datetime(df["date"])
            if len(df) >= 60:
                klines[sym] = df
                loaded = True

        # 2) 全局 kline_6m
        if not loaded:
            gpath = Path(GLOBAL_KLINE_DIR) / f"{sym}.csv"
            if gpath.exists():
                df = pd.read_csv(gpath)
                date_col = "date" if "date" in df.columns else "day"
                df = df.rename(columns={date_col: "date"})
                df["date"] = pd.to_datetime(df["date"])
                if len(df) >= 60:
                    df.to_csv(local, index=False)
                    klines[sym] = df
                    loaded = True

        # 3) qts_data
        if not loaded and qd is not None:
            try:
                df = qd.kline(sym)
                if len(df) >= 60:
                    df.to_csv(local, index=False)
                    klines[sym] = df
                    loaded = True
            except Exception:
                pass

        # 4) 网络兜底
        if not loaded:
            df = fetch_kline_sina(sym, datalen)
            if len(df) >= 60:
                df.to_csv(local, index=False)
                klines[sym] = df
                loaded = True

        if not loaded:
            print(f"  ⚠️ {sym}({stock['name']}): 数据不足，跳过")
    return klines


# ============================================================
# Backtrader 数据适配器
# ============================================================
class PandasData(bt.feeds.PandasData):
    """自定义Pandas数据源（date作为index）"""
    params = (
        ('datetime', None),  # None表示使用index作为datetime
        ('open', 'open'),
        ('high', 'high'),
        ('low', 'low'),
        ('close', 'close'),
        ('volume', 'volume'),
        ('openinterest', -1),
    )


# ============================================================
# Backtrader 策略：月初调仓，Top N 等权
# ============================================================
class MultiFactorStrategy(bt.Strategy):
    """
    多因子选股策略
    - 每月第一个交易日调仓
    - 买入综合得分前TOP_N只股票，等权配置
    - 其余股票清仓
    """

    params = (
        ('top_n', TOP_N),
        ('rebalance_day', 1),  # 每月第1个交易日调仓
        ('printlog', False),
    )

    def __init__(self):
        self.order_dict = {}
        self.trade_log = []
        self.monthly_returns = []
        self.last_month = None
        self.last_year = None
        self.month_start_value = None
        self.current_month_trades = []

    def log(self, txt, dt=None):
        if self.p.printlog:
            dt = dt or self.datas[0].datetime.date(0)
            print(f'  {dt}: {txt}')

    def notify_order(self, order):
        if order.status in [order.Completed]:
            dt = order.data.datetime.date(0)
            name = order.data._name
            if order.isbuy():
                self.log(f'买入 {name} @ {order.executed.price:.2f} x {order.executed.size:.0f}')
                self.current_month_trades.append({
                    'date': str(dt), 'name': name, 'action': '买入',
                    'price': order.executed.price, 'size': order.executed.size,
                    'cost': order.executed.value
                })
            elif order.issell():
                self.log(f'卖出 {name} @ {order.executed.price:.2f} x {order.executed.size:.0f}')
                self.current_month_trades.append({
                    'date': str(dt), 'name': name, 'action': '卖出',
                    'price': order.executed.price, 'size': order.executed.size,
                    'revenue': order.executed.value
                })

    def notify_trade(self, trade):
        if trade.isclosed:
            self.trade_log.append({
                'name': trade.data._name,
                'pnl': trade.pnl,
                'pnlcomm': trade.pnlcomm,
            })

    def next(self):
        dt = self.datas[0].datetime.date(0)
        current_month = dt.month

        # 月末记录
        if self.last_month is not None and current_month != self.last_month:
            portfolio_value = self.broker.getvalue()
            if self.month_start_value:
                ret = (portfolio_value - self.month_start_value) / self.month_start_value
                # 计算上个月的正确年份
                if current_month == 1 and self.last_month == 12:
                    last_year = dt.year - 1
                else:
                    last_year = dt.year
                self.monthly_returns.append({
                    'month': f"{last_year}-{self.last_month:02d}",
                    'return': ret,
                    'trades': self.current_month_trades.copy()
                })
            self.current_month_trades = []

        # 月初调仓
        if self.last_month != current_month:
            self.last_month = current_month
            self.last_year = dt.year
            self.month_start_value = self.broker.getvalue()

            # 取前N只股票（按数据顺序，即按综合得分从高到低）
            target_datas = self.datas[:self.p.top_n]

            # 计算目标持仓金额
            portfolio_value = self.broker.getvalue()
            target_value_per_stock = portfolio_value / self.p.top_n

            # 先卖出不在目标中的持仓
            for i, data in enumerate(self.datas):
                if i >= self.p.top_n:
                    position = self.getposition(data)
                    if position.size > 0:
                        self.close(data)

            # 买入/调仓目标股票
            for data in target_datas:
                position = self.getposition(data)
                current_value = position.size * data.close[0]
                diff = target_value_per_stock - current_value

                if diff > 0:  # 需要买入
                    size = int(diff / data.close[0] / 100) * 100  # A股100股整数
                    if size > 0:
                        self.buy(data, size=size)
                elif diff < -target_value_per_stock * 0.1:  # 偏差>10%则调整
                    sell_size = int(-diff / data.close[0] / 100) * 100
                    if sell_size > 0:
                        self.sell(data, size=sell_size)

    def stop(self):
        # 记录最后一个月
        if self.month_start_value:
            portfolio_value = self.broker.getvalue()
            ret = (portfolio_value - self.month_start_value) / self.month_start_value
            self.monthly_returns.append({
                'month': "最后期间",
                'return': ret,
                'trades': self.current_month_trades.copy()
            })


# ============================================================
# 回测执行
# ============================================================
def run_backtest(klines: dict, stocks: list) -> dict:
    """执行backtrader回测"""

    # 按得分排序，只取有数据的股票
    available = [s for s in stocks if s["symbol"] in klines]
    available = available[:TOP_N * 2]  # 取前20（足够覆盖Top10）

    print(f"\n📊 可用股票: {len(available)} 只")

    # 找到所有股票共有的日期范围
    common_dates = None
    for stock in available:
        sym = stock["symbol"]
        df = klines[sym]
        dates = set(df['date'].dt.date)
        if common_dates is None:
            common_dates = dates
        else:
            common_dates = common_dates & dates

    if not common_dates:
        print("❌ 没有共同交易日")
        return {}

    common_dates = sorted(common_dates)
    start_date = common_dates[0]
    end_date = common_dates[-1]
    print(f"📅 回测区间: {start_date} ~ {end_date} ({len(common_dates)} 个交易日)")

    # 创建Cerebro引擎
    cerebro = bt.Cerebro()
    cerebro.broker.setcash(1000000)  # 初始资金100万
    cerebro.broker.setcommission(commission=0.0003)  # 佣金万3
    cerebro.broker.set_slippage_perc(0.001)  # 滑点0.1%

    # 添加数据（按得分从高到低排序，前N只是买入目标）
    for stock in available:
        sym = stock["symbol"]
        df = klines[sym].copy()
        df = df.set_index('date')
        df = df.loc[pd.Timestamp(start_date):pd.Timestamp(end_date)]

        if len(df) < 20:
            continue

        data = PandasData(
            dataname=df,
            name=f"{sym}_{stock['name']}",
            fromdate=pd.Timestamp(start_date),
            todate=pd.Timestamp(end_date),
        )
        cerebro.adddata(data)

    # 添加策略
    cerebro.addstrategy(MultiFactorStrategy, top_n=TOP_N, printlog=False)

    # 添加分析器
    cerebro.addanalyzer(bt.analyzers.SharpeRatio,
                        _name='sharpe', timeframe=bt.TimeFrame.Days, annualize=True)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.TimeReturn, _name='timereturn', timeframe=bt.TimeFrame.Days)

    # 运行回测
    print("\n🚀 开始回测...")
    initial_value = cerebro.broker.getvalue()
    print(f"  初始资金: ¥{initial_value:,.2f}")

    results = cerebro.run()
    strat = results[0]

    final_value = cerebro.broker.getvalue()
    print(f"  最终资金: ¥{final_value:,.2f}")
    print(f"  总收益: ¥{final_value - initial_value:,.2f}")

    # ============================================================
    # 提取回测指标
    # ============================================================
    metrics = {}

    # 总收益率
    total_return = (final_value - initial_value) / initial_value
    metrics['total_return'] = total_return

    # 年化收益率
    trading_days = len(common_dates)
    years = trading_days / 244  # A股约244个交易日/年
    if years > 0 and total_return > -1:
        annual_return = (1 + total_return) ** (1 / years) - 1
    else:
        annual_return = total_return / years if years > 0 else 0
    metrics['annual_return'] = annual_return

    # 夏普比率
    sharpe_analysis = strat.analyzers.sharpe.get_analysis()
    sharpe_ratio = sharpe_analysis.get('sharperatio', None)
    metrics['sharpe_ratio'] = sharpe_ratio

    # 最大回撤
    dd_analysis = strat.analyzers.drawdown.get_analysis()
    max_drawdown = dd_analysis.get('max', {}).get('drawdown', 0) / 100
    metrics['max_drawdown'] = max_drawdown

    # 交易统计
    trade_analysis = strat.analyzers.trades.get_analysis()
    total_trades = trade_analysis.get('total', {}).get('total', 0)
    won_trades = trade_analysis.get('won', {}).get('total', 0)
    lost_trades = trade_analysis.get('lost', {}).get('total', 0)
    win_rate = won_trades / total_trades if total_trades > 0 else 0
    metrics['total_trades'] = total_trades
    metrics['won_trades'] = won_trades
    metrics['lost_trades'] = lost_trades
    metrics['win_rate'] = win_rate

    # 盈亏比
    avg_win = trade_analysis.get('won', {}).get('pnl', {}).get('average', 0)
    avg_loss = abs(trade_analysis.get('lost', {}).get('pnl', {}).get('average', 1))
    profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else float('inf')
    metrics['profit_loss_ratio'] = profit_loss_ratio

    # 日收益率序列
    daily_returns = strat.analyzers.timereturn.get_analysis()
    daily_ret_series = pd.Series(daily_returns)
    if len(daily_ret_series) > 1:
        volatility = daily_ret_series.std() * np.sqrt(244)
    else:
        volatility = 0
    metrics['volatility'] = volatility

    # Calmar比率
    calmar = annual_return / max_drawdown if max_drawdown > 0 else float('inf')
    metrics['calmar_ratio'] = calmar

    # 月度收益
    metrics['monthly_returns'] = strat.monthly_returns

    # 交易日志
    metrics['trade_log'] = strat.trade_log

    # 回测区间信息
    metrics['start_date'] = str(start_date)
    metrics['end_date'] = str(end_date)
    metrics['trading_days'] = trading_days
    metrics['initial_value'] = initial_value
    metrics['final_value'] = final_value

    # 保存图表
    try:
        figs = cerebro.plot(style='candle', barup='red', bardown='green',
                            volume=True, iplot=False)
        fig = figs[0][0]
        fig.set_size_inches(16, 10)
        fig.savefig(REPORT_DIR / "backtest_chart.png", dpi=150, bbox_inches='tight')
        plt.close(fig)
        print(f"\n📈 回测图表已保存")
    except Exception as e:
        print(f"\n⚠️ 图表生成失败: {e}")

    # 生成自定义净值曲线
    try:
        daily_returns = strat.analyzers.timereturn.get_analysis()
        dates = sorted(daily_returns.keys())
        nav = [1.0]
        for d in dates:
            nav.append(nav[-1] * (1 + daily_returns[d]))
        nav_dates = [dates[0] - timedelta(days=1)] + dates

        fig2, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8),
                                         gridspec_kw={'height_ratios': [3, 1]})
        fig2.suptitle('多因子选股策略 回测净值曲线', fontsize=14, fontweight='bold')

        # 净值曲线
        ax1.plot(nav_dates, nav, 'b-', linewidth=1.5, label='策略净值')
        ax1.axhline(y=1.0, color='gray', linestyle='--', alpha=0.5)
        ax1.fill_between(nav_dates, 1.0, nav, where=[n >= 1 for n in nav],
                         alpha=0.15, color='red')
        ax1.fill_between(nav_dates, 1.0, nav, where=[n < 1 for n in nav],
                         alpha=0.15, color='green')
        ax1.set_ylabel('净值')
        ax1.legend(loc='upper left')
        ax1.grid(True, alpha=0.3)

        # 回撤曲线
        peak = np.maximum.accumulate(nav)
        drawdown = [(n - p) / p for n, p in zip(nav, peak)]
        ax2.fill_between(nav_dates, 0, drawdown, color='green', alpha=0.4)
        ax2.set_ylabel('回撤')
        ax2.set_xlabel('日期')
        ax2.grid(True, alpha=0.3)

        plt.tight_layout()
        fig2.savefig(REPORT_DIR / "equity_curve.png", dpi=150, bbox_inches='tight')
        plt.close(fig2)
        print(f"📈 净值曲线已保存")
    except Exception as e:
        print(f"⚠️ 净值曲线生成失败: {e}")

    return metrics


# ============================================================
# 生成报告
# ============================================================
def generate_report(metrics: dict) -> str:
    """生成中文回测报告"""

    report = []
    report.append("=" * 70)
    report.append("           多因子选股策略 - 回测报告")
    report.append("=" * 70)
    report.append("")
    report.append(f"  生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append(f"  回测区间: {metrics.get('start_date', 'N/A')} ~ {metrics.get('end_date', 'N/A')}")
    report.append(f"  交易日数: {metrics.get('trading_days', 0)} 天")
    report.append(f"  初始资金: ¥{metrics.get('initial_value', 0):,.2f}")
    report.append(f"  最终资金: ¥{metrics.get('final_value', 0):,.2f}")
    report.append("")
    report.append("-" * 70)
    report.append("  【策略配置】")
    report.append("-" * 70)
    report.append(f"  调仓频率: 每月初（第一个交易日）")
    report.append(f"  持仓数量: {TOP_N} 只")
    report.append(f"  配置方式: 等权配置")
    report.append(f"  佣金费率: 万3")
    report.append(f"  滑点: 0.1%")
    report.append("")
    report.append("  选股因子:")
    report.append("    - 市盈率(PE) 权重20% —— 越低越好")
    report.append("    - 市净率(PB) 权重15% —— 越低越好")
    report.append("    - 换手率 权重15% —— 适中最优")
    report.append("    - 总市值 权重20% —— 越大越好")
    report.append("    - 成交额 权重15% —— 越大越好")
    report.append("    - 涨跌幅 权重15% —— 接近0最优")
    report.append("")

    report.append("-" * 70)
    report.append("  【核心绩效指标】")
    report.append("-" * 70)

    tr = metrics.get('total_return', 0)
    ar = metrics.get('annual_return', 0)
    sr = metrics.get('sharpe_ratio')
    md = metrics.get('max_drawdown', 0)
    wr = metrics.get('win_rate', 0)
    plr = metrics.get('profit_loss_ratio', 0)
    vol = metrics.get('volatility', 0)
    calmar = metrics.get('calmar_ratio', 0)

    report.append(f"  {'指标':<20} {'数值':>15}    说明")
    report.append(f"  {'-'*60}")
    report.append(f"  {'总收益率':<20} {tr:>14.2%}    策略总收益")
    report.append(f"  {'年化收益率':<20} {ar:>14.2%}    年化后收益")
    sr_str = f"{sr:.4f}" if sr is not None else "N/A"
    report.append(f"  {'夏普比率':<20} {sr_str:>15}    >1为佳, >2为优")
    report.append(f"  {'最大回撤':<20} {md:>14.2%}    越小越好")
    report.append(f"  {'胜率':<20} {wr:>14.2%}    盈利交易占比")
    report.append(f"  {'盈亏比':<20} {plr:>14.2f}    >1为佳")
    report.append(f"  {'年化波动率':<20} {vol:>14.2%}    越小越稳")
    report.append(f"  {'Calmar比率':<20} {calmar:>14.2f}    年化收益/最大回撤")
    report.append("")

    report.append("-" * 70)
    report.append("  【交易统计】")
    report.append("-" * 70)
    report.append(f"  总交易次数: {metrics.get('total_trades', 0)}")
    report.append(f"  盈利次数:   {metrics.get('won_trades', 0)}")
    report.append(f"  亏损次数:   {metrics.get('lost_trades', 0)}")
    report.append("")

    # 月度收益
    monthly = metrics.get('monthly_returns', [])
    if monthly:
        report.append("-" * 70)
        report.append("  【月度收益明细】")
        report.append("-" * 70)
        report.append(f"  {'月份':<12} {'收益率':>10}")
        report.append(f"  {'-'*25}")
        for m in monthly:
            ret = m.get('return', 0)
            report.append(f"  {m['month']:<12} {ret:>9.2%}")

    # 策略评价
    report.append("")
    report.append("-" * 70)
    report.append("  【策略评价】")
    report.append("-" * 70)

    comments = []
    if ar > 0.15:
        comments.append("✅ 年化收益优秀(>15%)")
    elif ar > 0.05:
        comments.append("🟡 年化收益一般(5%-15%)")
    else:
        comments.append("🔴 年化收益偏低(<5%)")

    if sr is not None:
        if sr > 2:
            comments.append("✅ 夏普比率优秀(>2)")
        elif sr > 1:
            comments.append("🟡 夏普比率良好(1-2)")
        else:
            comments.append("🔴 夏普比率偏低(<1)")

    if md < 0.1:
        comments.append("✅ 最大回撤控制优秀(<10%)")
    elif md < 0.2:
        comments.append("🟡 最大回撤可接受(10%-20%)")
    else:
        comments.append("🔴 最大回撤偏大(>20%)")

    if wr > 0.55:
        comments.append("✅ 胜率较高(>55%)")
    elif wr > 0.45:
        comments.append("🟡 胜率一般(45%-55%)")
    else:
        comments.append("🔴 胜率偏低(<45%)")

    for c in comments:
        report.append(f"  {c}")

    report.append("")
    report.append("=" * 70)
    report.append("  报告结束")
    report.append("=" * 70)

    return "\n".join(report)


# ============================================================
# 主函数
# ============================================================
def main():
    print("=" * 60)
    print("🚀 多因子选股策略 - 回测")
    print(f"   运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 1. 拉取K线数据
    klines = fetch_all_klines(TOP20_STOCKS, datalen=250)

    if len(klines) < TOP_N:
        print(f"❌ 可用股票不足{TOP_N}只({len(klines)}只)，无法回测")
        sys.exit(1)

    # 保存拉取的数据
    data_dir = REPORT_DIR / "data"
    data_dir.mkdir(exist_ok=True)
    for sym, df in klines.items():
        df.to_csv(data_dir / f"{sym}.csv", index=False)
    print(f"\n💾 K线数据已保存到 {data_dir}/")

    # 2. 运行回测
    metrics = run_backtest(klines, TOP20_STOCKS)

    if not metrics:
        print("❌ 回测失败")
        sys.exit(1)

    # 3. 生成报告
    report_text = generate_report(metrics)

    # 保存文本报告
    report_path = REPORT_DIR / "回测报告.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_text)
    print(f"\n📄 报告已保存: {report_path}")

    # 保存JSON格式指标
    json_metrics = {}
    for k, v in metrics.items():
        if k in ('monthly_returns', 'trade_log'):
            json_metrics[k] = v
        elif isinstance(v, float) and (math.isinf(v) or math.isnan(v)):
            json_metrics[k] = str(v)
        else:
            json_metrics[k] = v

    json_path = REPORT_DIR / "回测指标.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_metrics, f, ensure_ascii=False, indent=2, default=str)
    print(f"📊 指标已保存: {json_path}")

    # 打印报告
    print("\n" + report_text)

    return metrics


if __name__ == "__main__":
    main()
