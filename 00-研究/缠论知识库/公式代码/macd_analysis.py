# -*- coding: utf-8 -*-
"""
MACD辅助分析与背驰判断模块

包含：
1. MACD指标计算（DIF/DEA/MACD柱）
2. A/B/C三段划分与面积比较
3. 趋势背驰判断（两中枢后）
4. 盘整背驰判断（一中枢后）
5. 多级别背驰联立判断
6. MACD 0轴多空判断与防狼术

参考章节：第15、24、25、37、103课
"""

import numpy as np
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, field
from enum import Enum


# ==================== 枚举和数据结构 ====================

class BeichiType(Enum):
    """背驰类型"""
    TREND_BEICHI = "trend_beichi"          # 趋势背驰
    PANZHENG_BEICHI = "panzheng_beichi"    # 盘整背驰
    NO_BEICHI = "no_beichi"                # 无背驰


class MacdZone(Enum):
    """MACD 0轴位置"""
    ABOVE_ZERO = "above"      # 0轴之上（多头）
    BELOW_ZERO = "below"      # 0轴之下（空头）
    CROSSING = "crossing"     # 穿越中


@dataclass
class MacdData:
    """MACD计算数据"""
    dif: List[float]        # DIF快线
    dea: List[float]        # DEA慢线
    macd: List[float]       # MACD柱（值）
    macd_abs: List[float]   # MACD柱绝对值
    is_red: List[bool]      # 是否红柱（正值）

    @property
    def latest_dif(self) -> float:
        return self.dif[-1] if self.dif else 0.0

    @property
    def latest_dea(self) -> float:
        return self.dea[-1] if self.dea else 0.0

    @property
    def latest_macd(self) -> float:
        return self.macd[-1] if self.macd else 0.0

    @property
    def latest_zone(self) -> MacdZone:
        dif_val = self.latest_dif
        if dif_val > 0:
            return MacdZone.ABOVE_ZERO
        elif dif_val < 0:
            return MacdZone.BELOW_ZERO
        return MacdZone.CROSSING


@dataclass
class BeichiResult:
    """背驰分析结果"""
    beichi_type: BeichiType
    confidence: float         # 置信度 0~1
    segment_a_area: float = 0.0   # A段MACD面积
    segment_b_area: float = 0.0   # B段MACD面积（中枢）
    segment_c_area: float = 0.0   # C段MACD面积
    area_ratio: float = 0.0       # C面积/A面积
    description: str = ""
    level: str = ""


@dataclass
class SegmentForMacd:
    """用于背驰分析的走势段"""
    start: int
    end: int
    high: float
    low: float
    direction: str  # "up" / "down"


# ==================== MACD计算 ====================

