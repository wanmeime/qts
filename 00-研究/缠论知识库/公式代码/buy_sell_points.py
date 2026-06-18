# -*- coding: utf-8 -*-
"""
买卖点识别算法模块

包含：
1. 第一类买卖点识别（趋势背驰转折点）
2. 第二类买卖点识别（第一次次级别回调/反弹确认）
3. 第三类买卖点识别（次级别离开中枢后回试不破）
4. 类二买识别（中枢突破后回踩）
5. 多级别买卖点联立分析

参考章节：第12、14、17、20、21、53课
"""

import numpy as np
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, field
from enum import Enum


# ==================== 枚举和数据结构 ====================

class PointType(Enum):
    """买卖点类型"""
    FIRST_BUY = "first_buy"        # 第一类买点
    SECOND_BUY = "second_buy"      # 第二类买点
    THIRD_BUY = "third_buy"        # 第三类买点
    SECONDARY_BUY = "secondary_buy"  # 类二买
    FIRST_SELL = "first_sell"      # 第一类卖点
    SECOND_SELL = "second_sell"    # 第二类卖点
    THIRD_SELL = "third_sell"      # 第三类卖点


@dataclass
class TradePoint:
    """买卖点数据结构"""
    point_type: PointType
    price: float           # 买卖点价格
    index: int             # 在数据序列中的位置
    confidence: float      # 置信度 0~1
    level: str = ""        # 级别描述，如 "30分钟"
    description: str = ""  # 补充描述
    macd_confirm: bool = False     # MACD是否确认
    volume_confirm: bool = False   # 成交量是否确认
    related_zhongshu: Optional[Dict] = None  # 相关中枢信息

    @property
    def is_buy(self) -> bool:
        return self.point_type in [
            PointType.FIRST_BUY, PointType.SECOND_BUY,
            PointType.THIRD_BUY, PointType.SECONDARY_BUY
        ]

    @property
    def is_sell(self) -> bool:
        return self.point_type in [
            PointType.FIRST_SELL, PointType.SECOND_SELL,
            PointType.THIRD_SELL
        ]


@dataclass
class Segment:
    """走势段（用于背驰比较的A/B/C段）"""
    direction: str        # "up" / "down"
    start_index: int
    end_index: int
    high: float
    low: float
    macd_area: float = 0.0    # MACD柱子面积
    macd_high: float = 0.0    # MACD黄白线高度
    volume_sum: float = 0.0   # 成交量总和


# ==================== 第一类买卖点 ====================

def find_first_buy_point(
    segments: List[Segment],
    macd_data: Optional[Dict] = None
) -> Optional[TradePoint]:
    """
    识别第一类买点（第12、14、24课）

    条件：
    1. 走势处于下跌趋势中（至少两个同向中枢）
    2. 最后一个中枢之后出现趋势背驰
    3. MACD：C段绿柱子面积 < A段绿柱子面积
    4. 价格创出新低

    参数：
        segments: 走势段列表
        macd_data: MACD辅助数据 {"areas": [A_area, C_area], "黄白线高度": ...}

    返回：
        TradePoint 或 None
    """
    if len(segments) < 3:
        return None

    # 找最后三段的背驰比较
    # 下降趋势中：A段(下跌) + B段(中枢/反弹) + C段(下跌背驰段)
    last_three = segments[-3:]

    # 检查方向：C段必须是下跌段
    if last_three[2].direction != "down":
        return None

    # A段和C段是下跌段，B段是反弹段（中枢位置）
    if last_three[0].direction != "down" or last_three[1].direction != "up":
        return None

    # 判断背驰：C段力度小于A段
    beichi_detected = False

    if macd_data and "areas" in macd_data:
        # MACD面积比较
        c_area = abs(macd_data["areas"][-1])
        a_area = abs(macd_data["areas"][0])
        if c_area < a_area * 0.9:  # C段面积 < A段面积的90%
            beichi_detected = True
    else:
        # 没有MACD数据时，用价格速度判断
        a_speed = (last_three[0].high - last_three[0].low) / (
            last_three[0].end_index - last_three[0].start_index + 1
        ) if last_three[0].end_index != last_three[0].start_index else 0
        c_speed = (last_three[2].high - last_three[2].low) / (
            last_three[2].end_index - last_three[2].start_index + 1
        ) if last_three[2].end_index != last_three[2].start_index else 0
        if c_speed < a_speed * 0.85:
            beichi_detected = True

    if not beichi_detected:
        return None

    # 确认C段创新低
    c_low = last_three[2].low
    a_low = last_three[0].low
    if c_low >= a_low:
        return None  # C段没创新低，不是标准趋势背驰

    # 计算置信度
    confidence = 0.7
    if macd_data:
        confidence += 0.15
        if macd_data.get("黄白线回拉0轴", False):
            confidence += 0.15
    confidence = min(confidence, 1.0)

    return TradePoint(
        point_type=PointType.FIRST_BUY,
        price=c_low,
        index=last_three[2].end_index,
        confidence=confidence,
        description=(
            "下跌趋势背驰形成的第一类买点"
            if beichi_detected
            else "疑似第一类买点，需进一步确认"
        ),
        macd_confirm=bool(macd_data and "areas" in macd_data),
    )


