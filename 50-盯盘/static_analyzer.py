# -*- coding: utf-8 -*-
"""
静态分析模块（盘后运行）

流程：
  1. 加载持仓 + 自选股列表
  2. 获取日线K线数据
  3. 调用缠论引擎分析每只股票
  4. 提取买卖点对应的分型数据 → 生成信号模板
  5. 对持仓股检查15分钟背驰段
  6. 生成持仓风控信号
  7. 写入 DB

不依赖实时行情，每天收盘后运行一次。
"""
import sys
import json
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

import pandas as pd

# 项目路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "10-策略" / "缠论Agent"))
sys.path.insert(0, str(PROJECT_ROOT / "50-盯盘"))

from chanlun_core import (
    ChanlunCore, FractalType, Direction, BuySellType,
    BuySellPoint, Fractal, Bi,
)
from signal_templates import (
    BottomFractalSignal, TopFractalSignal,
    DivergenceZoneSignal, PositionRiskSignal,
    SignalStatus, DivergenceStatus, RiskLevel,
    BuySellLabel,
)
from state_store import StateStore
from realtime_fetcher import RealtimeFetcher

logger = logging.getLogger(__name__)

_CST = timezone(timedelta(hours=8))

# 路径常量
POSITION_FILE = PROJECT_ROOT / "40-执行" / "持仓" / "当前持仓.json"
WATCHLIST_FILE = PROJECT_ROOT / "00-研究" / "自选股" / "watchlist.json"
KLINE_CACHE_DIR = PROJECT_ROOT / "00-研究" / "数据源" / "缓存" / "kline_6m"


# ============================================================
# 数据加载
# ============================================================

