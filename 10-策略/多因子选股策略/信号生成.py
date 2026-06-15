#!/usr/bin/env python3
"""
多因子选股策略 - 信号生成脚本
=============================
从A股全市场行情数据中，通过多因子打分模型筛选出综合评分最高的股票。

运行方式：
    cd /home/jiaod/qts/10-策略/多因子选股策略/
    /usr/bin/python3 信号生成.py

输出：
    /home/jiaod/qts/30-信号/多因子选股_YYYYMMDD.csv
"""

import sys
import os
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

# 添加因子库路径
STRATEGY_DIR = Path(__file__).parent
sys.path.insert(0, str(STRATEGY_DIR))

from 因子库.factors import calculate_factor_scores, calculate_composite_score


def load_config(config_path: str = None) -> dict:
    """
    加载参数配置文件

    参数:
        config_path: 配置文件路径，默认为同目录下的参数配置.yaml

    返回:
        配置字典
    """
    if config_path is None:
        config_path = STRATEGY_DIR / "参数配置.yaml"

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # 校验权重之和
    total_weight = sum(f["weight"] for f in config["factors"].values())
    expected = config.get("weight_sum_check", 1.0)
    if abs(total_weight - expected) > 0.001:
        print(f"❌ 因子权重之和为 {total_weight}，不等于 {expected}，请检查配置！")
        sys.exit(1)
    print(f"✅ 因子权重校验通过: {total_weight}")

    return config


def load_data(config: dict) -> pd.DataFrame:
    """
    加载A股全市场行情数据

    参数:
        config: 配置字典

    返回:
        原始行情DataFrame
    """
    cache_file = config["data_source"]["cache_file"]
    encoding = config["data_source"].get("encoding", "utf-8")

    print(f"\n📂 加载数据: {cache_file}")
    df = pd.read_csv(cache_file, encoding=encoding)
    print(f"  原始股票数量: {len(df)}")

    # 显示列名
    print(f"  数据列: {list(df.columns)}")

    return df


def filter_stocks(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """
    预处理：排除不符合条件的股票

    排除规则：
    1. ST股票（名称含"ST"）
    2. 退市股（名称含"退"）
    3. PE < 0 的股票
    4. PB < 0 的股票

    参数:
        df: 原始行情DataFrame
        config: 配置字典

    返回:
        过滤后的DataFrame
    """
    exclusion = config["exclusion"]
    original_count = len(df)

    # 排除ST股
    if exclusion.get("exclude_st", True):
        mask_st = df["名称"].astype(str).str.contains("ST", case=False, na=False)
        df = df[~mask_st]
        print(f"  排除ST股: {mask_st.sum()} 只")

    # 排除退市股
    if exclusion.get("exclude_delist", True):
        mask_delist = df["名称"].astype(str).str.contains("退", na=False)
        df = df[~mask_delist]
        print(f"  排除退市股: {mask_delist.sum()} 只")

    # 排除PE < 0
    min_pe = exclusion.get("min_pe", 0)
    if "市盈率" in df.columns:
        mask_pe = pd.to_numeric(df["市盈率"], errors="coerce") < min_pe
        df = df[~mask_pe]
        print(f"  排除PE<{min_pe}: {mask_pe.sum()} 只")

    # 排除PB < 0
    min_pb = exclusion.get("min_pb", 0)
    if "市净率" in df.columns:
        mask_pb = pd.to_numeric(df["市净率"], errors="coerce") < min_pb
        df = df[~mask_pb]
        print(f"  排除PB<{min_pb}: {mask_pb.sum()} 只")

    # 排除关键字段缺失
    key_columns = ["市盈率", "市净率", "换手率", "总市值", "成交额", "涨跌幅"]
    for col in key_columns:
        if col in df.columns:
            before = len(df)
            df = df[pd.to_numeric(df[col], errors="coerce").notna()]
            removed = before - len(df)
            if removed > 0:
                print(f"  排除{col}缺失: {removed} 只")

    print(f"\n📊 过滤后股票数量: {len(df)} (排除了 {original_count - len(df)} 只)")

    return df.reset_index(drop=True)


def run_strategy():
    """主函数：执行完整的多因子选股流程"""
    print("=" * 60)
    print("🚀 多因子选股策略 - 信号生成")
    print(f"   运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 1. 加载配置
    print("\n📋 步骤1: 加载配置")
    config = load_config()

    # 2. 加载数据
    print("\n📋 步骤2: 加载数据")
    df = load_data(config)

    # 3. 预处理过滤
    print("\n📋 步骤3: 预处理 - 排除不符合条件的股票")
    df = filter_stocks(df, config)

    if len(df) == 0:
        print("❌ 过滤后无可用股票数据，退出")
        sys.exit(1)

    # 4. 确保数值列为数值类型
    numeric_columns = ["市盈率", "市净率", "换手率", "总市值", "成交额", "涨跌幅", "最新价"]
    for col in numeric_columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 5. 计算因子得分
    print("\n📋 步骤4: 计算因子得分")
    df = calculate_factor_scores(df, config)

    # 6. 计算综合得分
    print("\n📋 步骤5: 计算加权综合得分")
    df = calculate_composite_score(df, config)

    # 7. 排序并取前N名
    top_n = config["output"]["top_n"]
    df_ranked = df.sort_values("综合得分", ascending=False).head(top_n).copy()
    df_ranked["排名"] = range(1, len(df_ranked) + 1)

    # 8. 输出结果
    print(f"\n📋 步骤6: 输出Top {top_n} 选股结果")
    print("\n" + "=" * 60)
    print(f"{'排名':>4} {'代码':<10} {'名称':<8} {'最新价':>8} {'涨跌幅':>8} {'PE':>8} {'PB':>8} {'综合得分':>8}")
    print("-" * 60)

    for _, row in df_ranked.iterrows():
        print(f"{int(row['排名']):>4} "
              f"{str(row.get('代码', row.get('股票代码', ''))):<10} "
              f"{str(row.get('名称', '')):<8} "
              f"{row.get('最新价', 0):>8.2f} "
              f"{row.get('涨跌幅', 0):>7.2f}% "
              f"{row.get('市盈率', 0):>8.2f} "
              f"{row.get('市净率', 0):>8.2f} "
              f"{row.get('综合得分', 0):>8.2f}")

    # 9. 保存到文件
    signal_dir = config["output"]["signal_dir"]
    file_prefix = config["output"]["file_prefix"]
    today = datetime.now().strftime("%Y%m%d")
    output_file = os.path.join(signal_dir, f"{file_prefix}_{today}.csv")

    # 确保输出目录存在
    os.makedirs(signal_dir, exist_ok=True)

    # 选择输出列
    output_columns = ["排名", "代码", "股票代码", "名称", "最新价", "涨跌幅",
                       "市盈率", "市净率", "总市值", "换手率", "成交额", "综合得分"]
    # 只保留存在的列
    output_columns = [c for c in output_columns if c in df_ranked.columns]

    df_ranked[output_columns].to_csv(output_file, index=False, encoding="utf-8-sig")
    print(f"\n✅ 信号已保存到: {output_file}")
    print(f"   共选出 {len(df_ranked)} 只股票")

    return df_ranked


if __name__ == "__main__":
    result = run_strategy()
    print("\n" + "=" * 60)
    print("✅ 策略运行完成")
    print("=" * 60)