def find_first_sell_point(
    segments: List[Segment],
    macd_data: Optional[Dict] = None
) -> Optional[TradePoint]:
    """
    识别第一类卖点（第12、14、24课）

    与第一类买点对称：上涨趋势背驰后的转折点
    """
    if len(segments) < 3:
        return None

    last_three = segments[-3:]

    # C段必须是上涨段
    if last_three[2].direction != "up":
        return None

    # A段和C段是上涨段，B段是回调段（中枢位置）
    if last_three[0].direction != "up" or last_three[1].direction != "down":
        return None

    # 判断背驰
    beichi_detected = False
    if macd_data and "areas" in macd_data:
        c_area = abs(macd_data["areas"][-1])
        a_area = abs(macd_data["areas"][0])
        if c_area < a_area * 0.9:
            beichi_detected = True
    else:
        a_speed = (last_three[0].high - last_three[0].low) / (
            last_three[0].end_index - last_three[0].start_index + 1
        ) if last_three[0].end_index != last_three[0].start_index else 0
        c_speed = (last_three[2].high - last_three[2].low) / (
            last_three[2].end_index - last_three[2].start_index + 1
        ) if last_three[2].end_index != last_three[2].start_index else 0
        if c_speed < a_speed * 0.85:
            beichi_detected = True

    if not beichi_detected:
        return None

    # 确认C段创新高
    c_high = last_three[2].high
    a_high = last_three[0].high
    if c_high <= a_high:
        return None

    confidence = 0.7
    if macd_data:
        confidence += 0.15
        if macd_data.get("黄白线回拉0轴", False):
            confidence += 0.15
    confidence = min(confidence, 1.0)

    return TradePoint(
        point_type=PointType.FIRST_SELL,
        price=c_high,
        index=last_three[2].end_index,
        confidence=confidence,
        description="上涨趋势背驰形成的第一类卖点",
        macd_confirm=bool(macd_data and "areas" in macd_data),
    )


# ==================== 第二类买卖点 ====================

def find_second_buy_point(
    segments: List[Segment],
    first_buy: TradePoint,
    macd_data: Optional[Dict] = None
) -> Optional[TradePoint]:
    """
    识别第二类买点（第12、14、17课）

    条件：
    1. 已经出现第一类买点
    2. 从第一类买点开始的上涨结束后，出现第一次回调
    3. 回调的低点不破第一类买点

    定理：大级别的第二类买点由次一级别相应走势的第一类买点构成
    """
    if not first_buy or len(segments) < 2:
        return None

    # 找到第一类买点后的走势段
    post_buy_segments = [
        s for s in segments if s.start_index >= first_buy.index
    ]

    if len(post_buy_segments) < 2:
        return None

    # 第一段必须是上涨（从第一类买点开始的反弹）
    if post_buy_segments[0].direction != "up":
        return None

    # 第二段是第一段后的回调
    if post_buy_segments[1].direction != "down":
        return None

    # 回调低点不低于第一类买点
    second_buy_low = post_buy_segments[1].low
    if second_buy_low < first_buy.price:
        return None  # 跌破了，可能是下跌延续

    # 检查是否与第三类买点重合
    # 第二类买点与第三类买点重合的条件：
    # 第一段上涨直接突破最后一个中枢的上沿(ZG)，回调不跌破该中枢
    is_overlap_with_third = False

    # 计算置信度
    confidence = 0.65
    if second_buy_low > first_buy.price * 1.02:
        confidence += 0.1  # 回调幅度小，说明强势
    if macd_data:
        confidence += 0.1
    confidence = min(confidence, 1.0)

    point = TradePoint(
        point_type=PointType.SECOND_BUY,
        price=second_buy_low,
        index=post_buy_segments[1].end_index,
        confidence=confidence,
        description=(
            "第二类买点（与第三类买点重合）"
            if is_overlap_with_third
            else "第二类买点"
        ),
        macd_confirm=bool(macd_data),
    )

    return point


