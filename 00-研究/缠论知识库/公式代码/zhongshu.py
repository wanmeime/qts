# -*- coding: utf-8 -*-
"""
中枢识别与级别判断模块

包含：
1. 中枢定义与识别（三段次级别走势重叠）
2. ZG/ZD/GG/DD 计算
3. 中枢延伸检测
4. 中枢扩张与升级判断
5. 中枢级别递归判定
6. 中枢破坏检测（第三类买卖点）

参考章节：第17、18、20、35课
"""

import numpy as np
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, field
from enum import Enum


# ==================== 枚举和数据结构 ====================

class ZhongShuState(Enum):
    """中枢状态"""
    FORMING = "forming"       # 形成中（1-2段）
    FORMED = "formed"         # 已形成（3段完成）
    EXTENDING = "extending"   # 延伸中
    EXPANDING = "expanding"   # 扩张中
    DESTROYED = "destroyed"   # 被破坏
    UPGRADED = "upgraded"     # 已升级


@dataclass
class ZhongShu:
    """中枢数据结构"""
    start_index: int           # 起始位置（第一段起点）
    end_index: int             # 结束位置（第三段终点，或延伸后的终点）
    zg: float                  # 中枢上沿 = min(所有高点)
    zd: float                  # 中枢下沿 = max(所有低点)
    gg: float                  # 所有高点的最大值
    dd: float                  # 所有低点的最小值
    direction: str = ""        # "up"(回升形成) / "down"(回调形成)
    level: int = 0             # 级别(1=1分钟, 2=5分钟, 3=30分钟, 4=日线...)
    state: ZhongShuState = ZhongShuState.FORMED
    segments_count: int = 3    # 组成中枢的段数
    extend_count: int = 0      # 延伸段数
    wave_ranges: List[Tuple[float, float]] = field(default_factory=list)  # 各波动区间

    @property
    def width(self) -> float:
        """中枢宽度"""
        return self.zg - self.zd

    @property
    def is_valid(self) -> bool:
        """中枢是否有效"""
        return self.zg > self.zd

    @property
    def midpoint(self) -> float:
        """中枢中轴"""
        return (self.zg + self.zd) / 2


@dataclass
class SegmentForZS:
    """用于中枢识别的走势段"""
    start_index: int
    end_index: int
    high: float
    low: float
    direction: str  # "up" / "down"


# ==================== 核心识别函数 ====================

def identify_zhongshu(
    segments: List[SegmentForZS],
    min_overlap_ratio: float = 0.0
) -> Optional[ZhongShu]:
    """
    从走势段列表中识别第一个有效中枢（第17、18课）

    定义：被至少三个连续次级别走势类型所重叠的部分

    数学表达（第18课）：
        次级别的连续三个走势类型A、B、C
        A的高点低点 = (a1, a2)
        B的高点低点 = (b1, b2)
        C的高点低点 = (c1, c2)
        中枢区间 = [max(a2,b2,c2), min(a1,b1,c1)]

    简化公式（回升形成）：
        中枢 = [max(a2, c2), min(a1, c1)]

    参数：
        segments: 走势段列表（至少3段）
        min_overlap_ratio: 最小重叠比例要求

    返回：
        ZhongShu 或 None
    """
    if len(segments) < 3:
        return None

    # 遍历所有连续三段组合
    for i in range(len(segments) - 2):
        s1, s2, s3 = segments[i], segments[i + 1], segments[i + 2]

        # 三段的区间
        highs = [s1.high, s2.high, s3.high]
        lows = [s1.low, s2.low, s3.low]

        # 中枢上下沿
        zg = min(highs)  # 上沿
        zd = max(lows)   # 下沿

        # 检查是否有重叠
        if zg > zd:
            # 判断中枢形成方向
            if s1.direction == s3.direction == "up":
                direction = "up"  # 回升形成
            elif s1.direction == s3.direction == "down":
                direction = "down"  # 回调形成
            else:
                direction = "unknown"

            # 检查重叠比例（可选）
            if min_overlap_ratio > 0:
                total_range = max(highs) - min(lows)
                if total_range > 0:
                    overlap_ratio = (zg - zd) / total_range
                    if overlap_ratio < min_overlap_ratio:
                        continue

            return ZhongShu(
                start_index=s1.start_index,
                end_index=s3.end_index,
                zg=zg,
                zd=zd,
                gg=max(highs),
                dd=min(lows),
                direction=direction,
                wave_ranges=[(s1.low, s1.high), (s2.low, s2.high), (s3.low, s3.high)],
            )

    return None


