#!/usr/bin/env python3
"""
动量轮动策略回测脚本
====================
1. 从A股行情数据中筛选涨幅前20只股票
2. 通过新浪财经API（curl）拉取最近250个交易日K线数据
3. 使用backtrader回测动量策略：买入过去5日涨幅最大的股票，持有5天后卖出
4. 计算年化收益率、夏普比率、最大回撤、胜率
5. 生成中文回测报告

作者: QTS量化交易系统
日期: 2026-06-02
"""

import os
import sys
import json
import re
import subprocess
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path

# 将 qts_data 加入路径，优先复用本地 K 线数据
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
try:
    import qts_data as qd
except Exception:
    qd = None

GLOBAL_KLINE_DIR = str(Path("/home/jiaod/qts/00-研究/数据源/缓存/kline_6m"))
from collections import OrderedDict

import backtrader as bt
import backtrader.analyzers as btanalyzers

# ============================================================
# 配置
# ============================================================
DATA_SOURCE = "/home/jiaod/qts/00-研究/数据源/缓存/A股全市场行情.csv"
REPORT_DIR = "/home/jiaod/qts/20-回测/动量轮动策略/20260602-v1/"
CACHE_DIR = "/home/jiaod/qts/20-回测/动量轮动策略/20260602-v1/kline_cache"
TOP_N = 20
KLINE_DAYS = 250
LOOKBACK_DAYS = 5      # 动量回看窗口
HOLD_DAYS = 5          # 持有天数
INITIAL_CASH = 1_000_000  # 初始资金100万
COMMISSION = 0.001     # 手续费万一

os.makedirs(REPORT_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)


# ============================================================
# 第一步：筛选涨幅前20只股票
# ============================================================
def get_top_stocks():
    """从A股行情数据中筛选涨幅前20只股票"""
    print("=" * 60)
    print("📋 第一步：筛选涨幅前20只股票")
    print("=" * 60)

    df = pd.read_csv(DATA_SOURCE, encoding='utf-8')
    print(f"  数据总量: {len(df)} 只股票")

    # 过滤ST/退市
    for kw in ['ST', '*ST', '退市', '退']:
        df = df[~df['名称'].str.contains(kw, na=False, regex=False)]

    # 过滤低成交额
    df['成交额'] = pd.to_numeric(df['成交额'], errors='coerce')
    df = df[df['成交额'] >= 10_000_000]

    # 过滤涨跌幅
    df['涨跌幅'] = pd.to_numeric(df['涨跌幅'], errors='coerce')
    df = df.dropna(subset=['涨跌幅'])

    # 排序取前20
    top20 = df.sort_values('涨跌幅', ascending=False).head(TOP_N)

    stocks = []
    for _, row in top20.iterrows():
        code = str(row['代码']).strip()
        name = str(row['名称']).strip()
        chg = float(row['涨跌幅'])
        stocks.append({'code': code, 'name': name, 'change': chg})

    print(f"  筛选结果: {len(stocks)} 只股票")
    for i, s in enumerate(stocks, 1):
        print(f"    {i:2d}. {s['code']:10s} {s['name']:10s} 涨幅: {s['change']:+.2f}%")

    return stocks