def find_second_sell_point(
    segments: List[Segment],
    first_sell: TradePoint,
    macd_data: Optional[Dict] = None
) -> Optional[TradePoint]:
    """
    识别第二类卖点

    与第二类买点对称：第一类卖点后的第一次反弹高点
    """
    if not first_sell or len(segments) < 2:
        return None

    post_sell_segments = [
        s for s in segments if s.start_index >= first_sell.index
    ]

    if len(post_sell_segments) < 2:
        return None

    if post_sell_segments[0].direction != "down":
        return None
    if post_sell_segments[1].direction != "up":
        return None

    second_sell_high = post_sell_segments[1].high
    if second_sell_high > first_sell.price:
        return None  # 突破了，可能不是第二类卖点

    confidence = 0.65
    if macd_data:
        confidence += 0.1
    confidence = min(confidence, 1.0)

    return TradePoint(
        point_type=PointType.SECOND_SELL,
        price=second_sell_high,
        index=post_sell_segments[1].end_index,
        confidence=confidence,
        description="第二类卖点",
        macd_confirm=bool(macd_data),
    )


# ==================== 第三类买卖点 ====================

def find_third_buy_point(
    segments: List[Segment],
    zhongshu: Dict,
    macd_data: Optional[Dict] = None
) -> Optional[TradePoint]:
    """
    识别第三类买点（第20、53课）

    条件：
    1. 存在一个明确的中枢 [ZD, ZG]
    2. 一个次级别走势向上离开中枢
    3. 回试的次级别走势低点不跌破 ZG（中枢上沿）
    4. 必须是第一次回试

    特殊情况（第37课补充）：
    - 次级别趋势离开时，第二个次级别中枢不触及原中枢的，可看成3买
    - 条件：下上下中后下低于前下，或上下上中后上高于前上

    参数：
        segments: 走势段列表
        zhongshu: 中枢信息 {"zg": 上沿, "zd": 下沿, ...}
        macd_data: MACD辅助数据

    返回：
        TradePoint 或 None
    """
    if not zhongshu or len(segments) < 2:
        return None

    zg = zhongshu.get("zg", 0)  # 中枢上沿
    zd = zhongshu.get("zd", 0)  # 中枢下沿

    if zg == 0 or zd == 0:
        return None

    # 找中枢后的走势段
    zs_end = zhongshu.get("end_index", 0)
    post_zs_segments = [
        s for s in segments if s.start_index >= zs_end
    ]

    if len(post_zs_segments) < 2:
        return None

    # 第一段：向上离开中枢
    leave_seg = post_zs_segments[0]
    if leave_seg.direction != "up":
        return None

    # 离开段必须突破中枢上沿
    if leave_seg.high <= zg:
        return None

    # 第二段：向下回试
    test_seg = post_zs_segments[1]
    if test_seg.direction != "down":
        return None

    # 回试低点不能跌破中枢上沿 ZG
    test_low = test_seg.low
    if test_low < zg:
        return None

    # 计算置信度
    confidence = 0.6
    # 离开力度越强，置信度越高
    leave_strength = (leave_seg.high - zg) / (zg - zd + 0.001)
    if leave_strength > 1.0:
        confidence += 0.1
    if leave_strength > 2.0:
        confidence += 0.1
    # 回试越浅，置信度越高
    pullback_ratio = (leave_seg.high - test_low) / (leave_seg.high - zg + 0.001)
    if pullback_ratio < 0.5:
        confidence += 0.1
    if macd_data:
        confidence += 0.1
    confidence = min(confidence, 1.0)

    return TradePoint(
        point_type=PointType.THIRD_BUY,
        price=test_low,
        index=test_seg.end_index,
        confidence=confidence,
        description=f"第三类买点（离开力度{leave_strength:.1f}，回撤比{pullback_ratio:.1f}）",
        macd_confirm=bool(macd_data),
        related_zhongshu=zhongshu,
    )