def identify_all_zhongshus(
    segments: List[SegmentForZS]
) -> List[ZhongShu]:
    """
    识别所有中枢（滑动窗口法）

    遍历所有连续三段组合，识别每个有效中枢，
    然后合并重叠的中枢区间。
    """
    if len(segments) < 3:
        return []

    # 第一步：找出所有候选中枢
    candidates = []
    i = 0
    while i < len(segments) - 2:
        zs = identify_zhongshu(segments[i:i + 3])
        if zs:
            zs.start_index = segments[i].start_index
            zs.end_index = segments[i + 2].end_index
            candidates.append((i, zs))
        i += 1

    if not candidates:
        return []

    # 第二步：合并重叠/相邻的中枢候选
    # 取每段的最优中枢
    merged = []
    used = set()

    for i in range(len(candidates)):
        if i in used:
            continue

        best = candidates[i][1]
        best_segments = {candidates[i][0], candidates[i][0] + 1, candidates[i][0] + 2}

        # 检查后续候选是否与best重叠
        for j in range(i + 1, len(candidates)):
            if j in used:
                continue

            cj = candidates[j]
            # 如果中枢有较多共享段，合并
            cj_segments = {cj[0], cj[0] + 1, cj[0] + 2}
            overlap = best_segments & cj_segments

            if len(overlap) >= 2:  # 共享至少2段
                # 取更大的中枢区间
                best.zg = min(best.zg, cj[1].zg)
                best.zd = max(best.zd, cj[1].zd)
                best.gg = max(best.gg, cj[1].gg)
                best.dd = min(best.dd, cj[1].dd)
                best.wave_ranges.extend(cj[1].wave_ranges)
                best_segments.update(cj_segments)
                used.add(j)

        merged.append(best)
        used.add(i)

    # 按位置排序
    merged.sort(key=lambda z: z.start_index)

    return merged


# ==================== 中枢延伸检测 ====================

def check_extension(
    zhongshu: ZhongShu,
    subsequent_segments: List[SegmentForZS]
) -> ZhongShu:
    """
    检测中枢延伸（第18、20课）

    中枢形成后，后续的次级别走势如果与中枢区间有重叠，
    则属于中枢延伸。

    缠中说禅走势中枢中心定理一：
    走势中枢的延伸等价于任意区间[dn, gn]与[ZD, ZG]有重叠。
    若有Zn使得dn > ZG或gn < ZD，则必然产生高级别的走势中枢或趋势及延续。
    """
    if not subsequent_segments:
        return zhongshu

    zg, zd = zhongshu.zg, zhongshu.zd
    extend_count = 0
    last_index = zhongshu.end_index

    for seg in subsequent_segments:
        # 检查是否与中枢区间重叠
        overlaps_zs = not (seg.low > zg or seg.high < zd)

        if overlaps_zs:
            extend_count += 1
            zhongshu.wave_ranges.append((seg.low, seg.high))
            last_index = seg.end_index

            # 更新极值
            zhongshu.gg = max(zhongshu.gg, seg.high)
            zhongshu.dd = min(zhongshu.dd, seg.low)
        else:
            # 检查是否形成中枢破坏（第三类买卖点）
            if seg.low > zg:  # 向上突破不再回来
                if extend_count > 0:
                    zhongshu.state = ZhongShuState.DESTROYED
                break
            elif seg.high < zd:  # 向下跌破不再回来
                if extend_count > 0:
                    zhongshu.state = ZhongShuState.DESTROYED
                break
            else:
                # 只是一个短暂的波动，可能后续会回来
                continue

    zhongshu.end_index = last_index
    zhongshu.extend_count = extend_count
    zhongshu.segments_count = 3 + extend_count

    if extend_count >= 6:
        # 延伸超过9段（3+6=9），中枢已升级
        zhongshu.state = ZhongShuState.UPGRADED
    elif extend_count > 0:
        zhongshu.state = ZhongShuState.EXTENDING

    return zhongshu