# ============================================================
# 第二步：通过curl拉取K线数据
# ============================================================
def fetch_kline_sina(symbol: str, days: int = 250) -> pd.DataFrame:
    """
    通过新浪财经API拉取K线数据（用curl避免requests被封）
    symbol: sh600519 或 sz300750
    """
    url = (
        f"https://quotes.sina.cn/cn/api/jsonp_v2.php/"
        f"var%20_{symbol}=/CN_MarketDataService.getKLineData"
        f"?symbol={symbol}&scale=240&ma=no&datalen={days}"
    )

    try:
        result = subprocess.run(
            ['curl', '-s', '--max-time', '10', url],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            return pd.DataFrame()

        text = result.stdout
        # 提取JSON数组：找到第一个 [ 和最后一个 ]
        start = text.find('([')
        end = text.rfind('])')
        if start == -1 or end == -1:
            return pd.DataFrame()

        json_str = text[start+1:end+1]
        data = json.loads(json_str)

        if not data:
            return pd.DataFrame()

        df = pd.DataFrame(data)
        df['day'] = pd.to_datetime(df['day'])
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df = df.dropna()
        df = df.sort_values('day').reset_index(drop=True)
        return df

    except Exception as e:
        print(f"    ⚠️  拉取 {symbol} 失败: {e}")
        return pd.DataFrame()


def fetch_all_klines(stocks: list) -> dict:
    """拉取所有股票的K线数据，优先使用本地数据"""
    print("\n" + "=" * 60)
    print("📋 第二步：准备K线数据（本地优先）")
    print("=" * 60)

    klines = {}
    for i, stock in enumerate(stocks):
        code = stock['code']
        name = stock['name']
        symbol = code
        loaded = False

        # 1) 回测目录缓存
        cache_file = os.path.join(CACHE_DIR, f"{symbol}.csv")
        if os.path.exists(cache_file):
            df = pd.read_csv(cache_file)
            df['day'] = pd.to_datetime(df['day'])
            if len(df) >= 30:
                klines[symbol] = df
                print(f"  [{i+1:2d}/{len(stocks)}] {symbol} {name} - 本地缓存 ({len(df)}条)")
                loaded = True

        # 2) 全局 kline_6m 或 qts_data
        if not loaded:
            global_file = os.path.join(GLOBAL_KLINE_DIR, f"{symbol}.csv")
            if os.path.exists(global_file):
                df = pd.read_csv(global_file)
                date_col = "date" if "date" in df.columns else "day"
                df = df.rename(columns={date_col: "day"})
                df['day'] = pd.to_datetime(df['day'])
                if len(df) >= 30:
                    df.to_csv(cache_file, index=False)
                    klines[symbol] = df
                    print(f"  [{i+1:2d}/{len(stocks)}] {symbol} {name} - 全局K线 ({len(df)}条)")
                    loaded = True

        if not loaded and qd is not None:
            try:
                df = qd.kline(symbol)
                if len(df) >= 30:
                    df = df.rename(columns={"date": "day"})
                    df.to_csv(cache_file, index=False)
                    klines[symbol] = df
                    print(f"  [{i+1:2d}/{len(stocks)}] {symbol} {name} - qts_data ({len(df)}条)")
                    loaded = True
            except Exception:
                pass

        # 3) 兜底到网络
        if not loaded:
            print(f"  [{i+1:2d}/{len(stocks)}] {symbol} {name} - 网络拉取中...", end='', flush=True)
            df = fetch_kline_sina(symbol, KLINE_DAYS)
            if not df.empty and len(df) >= 30:
                df.to_csv(cache_file, index=False)
                klines[symbol] = df
                print(f" ✅ {len(df)}条K线")
            else:
                print(f" ❌ 失败(仅{len(df)}条)")

    print(f"\n  成功准备: {len(klines)}/{len(stocks)} 只股票")
    return klines


# ============================================================
# 第三步：Backtrader回测
# ============================================================
class PandasDataFeed(bt.feeds.PandasData):
    """自定义数据源（datetime为索引）"""
    params = (
        ('datetime', None),   # 使用DataFrame的index作为日期
        ('open', 'open'),
        ('high', 'high'),
        ('low', 'low'),
        ('close', 'close'),
        ('volume', 'volume'),
        ('openinterest', -1),
    )


class MomentumRotationStrategy(bt.Strategy):
    """
    动量轮动策略
    - 每个调仓日（每HOLD_DAYS个交易日），计算所有股票过去LOOKBACK_DAYS的涨幅
    - 买入涨幅最大的股票（等权分配）
    - 持有HOLD_DAYS天后卖出
    """
    params = (
        ('lookback', LOOKBACK_DAYS),
        ('hold_days', HOLD_DAYS),
        ('verbose', False),
    )

    def __init__(self):
        self.order_list = []
        self.hold_counter = 0
        self.trade_log = []
        self.day_count = 0

    def next(self):
        self.day_count += 1
        # 如果持有中，计数
        if self.hold_counter > 0:
            self.hold_counter -= 1
            if self.hold_counter == 0:
                # 卖出所有持仓
                for d in self.datas:
                    pos = self.getposition(d)
                    if pos.size > 0:
                        self.sell(data=d, size=pos.size)
            return

        # 检查是否有足够数据计算动量
        momentum_scores = {}
        for d in self.datas:
            if len(d) < self.p.lookback + 1:
                continue
            close_now = d.close[0]
            close_prev = d.close[-self.p.lookback]
            if close_prev > 0:
                ret = (close_now - close_prev) / close_prev
                momentum_scores[d] = ret

        if not momentum_scores:
            return

        # 选涨幅最大的股票
        best_data = max(momentum_scores, key=momentum_scores.get)
        best_ret = momentum_scores[best_data]

        if best_ret <= 0:
            return  # 所有股票都下跌，不买入

        # 等权买入（用总资金的95%）
        cash = self.broker.getcash() * 0.95
        price = best_data.close[0]
        if price > 0:
            size = int(cash / price / 100) * 100  # A股100股整数倍
            if size > 0:
                self.buy(data=best_data, size=size)
                self.hold_counter = self.p.hold_days
                self.trade_log.append({
                    'date': best_data.datetime.date(0),
                    'action': 'BUY',
                    'stock': best_data._name,
                    'price': price,
                    'size': size,
                    'momentum': best_ret * 100,
                })


def run_backtest(klines: dict, stock_names: dict) -> dict:
    """运行backtrader回测"""
    print("\n" + "=" * 60)
    print("📋 第三步：运行Backtrader回测")
    print("=" * 60)
    print(f"  策略: 动量轮动 - 买入{LOOKBACK_DAYS}日涨幅最大股，持有{HOLD_DAYS}日")
    print(f"  初始资金: {INITIAL_CASH:,.0f} 元")
    print(f"  手续费: {COMMISSION*100:.1f}%")
    print(f"  股票池: {len(klines)} 只")

    cerebro = bt.Cerebro()

    # 添加数据源
    valid_count = 0
    for symbol, df in klines.items():
        if len(df) < 30:
            continue
        df_feed = df[['day', 'open', 'high', 'low', 'close', 'volume']].copy()
        df_feed = df_feed.set_index('day')
        df_feed.index = pd.DatetimeIndex(df_feed.index)
        data = PandasDataFeed(dataname=df_feed, name=symbol)
        cerebro.adddata(data)
        valid_count += 1

    if valid_count == 0:
        print("  ❌ 没有可用数据，回测终止")
        return {}

    print(f"  有效数据源: {valid_count} 只")

    # 添加策略
    cerebro.addstrategy(MomentumRotationStrategy)

    # 设置broker
    cerebro.broker.setcash(INITIAL_CASH)
    cerebro.broker.setcommission(commission=COMMISSION)

    # 添加分析器
    cerebro.addanalyzer(btanalyzers.AnnualReturn, _name='annual_return')
    cerebro.addanalyzer(btanalyzers.SharpeRatio, _name='sharpe',
                       riskfreerate=0.02, annualize=True)
    cerebro.addanalyzer(btanalyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(btanalyzers.Returns, _name='returns')
    cerebro.addanalyzer(btanalyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(btanalyzers.TimeReturn, _name='time_return')

    # 运行回测
    print("  🔄 回测运行中...")
    results = cerebro.run()
    strat = results[0]

    final_value = cerebro.broker.getvalue()
    print(f"  ✅ 回测完成！最终资产: {final_value:,.2f} 元")

    # 提取分析结果
    analysis = {}

    # 年化收益率
    returns_analyzer = strat.analyzers.returns.get_analysis()
    total_return = (final_value - INITIAL_CASH) / INITIAL_CASH
    analysis['total_return'] = total_return

    # 计算交易天数
    time_returns = strat.analyzers.time_return.get_analysis()
    n_days = len(time_returns)
    n_years = n_days / 252 if n_days > 0 else 1
    annual_return = (1 + total_return) ** (1 / n_years) - 1 if n_years > 0 else 0
    analysis['annual_return'] = annual_return
    analysis['n_days'] = n_days

    # 夏普比率
    sharpe = strat.analyzers.sharpe.get_analysis()
    sharpe_ratio = sharpe.get('sharperatio', 0) or 0
    analysis['sharpe_ratio'] = sharpe_ratio

    # 最大回撤
    dd = strat.analyzers.drawdown.get_analysis()
    max_drawdown = dd.get('max', {}).get('drawdown', 0) or 0
    analysis['max_drawdown'] = max_drawdown

    # 胜率
    trades = strat.analyzers.trades.get_analysis()
    total_trades = trades.get('total', {}).get('total', 0) or 0
    won = trades.get('won', {}).get('total', 0) or 0
    lost = trades.get('lost', {}).get('total', 0) or 0
    win_rate = won / total_trades if total_trades > 0 else 0
    analysis['total_trades'] = total_trades
    analysis['won'] = won
    analysis['lost'] = lost
    analysis['win_rate'] = win_rate

    # 交易日志
    analysis['trade_log'] = strat.trade_log
    analysis['initial_cash'] = INITIAL_CASH
    analysis['final_value'] = final_value

    # 每日收益序列
    daily_returns = []
    for dt, ret in sorted(time_returns.items()):
        daily_returns.append({'date': dt, 'return': ret})
    analysis['daily_returns'] = daily_returns

    # 净值曲线
    nav = [1.0]
    for dr in daily_returns:
        nav.append(nav[-1] * (1 + dr['return']))
    analysis['nav'] = nav
    analysis['nav_dates'] = [daily_returns[0]['date']] if daily_returns else []
    for dr in daily_returns[1:]:
        analysis['nav_dates'].append(dr['date'])

    return analysis


# ============================================================
# 第四步：生成回测报告
# ============================================================
def generate_report(stocks: list, stock_names: dict, analysis: dict):
    """生成中文回测报告"""
    print("\n" + "=" * 60)
    print("📋 第四步：生成回测报告")
    print("=" * 60)

    # === Markdown报告 ===
    report_lines = []
    report_lines.append("# 动量轮动策略回测报告")
    report_lines.append("")
    report_lines.append(f"**生成日期**: 2026-06-02")
    report_lines.append(f"**策略版本**: v1")
    report_lines.append("")
    report_lines.append("---")
    report_lines.append("")

    # 策略概述
    report_lines.append("## 一、策略概述")
    report_lines.append("")
    report_lines.append("| 参数 | 值 |")
    report_lines.append("|------|-----|")
    report_lines.append(f"| 股票池 | A股涨幅前{TOP_N}只股票（排除ST/退市/低成交额） |")
    report_lines.append(f"| 动量信号 | 过去{LOOKBACK_DAYS}个交易日涨幅最大的股票 |")
    report_lines.append(f"| 持仓周期 | 买入后持有{HOLD_DAYS}个交易日 |")
    report_lines.append(f"| 初始资金 | {INITIAL_CASH:,.0f} 元 |")
    report_lines.append(f"| 手续费 | {COMMISSION*100:.1f}% |")
    report_lines.append(f"| 调仓频率 | 每{HOLD_DAYS}个交易日 |")
    report_lines.append("")

    # 核心指标
    report_lines.append("## 二、核心绩效指标")
    report_lines.append("")
    report_lines.append("| 指标 | 值 |")
    report_lines.append("|------|-----|")

    total_ret = analysis.get('total_return', 0)
    annual_ret = analysis.get('annual_return', 0)
    sharpe = analysis.get('sharpe_ratio', 0)
    max_dd = analysis.get('max_drawdown', 0)
    win_rate = analysis.get('win_rate', 0)
    total_trades = analysis.get('total_trades', 0)
    won = analysis.get('won', 0)
    lost = analysis.get('lost', 0)
    n_days = analysis.get('n_days', 0)
    final_value = analysis.get('final_value', INITIAL_CASH)

    report_lines.append(f"| 总收益率 | {total_ret*100:+.2f}% |")
    report_lines.append(f"| 年化收益率 | {annual_ret*100:+.2f}% |")
    report_lines.append(f"| 夏普比率 | {sharpe:.4f} |")
    report_lines.append(f"| 最大回撤 | {max_dd:.2f}% |")
    report_lines.append(f"| 总交易次数 | {total_trades} |")
    report_lines.append(f"| 盈利次数 | {won} |")
    report_lines.append(f"| 亏损次数 | {lost} |")
    report_lines.append(f"| 胜率 | {win_rate*100:.1f}% |")
    report_lines.append(f"| 回测天数 | {n_days} 个交易日 |")
    report_lines.append(f"| 初始资金 | {INITIAL_CASH:,.0f} 元 |")
    report_lines.append(f"| 最终资产 | {final_value:,.2f} 元 |")
    report_lines.append(f"| 盈亏金额 | {final_value - INITIAL_CASH:+,.2f} 元 |")
    report_lines.append("")

    # 评级
    report_lines.append("## 三、策略评级")
    report_lines.append("")
    score = 0
    if annual_ret > 0.1: score += 2
    elif annual_ret > 0: score += 1
    if sharpe > 1: score += 2
    elif sharpe > 0.5: score += 1
    if max_dd < 10: score += 2
    elif max_dd < 20: score += 1
    if win_rate > 0.5: score += 2
    elif win_rate > 0.4: score += 1

    stars = "⭐" * min(score, 5)
    report_lines.append(f"综合评级: {stars} ({score}/8)")
    report_lines.append("")

    if score >= 6:
        comment = "策略表现优秀，各指标均较理想，可考虑实盘小资金测试。"
    elif score >= 4:
        comment = "策略表现中等，存在优化空间。建议调整参数或增加过滤条件后再测试。"
    else:
        comment = "策略表现较弱，不建议实盘使用。需要重新审视策略逻辑和参数。"
    report_lines.append(f"**评语**: {comment}")
    report_lines.append("")

    # 股票池
    report_lines.append("## 四、股票池（涨幅前20）")
    report_lines.append("")
    report_lines.append("| 排名 | 代码 | 名称 | 当日涨幅 |")
    report_lines.append("|------|------|------|----------|")
    for i, s in enumerate(stocks, 1):
        report_lines.append(f"| {i} | {s['code']} | {s['name']} | {s['change']:+.2f}% |")
    report_lines.append("")

    # 交易日志（前20笔）
    trade_log = analysis.get('trade_log', [])
    if trade_log:
        report_lines.append("## 五、交易日志（前20笔）")
        report_lines.append("")
        report_lines.append("| 序号 | 日期 | 操作 | 股票 | 价格 | 数量 | 动量(%) |")
        report_lines.append("|------|------|------|------|------|------|---------|")
        for i, t in enumerate(trade_log[:20], 1):
            stock_name = stock_names.get(t['stock'], t['stock'])
            report_lines.append(
                f"| {i} | {t['date']} | {t['action']} | {stock_name} | "
                f"{t['price']:.2f} | {t['size']} | {t['momentum']:.2f}% |"
            )
        report_lines.append("")

    # 风险提示
    report_lines.append("## 六、风险提示")
    report_lines.append("")
    report_lines.append("1. 历史回测不代表未来收益，市场环境变化可能导致策略失效")
    report_lines.append("2. 本回测未考虑涨跌停限制、停牌等因素")
    report_lines.append("3. 实际交易中滑点和流动性成本可能更高")
    report_lines.append("4. A股T+1制度下，买入当日无法卖出，实际持仓可能超过5天")
    report_lines.append("5. 建议先用小资金模拟验证后再考虑实盘")
    report_lines.append("")
    report_lines.append("---")
    report_lines.append("*报告由QTS量化交易系统自动生成*")

    # 写入文件
    report_path = os.path.join(REPORT_DIR, "回测报告.md")
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(report_lines))
    print(f"  ✅ Markdown报告: {report_path}")

    # === JSON指标文件 ===
    metrics = {
        "策略名称": "动量轮动策略",
        "版本": "v1",
        "回测日期": "2026-06-02",
        "参数": {
            "动量回看天数": LOOKBACK_DAYS,
            "持仓天数": HOLD_DAYS,
            "股票池数量": TOP_N,
            "初始资金": INITIAL_CASH,
            "手续费率": COMMISSION,
        },
        "绩效指标": {
            "总收益率": f"{total_ret*100:.2f}%",
            "年化收益率": f"{annual_ret*100:.2f}%",
            "夏普比率": round(sharpe, 4),
            "最大回撤": f"{max_dd:.2f}%",
            "总交易次数": total_trades,
            "胜率": f"{win_rate*100:.1f}%",
            "回测天数": n_days,
            "最终资产": round(final_value, 2),
            "盈亏金额": round(final_value - INITIAL_CASH, 2),
        }
    }
    metrics_path = os.path.join(REPORT_DIR, "指标.json")
    with open(metrics_path, 'w', encoding='utf-8') as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)
    print(f"  ✅ 指标JSON: {metrics_path}")

    # === 净值曲线CSV ===
    nav_data = analysis.get('daily_returns', [])
    if nav_data:
        nav_list = []
        nav_val = 1.0
        nav_list.append({'date': 'start', 'nav': 1.0, 'daily_return': 0})
        for dr in nav_data:
            nav_val *= (1 + dr['return'])
            nav_list.append({
                'date': dr['date'].strftime('%Y-%m-%d') if hasattr(dr['date'], 'strftime') else str(dr['date']),
                'nav': round(nav_val, 6),
                'daily_return': round(dr['return'] * 100, 4),
            })
        nav_df = pd.DataFrame(nav_list)
        nav_path = os.path.join(REPORT_DIR, "净值曲线.csv")
        nav_df.to_csv(nav_path, index=False, encoding='utf-8-sig')
        print(f"  ✅ 净值曲线: {nav_path}")

    print(f"\n  📁 所有报告已生成至: {REPORT_DIR}")
    return report_path


# ============================================================
# 主函数
# ============================================================
def main():
    print("=" * 60)
    print("🚀 动量轮动策略 - 回测系统")
    print("=" * 60)

    # 第一步：筛选股票
    stocks = get_top_stocks()
    stock_names = {s['code']: s['name'] for s in stocks}

    # 第二步：拉取K线数据
    klines = fetch_all_klines(stocks)

    if len(klines) < 2:
        print("\n❌ 可用K线数据不足（至少需要2只股票），回测终止")
        # 尝试扩大范围拉取更多股票
        print("  尝试扩大股票池范围...")
        # 从涨跌幅前100中选取
        df = pd.read_csv(DATA_SOURCE)
        for kw in ['ST', '*ST', '退市', '退']:
            df = df[~df['名称'].str.contains(kw, na=False, regex=False)]
        df['成交额'] = pd.to_numeric(df['成交额'], errors='coerce')
        df = df[df['成交额'] >= 10_000_000]
        df['涨跌幅'] = pd.to_numeric(df['涨跌幅'], errors='coerce')
        df = df.dropna(subset=['涨跌幅'])
        top100 = df.sort_values('涨跌幅', ascending=False).head(100)

        # 只取sh/sz开头的（新浪API支持）
        extra_stocks = []
        for _, row in top100.iterrows():
            code = str(row['代码']).strip()
            if code.startswith('sh') or code.startswith('sz'):
                extra_stocks.append({
                    'code': code,
                    'name': str(row['名称']).strip(),
                    'change': float(row['涨跌幅'])
                })

        if len(extra_stocks) > len(stocks):
            stocks = extra_stocks[:30]  # 最多30只
            stock_names = {s['code']: s['name'] for s in stocks}
            klines = fetch_all_klines(stocks)

    if len(klines) < 2:
        print("❌ 仍然数据不足，无法回测")
        sys.exit(1)

    # 第三步：运行回测
    analysis = run_backtest(klines, stock_names)

    if not analysis:
        print("❌ 回测失败")
        sys.exit(1)

    # 第四步：生成报告
    generate_report(stocks, stock_names, analysis)

    # 打印摘要
    print("\n" + "=" * 60)
    print("📊 回测结果摘要")
    print("=" * 60)
    print(f"  总收益率:   {analysis.get('total_return', 0)*100:+.2f}%")
    print(f"  年化收益率: {analysis.get('annual_return', 0)*100:+.2f}%")
    print(f"  夏普比率:   {analysis.get('sharpe_ratio', 0):.4f}")
    print(f"  最大回撤:   {analysis.get('max_drawdown', 0):.2f}%")
    print(f"  胜率:       {analysis.get('win_rate', 0)*100:.1f}%")
    print(f"  交易次数:   {analysis.get('total_trades', 0)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