def find_third_sell_point(
    segments: List[Segment],
    zhongshu: Dict,
    macd_data: Optional[Dict] = None
) -> Optional[TradePoint]:
    """
    识别第三类卖点（第20、53课）

    与第三类买点对称：次级别向下离开中枢后，回抽不升破ZD
    """
    if not zhongshu or len(segments) < 2:
        return None

    zg = zhongshu.get("zg", 0)
    zd = zhongshu.get("zd", 0)

    zs_end = zhongshu.get("end_index", 0)
    post_zs_segments = [
        s for s in segments if s.start_index >= zs_end
    ]

    if len(post_zs_segments) < 2:
        return None

    # 第一段：向下离开中枢
    leave_seg = post_zs_segments[0]
    if leave_seg.direction != "down":
        return None

    if leave_seg.low >= zd:
        return None

    # 第二段：向上回抽
    test_seg = post_zs_segments[1]
    if test_seg.direction != "up":
        return None

    # 回抽高点不能升破中枢下沿 ZD
    test_high = test_seg.high
    if test_high > zd:
        return None

    confidence = 0.6
    leave_strength = (zd - leave_seg.low) / (zg - zd + 0.001)
    if leave_strength > 1.0:
        confidence += 0.1
    if macd_data:
        confidence += 0.1
    confidence = min(confidence, 1.0)

    return TradePoint(
        point_type=PointType.THIRD_SELL,
        price=test_high,
        index=test_seg.end_index,
        confidence=confidence,
        description=f"第三类卖点（离开力度{leave_strength:.1f}）",
        macd_confirm=bool(macd_data),
        related_zhongshu=zhongshu,
    )


# ==================== 类二买 ====================

def find_secondary_buy(
    segments: List[Segment],
    zhongshus: List[Dict],
    macd_data: Optional[Dict] = None
) -> Optional[TradePoint]:
    """
    识别类二买

    条件：
    1. 上涨趋势中的第一个上涨中枢横盘突破后形成
    2. 中枢方向向上
    3. 中枢后的走势向上突破中枢

    操作意义：
    - 类二买是第二类买点的变体
    - 出现在中枢突破后，可视为追涨信号
    - 强度通常不如标准第二类买点
    """
    if len(zhongshus) < 1 or len(segments) < 2:
        return None

    # 找最后一个向上中枢
    up_zhongshus = [zs for zs in zhongshus if zs.get("direction") == "up"]
    if not up_zhongshus:
        return None

    last_zs = up_zhongshus[-1]
    zg = last_zs.get("zg", 0)

    zs_end = last_zs.get("end_index", 0)
    post_zs_segments = [
        s for s in segments if s.start_index >= zs_end
    ]

    if not post_zs_segments:
        return None

    # 第一段向上突破中枢
    first_post = post_zs_segments[0]
    if first_post.direction != "up" or first_post.high <= zg:
        return None

    # 如果有第二段回调不破ZG，更加确认
    if len(post_zs_segments) >= 2:
        second_post = post_zs_segments[1]
        if second_post.direction == "down" and second_post.low > zg:
            return TradePoint(
                point_type=PointType.SECONDARY_BUY,
                price=second_post.low,
                index=second_post.end_index,
                confidence=0.7 if macd_data else 0.55,
                description="类二买（突破中枢后回踩确认）",
                macd_confirm=bool(macd_data),
            )

    # 只有突破没有回踩，也算类二买但置信度低
    return TradePoint(
        point_type=PointType.SECONDARY_BUY,
        price=first_post.high,
        index=first_post.end_index,
        confidence=0.4,
        description="类二买（突破中枢，尚未回踩确认）",
        macd_confirm=False,
    )


# ==================== 多级别联立分析 ====================

