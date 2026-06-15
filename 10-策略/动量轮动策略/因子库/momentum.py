"""
动量因子计算模块
================

提供动量因子的计算逻辑，用于动量轮动策略。

主要功能：
- 从 K 线数据计算多周期动量
- 生成综合动量得分
- 对股票进行动量排名

作者: QTS量化交易系统
日期: 2026-06-02
"""

import pandas as pd
import numpy as np
from typing import Optional


def calculate_returns(prices: pd.Series, period: int = 5) -> Optional[float]:
    """计算最近一期 N 日收益率（百分比）。"""
    if len(prices) < period + 1:
        return None
    if prices.iloc[-period - 1] <= 0:
        return None
    return (prices.iloc[-1] / prices.iloc[-period - 1] - 1) * 100


def calculate_momentum_score(
    kline: pd.DataFrame,
    short_period: int = 5,
    mid_period: int = 10,
    long_period: int = 20,
    weight_short: float = 0.5,
    weight_mid: float = 0.3,
    weight_long: float = 0.2
) -> Optional[float]:
    """
    从 K 线 DataFrame 计算综合动量得分。

    参数:
        kline: 包含 date/close 的 K 线 DataFrame
        short_period/mid_period/long_period: 周期长度
        weight_short/weight_mid/weight_long: 各周期权重

    返回:
        综合动量得分；若数据不足返回 None
    """
    if kline is None or len(kline) < long_period + 1:
        return None

    kline = kline.copy()
    date_col = "date" if "date" in kline.columns else "day"
    close_col = "close" if "close" in kline.columns else None
    if close_col is None:
        return None

    kline[date_col] = pd.to_datetime(kline[date_col])
    kline = kline.sort_values(date_col)
    prices = pd.to_numeric(kline[close_col], errors="coerce")

    ret_short = calculate_returns(prices, short_period)
    ret_mid = calculate_returns(prices, mid_period)
    ret_long = calculate_returns(prices, long_period)

    if ret_short is None or ret_mid is None or ret_long is None:
        return None

    return weight_short * ret_short + weight_mid * ret_mid + weight_long * ret_long


def batch_momentum_scores(
    kline_map: dict,
    short_period: int = 5,
    mid_period: int = 10,
    long_period: int = 20,
    weight_short: float = 0.5,
    weight_mid: float = 0.3,
    weight_long: float = 0.2
) -> dict:
    """批量计算多个标的的动量得分。"""
    scores = {}
    for symbol, kline in kline_map.items():
        score = calculate_momentum_score(
            kline,
            short_period=short_period,
            mid_period=mid_period,
            long_period=long_period,
            weight_short=weight_short,
            weight_mid=weight_mid,
            weight_long=weight_long,
        )
        if score is not None:
            scores[symbol] = score
    return scores


def rank_by_momentum(
    df: pd.DataFrame,
    score_col: str = '动量得分',
    ascending: bool = False
) -> pd.DataFrame:
    """
    按动量得分排名
    """
    result = df.copy()
    result['动量排名'] = result[score_col].rank(
        ascending=ascending,
        method='min'
    ).astype(int)
    result = result.sort_values('动量排名', ascending=True)
    return result


def get_momentum_summary(df: pd.DataFrame) -> dict:
    """
    获取动量因子统计摘要
    """
    if '动量得分' not in df.columns:
        return {"错误": "数据中未找到动量得分列"}

    summary = {
        "股票总数": len(df),
        "动量得分_均值": round(df['动量得分'].mean(), 4),
        "动量得分_中位数": round(df['动量得分'].median(), 4),
        "动量得分_标准差": round(df['动量得分'].std(), 4),
        "动量得分_最大值": round(df['动量得分'].max(), 4),
        "动量得分_最小值": round(df['动量得分'].min(), 4),
        "正动量股票数": int((df['动量得分'] > 0).sum()),
        "负动量股票数": int((df['动量得分'] < 0).sum()),
    }
    return summary


# ============================================================
# 测试代码
# ============================================================
if __name__ == "__main__":
    dates = pd.date_range("2026-01-01", periods=30)
    test_kline = pd.DataFrame({
        "date": dates,
        "open": 100,
        "high": 110,
        "low": 90,
        "close": [100 + i * 0.5 for i in range(30)],
        "volume": 1000
    })
    print("=== 动量得分计算 ===")
    print("score:", calculate_momentum_score(test_kline))
    summary = get_momentum_summary(pd.DataFrame({"动量得分": [1.0, -0.2, 0.3]}))
    print("summary:", summary)