def load_positions() -> List[Dict]:
    """加载当前持仓"""
    if not POSITION_FILE.exists():
        logger.warning(f"持仓文件不存在: {POSITION_FILE}")
        return []
    try:
        with open(POSITION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("持仓明细", [])
    except Exception as e:
        logger.error(f"加载持仓失败: {e}")
        return []


def load_watchlist() -> List[Dict]:
    """加载自选股列表"""
    if not WATCHLIST_FILE.exists():
        return []
    try:
        with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return data.get("stocks", data.get("list", []))
    except Exception as e:
        logger.error(f"加载自选股失败: {e}")
        return []


def load_kline_data(code: str, days: int = 365, scale: int = 240) -> Optional[pd.DataFrame]:
    """
    加载K线数据（日线或15分钟）

    复用 watchdog.py 中的 fetch_kline 逻辑，
    此处直接调用以保证数据一致性。
    """
    try:
        from watchdog import fetch_kline
        return fetch_kline(code, days=days, scale=scale)
    except ImportError:
        logger.error("无法导入 fetch_kline（watchdog.py）")
        return None


# ============================================================
# 信号模板生成
# ============================================================

def _buy_type_from_point(bp: BuySellPoint) -> Optional[BuySellLabel]:
    """将 BuySellType 转为信号模板的 BuySellLabel"""
    mapping = {
        BuySellType.BUY1: BuySellLabel.BUY1,
        BuySellType.BUY2: BuySellLabel.BUY2,
        BuySellType.BUY3: BuySellLabel.BUY3,
        BuySellType.SECONDARY_BUY: BuySellLabel.SECONDARY_BUY,
    }
    return mapping.get(bp.type)


def _sell_type_from_point(bp: BuySellPoint) -> Optional[BuySellLabel]:
    mapping = {
        BuySellType.SELL1: BuySellLabel.SELL1,
        BuySellType.SELL2: BuySellLabel.SELL2,
        BuySellType.SELL3: BuySellLabel.SELL3,
    }
    return mapping.get(bp.type)


def _find_fractal_for_point(
    core: ChanlunCore,
    bp: BuySellPoint,
) -> Optional[Fractal]:
    """在 core.fractals 中找与买卖点对应的分型"""
    for f in core.fractals:
        if f.index == bp.index:
            return f
    return None


def _is_buy_point(bp: BuySellPoint) -> bool:
    return bp.type in (BuySellType.BUY1, BuySellType.BUY2,
                       BuySellType.BUY3, BuySellType.SECONDARY_BUY)


def _is_sell_point(bp: BuySellPoint) -> bool:
    return bp.type in (BuySellType.SELL1, BuySellType.SELL2, BuySellType.SELL3)


# ============================================================
# 日线信号模板提取
# ============================================================

def generate_daily_signals(
    stock_code: str,
    stock_name: str,
    core: ChanlunCore,
    daily_df: pd.DataFrame,
    analysis_date: str,
    is_position: bool = False,
) -> List[object]:
    """
    从缠论分析结果中提取日线分型信号模板

    遍历 core.buy_sell_points，为每个买卖点找到对应的分型，
    生成 BottomFractalSignal（买点）或 TopFractalSignal（卖点）。

    策略过滤条件：
      - 只保留第三根K线为最新日K线的分型（昨天收盘刚形成的）
      - 买点信号需要成交量 > 近5日均量 × 1.5
    """
    signals = []
    seen = set()  # 同一个分型只生成一个信号

    # 策略要求：只监控昨天刚形成第三根K线的底分型/顶分型
    # 更早的分型已被后续走势验证或被覆盖，盯它没有意义
    # 第三根K线位置 = fractal.index + 1（在 processed_klines 中）

    # 成交量检查：计算近5日均量
    vol = daily_df['volume'].astype(float)
    avg_vol_5 = vol.tail(5).mean()
    latest_vol = vol.iloc[-1]
    vol_ratio = latest_vol / avg_vol_5 if avg_vol_5 > 0 else 0

    for bp in core.buy_sell_points:
        fractal = _find_fractal_for_point(core, bp)
        if fractal is None:
            continue

        # 策略：只监控昨天刚形成第三根K线的分型（盘中待验证）
        # 判断方式：第三根K线必须是 processed_klines 中的最后一根
        # （即最新完成的日K线，昨天收盘的那根）
        third_kline_idx = fractal.index + 1
        last_kline_idx = len(core.processed_klines) - 1
        if third_kline_idx != last_kline_idx:
            continue  # 第三根K线不是最新K线，跳过

        # 去重：同一个分型只输出一个信号
        if fractal.index in seen:
            continue
        seen.add(fractal.index)

        if _is_buy_point(bp):
            # 策略：买点需要成交量 > 近5日均量 × 1.5
            if vol_ratio < 1.5:
                continue

            label = _buy_type_from_point(bp)
            if label is None:
                continue
            sig = BottomFractalSignal(
                stock_code=stock_code,
                stock_name=stock_name,
                fractal_index=fractal.index,
                fractal_timestamp=fractal.timestamp,
                fractal_price=fractal.price,
                fractal_high=fractal.high,
                fractal_low=fractal.low,
                third_high=fractal.third_high,
                stop_loss=fractal.low,
                buy_label=label,
                analysis_date=analysis_date,
            )
            signals.append(sig)

        elif _is_sell_point(bp):
            # 卖点信号只对持仓股有意义，非持仓跳过
            if not is_position:
                continue
            label = _sell_type_from_point(bp)
            if label is None:
                continue
            sig = TopFractalSignal(
                stock_code=stock_code,
                stock_name=stock_name,
                fractal_index=fractal.index,
                fractal_timestamp=fractal.timestamp,
                fractal_price=fractal.price,
                fractal_high=fractal.high,
                fractal_low=fractal.low,
                third_low=fractal.third_low,
                stop_loss=fractal.high,
                sell_label=label,
                analysis_date=analysis_date,
            )
            signals.append(sig)

    return signals


# ============================================================
# 15分钟背驰段信号（持仓专用）
# ============================================================

def check_divergence_zone(
    core_15min: ChanlunCore,
) -> tuple:
    """
    检查15分钟级别是否在背驰段

    返回: (in_zone, zs_high, zs_low, prev_area)

    判断逻辑（完全分类）：
      - 有2个下跌中枢 → 看第二个中枢的离开笔
      - 离开笔的MACD面积 < 前一段离开笔 → 背驰段
      - 否则 → 不在背驰段
    """
    # 找下跌中枢
    down_zs = [zs for zs in core_15min.zhong_shus
               if zs.direction == Direction.DOWN]

    if len(down_zs) < 2:
        return False, None, None, None

    # 取第二个中枢
    zs = down_zs[-1]

    # 找中枢后的向下离开笔
    exit_bis = [
        b for i, b in enumerate(core_15min.bis)
        if b.direction == Direction.DOWN and i >= zs.end_bi_index
    ]
    if not exit_bis:
        return False, None, None, None

    # 找前一段离开笔
    prev_exit_bis = [
        b for i, b in enumerate(core_15min.bis)
        if b.direction == Direction.DOWN and i < zs.end_bi_index
        and i >= zs.start_bi_index - 2
    ]
    if len(prev_exit_bis) < 1:
        return False, None, None, None

    prev_exit = prev_exit_bis[-1]
    curr_exit = exit_bis[-1]

    # 计算MACD面积
    prev_area = core_15min._bi_macd_area(prev_exit)
    curr_area = core_15min._bi_macd_area(curr_exit)

    # 背驰判断：当前离开笔 MACD 面积 < 前一段的 85%
    in_zone = (prev_area > 0 and curr_area < prev_area * 0.85)

    return in_zone, zs.high, zs.low, prev_area


# ============================================================
# 主流程
# ============================================================

def run_static_analysis(
    state_store: StateStore,
    analysis_date: Optional[str] = None,
) -> List[object]:
    """
    运行完整静态分析，生成所有信号模板

    Args:
        state_store: StateStore 实例
        analysis_date: 分析日期（默认今天）

    Returns:
        所有生成的信号模板列表
    """
    if analysis_date is None:
        analysis_date = datetime.now(_CST).strftime("%Y-%m-%d")

    logger.info(f"=== 开始静态分析: {analysis_date} ===")

    # 1. 加载数据源
    positions = load_positions()
    watchlist = load_watchlist()
    logger.info(f"持仓: {len(positions)} 只, 自选股: {len(watchlist)} 只")

    # 2. 构建待分析代码列表
    watchlist_codes = set()
    for w in watchlist:
        code = w.get("code", "") if isinstance(w, dict) else str(w)
        if code and not code.startswith("399") and not code.startswith("880"):
            watchlist_codes.add(code)

    position_codes = {p.get("股票代码", "") for p in positions}
    # 重点关注的股票 = 持仓 + 自选股
    all_codes = position_codes | watchlist_codes

    all_signals = []
    fetcher = RealtimeFetcher()

    for code in sorted(all_codes):
        stock_name = ""
        # 尝试获取名称
        for p in positions:
            if p.get("股票代码") == code:
                stock_name = p.get("名称", code)
                break
        if not stock_name:
            for w in watchlist:
                wc = w.get("code", "") if isinstance(w, dict) else str(w)
                if wc == code:
                    stock_name = w.get("name", code) if isinstance(w, dict) else code
                    break
        if not stock_name:
            stock_name = code

        # 3. 日线分析
        daily_df = load_kline_data(code, days=365, scale=240)
        if daily_df is None or len(daily_df) < 60:
            logger.debug(f"{code} 日线数据不足，跳过")
            continue

        core = ChanlunCore()
        core.process_klines(daily_df[["open", "high", "low", "close"]])
        core.find_fractals()
        core.find_bis()
        core.find_zhong_shus()
        if len(daily_df) > 30:
            core._calc_macd(daily_df["close"].astype(float))
        core.find_buy_sell_points()

        logger.info(f"{code} {stock_name}: "
                     f"分型={len(core.fractals)} 笔={len(core.bis)} "
                     f"中枢={len(core.zhong_shus)} 买卖点={len(core.buy_sell_points)}")

        # 4. 生成日线信号模板
        is_pos = code in position_codes
        daily_signals = generate_daily_signals(code, stock_name, core, daily_df, analysis_date, is_position=is_pos)
        all_signals.extend(daily_signals)

        # 5. 持仓 → 15分钟背驰段检查
        if code in position_codes:
            min15_df = load_kline_data(code, days=60, scale=15)
            if min15_df is not None and len(min15_df) >= 60:
                core_15 = ChanlunCore()
                core_15.process_klines(min15_df[["open", "high", "low", "close"]])
                core_15.find_fractals()
                core_15.find_bis()
                core_15.find_zhong_shus()
                if len(min15_df) > 30:
                    core_15._calc_macd(min15_df["close"].astype(float))

                in_zone, zs_high, zs_low, prev_area = check_divergence_zone(core_15)

                div_signal = DivergenceZoneSignal(
                    stock_code=code,
                    stock_name=stock_name,
                    div_status=DivergenceStatus.IN_ZONE if in_zone else DivergenceStatus.NOT_IN_ZONE,
                    zhongshu_high=zs_high,
                    zhongshu_low=zs_low,
                    prev_exit_bi_macd_area=prev_area,
                )
                all_signals.append(div_signal)

                if in_zone:
                    logger.info(f"  ⚠ {stock_name} 15分钟在背驰段")

    # 6. 生成持仓风控信号
    for p in positions:
        code = p.get("股票代码", "")
        name = p.get("名称", code)
        cost = float(p.get("成本价", 0))
        shares = int(p.get("持有数量", 0))

        # 风控阈值：优先使用持仓文件中手动设置的止损价
        buy_reason = p.get("买入依据", {})
        manual_stop = buy_reason.get("止损价", 0) if isinstance(buy_reason, dict) else 0
        stop_loss = float(manual_stop) if manual_stop > 0 else (round(cost * 0.95, 2) if cost else 0)
        profit_30 = round(cost * 1.30, 2) if cost else 0
        alert_up = round(cost * 1.03, 2) if cost else 0
        alert_down = round(cost * 0.97, 2) if cost else 0

        risk_signal = PositionRiskSignal(
            stock_code=code,
            stock_name=name,
            cost_price=cost,
            position_shares=shares,
            position_value=cost * shares,
            stop_loss_price=stop_loss,
            profit_30pct_price=profit_30,
            alert_3pct_up=alert_up,
            alert_3pct_down=alert_down,
        )
        all_signals.append(risk_signal)

    # 7. 写入 DB（先清空旧数据）
    logger.info(f"生成信号模板 {len(all_signals)} 条，写入 DB")
    state_store.clear_signal_templates()
    state_store.save_signal_templates(all_signals)
    logger.info("=== 静态分析完成 ===")

    return all_signals


# ============================================================
# 独立入口
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    store = StateStore()
    run_static_analysis(store)