def analyze_multi_level(
    points_by_level: Dict[str, List[TradePoint]]
) -> Dict:
    """
    多级别买卖点联立分析

    参数：
        points_by_level: {"1分钟": [...], "5分钟": [...], "30分钟": [...]}

    返回：
        {
            "共振": [(级别1, 级别2, 买卖点类型, 价格范围), ...],
            "区间套": {...},
            "建议": "..."
        }
    """
    result = {
        "共振": [],
        "区间套": {},
        "建议": "",
    }

    levels = ["1分钟", "5分钟", "30分钟", "日线", "周线"]
    available_levels = [l for l in levels if l in points_by_level]

    # 寻找多级别共振
    for i in range(len(available_levels)):
        for j in range(i + 1, len(available_levels)):
            l1 = available_levels[i]
            l2 = available_levels[j]

            for p1 in points_by_level.get(l1, []):
                for p2 in points_by_level.get(l2, []):
                    # 同向买卖点且价格范围接近
                    if p1.is_buy == p2.is_buy:
                        price_overlap = abs(p1.price - p2.price) / max(
                            p1.price, p2.price, 0.01
                        )
                        if price_overlap < 0.03:  # 价格差距3%以内
                            result["共振"].append({
                                "级别1": l1,
                                "级别2": l2,
                                "类型": p1.point_type.value,
                                "价格区间": f"{min(p1.price, p2.price):.2f} - "
                                           f"{max(p1.price, p2.price):.2f}",
                                "置信度": (p1.confidence + p2.confidence) / 2,
                            })

    # 寻找区间套
    for buy_type in [PointType.FIRST_BUY, PointType.SECOND_BUY, PointType.THIRD_BUY]:
        buy_points_at_level = {}
        for level in available_levels:
            pts = [
                p for p in points_by_level.get(level, [])
                if p.point_type == buy_type
            ]
            if pts:
                buy_points_at_level[level] = min(pts, key=lambda p: p.price)

        if len(buy_points_at_level) >= 2:
            result["区间套"][buy_type.value] = {
                level: p.price for level, p in buy_points_at_level.items()
            }

    # 生成建议
    resonance_count = len(result["共振"])
    if resonance_count >= 2:
        result["建议"] = f"发现{resonance_count}组多级别共振信号，操作可靠性较高"
    elif resonance_count == 1:
        result["建议"] = "发现1组共振信号，可结合其他指标确认"
    else:
        result["建议"] = "未发现明显多级别共振"

    return result


# ==================== 综合分析 ====================

def find_all_points(
    segments: List[Segment],
    zhongshus: List[Dict],
    macd_data: Optional[Dict] = None
) -> List[TradePoint]:
    """
    综合识别所有买卖点

    参数：
        segments: 走势段列表（A/B/C段结构）
        zhongshus: 中枢列表
        macd_data: MACD辅助数据

    返回：
        所有识别到的买卖点列表
    """
    points = []

    # 第一类买卖点
    first_buy = find_first_buy_point(segments, macd_data)
    if first_buy:
        points.append(first_buy)

    first_sell = find_first_sell_point(segments, macd_data)
    if first_sell:
        points.append(first_sell)

    # 第二类买卖点（基于第一类）
    if first_buy:
        second_buy = find_second_buy_point(segments, first_buy, macd_data)
        if second_buy:
            points.append(second_buy)

    if first_sell:
        second_sell = find_second_sell_point(segments, first_sell, macd_data)
        if second_sell:
            points.append(second_sell)

    # 第三类买卖点（基于每个中枢）
    for zs in zhongshus:
        third_buy = find_third_buy_point(segments, zs, macd_data)
        if third_buy:
            points.append(third_buy)

        third_sell = find_third_sell_point(segments, zs, macd_data)
        if third_sell:
            points.append(third_sell)

    # 类二买
    secondary_buy = find_secondary_buy(segments, zhongshus, macd_data)
    if secondary_buy:
        points.append(secondary_buy)

    # 按位置排序
    points.sort(key=lambda p: p.index)

    return points


def summarize_points(points: List[TradePoint]) -> str:
    """生成买卖点汇总文本"""
    if not points:
        return "未识别到买卖点"

    lines = ["=== 买卖点汇总 ==="]
    for p in points:
        lines.append(
            f"  [{p.point_type.value}] 价格:{p.price:.2f} "
            f"位置:{p.index} 置信度:{p.confidence:.0%}"
        )
        if p.description:
            lines.append(f"    → {p.description}")
    return "\n".join(lines)


if __name__ == "__main__":
    # 示例用法
    print("买卖点识别模块加载成功")
    print("支持的买卖点类型:")
    for pt in PointType:
        print(f"  - {pt.value}")