def compute_macd(
    close_prices: List[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9
) -> MacdData:
    """
    计算MACD指标（第24课）

    计算公式：
        DIF = EMA(close, fast) - EMA(close, slow)
        DEA = EMA(DIF, signal)
        MACD柱 = 2 * (DIF - DEA)

    参数：
        close_prices: 收盘价列表
        fast: 快线周期（默认12）
        slow: 慢线周期（默认26）
        signal: 信号线周期（默认9）

    返回：
        MacdData 对象
    """
    prices = np.array(close_prices, dtype=np.float64)
    n = len(prices)

    if n < slow:
        return MacdData(dif=[], dea=[], macd=[], macd_abs=[], is_red=[])

    # 计算EMA
    def ema(data: np.ndarray, period: int) -> np.ndarray:
        result = np.zeros_like(data)
        result[0] = data[0]
        alpha = 2.0 / (period + 1)
        for i in range(1, len(data)):
            result[i] = alpha * data[i] + (1 - alpha) * result[i - 1]
        return result

    ema_fast = ema(prices, fast)
    ema_slow = ema(prices, slow)

    # DIF
    dif = ema_fast - ema_slow

    # DEA
    dea = ema(dif, signal)

    # MACD柱
    macd = 2.0 * (dif - dea)

    macd_abs = np.abs(macd)
    is_red = macd > 0

    return MacdData(
        dif=dif.tolist(),
        dea=dea.tolist(),
        macd=macd.tolist(),
        macd_abs=macd_abs.tolist(),
        is_red=is_red.tolist(),
    )


# ==================== A/B/C段划分与面积计算 ====================

def compute_segment_macd_area(
    segment: SegmentForMacd,
    macd_data: MacdData
) -> float:
    """
    计算某走势段的MACD柱子面积（第24课）

    面积 = 对应时间段内MACD柱子绝对值之和
    向上趋势看红柱子，向下趋势看绿柱子

    参数：
        segment: 走势段
        macd_data: MACD数据

    返回：
        MACD柱子面积
    """
    start = max(0, segment.start)
    end = min(len(macd_data.macd), segment.end + 1)

    if start >= end:
        return 0.0

    if segment.direction == "up":
        # 上涨段：红柱子面积
        values = [
            max(0, macd_data.macd[i])
            for i in range(start, end)
        ]
    else:
        # 下跌段：绿柱子面积（取绝对值）
        values = [
            abs(min(0, macd_data.macd[i]))
            for i in range(start, end)
        ]

    return sum(values)


def compute_segment_dif_height(
    segment: SegmentForMacd,
    macd_data: MacdData
) -> float:
    """
    计算走势段的DIF黄白线高度

    用于辅助判断背驰（黄白线不创新高/低也是背驰信号）
    """
    start = max(0, segment.start)
    end = min(len(macd_data.dif), segment.end + 1)

    if start >= end:
        return 0.0

    if segment.direction == "up":
        return max(macd_data.dif[start:end])
    else:
        return min(macd_data.dif[start:end])


def get_zhongshu_macd_state(
    macd_data: MacdData,
    zhongshu_start: int,
    zhongshu_end: int
) -> Dict:
    """
    获取中枢区域的MACD状态（第25课）

    标准两个中枢上涨的MACD形态：
    1. 第一段上涨：MACD黄白线从0轴下上穿，形成第一中枢
    2. 突破第一中枢：MACD快速拉起，最有力的一段
    3. 形成第二中枢：MACD黄白线回拉0轴附近
    4. 突破第二中枢：MACD黄白线/柱子不创新高 → 背驰

    返回：
        {"dif_peak": 黄白线峰值, "dif_trough": 黄白线谷值,
         "dif_pullback_to_zero": 是否回拉0轴, ...}
    """
    if not macd_data.dif:
        return {}

    start = max(0, zhongshu_start)
    end = min(len(macd_data.dif), zhongshu_end + 1)

    if start >= end:
        return {}

    dif_segment = macd_data.dif[start:end]
    macd_segment = macd_data.macd[start:end]

    # 黄白线是否回拉到0轴附近
    dif_abs_min = min(abs(d) for d in dif_segment) if dif_segment else 999
    pullback_to_zero = dif_abs_min < 0.5 * max(abs(d) for d in dif_segment)

    return {
        "dif_peak": max(dif_segment) if dif_segment else 0,
        "dif_trough": min(dif_segment) if dif_segment else 0,
        "dif_pullback_to_zero": pullback_to_zero,
        "macd_peak": max(macd_segment) if macd_segment else 0,
        "macd_trough": min(macd_segment) if macd_segment else 0,
    }


# ==================== 趋势背驰判断 ====================

def check_trend_beichi(
    segment_a: SegmentForMacd,
    segment_b: SegmentForMacd,
    segment_c: SegmentForMacd,
    macd_data: MacdData
) -> BeichiResult:
    """
    判断趋势背驰（第24、37课）

    条件：
    1. 走势处于趋势中（至少两个同向中枢）
    2. A、B、C三段中，B的中枢级别比A、C里的中枢级别都要大
    3. B段的中枢会将MACD黄白线回拉到0轴附近
    4. C段的MACD柱子面积比A段小
    5. C段必须创新高（上涨）或创新低（下跌）

    参数：
        segment_a: A段（第一个中枢前的走势）
        segment_b: B段（中间的中枢区域）
        segment_c: C段（第二个中枢后的走势）
        macd_data: MACD数据

    返回：
        BeichiResult
    """
    if not macd_data.dif:
        return BeichiResult(
            beichi_type=BeichiType.NO_BEICHI,
            confidence=0,
            description="MACD数据为空",
        )

    # 检查方向一致性
    if not (segment_a.direction == segment_c.direction):
        return BeichiResult(
            beichi_type=BeichiType.NO_BEICHI,
            confidence=0,
            description="A段和C段方向不一致，不是标准趋势结构",
        )

    # 计算面积
    area_a = compute_segment_macd_area(segment_a, macd_data)
    area_b = compute_segment_macd_area(segment_b, macd_data)
    area_c = compute_segment_macd_area(segment_c, macd_data)

    if area_a == 0:
        return BeichiResult(
            beichi_type=BeichiType.NO_BEICHI,
            confidence=0,
            description="A段面积为0，无法比较",
        )

    # 面积比
    if segment_a.direction == "up":
        # 上涨趋势：红柱子面积
        area_ratio = area_c / area_a if area_a > 0 else 999
    else:
        # 下跌趋势：绿柱子面积
        area_ratio = area_c / area_a if area_a > 0 else 999

    # 检查黄白线回拉0轴
    b_state = get_zhongshu_macd_state(
        macd_data, segment_b.start, segment_b.end
    )
    pullback_to_zero = b_state.get("dif_pullback_to_zero", False)

    # 检查黄白线高度
    dif_height_c = compute_segment_dif_height(segment_c, macd_data)
    dif_height_a = compute_segment_dif_height(segment_a, macd_data)

    if segment_a.direction == "up":
        # 上涨趋势：C段黄白线高度应低于A段
        dif_confirm = dif_height_c < dif_height_a
    else:
        # 下跌趋势：C段黄白线深度应高于A段（更浅）
        dif_confirm = dif_height_c > dif_height_a

    # 判断是否背驰
    is_beichi = False
    confidence = 0.0
    description_parts = []

    if area_ratio < 0.9:
        is_beichi = True
        confidence = 0.6 + (1 - area_ratio) * 0.3
        description_parts.append(f"面积比 {area_ratio:.2f}（C < A 的90%）")
        if pullback_to_zero:
            confidence += 0.15
            description_parts.append("B段黄白线回拉0轴")
        if dif_confirm:
            confidence += 0.15
            description_parts.append("黄白线高度确认")
    elif area_ratio < 1.0:
        # 面积减小但幅度不大，疑似背驰
        confidence = 0.3
        description_parts.append(f"面积比 {area_ratio:.2f}（疑似盘整背驰）")
    else:
        # 没有背驰
        description_parts.append(f"面积比 {area_ratio:.2f}（C >= A，无背驰）")

    confidence = min(confidence, 1.0)

    direction_label = "上涨" if segment_a.direction == "up" else "下跌"

    return BeichiResult(
        beichi_type=BeichiType.TREND_BEICHI if is_beichi else BeichiType.NO_BEICHI,
        confidence=confidence,
        segment_a_area=area_a,
        segment_b_area=area_b,
        segment_c_area=area_c,
        area_ratio=area_ratio,
        description=(
            f"{direction_label}趋势背驰：{'是' if is_beichi else '否'} | "
            + ", ".join(description_parts)
        ),
    )


# ==================== 盘整背驰判断 ====================

def check_panzheng_beichi(
    segment_a: SegmentForMacd,
    segment_c: SegmentForMacd,
    zhongshu_zd: float,
    zhongshu_zg: float,
    macd_data: MacdData
) -> BeichiResult:
    """
    判断盘整背驰（第24课）

    条件：
    1. 走势处于盘整中（只有一个中枢）
    2. C段与A段比较MACD面积
    3. 如果C段不破中枢 → 盘整背驰必定回跌
    4. 如果C段上破中枢但MACD面积小 → 先出来，看回跌是否构成三买

    参数：
        segment_a: A段（中枢前的走势）
        segment_c: C段（中枢后的走势）
        zhongshu_zd: 中枢下沿
        zhongshu_zg: 中枢上沿
        macd_data: MACD数据
    """
    if not macd_data.dif:
        return BeichiResult(
            beichi_type=BeichiType.NO_BEICHI,
            confidence=0,
            description="MACD数据为空",
        )

    area_a = compute_segment_macd_area(segment_a, macd_data)
    area_c = compute_segment_macd_area(segment_c, macd_data)

    if area_a == 0:
        return BeichiResult(
            beichi_type=BeichiType.NO_BEICHI,
            confidence=0,
            description="A段面积为0",
        )

    area_ratio = area_c / area_a
    is_beichi = area_ratio < 0.9

    # C段是否突破中枢
    if segment_c.direction == "up":
        broke_zhongshu = segment_c.high > zhongshu_zg
    else:
        broke_zhongshu = segment_c.low < zhongshu_zd

    # 结果描述
    if is_beichi and not broke_zhongshu:
        desc = "盘整背驰（C段未破中枢），其后必定回跌"
        confidence = 0.75
    elif is_beichi and broke_zhongshu:
        desc = "盘整背驰（C段突破中枢），注意是否形成第三类买点"
        confidence = 0.55
    else:
        desc = f"非盘整背驰（面积比 {area_ratio:.2f}）"
        confidence = 0.0

    return BeichiResult(
        beichi_type=BeichiType.PANZHENG_BEICHI if is_beichi else BeichiType.NO_BEICHI,
        confidence=confidence,
        segment_a_area=area_a,
        segment_c_area=area_c,
        area_ratio=area_ratio,
        description=desc,
    )


# ==================== 多级别背驰联立判断 ====================

def analyze_beichi_multi_level(
    macd_by_level: Dict[str, MacdData],
    segments_by_level: Dict[str, Tuple[SegmentForMacd, SegmentForMacd, SegmentForMacd]]
) -> Dict:
    """
    多级别背驰联立分析（第25课）

    背驰的回跌力度和级别很有关系：
    - 日线上涨中途，5分钟背驰下跌力度有限
    - 日线最后阶段，1分钟背驰足以引发暴跌

    参数：
        macd_by_level: {"1分钟": MacdData, "5分钟": MacdData, ...}
        segments_by_level: {"1分钟": (A, B, C), ...}

    返回：
        {"results": {级别: BeichiResult},
         "multi_level_confirm": bool,
         "dominant_level": str,
         "suggestion": str}
    """
    results = {}
    confirmed_levels = []

    for level_name in ["1分钟", "5分钟", "30分钟", "日线"]:
        if level_name not in macd_by_level or level_name not in segments_by_level:
            continue

        macd = macd_by_level[level_name]
        a, b, c = segments_by_level[level_name]

        result = check_trend_beichi(a, b, c, macd)
        results[level_name] = result

        if result.beichi_type == BeichiType.TREND_BEICHI and result.confidence > 0.6:
            confirmed_levels.append((level_name, result.confidence))

    # 判断主导级别
    dominant_level = "无"
    suggestion = ""

    if confirmed_levels:
        # 按置信度排序
        confirmed_levels.sort(key=lambda x: x[1], reverse=True)

        highest_level = confirmed_levels[0][0]
        dominant_level = highest_level

        # 多级别同时背驰 = 强烈信号
        if len(confirmed_levels) >= 2:
            suggestion = (
                f"多级别共振背驰！{', '.join(l for l, _ in confirmed_levels)} "
                f"同时出现背驰信号，转折力度将很大"
            )
        elif highest_level == "日线":
            suggestion = "日线级别背驰，趋势可能已经到头，需高度重视"
        elif highest_level == "30分钟":
            suggestion = "30分钟级别背驰，可能引发日线级别的调整"
        elif highest_level == "5分钟":
            suggestion = "5分钟级别背驰，适合做短差"
        else:
            suggestion = "1分钟级别背驰，小级别波动"

    return {
        "results": results,
        "multi_level_confirm": len(confirmed_levels) >= 2,
        "dominant_level": dominant_level,
        "suggestion": suggestion,
    }


# ==================== 0轴多空判断与防狼术 ====================

def check_macd_zone(macd_data: MacdData) -> MacdZone:
    """
    MACD 0轴多空判断（第103课）

    一旦MACD指标陷入0轴之下，就在对应时间单位的图表下进入空头主导。
    这是最基本的防狼术：回避所有MACD黄白线在0轴下面的市场或股票。
    """
    if not macd_data.dif:
        return MacdZone.CROSSING

    latest = macd_data.dif[-1]
    if latest > 0:
        return MacdZone.ABOVE_ZERO
    elif latest < 0:
        return MacdZone.BELOW_ZERO
    return MacdZone.CROSSING


def is_wolf_protection_needed(
    macd_data_30min: Optional[MacdData] = None,
    macd_data_60min: Optional[MacdData] = None
) -> Dict:
    """
    防狼术检查（第103课）

    原则：根据自己的能力决定一个最低时间周期，
    一旦该周期MACD在0轴以下，就彻底离开这个市场
    直到重新站住0轴再说。

    返回：
        {"safe": bool, "reason": str, "zones": {周期: 位置}}
    """
    zones = {}

    if macd_data_60min:
        zones["60分钟"] = check_macd_zone(macd_data_60min).value
    if macd_data_30min:
        zones["30分钟"] = check_macd_zone(macd_data_30min).value

    # 判断是否安全
    for period, zone in zones.items():
        if zone == "below":
            return {
                "safe": False,
                "reason": f"{period}周期MACD在0轴下方，建议空仓观望",
                "zones": zones,
            }

    return {
        "safe": True,
        "reason": "MACD在0轴上方运行，多头主导",
        "zones": zones,
    }


# ==================== 综合分析 ====================

def full_macd_analysis(
    close_prices: List[float],
    segments_abc: Optional[Tuple[SegmentForMacd, SegmentForMacd, SegmentForMacd]] = None,
    zhongshu_info: Optional[Dict] = None
) -> Dict:
    """
    MACD完整分析流程

    1. 计算MACD
    2. 划分A/B/C段
    3. 观察黄白线回拉0轴
    4. 比较柱子面积
    5. 判断背驰
    6. 结合级别

    返回：
        {"macd": MacdData,
         "trend_beichi": BeichiResult,
         "panzheng_beichi": BeichiResult,
         "zone": MacdZone,
         "summary": str}
    """
    macd_data = compute_macd(close_prices)

    if not macd_data.dif:
        return {"macd": macd_data, "summary": "MACD计算失败"}

    result = {
        "macd": macd_data,
        "zone": check_macd_zone(macd_data).value,
    }

    # 趋势背驰分析
    if segments_abc:
        a, b, c = segments_abc
        trend_result = check_trend_beichi(a, b, c, macd_data)
        result["trend_beichi"] = trend_result

        # 盘整背驰分析
        if zhongshu_info:
            panzheng_result = check_panzheng_beichi(
                a, c,
                zhongshu_info.get("zd", 0),
                zhongshu_info.get("zg", 0),
                macd_data,
            )
            result["panzheng_beichi"] = panzheng_result

    # 生成摘要
    zone_label = {
        "above": "多头(0轴上)",
        "below": "空头(0轴下)",
        "crossing": "穿越中",
    }.get(result.get("zone", ""), "未知")

    summary_parts = [f"MACD状态: {zone_label}"]

    if "trend_beichi" in result:
        tb = result["trend_beichi"]
        summary_parts.append(
            f"趋势背驰: {'是' if tb.beichi_type == BeichiType.TREND_BEICHI else '否'}"
            f"(置信度 {tb.confidence:.0%})"
        )

    if "panzheng_beichi" in result:
        pb = result["panzheng_beichi"]
        summary_parts.append(
            f"盘整背驰: {'是' if pb.beichi_type == BeichiType.PANZHENG_BEICHI else '否'}"
        )

    result["summary"] = " | ".join(summary_parts)

    return result


if __name__ == "__main__":
    print("MACD辅助分析模块加载成功")
    print(f"支持的背驰类型: {[b.value for b in BeichiType]}")
