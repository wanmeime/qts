# -*- coding: utf-8 -*-
"""
MACD 分析模块

包含：
1. MACD 计算（DIF、DEA、MACD柱）
2. 金叉/死叉识别
3. 背驰检测（顶背驰、底背驰）
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import List, Tuple, Optional
from enum import Enum

class MACDSignal(Enum):
    GOLD_CROSS = "gold_cross"    # 金叉
    DEAD_CROSS = "dead_cross"    # 死叉
    TOP_DIVERGENCE = "top_divergence"  # 顶背驰
    BOTTOM_DIVERGENCE = "bottom_divergence"  # 底背驰

@dataclass
class MACDPoint:
    """MACD 数据点"""
    timestamp: str
    dif: float
    dea: float
    macd: float

@dataclass
class MACDSignalPoint:
    """MACD 信号"""
    timestamp: str
    signal: MACDSignal
    price: float
    macd_value: float

class MACDAnalysis:
    """MACD 分析类"""

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9):
        """
        初始化 MACD 参数

        参数：
        - fast: 快线周期，默认12
        - slow: 慢线周期，默认26
        - signal: 信号线周期，默认9
        """
        self.fast = fast
        self.slow = slow
        self.signal = signal
        self.macd_data: List[MACDPoint] = []

    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        计算 MACD 指标

        返回包含 DIF, DEA, MACD 列的 DataFrame
        """
        # 计算 EMA
        ema_fast = df['close'].ewm(span=self.fast, adjust=False).mean()
        ema_slow = df['close'].ewm(span=self.slow, adjust=False).mean()

        # DIF = 快线 - 慢线
        dif = ema_fast - ema_slow

        # DEA = DIF 的 EMA
        dea = dif.ewm(span=self.signal, adjust=False).mean()

        # MACD 柱 = 2 * (DIF - DEA)
        macd = 2 * (dif - dea)

        # 保存结果
        self.macd_data = []
        for i in range(len(df)):
            self.macd_data.append(MACDPoint(
                timestamp=str(df.index[i]),
                dif=dif.iloc[i],
                dea=dea.iloc[i],
                macd=macd.iloc[i]
            ))

        # 添加到 DataFrame
        df = df.copy()
        df['DIF'] = dif
        df['DEA'] = dea
        df['MACD'] = macd

        return df

    def find_crosses(self) -> List[MACDSignalPoint]:
        """
        识别金叉和死叉

        金叉：DIF 从下方穿越 DEA
        死叉：DIF 从上方穿越 DEA
        """
        if not self.macd_data:
            return []

        signals = []

        for i in range(1, len(self.macd_data)):
            prev = self.macd_data[i-1]
            curr = self.macd_data[i]

            # 金叉：前一根 DIF < DEA，当前 DIF >= DEA
            if prev.dif < prev.dea and curr.dif >= curr.dea:
                signals.append(MACDSignalPoint(
                    timestamp=curr.timestamp,
                    signal=MACDSignal.GOLD_CROSS,
                    price=0,  # 需要外部传入价格
                    macd_value=curr.macd
                ))

            # 死叉：前一根 DIF > DEA，当前 DIF <= DEA
            if prev.dif > prev.dea and curr.dif <= curr.dea:
                signals.append(MACDSignalPoint(
                    timestamp=curr.timestamp,
                    signal=MACDSignal.DEAD_CROSS,
                    price=0,
                    macd_value=curr.macd
                ))

        return signals

    def detect_divergence(self, df: pd.DataFrame, lookback: int = 20) -> List[MACDSignalPoint]:
        """
        检测背驰

        顶背驰：价格创新高，但 MACD 柱未创新高
        底背驰：价格创新低，但 MACD 柱未创新低
        """
        if not self.macd_data or len(df) < lookback:
            return []

        signals = []

        for i in range(lookback, len(df)):
            # 获取回溯窗口
            window_prices = df['high'].iloc[i-lookback:i+1]
            window_macd = [d.macd for d in self.macd_data[i-lookback:i+1]]

            current_price = df['high'].iloc[i]
            current_macd = self.macd_data[i].macd

            # 顶背驰检测
            if current_price >= window_prices.max():
                # 价格是窗口内最高
                max_macd_before = max(window_macd[:-1])
                if current_macd < max_macd_before:
                    # MACD 未创新高
                    signals.append(MACDSignalPoint(
                        timestamp=self.macd_data[i].timestamp,
                        signal=MACDSignal.TOP_DIVERGENCE,
                        price=current_price,
                        macd_value=current_macd
                    ))

            # 底背驰检测
            window_low_prices = df['low'].iloc[i-lookback:i+1]
            if current_price <= window_low_prices.min():
                # 价格是窗口内最低
                min_macd_before = min(window_macd[:-1])
                if current_macd > min_macd_before:
                    # MACD 未创新低
                    signals.append(MACDSignalPoint(
                        timestamp=self.macd_data[i].timestamp,
                        signal=MACDSignal.BOTTOM_DIVERGENCE,
                        price=df['low'].iloc[i],
                        macd_value=current_macd
                    ))

        return signals

    def analyze(self, df: pd.DataFrame) -> dict:
        """
        完整 MACD 分析

        返回：
        - MACD 数据
        - 交叉信号
        - 背驰信号
        """
        df_with_macd = self.calculate(df)
        crosses = self.find_crosses()
        divergences = self.detect_divergence(df)

        return {
            'df': df_with_macd,
            'macd_data': self.macd_data,
            'crosses': crosses,
            'divergences': divergences
        }

    def get_macd_at(self, index: int) -> Optional[MACDPoint]:
        """获取指定索引的 MACD 数据"""
        if 0 <= index < len(self.macd_data):
            return self.macd_data[index]
        return None

    def get_trend(self) -> str:
        """
        获取当前 MACD 趋势

        返回：
        - "bullish": DIF > DEA
        - "bearish": DIF < DEA
        - "neutral": DIF == DEA
        """
        if not self.macd_data:
            return "neutral"

        last = self.macd_data[-1]
        if last.dif > last.dea:
            return "bullish"
        elif last.dif < last.dea:
            return "bearish"
        else:
            return "neutral"
