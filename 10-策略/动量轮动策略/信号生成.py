#!/usr/bin/env python3
"""
动量轮动策略 - 信号生成脚本
============================

从A股全市场股票中筛选动量最强的股票，输出买入信号。

核心逻辑：
1. 加载A股全市场行情数据
2. 过滤ST、退市股、低成交额股票
3. 通过本地 K 线数据计算真实的多周期动量得分
4. 按动量得分排名，取前N只
5. 输出买入信号CSV

数据源:
- 行情快照: /home/jiaod/qts/00-研究/数据源/缓存/A股全市场行情.csv
- K线数据: /home/jiaod/qts/00-研究/数据源/缓存/kline_6m/ 或 qts_data

输出到:
- /home/jiaod/qts/30-信号/

使用方法:
    /usr/bin/python3 信号生成.py
    /usr/bin/python3 信号生成.py --date 20260602
    /usr/bin/python3 信号生成.py --top 30

作者: QTS量化交易系统
日期: 2026-06-02
"""

import os
import sys
import argparse
import pandas as pd
from datetime import date
from pathlib import Path

# 将因子库目录加入Python路径
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir / '因子库'))
sys.path.insert(0, str(current_dir.parents[1]))

from momentum import calculate_momentum_score, rank_by_momentum, get_momentum_summary
import qts_data as qd

# ============================================================
# 配置常量
# ============================================================

DATA_SOURCE_PATH = "/home/jiaod/qts/00-研究/数据源/缓存/A股全市场行情.csv"
GLOBAL_KLINE_DIR = "/home/jiaod/qts/00-研究/数据源/缓存/kline_6m"
SIGNAL_OUTPUT_DIR = "/home/jiaod/qts/30-信号/"

EXCLUDE_KEYWORDS = ["ST", "*ST", "退市", "退"]
MIN_TURNOVER_AMOUNT = 10_000_000  # 1000万元

WEIGHT_SHORT = 0.5
WEIGHT_MID = 0.3
WEIGHT_LONG = 0.2
DEFAULT_TOP_N = 20


# ============================================================
# 核心函数
# ============================================================

def load_data(filepath: str) -> pd.DataFrame:
    """加载A股全市场行情数据"""
    print(f"📂 正在加载数据: {filepath}")
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"数据文件不存在: {filepath}")
    df = pd.read_csv(filepath, encoding='utf-8')
    print(f"✅ 数据加载完成: 共 {len(df)} 只股票")
    return df


def filter_stocks(df: pd.DataFrame) -> pd.DataFrame:
    """过滤不满足基本条件的股票"""
    initial_count = len(df)
    print(f"\n🔍 开始股票过滤（初始: {initial_count} 只）")

    if '名称' in df.columns:
        for keyword in EXCLUDE_KEYWORDS:
            df = df[~df['名称'].astype(str).str.contains(keyword, na=False, regex=False)]
        print(f"   排除ST/退市股后: {len(df)} 只")

    if '成交额' in df.columns:
        df['成交额'] = pd.to_numeric(df['成交额'], errors='coerce')
        df = df[df['成交额'] >= MIN_TURNOVER_AMOUNT]
        print(f"   排除低成交额后: {len(df)} 只（阈值: {MIN_TURNOVER_AMOUNT/10000:.0f}万元）")

    if '最新价' in df.columns:
        df['最新价'] = pd.to_numeric(df['最新价'], errors='coerce')
        df = df[df['最新价'] > 0]
        df = df.dropna(subset=['最新价'])
        print(f"   排除无价格后: {len(df)} 只")

    if '涨跌幅' in df.columns:
        df['涨跌幅'] = pd.to_numeric(df['涨跌幅'], errors='coerce')
        df = df.dropna(subset=['涨跌幅'])

    filtered_count = initial_count - len(df)
    print(f"✅ 过滤完成: 排除 {filtered_count} 只，剩余 {len(df)} 只")
    return df


def load_kline(symbol: str) -> pd.DataFrame:
    """加载本地 K 线数据，优先全局缓存，其次 qts_data。"""
    global_path = Path(GLOBAL_KLINE_DIR) / f"{symbol}.csv"
    if global_path.exists():
        df = pd.read_csv(global_path)
        df = df.rename(columns={"day": "date"}) if "date" not in df.columns and "day" in df.columns else df
        df['date'] = pd.to_datetime(df['date'])
        if len(df) >= 30:
            return df

    try:
        df = qd.kline(symbol)
        if len(df) >= 30:
            return df
    except Exception:
        pass

    return pd.DataFrame()


