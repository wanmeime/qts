# -*- coding: utf-8 -*-
"""
缠论分析服务（盘中后台线程）

职责：
  - 接收实时盯盘模块的分析请求
  - 实例化 ChanlunCore 执行分析
  - 返回分析结果

设计原则：
  - 不修改 10-策略/缠论Agent/ 的引擎代码
  - 自身在 50-盯盘/ 中，属于盯盘基础设施
  - 通过 Queue 通信，不阻塞实时主循环

支持的分析类型：
  1. check_divergence_zone  — 15分钟背驰段检测
  2. check_full_15min       — 完整15分钟缠论分析
"""
import sys
import json
import logging
import threading
import uuid
from pathlib import Path
from queue import Queue, Empty
from typing import Dict, Optional, Any
from dataclasses import dataclass, field

import pandas as pd

# 项目路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "10-策略" / "缠论Agent"))
sys.path.insert(0, str(PROJECT_ROOT / "50-盯盘"))

from chanlun_core import ChanlunCore, Direction
from signal_templates import DivergenceStatus

logger = logging.getLogger(__name__)


# ============================================================
# 请求 / 响应 数据模型
# ============================================================

@dataclass
class AnalysisRequest:
    """分析请求"""
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    request_type: str = ""            # check_divergence_zone / check_full_15min
    stock_code: str = ""
    stock_name: str = ""
    scale: int = 15                   # K线周期（分钟）
    days: int = 60                    # 获取天数
    kline_data: Optional[pd.DataFrame] = None  # 直接传入K线数据（避免重复获取）


@dataclass
class AnalysisResponse:
    """分析响应"""
    request_id: str = ""
    request_type: str = ""
    stock_code: str = ""
    success: bool = False
    error: Optional[str] = None

    # 背驰段检测结果
    in_divergence_zone: bool = False
    div_status: str = "not_in_zone"
    zhongshu_high: Optional[float] = None
    zhongshu_low: Optional[float] = None
    prev_exit_bi_macd_area: Optional[float] = None
    curr_exit_bi_macd_area: Optional[float] = None

    # 完整分析结果
    analysis_result: Optional[Dict] = None
    bis_count: int = 0
    zhongshu_count: int = 0


# ============================================================
# 缠论服务
# ============================================================

