# -*- coding: utf-8 -*-
"""
信号模板数据结构

定义静态分析模块 → 实时盯盘模块 之间的信号契约。

共 4 类信号：
1. BottomFractalSignal  — 日线底分型待突破信号（带买卖点标签）
2. TopFractalSignal     — 日线顶分型待跌破信号（带买卖点标签）
3. DivergenceZoneSignal — 15分钟背驰段监控信号（持仓专用）
4. PositionRiskSignal   — 持仓风控信号（止损/止盈/波动报警）
"""

from dataclasses import dataclass, field
from typing import Optional, List
from enum import Enum
from datetime import datetime


# ============================================================
# 枚举
# ============================================================

class SignalStatus(Enum):
    """信号状态"""
    PENDING = "pending"           # 待触发（阈值未到）
    ACTIVATED = "activated"       # 已触发（突破/跌破确认）
    INVALIDATED = "invalidated"   # 已失效（反向突破）
    EXPIRED = "expired"           # 已过期（新交易时段覆盖）


class BuySellLabel(Enum):
    """买卖点标签（由静态分析模块标记，实时模块原样传递）"""
    BUY1 = "buy1"
    BUY2 = "buy2"
    BUY3 = "buy3"
    SECONDARY_BUY = "secondary_buy"
    SELL1 = "sell1"
    SELL2 = "sell2"
    SELL3 = "sell3"


class DivergenceStatus(Enum):
    """背驰段状态"""
    NOT_IN_ZONE = "not_in_zone"           # 不在背驰段
    IN_ZONE = "in_zone"                   # 在背驰段，待观察
    CONFIRMED = "confirmed"               # 背驰确认（顶分型+MACD缩小）
    FAILED = "failed"                     # 背驰失败（离开笔力度放大）


class RiskLevel(Enum):
    """风控等级"""
    NORMAL = "normal"
    ALERT = "alert"            # ±3%波动告警
    STOP_LOSS = "stop_loss"    # 触发止损
    TAKE_PROFIT = "take_profit"  # 浮盈>30%减仓


# ============================================================
# 信号模板
# ============================================================

@dataclass
class BottomFractalSignal:
    """
    日线底分型待突破信号

    缠论引擎识别出一买/二买/三买/类二买后，提取对应的底分型数据。
    实时盯盘模块观察：价格突破 third_high → 买入确认；跌破底分型低点 → 失效。

    字段说明：
      - fractal_price: 底分型中间K线的低点（该分型的特征值）
      - fractal_high:  底分型三K线的最高价
      - third_high:    底分型第三根K线的高点（突破此点确认买入）
      - stop_loss:     底分型三K线的最低价（跌破此点分型失效）
      - buy_label:     对应的买卖点类型（一买/二买/三买/类二买）
    """
    stock_code: str
    stock_name: str

    # 分型数据
    fractal_index: int          # 在 processed_klines 中的索引（用于关联）
    fractal_timestamp: str      # 底分型日期
    fractal_price: float        # 底分型特征值（中间K线低点）
    fractal_high: float         # 三K线最高价
    fractal_low: float          # 三K线最低价
    third_high: float           # 第三根K线高点（突破确认买入）
    stop_loss: float            # 跌破此点分型失效

    # 买卖点标签（由静态分析模块从缠论结果中提取）
    buy_label: BuySellLabel     # buy1 / buy2 / buy3 / secondary_buy

    # 状态管理
    status: SignalStatus = SignalStatus.PENDING
    triggered_at: Optional[str] = None
    triggered_price: Optional[float] = None

    # 元信息
    created_at: str = field(default_factory=lambda: datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    updated_at: str = field(default_factory=lambda: datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    analysis_date: str = ""      # 生成该信号的静态分析日期


@dataclass
class TopFractalSignal:
    """
    日线顶分型待跌破信号

    缠论引擎识别出一卖/二卖/三卖后，提取对应的顶分型数据。
    实时盯盘模块观察：价格跌破 third_low → 卖出确认；涨破顶分型高点 → 失效。

    字段说明：
      - fractal_price: 顶分型中间K线的高点（该分型的特征值）
      - fractal_low:   顶分型三K线的最低价
      - third_low:     顶分型第三根K线的低点（跌破此点确认卖出）
      - stop_loss:     顶分型三K线的最高价（涨破此点分型失效）
      - sell_label:    对应的买卖点类型（一卖/二卖/三卖）
    """
    stock_code: str
    stock_name: str

    # 分型数据
    fractal_index: int
    fractal_timestamp: str
    fractal_price: float        # 顶分型特征值（中间K线高点）
    fractal_high: float         # 三K线最高价
    fractal_low: float          # 三K线最低价
    third_low: float            # 第三根K线低点（跌破确认卖出）
    stop_loss: float            # 涨破此点分型失效

    # 买卖点标签
    sell_label: BuySellLabel    # sell1 / sell2 / sell3

    # 状态管理
    status: SignalStatus = SignalStatus.PENDING
    triggered_at: Optional[str] = None
    triggered_price: Optional[float] = None

    # 元信息
    created_at: str = field(default_factory=lambda: datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    updated_at: str = field(default_factory=lambda: datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    analysis_date: str = ""


@dataclass
class DivergenceZoneSignal:
    """
    15分钟背驰段监控信号（持仓专用）

    缠论引擎在15分钟级别上判断当前是否在背驰段。
    如果在背驰段（in_zone），实时模块观察15分钟顶分型何时形成；
    如果不在背驰段（not_in_zone），实时模块无需关注此信号，
    仅由 chanlun_service 盘中按需更新状态。

    背驰确认条件：
      - 15分钟顶分型形成
      - 当前离开笔MACD柱面积 < 前一段离开笔MACD柱面积
    """
    stock_code: str
    stock_name: str

    # 是否在背驰段（由 chanlun_service 盘中判断）
    div_status: DivergenceStatus = DivergenceStatus.NOT_IN_ZONE

    # 背驰段结构参数（仅在 in_zone 时有意义）
    zhongshu_high: Optional[float] = None
    zhongshu_low: Optional[float] = None
    prev_exit_bi_macd_area: Optional[float] = None  # 前一段离开笔MACD面积
    curr_exit_bi_macd_area: Optional[float] = None   # 当前离开笔MACD面积
    curr_exit_bi_high: Optional[float] = None         # 当前离开笔最新高点

    # 背驰确认时记录
    confirmed_at: Optional[str] = None
    confirmed_price: Optional[float] = None

    # 元信息
    created_at: str = field(default_factory=lambda: datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    updated_at: str = field(default_factory=lambda: datetime.now().strftime('%Y-%m-%d %H:%M:%S'))


@dataclass
class PositionRiskSignal:
    """
    持仓风控信号

    针对每只持仓股生成，独立于缠论分析。
    条件完全由持仓成本 + 静态策略规则决定。
    """
    stock_code: str
    stock_name: str

    # 持仓参数
    cost_price: float
    current_price: float = 0.0
    position_shares: int = 0
    position_value: float = 0.0

    # 风控阈值（由策略规则设定）
    stop_loss_price: Optional[float] = None
    profit_30pct_price: Optional[float] = None   # 浮盈30%减仓线
    alert_3pct_up: Optional[float] = None         # 上涨3%报警线
    alert_3pct_down: Optional[float] = None        # 下跌3%报警线

    # 当前状态
    risk_level: RiskLevel = RiskLevel.NORMAL
    profit_pct: float = 0.0                       # 当前盈亏百分比

    # 元信息
    created_at: str = field(default_factory=lambda: datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    updated_at: str = field(default_factory=lambda: datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