def generate_signals(df: pd.DataFrame, top_n: int = DEFAULT_TOP_N) -> pd.DataFrame:
    """基于真实 K 线计算动量得分，并输出 Top N 信号。"""
    print("\n📊 开始计算动量因子（基于本地 K 线）...")

    scores = []
    processed = 0
    skipped = 0

    for _, row in df.iterrows():
        code = str(row.get('代码', '')).strip()
        if not code:
            continue

        kline = load_kline(code)
        score = calculate_momentum_score(
            kline,
            weight_short=WEIGHT_SHORT,
            weight_mid=WEIGHT_MID,
            weight_long=WEIGHT_LONG,
        )
        if score is None:
            skipped += 1
            continue

        processed += 1
        item = row.to_dict()
        item['动量得分'] = round(float(score), 4)
        scores.append(item)

    if not scores:
        raise RuntimeError("无可用动量得分，请检查 K 线数据是否完整")

    df_score = pd.DataFrame(scores)
    df_ranked = rank_by_momentum(df_score, score_col='动量得分', ascending=False)
    signals = df_ranked.head(top_n).copy()
    signals = signals.reset_index(drop=True)
    signals.index = signals.index + 1
    signals.index.name = '排名'

    print(f"   成功计算: {processed} 只 | 数据不足跳过: {skipped} 只")
    summary = get_momentum_summary(df_score)
    print("\n📈 动量因子统计:")
    for k, v in summary.items():
        print(f"   {k}: {v}")

    return signals


def save_signals(signals: pd.DataFrame, signal_date: str) -> str:
    """保存信号到CSV文件"""
    os.makedirs(SIGNAL_OUTPUT_DIR, exist_ok=True)
    filepath = os.path.join(SIGNAL_OUTPUT_DIR, f"动量轮动_买入信号_{signal_date}.csv")

    output_columns = []
    for col in ['代码', '股票代码', '名称', '最新价', '涨跌幅', '成交额', '换手率',
                '市盈率', '市净率', '总市值', '流通市值', '动量得分', '动量排名']:
        if col in signals.columns:
            output_columns.append(col)

    output_df = signals[output_columns].copy()
    output_df['信号日期'] = signal_date
    output_df.to_csv(filepath, encoding='utf-8-sig', index=True)
    print(f"\n💾 信号已保存: {filepath}")
    print(f"   文件大小: {os.path.getsize(filepath)} 字节")
    return filepath


def display_signals(signals: pd.DataFrame):
    """在终端显示信号摘要"""
    print(f"\n{'='*70}")
    print(f"🚀 动量轮动策略 - 买入信号 TOP {len(signals)}")
    print(f"{'='*70}")

    display_cols = ['名称', '最新价', '涨跌幅', '成交额', '动量得分']
    available_cols = [c for c in display_cols if c in signals.columns]

    if available_cols:
        display_df = signals[available_cols].copy()
        if '成交额' in display_df.columns:
            display_df['成交额'] = display_df['成交额'].apply(lambda x: f"{x/10000:.0f}万" if pd.notna(x) else "N/A")
        if '涨跌幅' in display_df.columns:
            display_df['涨跌幅'] = display_df['涨跌幅'].apply(lambda x: f"{x:+.2f}%" if pd.notna(x) else "N/A")
        if '动量得分' in display_df.columns:
            display_df['动量得分'] = display_df['动量得分'].apply(lambda x: f"{x:.2f}" if pd.notna(x) else "N/A")
        if '最新价' in display_df.columns:
            display_df['最新价'] = display_df['最新价'].apply(lambda x: f"{x:.2f}" if pd.notna(x) else "N/A")
        print(display_df.to_string())
    print(f"{'='*70}")


def main():
    parser = argparse.ArgumentParser(description='动量轮动策略 - 信号生成')
    parser.add_argument('--date', type=str, default=None, help='信号日期，格式: YYYYMMDD（默认: 今天）')
    parser.add_argument('--top', type=int, default=DEFAULT_TOP_N, help=f'选取股票数量（默认: {DEFAULT_TOP_N}）')
    parser.add_argument('--data', type=str, default=DATA_SOURCE_PATH, help='数据源路径')
    args = parser.parse_args()

    signal_date = args.date or date.today().strftime('%Y%m%d')
    print("=" * 70)
    print("📋 动量轮动策略 - 信号生成")
    print(f"📅 信号日期: {signal_date}")
    print(f"🎯 选股数量: {args.top}")
    print("=" * 70)

    try:
        df = load_data(args.data)
        df_filtered = filter_stocks(df)
        if len(df_filtered) == 0:
            raise RuntimeError("过滤后无可用股票，请检查数据源")
        signals = generate_signals(df_filtered, top_n=args.top)
        display_signals(signals)
        output_path = save_signals(signals, signal_date)
        print(f"\n✅ 信号生成完成！")
        print(f"   输出文件: {output_path}")
    except Exception as e:
        print(f"\n❌ 运行出错: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