class ChanlunService:
    """
    缠论分析服务（后台线程）

    用法：
        service = ChanlunService()
        service.start()

        # 发请求
        service.request_queue.put(request)

        # 收响应
        response = service.response_queue.get(timeout=10)

        # 停止
        service.stop()
    """

    def __init__(self):
        self.request_queue: Queue = Queue()
        self.response_queue: Queue = Queue()
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self):
        """启动后台线程"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="chanlun-service")
        self._thread.start()
        logger.info("缠论分析服务已启动")

    def stop(self):
        """停止后台线程"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("缠论分析服务已停止")

    def _run_loop(self):
        """后台主循环"""
        while self._running:
            try:
                request = self.request_queue.get(timeout=1.0)
                self._handle_request(request)
            except Empty:
                continue
            except Exception as e:
                logger.error(f"缠论服务异常: {e}")

    def _handle_request(self, request: AnalysisRequest):
        """处理单个请求"""
        try:
            if request.request_type == "check_divergence_zone":
                response = self._check_divergence_zone(request)
            elif request.request_type == "check_full_15min":
                response = self._check_full_15min(request)
            else:
                response = AnalysisResponse(
                    request_id=request.request_id,
                    request_type=request.request_type,
                    stock_code=request.stock_code,
                    success=False,
                    error=f"未知请求类型: {request.request_type}",
                )
            self.response_queue.put(response)

        except Exception as e:
            logger.exception(f"处理请求失败 {request.request_type} {request.stock_code}")
            self.response_queue.put(AnalysisResponse(
                request_id=request.request_id,
                request_type=request.request_type,
                stock_code=request.stock_code,
                success=False,
                error=str(e),
            ))

    # ============================================================
    # 分析逻辑
    # ============================================================

    @staticmethod
    def _load_kline(code: str, days: int = 60, scale: int = 15) -> Optional[pd.DataFrame]:
        """加载K线数据"""
        try:
            from watchdog import fetch_kline
            return fetch_kline(code, days=days, scale=scale)
        except ImportError:
            logger.error("无法导入 fetch_kline")
            return None

    def _run_chanlun_core(self, df: pd.DataFrame) -> ChanlunCore:
        """在 DataFrame 上跑完整缠论分析"""
        core = ChanlunCore()
        core.process_klines(df[["open", "high", "low", "close"]])
        core.find_fractals()
        core.find_bis()
        core.find_zhong_shus()
        if len(df) > 30:
            core._calc_macd(df["close"].astype(float))
        return core

    def _check_divergence_zone(self, request: AnalysisRequest) -> AnalysisResponse:
        """
        检查15分钟背驰段

        与 static_analyzer.check_divergence_zone() 逻辑一致，
        此处独立实现以保证盘中服务不依赖静态分析模块。
        """
        # 获取K线数据
        if request.kline_data is not None:
            df = request.kline_data
        else:
            df = self._load_kline(request.stock_code, days=request.days, scale=request.scale)

        if df is None or len(df) < 60:
            return AnalysisResponse(
                request_id=request.request_id,
                request_type=request.request_type,
                stock_code=request.stock_code,
                success=False,
                error=f"K线数据不足: {len(df) if df is not None else 0}",
            )

        # 缠论分析
        core = self._run_chanlun_core(df)

        # 找下跌中枢
        down_zs = [zs for zs in core.zhong_shus if zs.direction == Direction.DOWN]

        resp = AnalysisResponse(
            request_id=request.request_id,
            request_type=request.request_type,
            stock_code=request.stock_code,
            success=True,
            bis_count=len(core.bis),
            zhongshu_count=len(core.zhong_shus),
        )

        if len(down_zs) < 2:
            # 不满足两个下跌中枢，不在背驰段
            resp.in_divergence_zone = False
            resp.div_status = DivergenceStatus.NOT_IN_ZONE.value
            return resp

        # 取第二个中枢
        zs = down_zs[-1]
        resp.zhongshu_high = zs.high
        resp.zhongshu_low = zs.low

        # 找中枢后的向下离开笔
        exit_bis = [
            b for i, b in enumerate(core.bis)
            if b.direction == Direction.DOWN and i >= zs.end_bi_index
        ]
        if not exit_bis:
            resp.in_divergence_zone = False
            resp.div_status = DivergenceStatus.NOT_IN_ZONE.value
            return resp

        # 找前一段离开笔
        prev_exit_bis = [
            b for i, b in enumerate(core.bis)
            if b.direction == Direction.DOWN and i < zs.end_bi_index
            and i >= zs.start_bi_index - 2
        ]
        if not prev_exit_bis:
            resp.in_divergence_zone = False
            resp.div_status = DivergenceStatus.NOT_IN_ZONE.value
            return resp

        prev_exit = prev_exit_bis[-1]
        curr_exit = exit_bis[-1]

        # MACD面积对比
        prev_area = core._bi_macd_area(prev_exit)
        curr_area = core._bi_macd_area(curr_exit)

        resp.prev_exit_bi_macd_area = prev_area
        resp.curr_exit_bi_macd_area = curr_area

        if prev_area > 0 and curr_area < prev_area * 0.85:
            resp.in_divergence_zone = True
            resp.div_status = DivergenceStatus.IN_ZONE.value
        else:
            resp.in_divergence_zone = False
            resp.div_status = DivergenceStatus.NOT_IN_ZONE.value

        return resp

    def _check_full_15min(self, request: AnalysisRequest) -> AnalysisResponse:
        """完整15分钟缠论分析（含买卖点）"""
        if request.kline_data is not None:
            df = request.kline_data
        else:
            df = self._load_kline(request.stock_code, days=request.days, scale=request.scale)

        if df is None or len(df) < 60:
            return AnalysisResponse(
                request_id=request.request_id,
                request_type=request.request_type,
                stock_code=request.stock_code,
                success=False,
                error=f"K线数据不足: {len(df) if df is not None else 0}",
            )

        core = self._run_chanlun_core(df)
        core.find_buy_sell_points()

        # 将 result 序列化为可传输的格式
        result = {
            "klines": len(core.processed_klines),
            "fractals": len(core.fractals),
            "bis": len(core.bis),
            "zhong_shus": len(core.zhong_shus),
            "buy_sell_points": [
                {"type": p.type.value, "price": p.price, "index": p.index, "timestamp": p.timestamp}
                for p in core.buy_sell_points
            ],
        }

        return AnalysisResponse(
            request_id=request.request_id,
            request_type=request.request_type,
            stock_code=request.stock_code,
            success=True,
            analysis_result=result,
            bis_count=len(core.bis),
            zhongshu_count=len(core.zhong_shus),
        )
