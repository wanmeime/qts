"""
策略配置 — 回测与实时盯盘共享的统一参数
修改此文件后，回测和盯盘同时生效
"""
from typing import Dict

# ── 买入规则 ──

# 买点信号类型及其优先级（值越大优先级越高）
BUY_SIGNAL_PRIORITY: Dict[str, int] = {
    "buy2": 3,             # 二买（最高优先）
    "secondary_buy": 2,    # 类二买
    "buy3": 1,             # 三买
}

# 成交量过滤：当日成交量必须大于 N 倍 5日均量
VOLUME_RATIO: float = 1.5

# ── 止盈规则 ──

# 浮盈达到此比例时减半仓（0.3 = 30%）
TAKEPROFIT_PCT: float = 0.3

# ── 止损规则 ──

# 底分型振幅阈值（超过此值启用中位止损）
FRACTAL_AMPLITUDE_THRESHOLD: float = 0.05  # 5%

# ── 卖出规则 ──

# 启用的卖出条件
ENABLE_15MIN_DIVERGENCE: bool = True   # 15分钟背驰
ENABLE_SELL_SIGNALS: bool = True       # 一卖/二卖信号

# ── 交易成本（仅回测用，盯盘不需要） ──

COMMISSION_RATE: float = 0.00025    # 佣金万2.5
MIN_COMMISSION: float = 5.0         # 最低佣金5元
STAMP_TAX_RATE: float = 0.0005      # 印花税万5（仅卖出）
TRANSFER_FEE_RATE: float = 0.00001  # 过户费万0.1
SLIPPAGE: float = 0.001             # 滑点0.1%

# ── 缠论参数 ──

MAX_FRACTAL_AGE: int = 60    # 分型最大时效（交易日数）
MIN_BUY_SCORE: int = 90      # 最低买入评分

# ── 买点信号类型中文名 ──

SIGNAL_TYPE_CN: Dict[str, str] = {
    "buy1": "一买",
    "buy2": "二买",
    "buy3": "三买",
    "secondary_buy": "类二买",
    "sell1": "一卖",
    "sell2": "二卖",
    "sell3": "三卖",
}