# ==================== 中枢扩张与升级判断 ====================

def check_expansion(
    zhongshu_a: ZhongShu,
    zhongshu_b: ZhongShu
) -> Optional[ZhongShu]:
    """
    检测两个中枢是否扩张为更高级别中枢（第20课）

    缠中说禅走势级别延续定理二：
    更大级别缠中说禅走势中枢产生，当且仅当围绕连续两个
    同级别缠中说禅走势中枢产生的波动区间产生重叠。

    即：后中枢的GG > 前中枢的DD，且两个中枢的波动区间重叠
    """
    if not zhongshu_a.is_valid or not zhongshu_b.is_valid:
        return None

    # 检查位置关系：b在a之后
    if zhongshu_b.start_index <= zhongshu_a.end_index:
        return None

    # 检查波动区间是否重叠
    # a的波动区间：[a.dd, a.gg]
    # b的波动区间：[b.dd, b.gg]
    # 重叠条件：a.gg >= b.dd 且 b.gg >= a.dd
    wave_overlap = (zhongshu_a.gg >= zhongshu_b.dd and
                    zhongshu_b.gg >= zhongshu_a.dd)

    if not wave_overlap:
        return None

    # 形成更高级别中枢
    upgrade_zs = ZhongShu(
        start_index=zhongshu_a.start_index,
        end_index=zhongshu_b.end_index,
        zg=min(zhongshu_a.zg, zhongshu_b.zg),
        zd=max(zhongshu_a.zd, zhongshu_b.zd),
        gg=max(zhongshu_a.gg, zhongshu_b.gg),
        dd=min(zhongshu_a.dd, zhongshu_b.dd),
        direction=zhongshu_a.direction,
        level=zhongshu_a.level + 1,  # 级别+1
        state=ZhongShuState.UPGRADED,
        segments_count=zhongshu_a.segments_count + zhongshu_b.segments_count,
        wave_ranges=zhongshu_a.wave_ranges + zhongshu_b.wave_ranges,
    )

    return upgrade_zs


def compute_zhongshu_level(
    zhongshu: ZhongShu,
    base_level_name: str = "1分钟"
) -> str:
    """
    计算中枢的级别名称

    参数：
        zhongshu: 中枢对象
        base_level_name: 基础级别名称

    返回：
        级别名称，如 "5分钟"、"30分钟"、"日线"
    """
    level_names = {
        0: base_level_name,
        1: "5分钟",
        2: "30分钟",
        3: "日线",
        4: "周线",
        5: "月线",
        6: "季线",
        7: "年线",
    }

    # 根据延伸段数判断级别
    if zhongshu.state == ZhongShuState.UPGRADED:
        # 已升级的中枢使用预设级别
        return level_names.get(zhongshu.level, f"级别{zhongshu.level}")

    # 未升级的中枢根据延伸段数估算级别
    if zhongshu.extend_count >= 6:
        return level_names.get(1, "5分钟")
    elif zhongshu.extend_count >= 3:
        return level_names.get(0, "1分钟")

    return level_names.get(0, "1分钟")


# ==================== 中枢破坏检测 ====================

