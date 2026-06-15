"""
多因子计算模块
==============
提供六大因子的标准化评分函数，每个因子输出0-100分。

因子列表：
1. PE（市盈率）- 负向因子，越低越好
2. PB（市净率）- 负向因子，越低越好
3. 换手率 - 适中因子，中间最优
4. 总市值 - 正向因子，越大越好
5. 成交额 - 正向因子，越大越好
6. 涨跌幅 - 适中因子，接近0最优
"""

import numpy as np
import pandas as pd


def score_positive(series: pd.Series) -> pd.Series:
    """
    正向因子打分：值越大得分越高
    使用最小-最大归一化映射到0-100

    参数:
        series: 因子原始值序列

    返回:
        0-100的得分序列
    """
    s_min = series.min()
    s_max = series.max()
    # 避免除零：如果最大值等于最小值，所有股票得50分
    if s_max == s_min:
        return pd.Series(50.0, index=series.index)
    return (series - s_min) / (s_max - s_min) * 100


def score_negative(series: pd.Series) -> pd.Series:
    """
    负向因子打分：值越小得分越高
    使用反转的最小-最大归一化映射到0-100

    参数:
        series: 因子原始值序列

    返回:
        0-100的得分序列
    """
    s_min = series.min()
    s_max = series.max()
    if s_max == s_min:
        return pd.Series(50.0, index=series.index)
    return (s_max - series) / (s_max - s_min) * 100


def score_moderate(series: pd.Series, optimal_percentile: float = 50.0) -> pd.Series:
    """
    适中因子打分：距最优百分位越近得分越高
    使用高斯衰减函数，标准差为数据范围的1/4

    参数:
        series: 因子原始值序列
        optimal_percentile: 最优值所在的百分位（默认50%，即中位数）

    返回:
        0-100的得分序列
    """
    # 计算最优值（指定百分位）
    optimal_value = np.percentile(series.dropna(), optimal_percentile)

    # 计算标准差（数据范围的1/4作为衰减宽度）
    data_range = series.max() - series.min()
    if data_range == 0:
        return pd.Series(50.0, index=series.index)
    sigma = data_range / 4

    # 高斯衰减：exp(-((x - optimal)^2) / (2 * sigma^2)) * 100
    scores = np.exp(-((series - optimal_value) ** 2) / (2 * sigma ** 2)) * 100
    return scores


def score_moderate_fixed(series: pd.Series, optimal_value: float = 0.0) -> pd.Series:
    """
    适中因子打分（固定最优值）：距固定最优值越近得分越高
    适用于涨跌幅等有明确最优值的因子

    参数:
        series: 因子原始值序列
        optimal_value: 固定最优值（默认0.0）

    返回:
        0-100的得分序列
    """
    data_range = series.max() - series.min()
    if data_range == 0:
        return pd.Series(50.0, index=series.index)
    sigma = data_range / 4

    scores = np.exp(-((series - optimal_value) ** 2) / (2 * sigma ** 2)) * 100
    return scores


def calculate_factor_scores(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """
    计算所有因子的标准化得分

    参数:
        df: 包含原始因子数据的DataFrame
        config: 因子配置字典（来自参数配置.yaml）

    返回:
        添加了各因子得分列的DataFrame
    """
    result = df.copy()

    factors_config = config["factors"]

    for factor_key, factor_cfg in factors_config.items():
        column = factor_cfg["column"]
        direction = factor_cfg["direction"]
        score_col = f"{column}_得分"

        if column not in result.columns:
            print(f"  ⚠️  列 '{column}' 不存在，跳过因子: {factor_cfg['name']}")
            result[score_col] = 0.0
            continue

        if direction == "positive":
            result[score_col] = score_positive(result[column])
        elif direction == "negative":
            result[score_col] = score_negative(result[column])
        elif direction == "moderate":
            if factor_key == "change_pct":
                # 涨跌幅使用固定最优值（0%）
                opt_val = factor_cfg.get("optimal_value", 0.0)
                result[score_col] = score_moderate_fixed(result[column], optimal_value=opt_val)
            else:
                # 换手率使用百分位最优值
                opt_pct = factor_cfg.get("optimal_percentile", 50.0)
                result[score_col] = score_moderate(result[column], optimal_percentile=opt_pct)

        print(f"  ✅ {factor_cfg['name']}({column}): 权重={factor_cfg['weight']}, 方向={direction}")

    return result


def calculate_composite_score(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """
    计算加权综合得分

    参数:
        df: 包含各因子得分的DataFrame
        config: 因子配置字典

    返回:
        添加了综合得分列的DataFrame
    """
    result = df.copy()
    result["综合得分"] = 0.0

    factors_config = config["factors"]

    for factor_key, factor_cfg in factors_config.items():
        column = factor_cfg["column"]
        weight = factor_cfg["weight"]
        score_col = f"{column}_得分"

        if score_col in result.columns:
            result["综合得分"] += result[score_col] * weight

    return result