def check_destruction(
    zhongshu: ZhongShu,
    segments: List[SegmentForZS]
) -> Tuple[bool, Optional[str]]:
    """
    检测中枢是否被破坏（第18课）

    缠中说禅走势中枢破坏定理：
    某级别"缠中说禅走势中枢"的破坏，当且仅当一个次级别走势
    离开该中枢后，其后的次级别回抽走势不重新回到该中枢内。

    破坏的三种组合：
    1. 趋势+盘整（最有力的破坏）
    2. 趋势+反趋势
    3. 盘整+反趋势
    """
    if not zhongshu or not segments:
        return False, None

    zg, zd = zhongshu.zg, zhongshu.zd

    # 找中枢后的走势段
    post_zs = [
        s for s in segments if s.start_index > zhongshu.end_index
    ]

    if len(post_zs) < 2:
        return False, None

    # 离开段
    leave_seg = post_zs[0]

    # 检查离开方向
    if leave_seg.low > zg:
        # 向上离开
        direction = "up"
    elif leave_seg.high < zd:
        # 向下离开
        direction = "down"
    else:
        return False, None

    if len(post_zs) < 2:
        return False, None

    # 回抽/回试段
    test_seg = post_zs[1]

    if direction == "up":
        # 向上离开，回试不破ZG -> 第三类买点，中枢被破坏
        if test_seg.low > zg:
            # 判断破坏类型
            if len(post_zs) >= 3:
                third_seg = post_zs[2]
                if third_seg.direction == direction:
                    return True, "趋势+盘整（最有力）"
                else:
                    return True, "趋势+反趋势"
            return True, "盘整+反趋势"
        else:
            return False, None
    else:
        # 向下离开，回抽不升破ZD -> 第三类卖点，中枢被破坏
        if test_seg.high < zd:
            if len(post_zs) >= 3:
                third_seg = post_zs[2]
                if third_seg.direction == direction:
                    return True, "趋势+盘整（最有力）"
                else:
                    return True, "趋势+反趋势"
            return True, "盘整+反趋势"
        else:
            return False, None


# ==================== 中枢的"生住坏灭"分析 ====================

def analyze_zhongshu_lifecycle(
    segments: List[SegmentForZS]
) -> List[Dict]:
    """
    分析中枢的完整生命周期（第18课）

    中枢如同众生的生命周期：
    - 生：中枢的产生
    - 住：中枢的维持（延伸）
    - 坏：中枢被破坏
    - 灭：中枢废弃

    返回：
        [{state, start, end, zhongshu, ...}]
    """
    if len(segments) < 3:
        return []

    lifecycle = []

    # 识别所有中枢
    zhongshus = identify_all_zhongshus(segments)

    for zs in zhongshus:
        # 检测延伸
        post_zs_segments = [
            s for s in segments if s.start_index > zs.end_index
        ]
        zs = check_extension(zs, post_zs_segments)

        # 检测破坏
        destroyed, destroy_type = check_destruction(zs, segments)

        lifecycle.append({
            "state": "生" if zs.state == ZhongShuState.FORMED else zs.state.value,
            "start_index": zs.start_index,
            "end_index": zs.end_index,
            "zg": zs.zg,
            "zd": zs.zd,
            "width": zs.width,
            "segments_count": zs.segments_count,
            "extend_count": zs.extend_count,
            "destroyed": destroyed,
            "destroy_type": destroy_type,
        })

    return lifecycle


# ==================== 工具函数 ====================

def zhongshu_overlap(
    zs1: ZhongShu,
    zs2: ZhongShu
) -> bool:
    """判断两个中枢是否有区间重叠"""
    return not (zs1.zg < zs2.zd or zs2.zg < zs1.zd)


def price_in_zhongshu(
    price: float,
    zhongshu: ZhongShu
) -> str:
    """判断价格相对于中枢的位置"""
    if price > zhongshu.zg:
        return "above"    # 中枢上方
    elif price < zhongshu.zd:
        return "below"    # 中枢下方
    else:
        return "inside"   # 中枢内部


def zhongshu_summary(zhongshu: ZhongShu) -> str:
    """生成中枢摘要文本"""
    return (
        f"中枢 [{zhongshu.start_index}-{zhongshu.end_index}] "
        f"区间 [{zhongshu.zd:.2f}, {zhongshu.zg:.2f}] "
        f"宽 {zhongshu.width:.2f} "
        f"方向 {zhongshu.direction} "
        f"状态 {zhongshu.state.value} "
        f"段数 {zhongshu.segments_count}"
    )


if __name__ == "__main__":
    # 示例用法
    print("中枢识别模块加载成功")
    print(f"支持的中枢状态: {[s.value for s in ZhongShuState]}")
