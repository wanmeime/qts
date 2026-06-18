#!/usr/bin/env python3
"""
盯盘系统 - 交易联动版
=====================

与交易系统深度整合：
1. 读取持仓 → 监控持仓盈亏、成本线
2. 对自选股跑缠论分析 → 检测新买点/卖点
3. 结合持仓给出操作建议（加仓/减仓/止损）
4. 飞书实时推送

使用方法:
    python3 watchdog.py                    # 正常运行
    python3 watchdog.py --once             # 扫描一次后退出
    python3 watchdog.py --test             # 测试模式（忽略交易时段）
    python3 watchdog.py --stocks 600519,000858  # 只扫描指定股票
"""
import os
import sys
import json
import time
import signal
import argparse
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

# 添加策略模块路径
sys.path.insert(0, str(Path(__file__).parent.parent / "10-策略" / "自选股监控"))

from realtime_fetcher import RealtimeFetcher, QmtFetcher, is_trading_hours, get_market_status
from state_store import StateStore
from notifier import Notifier

try:
    from 缠论分析 import analyze as chanlun_analyze, Signal
    from signal_generator import score_signals, filter_signals
    HAS_CHANLUN = True
except ImportError:
    HAS_CHANLUN = False
    print("WARNING: 缠论分析模块不可用，将跳过技术分析")

# 多级别分析模块
try:
    sys.path.insert(0, str(Path(__file__).parent.parent / "10-策略" / "缠论Agent"))
    from multi_level import MultiLevelAnalysis, Level
    from knowledge_base import ChanlunKnowledgeBase
    from chanlun_core import FractalType
    HAS_MULTI_LEVEL = True
except ImportError:
    HAS_MULTI_LEVEL = False
    ChanlunKnowledgeBase = None
    print("WARNING: 多级别分析模块不可用，将使用单级别分析")

try:
    import yaml
except ImportError:
    yaml = None

import pandas as pd
import requests as req_lib

_CST = timezone(timedelta(hours=8))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ============================================================
# 路径常量
# ============================================================
PROJECT_ROOT = Path(__file__).parent.parent
POSITION_FILE = PROJECT_ROOT / "40-执行" / "持仓" / "当前持仓.json"
WATCHLIST_FILE = PROJECT_ROOT / "00-研究" / "自选股" / "watchlist.json"
KLINE_CACHE_DIR = PROJECT_ROOT / "00-研究" / "数据源" / "缓存" / "kline_6m"


# ============================================================
# 配置加载
# ============================================================

def load_config(config_path: str = None) -> dict:
    path = Path(config_path) if config_path else current_dir / "config.yaml"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            if yaml:
                return yaml.safe_load(f) or {}
            return json.load(f)
    return _default_config()


def _default_config() -> dict:
    return {
        "schedule": {"interval_seconds": 60, "run_outside_hours": False},
        "data_source": {"primary": "eastmoney", "timeout": 10},
        "alert_rules": {
            "position_pnl_alert_pct": -5.0,
            "position_pnl_profit_pct": 10.0,
            "signal_min_score": 60,
            "signal_dedup_days": 5,
        },
        "notification": {
            "feishu": {"enabled": True, "chat_id": "oc_d2e8df3c676afa2c352d8ece0a9b6141"},
            "dedup_window_seconds": 300,
        },
        "storage": {"db_path": str(current_dir / "watchdog.db")},
    }


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
        positions = data.get("持仓明细", [])
        logger.info(f"加载持仓: {len(positions)} 只")
        return positions
    except Exception as e:
        logger.error(f"加载持仓失败: {e}")
        return []


def load_watchlist_codes() -> List[str]:
    """加载自选股代码列表"""
    if not WATCHLIST_FILE.exists():
        return []
    try:
        with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        codes = []
        for item in data:
            if isinstance(item, dict):
                code = item.get("code", "")
                market = item.get("market", "")
                # 跳过指数
                if code.startswith("399") or code.startswith("880"):
                    continue
                # 只保留A股
                if "A股" in market or "创业板" in market:
                    codes.append(code)
            elif isinstance(item, str):
                codes.append(item)
        logger.info(f"加载自选股: {len(codes)} 只")
        return codes
    except Exception as e:
        logger.error(f"加载自选股失败: {e}")
        return []


def fetch_kline(code: str, days: int = 120, scale: int = 240) -> pd.DataFrame:
    """
    获取K线数据（优先同花顺本地数据 → 缓存 → 新浪）
    
    Args:
        code: 股票代码
        days: 获取天数
        scale: K线周期（分钟），240=日线，15=15分钟
    """
    # 仅日线支持本地数据源
    if scale == 240:
        # 1. 优先同花顺本地数据
        ths_df = None
        try:
            from qmt_bridge.hexin_reader import get_hexin_kline, has_hexin_data
            if has_hexin_data(code):
                ths_df = get_hexin_kline(code, days=days + 60)
        except Exception:
            pass

        # 2. 缓存（仅当无同花顺数据时）
        csv_df = None
        if ths_df is None or len(ths_df) < 30:
            csv_path = KLINE_CACHE_DIR / f"{code}.csv"
            if csv_path.exists():
                try:
                    csv_df = pd.read_csv(csv_path)
                    if "day" in csv_df.columns and "date" not in csv_df.columns:
                        csv_df = csv_df.rename(columns={"day": "date"})
                    if len(csv_df) >= 30:
                        csv_df = csv_df.set_index("date")
                        csv_df.index = pd.to_datetime(csv_df.index)
                except Exception:
                    pass

        # 3. 新浪接口（获取完整数据，用于填补空缺）
        sina_df = None
        try:
            if code.startswith("6") or code.startswith("9"):
                symbol = f"sh{code}"
            else:
                symbol = f"sz{code}"
            url = f"https://quotes.sina.cn/cn/api/jsonp.php/=/CN_MarketDataService.getKLineData?symbol={symbol}&scale={scale}&ma=no&datalen={days + 60}"
            resp = req_lib.get(url, timeout=10)
            text = resp.text
            start = text.index("[")
            end = text.rindex("]") + 1
            data = json.loads(text[start:end])
            if data:
                sina_df = pd.DataFrame(data)
                sina_df = sina_df.rename(columns={"day": "date"})
                for col in ["open", "close", "high", "low", "volume"]:
                    if col in sina_df.columns:
                        sina_df[col] = pd.to_numeric(sina_df[col], errors="coerce")
                sina_df["date"] = pd.to_datetime(sina_df["date"])
                sina_df = sina_df.set_index("date")
        except Exception:
            pass

        # 设置日期索引（确保后续缠论分析能用正确日期）
        def _set_date_index(df):
            if "date" in df.columns:
                df = df.set_index(pd.to_datetime(df["date"]))
            return df

        # 4. 合并数据：优先同花顺，空缺用新浪补（用同花顺价格计算修正系数）
        if ths_df is not None and len(ths_df) >= 30 and sina_df is not None and len(sina_df) >= 30:
            # 计算复权系数（用同时有数据的日期）
            common_dates = ths_df.index.intersection(sina_df.index)
            if len(common_dates) > 5:
                ratios = (ths_df.loc[common_dates, "close"] / sina_df.loc[common_dates, "close"]).values
                ratio = sum(ratios) / len(ratios)
            else:
                ratio = 1.0
            
            # 用同花顺数据，缺失日期用新浪×系数填补
            all_dates = sina_df.index.union(ths_df.index).sort_values()
            merged = pd.DataFrame(index=all_dates)
            # 同花顺列
            for col in ["open", "high", "low", "close", "volume"]:
                if col in ths_df.columns:
                    merged[f"ths_{col}"] = ths_df[col]
                    merged[f"sina_{col}"] = sina_df[col] * ratio
            
            # 填值：优先同花顺，没有的用新浪修正值
            for col in ["open", "high", "low", "close"]:
                merged[col] = merged[f"ths_{col}"].fillna(merged[f"sina_{col}"])
            merged["volume"] = merged["ths_volume"].fillna(merged["sina_volume"]).fillna(0).astype(int)
            
            merged = merged.drop(columns=[c for c in merged.columns if c.startswith("ths_") or c.startswith("sina_")])
            merged = merged.dropna(subset=["close"])
            
            if len(merged) >= 30:
                return merged.tail(days).reset_index(drop=False).rename(columns={"index": "date"})
        
        # 5. 仅同花顺（无新浪）
        if ths_df is not None and len(ths_df) >= 30:
            return ths_df.reset_index().tail(days).reset_index(drop=True)
        
        # 6. 仅缓存
        if csv_df is not None and len(csv_df) >= 30:
            return csv_df.tail(days).reset_index(drop=True)

    # 7. 仅有新浪（或非日线）
    try:
        if sina_df is not None and len(sina_df) >= 30:
            return sina_df.tail(days).reset_index(drop=False).rename(columns={"index": "date"})
        
        # 重新从新浪拉
        if code.startswith("6") or code.startswith("9"):
            symbol = f"sh{code}"
        else:
            symbol = f"sz{code}"
        url = f"https://quotes.sina.cn/cn/api/jsonp.php/=/CN_MarketDataService.getKLineData?symbol={symbol}&scale={scale}&ma=no&datalen={days + 30}"
        resp = req_lib.get(url, timeout=10)
        text = resp.text
        start = text.index("[")
        end = text.rindex("]") + 1
        data = json.loads(text[start:end])
        if not data:
            return pd.DataFrame()
        df = pd.DataFrame(data)
        df = df.rename(columns={"day": "date"})
        for col in ["open", "close", "high", "low", "volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df.tail(days).reset_index(drop=True)
    except Exception as e:
        logger.debug(f"获取 {code} K线(scale={scale})失败: {e}")
        return pd.DataFrame()


# ============================================================
# 核心分析
# ============================================================

def analyze_stock(code: str, kline_df: pd.DataFrame, config: dict) -> Dict:
    """
    对单只股票进行完整分析。

    返回:
        {
            code, name, current_price,
            chanlun: {signals, summary, multi_level},
            pnl: {cost, current, pnl_pct, ...} (仅持仓股),
        }
    """
    result = {
        "code": code,
        "name": "",
        "current_price": None,
        "chanlun": None,
        "pnl": None,
    }

    if kline_df.empty or len(kline_df) < 30:
        return result

    # 当前价格
    if "close" in kline_df.columns:
        result["current_price"] = float(kline_df["close"].iloc[-1])

    # 多级别联立分析
    if HAS_MULTI_LEVEL and HAS_CHANLUN:
        try:
            # 获取15分钟K线数据
            min15_df = fetch_kline(code, days=60, scale=15)
            if not min15_df.empty and "date" in min15_df.columns:
                min15_df = min15_df.set_index(pd.to_datetime(min15_df["date"]))
            
            # 确保日线数据有日期索引
            daily_df = kline_df.copy()
            if "date" in daily_df.columns:
                daily_df = daily_df.set_index(pd.to_datetime(daily_df["date"]))
            
            # 多级别分析
            analyzer = MultiLevelAnalysis()
            multi_result = analyzer.analyze_multi_level(code, daily_df, min15_df)
            
            # 信号类型中文名映射
            _type_cn = {
                "buy1": "一买", "buy2": "二买", "buy3": "三买",
                "sell1": "一卖", "sell2": "二卖", "sell3": "三卖",
            }
            _level_cn = {"daily": "日线", "15min": "15分钟"}
            signals = []

            # ---- 日线买/卖点 + 底分型确认突破 = 入场/离场信号 ----
            # 日线有买点 → 检查日线底分型是否被突破
            # 直接检查日线底分型确认突破
            dly_core = None
            if multi_result and multi_result.daily:
                dly_core = multi_result.daily.chanlun_core
            if dly_core and dly_core.fractals:
                for f in reversed(dly_core.fractals):
                    if f.type == FractalType.BOTTOM:
                        entry = f.third_high
                        cp = result.get('current_price', 0)
                        if cp > entry:
                            # 小转大（默认）
                            desc = '日线小转大'
                            sig_type = 'inflection'
                            sig_date = ''
                            sig_price = entry
                            sig_score = 85
                            
                            # 检查是否有同期的标准买点
                            if multi_result and multi_result.daily and multi_result.daily.latest_buy_point:
                                bp = multi_result.daily.latest_buy_point
                                try:
                                    from datetime import datetime
                                    bpd = datetime.strptime(str(bp.timestamp)[:10], '%Y-%m-%d')
                                    bfd = datetime.strptime(str(f.timestamp)[:10], '%Y-%m-%d')
                                    if abs((bfd - bpd).days) <= 10:
                                        lvl = getattr(bp, "level", "daily")
                                        desc = f"{_level_cn.get(lvl, lvl)}{_type_cn.get(bp.type.value.lower(), bp.type.value)}"
                                        sig_type = bp.type.value.lower()
                                        sig_date = bp.timestamp
                                        sig_price = bp.price
                                        sig_score = 90
                                except:
                                    pass
                            
                            signals.append(Signal(
                                type=sig_type, date=sig_date, price=sig_price, score=sig_score,
                                description=f"{desc} ✅ 底分型确认突破{entry:.2f}✓",
                                macd_confirm=True, volume_confirm=False))
                        break
                        break

            # 直接检查日线顶分型是否被跌破
            if dly_core and dly_core.fractals:
                for f in reversed(dly_core.fractals):
                    if f.type == FractalType.TOP:
                        exit_p = f.third_low
                        if result.get('current_price', 0) < exit_p:
                            # 判断是什么类型的卖点
                            if multi_result.daily and multi_result.daily.latest_sell_point:
                                sp = multi_result.daily.latest_sell_point
                                sp_ts = str(sp.timestamp)[:10]
                                sf_ts = str(f.timestamp)[:10]
                                try:
                                    from datetime import datetime
                                    spd = datetime.strptime(sp_ts, '%Y-%m-%d')
                                    sfd = datetime.strptime(sf_ts, '%Y-%m-%d')
                                    dd = abs((sfd - spd).days)
                                except:
                                    dd = 99
                                if dd <= 10:
                                    lvl = getattr(sp, "level", "daily")
                                    desc = f"{_level_cn.get(lvl, lvl)}{_type_cn.get(sp.type.value.lower(), sp.type.value)}"
                                    signals.append(Signal(type=sp.type.value.lower(), date=sp.timestamp, price=sp.price, score=90,
                                        description=f"{desc} ⚠ 顶分型确认跌破{exit_p:.2f}⚠", macd_confirm=True, volume_confirm=False))
                                else:
                                    signals.append(Signal(type='inflection', date='', price=exit_p, score=85,
                                        description=f"日线小转大 ⚠ 顶分型确认跌破{exit_p:.2f}⚠", macd_confirm=True, volume_confirm=False))
                            else:
                                signals.append(Signal(type='inflection', date='', price=exit_p, score=85,
                                    description=f"日线顶分型确认跌破{exit_p:.2f}⚠", macd_confirm=True, volume_confirm=False))
                        break
            # 评分和过滤
            min_score = config.get("alert_rules", {}).get("signal_min_score", 60)
            scored = score_signals(signals)
            
            # 为每个信号添加级别信息
            for s in scored:
                desc = s.get("description", "")
                if "15分钟" in desc:
                    s["level"] = "15min"
                elif "日线" in desc:
                    s["level"] = "daily"
                else:
                    s["level"] = "unknown"
            
            filtered = filter_signals(scored, min_score)
            
            result["chanlun"] = {
                "signals": filtered,
                "all_signals": scored,
                "summary": multi_result.summary,
                "multi_level": {
                    "overall_signal": multi_result.overall_signal,
                    "signal_reasons": multi_result.signal_reasons,
                    "daily_signal": "buy" if multi_result.daily and multi_result.daily.latest_buy_point else "sell" if multi_result.daily and multi_result.daily.latest_sell_point else "hold",
                    "min15_signal": "buy" if multi_result.min15 and multi_result.min15.latest_buy_point else "sell" if multi_result.min15 and multi_result.min15.latest_sell_point else "hold",
                },
            }
        except Exception as e:
            logger.warning(f"多级别分析 {code} 失败: {e}")
            # 回退到单级别分析
            _analyze_stock_single(code, kline_df, config, result)
    elif HAS_CHANLUN:
        _analyze_stock_single(code, kline_df, config, result)

    return result


def _analyze_stock_single(code: str, kline_df: pd.DataFrame, config: dict, result: Dict):
    """单级别缠论分析（回退方案）"""
    try:
        cfg = {
            "macd": config.get("chanlun", {}).get("macd", {"fast": 12, "slow": 26, "signal": 9}),
            "divergence_window": config.get("chanlun", {}).get("divergence_window", 20),
        }
        analysis = chanlun_analyze(kline_df, cfg)

        # 评分
        if analysis.get("signals"):
            min_score = config.get("alert_rules", {}).get("signal_min_score", 60)
            scored = score_signals(analysis["signals"])
            filtered = filter_signals(scored, min_score)
            result["chanlun"] = {
                "signals": filtered,
                "all_signals": scored,
                "summary": analysis.get("summary", ""),
                "multi_level": None,
            }
    except Exception as e:
        logger.warning(f"缠论分析 {code} 失败: {e}")


def check_position_alerts(
    positions: List[Dict],
    realtime_data: Dict[str, Dict],
    config: dict,
) -> List[Dict]:
    """
    检查持仓报警：
    - 盈亏超过阈值
    - 接近成本线
    - 大幅波动
    """
    alerts = []
    rules = config.get("alert_rules", {})
    loss_pct = rules.get("position_pnl_alert_pct", -5.0)
    profit_pct = rules.get("position_pnl_profit_pct", 10.0)

    for pos in positions:
        code = pos.get("股票代码", "")
        name = pos.get("名称", "")
        cost = pos.get("成本价", 0)
        shares = pos.get("持股数量", 0)

        if not code or not cost:
            continue

        # 获取实时价格
        rt = realtime_data.get(code, {})
        current_price = rt.get("price", 0)
        change_pct = rt.get("change_pct", 0)

        if not current_price:
            continue

        # 计算盈亏
        pnl_pct = (current_price - cost) / cost * 100
        pnl_amt = (current_price - cost) * shares

        # 止损报警
        if pnl_pct <= loss_pct:
            alerts.append({
                "code": code,
                "name": name,
                "type": "position_loss",
                "level": "critical",
                "message": f"🔴 {name}({code}) 亏损 {pnl_pct:.1f}%，现价 {current_price:.2f}，成本 {cost:.2f}，浮亏 {pnl_amt:,.0f}元",
                "price": current_price,
                "change_pct": pnl_pct,
                "action": "建议止损",
            })

        # 止盈提醒
        elif pnl_pct >= profit_pct:
            alerts.append({
                "code": code,
                "name": name,
                "type": "position_profit",
                "level": "info",
                "message": f"🟢 {name}({code}) 盈利 {pnl_pct:.1f}%，现价 {current_price:.2f}，成本 {cost:.2f}，浮盈 {pnl_amt:,.0f}元",
                "price": current_price,
                "change_pct": pnl_pct,
                "action": "考虑止盈",
            })

        # 大幅波动
        if abs(change_pct) >= 5:
            alerts.append({
                "code": code,
                "name": name,
                "type": "position_volatile",
                "level": "warning",
                "message": f"⚡ {name}({code}) {'大涨' if change_pct > 0 else '大跌'} {change_pct:.2f}%，现价 {current_price:.2f}",
                "price": current_price,
                "change_pct": change_pct,
                "action": "关注",
            })

    return alerts


def _get_signal_type_cn(sig_type: str, knowledge_base=None) -> str:
    """
    获取买卖点类型的中文名称，优先从知识库获取，回退到硬编码字典
    """
    # 硬编码字典（回退方案）
    fallback = {
        "buy1": "一类买点", "buy2": "二类买点", "buy3": "三类买点",
        "sell1": "一类卖点", "sell2": "二类卖点", "sell3": "三类卖点",
    }
    
    # 尝试从知识库获取
    if knowledge_base and knowledge_base.is_available():
        try:
            rules = knowledge_base.get_buy_sell_rules(sig_type)
            if rules.get("found"):
                return rules.get("cn_name", fallback.get(sig_type, sig_type))
        except Exception:
            pass
    
    return fallback.get(sig_type, sig_type)


def _get_signal_rule_ref(sig_type: str, knowledge_base=None, max_chars: int = 80) -> str:
    """
    获取买卖点规则摘要，用于追加到推送消息中
    
    返回格式："📖 二买是一买后第一次次级别回调的低点..."
    空字符串表示无规则参考
    """
    if not knowledge_base or not knowledge_base.is_available():
        return ""
    
    try:
        rules = knowledge_base.get_buy_sell_rules(sig_type)
        if not rules.get("found"):
            return ""
        
        content = rules.get("content", "")
        # 取第一段有意义的文字
        lines = [l.strip() for l in content.split("\n") if l.strip() and not l.startswith("#")]
        ref = ""
        for line in lines:
            # 跳过代码块和空行
            if line.startswith("```") or len(line) < 10:
                continue
            ref = line
            break
        
        if ref:
            if len(ref) > max_chars:
                ref = ref[:max_chars] + "..."
            return f"📖 {ref}"
    except Exception:
        pass
    
    return ""


def check_signal_alerts(
    analyses: Dict[str, Dict],
    positions: List[Dict],
    config: dict,
    knowledge_base=None,
) -> List[Dict]:
    """
    检查缠论信号报警：
    - 新买点出现（自选股）
    - 新卖点出现（持仓股）
    
    信号包含级别信息：daily（日线）或 15min（15分钟）
    当 knowledge_base 可用时，消息中附带规则参考。
    """
    alerts = []
    rules = config.get("alert_rules", {})
    dedup_days = rules.get("signal_dedup_days", 5)

    # 持仓代码集合
    position_codes = {p.get("股票代码") for p in positions}

    for code, analysis in analyses.items():
        chanlun = analysis.get("chanlun")
        if not chanlun:
            continue

        signals = chanlun.get("signals", [])
        if not signals:
            continue

        name = analysis.get("name", code)
        multi_level = chanlun.get("multi_level")

        # 只报最近5个交易日内的信号，旧信号不重复报警
        now = datetime.now(_CST)
        recent_signals = []
        for sig in signals:
            sig_date_str = str(sig.get("date", ""))[:10]
            try:
                sig_date = datetime.strptime(sig_date_str, "%Y-%m-%d")
                if (now - sig_date).days <= 7:  # 7天内（含非交易日约5个交易日）
                    recent_signals.append(sig)
            except:
                continue
        
        if not recent_signals:
            continue
        
        # 按日期排序（最新的在前）
        recent_signals.sort(key=lambda s: str(s.get("date", "")), reverse=True)
        
        # 只保留最近的一个买点和一个卖点
        latest_buy = None
        latest_sell = None
        for sig in recent_signals:
            sig_type = sig.get("type", "")
            if "buy" in sig_type and latest_buy is None:
                latest_buy = sig
            elif "sell" in sig_type and latest_sell is None:
                latest_sell = sig
            if latest_buy and latest_sell:
                break
        
        for sig in filter(None, [latest_buy, latest_sell]):
            sig_type = sig.get("type", "")
            sig_date = sig.get("date", "")
            sig_price = sig.get("price", 0)
            sig_score = sig.get("final_score", 0)
            macd_ok = sig.get("macd_confirm", False)
            sig_level = sig.get("level", "unknown")
            desc = sig.get("description", "")

            # 级别中文映射
            level_cn = {"daily": "日线", "15min": "15分钟"}.get(sig_level, sig_level)
            
            # 从知识库获取类型中文名和规则参考
            type_cn = _get_signal_type_cn(sig_type, knowledge_base)
            rule_ref = _get_signal_rule_ref(sig_type, knowledge_base)
            
            # 多级别共振标记
            resonance_mark = ""
            if multi_level:
                if sig_level == "daily" and multi_level.get("min15_signal") == "buy" and "buy" in sig_type:
                    resonance_mark = "🔥15分钟确认"
                elif sig_level == "daily" and multi_level.get("min15_signal") == "sell" and "sell" in sig_type:
                    resonance_mark = "🔥15分钟确认"
                elif sig_level == "15min" and multi_level.get("daily_signal") == "buy" and "buy" in sig_type:
                    resonance_mark = "🔥日线确认"

            # 构建消息正文
            ref_line = f"\n   {rule_ref}" if rule_ref else ""

            # 买点信号
            if "buy" in sig_type:
                in_position = code in position_codes

                if in_position:
                    alerts.append({
                        "code": code,
                        "name": name,
                        "type": f"signal_{sig_type}",
                        "level": "info",
                        "message": f"📈 {name}({code}) {level_cn}出现{type_cn}！价格 {sig_price:.2f}，评分 {sig_score:.0f}分{resonance_mark}\n   → 持仓中，可考虑加仓{ref_line}",
                        "price": sig_price,
                        "score": sig_score,
                        "signal_level": sig_level,
                        "action": "加仓机会",
                    })
                else:
                    alerts.append({
                        "code": code,
                        "name": name,
                        "type": f"signal_{sig_type}",
                        "level": "info",
                        "message": f"🎯 {name}({code}) {level_cn}出现{type_cn}！价格 {sig_price:.2f}，评分 {sig_score:.0f}分{resonance_mark}\n   → 建仓机会{ref_line}",
                        "price": sig_price,
                        "score": sig_score,
                        "signal_level": sig_level,
                        "action": "建仓机会",
                    })

            # 卖点信号
            elif "sell" in sig_type:
                in_position = code in position_codes

                if in_position:
                    alerts.append({
                        "code": code,
                        "name": name,
                        "type": f"signal_{sig_type}",
                        "level": "warning",
                        "message": f"⚠️ {name}({code}) {level_cn}出现{type_cn}！价格 {sig_price:.2f}，评分 {sig_score:.0f}分{resonance_mark}\n   → 持仓中，建议减仓{ref_line}",
                        "price": sig_price,
                        "score": sig_score,
                        "signal_level": sig_level,
                        "action": "减仓信号",
                    })
                else:
                    alerts.append({
                        "code": code,
                        "name": name,
                        "type": f"signal_{sig_type}",
                        "level": "info",
                        "message": f"🔻 {name}({code}) {level_cn}出现{type_cn}，价格 {sig_price:.2f}，评分 {sig_score:.0f}分，回避{ref_line}",
                        "price": sig_price,
                        "score": sig_score,
                        "signal_level": sig_level,
                        "action": "回避",
                    })

    return alerts


# ============================================================
# 消息格式化
# ============================================================

def build_alert_card(alerts: List[Dict], index_data: Dict = None) -> dict:
    """
    构建飞书 interactive 卡片 JSON

    返回 Feishu 卡片消息结构，包含：
    - 头部：大盘指数+时间
    - 买入信号分区（蓝色）
    - 卖出信号分区（红色）
    - 持仓异动分区
    - 每条预警带规则参考
    """
    if not alerts:
        return {}

    now = datetime.now(_CST).strftime("%m-%d %H:%M")

    # 判断整体严重级别
    has_loss = any(a.get("type", "").startswith("position_loss") for a in alerts)
    has_sell = any("sell" in a.get("type", "") for a in alerts)
    has_buy = any("buy" in a.get("type", "") for a in alerts)

    if has_loss:
        header_template = "red"
    elif has_sell:
        header_template = "yellow"
    elif has_buy:
        header_template = "blue"
    else:
        header_template = "green"

    # ---- 构建卡片元素 ----
    elements = []

    # ===== 大盘指数栏 =====
    if index_data:
        index_parts = []
        for code, data in index_data.items():
            name = data.get("name", code)
            change = data.get("change_pct", 0)
            sign = "+" if change > 0 else ""
            emoji = "🟢" if change >= 0 else "🔴"
            index_parts.append(f"{emoji}{name} {sign}{change:.2f}%")
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": "**大盘指数**\n" + " | ".join(index_parts),
            }
        })
        elements.append({"tag": "hr"})

    # ===== 买入信号 =====
    buy_signals = [a for a in alerts if "buy" in a["type"]]
    if buy_signals:
        buy_lines = []
        for a in buy_signals:
            msg = a.get("message", "")
            score = a.get("score", 0)
            action = a.get("action", "")
            buy_lines.append(
                f"{msg}\n"
                f"⭐ **评分 {score:.0f}**　|　**{action}**"
            )
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**📈 买入信号**（{len(buy_signals)} 条）\n\n" + "\n\n".join(buy_lines),
            }
        })
        elements.append({"tag": "hr"})

    # ===== 卖出信号 =====
    sell_signals = [a for a in alerts if "sell" in a["type"]]
    if sell_signals:
        sell_lines = []
        for a in sell_signals:
            msg = a.get("message", "")
            score = a.get("score", 0)
            action = a.get("action", "")
            sell_lines.append(
                f"{msg}\n"
                f"⭐ **评分 {score:.0f}**　|　**{action}**"
            )
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**⚠️ 卖出信号**（{len(sell_signals)} 条）\n\n" + "\n\n".join(sell_lines),
            }
        })
        elements.append({"tag": "hr"})

    # ===== 持仓异动 =====
    position_alerts = [a for a in alerts if a["type"].startswith("position_")]
    if position_alerts:
        pos_lines = []
        for a in position_alerts:
            pos_lines.append(a.get("message", ""))
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**🔔 持仓异动**（{len(position_alerts)} 条）\n\n" + "\n\n".join(pos_lines),
            }
        })

    # ---- 底部注脚 ----
    elements.append({
        "tag": "note",
        "elements": [
            {"tag": "plain_text", "content": f"⏱ {now}　|　缠论多级别联立分析"}
        ]
    })

    # ---- 组装卡片 ----
    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"📊 盯盘报警（{len(alerts)} 条）"},
            "template": header_template,
        },
        "elements": elements,
    }

    return card


def format_summary(
    positions: List[Dict],
    realtime_data: Dict[str, Dict],
    index_data: Dict[str, Dict],
    analyses: Dict[str, Dict],
) -> str:
    """格式化持仓摘要"""
    now = datetime.now(_CST).strftime("%Y-%m-%d %H:%M")

    lines = [f"## 📋 持仓摘要 ({now})", ""]

    # 大盘
    if index_data:
        parts = []
        for code, data in index_data.items():
            name = data.get("name", code)
            change = data.get("change_pct", 0)
            sign = "+" if change > 0 else ""
            parts.append(f"{name} {sign}{change:.2f}%")
        lines.append("**大盘**: " + " | ".join(parts))
        lines.append("")

    if not positions:
        lines.append("暂无持仓")
        return "\n".join(lines)

    # 持仓表格
    lines.append("| 名称 | 代码 | 数量 | 成本 | 现价 | 盈亏 | 盈亏率 |")
    lines.append("|------|------|------|------|------|------|--------|")

    total_cost = 0
    total_market = 0

    for pos in positions:
        code = pos.get("股票代码", "")
        name = pos.get("名称", "")
        shares = pos.get("持股数量", 0)
        cost = pos.get("成本价", 0)

        rt = realtime_data.get(code, {})
        price = rt.get("price", 0)
        change = rt.get("change_pct", 0)

        if price and cost:
            pnl_pct = (price - cost) / cost * 100
            pnl_amt = (price - cost) * shares
            sign = "+" if pnl_pct > 0 else ""
            color = "🔴" if pnl_pct < 0 else "🟢"
            total_cost += cost * shares
            total_market += price * shares
            lines.append(f"| {name} | {code} | {shares} | {cost:.2f} | {price:.2f} | {color}{sign}{pnl_amt:,.0f} | {sign}{pnl_pct:.1f}% |")
        else:
            lines.append(f"| {name} | {code} | {shares} | {cost:.2f} | - | - | - |")

    # 汇总
    total_pnl = total_market - total_cost
    total_pnl_pct = total_pnl / total_cost * 100 if total_cost > 0 else 0
    sign = "+" if total_pnl > 0 else ""
    lines.append("")
    lines.append(f"**总市值**: {total_market:,.0f}元 | **总盈亏**: {sign}{total_pnl:,.0f}元 ({sign}{total_pnl_pct:.1f}%)")

    return "\n".join(lines)


# ============================================================
# 主调度器
# ============================================================

class Watchdog:
    def __init__(self, config: dict):
        self.config = config
        # 优先使用 QMT 数据源，不可用时回退到 HTTP 源
        qmt_fetcher = QmtFetcher(timeout=config.get("data_source", {}).get("timeout", 10))
        if qmt_fetcher.fetch_batch(["000001"]):
            self.fetcher = qmt_fetcher
            logger.info("数据源: QMT (Windows 行情转发)")
        else:
            self.fetcher = RealtimeFetcher(timeout=config.get("data_source", {}).get("timeout", 10))
            logger.warning("QMT 不可用，回退到东方财富 HTTP 数据源")
        self.store = StateStore(config.get("storage", {}).get("db_path", str(current_dir / "watchdog.db")))
        self.notifier = Notifier(config)

        self.running = True
        self.start_time = datetime.now(_CST)
        self.scan_count = 0

        # 加载数据
        self.positions = load_positions()
        self.watchlist_codes = load_watchlist_codes()

        # 合并监控列表：持仓 + 自选股
        position_codes = [p.get("股票代码") for p in self.positions if p.get("股票代码")]
        self.all_codes = list(set(position_codes + self.watchlist_codes))

        self.index_codes = {
            "000001": "上证指数",
            "399001": "深证成指",
            "000300": "沪深300",
            "399006": "创业板指",
        }

        self.dedup_window = config.get("notification", {}).get("dedup_window_seconds", 300)

        # 初始化缠论知识库（Qdrant）
        self.knowledge_base = None
        if ChanlunKnowledgeBase is not None:
            try:
                kb = ChanlunKnowledgeBase()
                if kb.is_available():
                    self.knowledge_base = kb
                    logger.info("缠论知识库已连接 (Qdrant)")
                else:
                    logger.info("缠论知识库服务未运行，跳过")
            except Exception as e:
                logger.warning(f"缠论知识库连接失败: {e}")

    def scan_once(self, specific_codes: List[str] = None) -> List[Dict]:
        """执行一次扫描"""
        self.scan_count += 1
        codes = specific_codes or self.all_codes
        logger.info(f"=== 第 {self.scan_count} 次扫描 ({len(codes)} 只) ===")

        # 1. 获取实时行情
        logger.info("获取实时行情...")
        realtime_data = self.fetcher.fetch_batch(codes)
        logger.info(f"获取到 {len(realtime_data)} 只有效数据")

        # 2. 获取大盘指数
        index_data = self.fetcher.fetch_indices(self.index_codes)

        # 3. 缠论分析（仅对有K线数据的股票）
        analyses = {}
        if HAS_CHANLUN:
            analysis_type = "多级别联立分析" if HAS_MULTI_LEVEL else "单级别分析"
            logger.info(f"缠论分析中（{analysis_type}）...")
            for i, code in enumerate(codes):
                if i % 20 == 0 and i > 0:
                    logger.info(f"  进度: {i}/{len(codes)}")
                kline = fetch_kline(code)
                if not kline.empty:
                    analysis = analyze_stock(code, kline, self.config)
                    # 补充名称
                    if code in realtime_data:
                        analysis["name"] = realtime_data[code].get("name", "")
                    analyses[code] = analysis
                time.sleep(0.2)  # 避免请求过快
            logger.info(f"完成分析: {len(analyses)} 只")

        # 4. 检测报警
        alerts = []

        # 持仓报警
        pos_alerts = check_position_alerts(self.positions, realtime_data, self.config)
        alerts.extend(pos_alerts)

        # 信号报警（带知识库规则参考）
        sig_alerts = check_signal_alerts(analyses, self.positions, self.config, self.knowledge_base)
        alerts.extend(sig_alerts)

        logger.info(f"检测到 {len(alerts)} 条报警")

        # 5. 去重并推送
        new_alerts = []
        for alert in alerts:
            dedup_key = f"{alert['code']}_{alert['type']}"
            if not self.store.was_alerted(dedup_key, alert["type"], self.dedup_window):
                new_alerts.append(alert)
                self.store.record_alert(dedup_key, alert["type"], alert["message"], alert.get("price", 0))

        # 精简推送：只推2类关键消息到飞书
        # 1) 持仓大幅波动(±5%)或触发止损
        # 2) 高评分买入信号（评分>=80，仅限持仓股）
        critical_alerts = []
        for a in new_alerts:
            atype = a.get("type", "")
            score = a.get("score", 0)
            is_position = atype.startswith("position_")
            is_buy = "buy" in atype
            is_loss_or_profit = is_position and abs(a.get("change_pct", 0)) >= 5

            if is_loss_or_profit:
                # 持仓±5%或止损 → 必须推送
                a["message"] = "🔔 " + a.get("message", "")
                critical_alerts.append(a)
            elif is_position and "loss" in atype:
                # 持仓亏损报警（含跌破止损线）
                critical_alerts.append(a)
            elif is_buy and score >= 80 and self.positions:
                # 高评分买入信号（持仓股出现买点）
                pos_codes = {p.get("股票代码") for p in self.positions}
                if a.get("code") in pos_codes:
                    critical_alerts.append(a)

        if critical_alerts:
            max_per_card = 15
            logger.info(f"精简推送: {len(critical_alerts)}/{len(new_alerts)} 条关键报警")
            for i in range(0, len(critical_alerts), max_per_card):
                batch = critical_alerts[i:i + max_per_card]
                card = build_alert_card(batch, index_data)
                if card:
                    logger.info(f"推送卡片 [{i//max_per_card + 1}/{(len(critical_alerts)-1)//max_per_card + 1}]")
                    self.notifier.send_card(card)
                    time.sleep(0.5)
        elif new_alerts:
            logger.info(f"无关键报警，跳过推送 ({len(new_alerts)} 条非关键信号)")
        else:
            logger.info("无新报警")

        # 6. 保存状态
        all_data = {**realtime_data, **index_data}
        if all_data:
            self.store.update_prices(all_data)

        # 6.5 写入通知文件（供 Dashboard 读取）
        self._write_notifications(new_alerts, index_data)

        # 7. 打印摘要
        self._print_summary(realtime_data, index_data, analyses)

        return alerts

    def _write_notifications(self, alerts: List[Dict], index_data: Dict):
        """将本次报警写入通知文件（供 Dashboard 读取）"""
        try:
            now = datetime.now(_CST)
            notif_path = current_dir / "notifications.json"
            max_alerts = 200

            # 读取已有记录
            existing = []
            if notif_path.exists():
                try:
                    with open(notif_path, "r", encoding="utf-8") as f:
                        old = json.load(f)
                    existing = old.get("alerts", [])
                except:
                    existing = []

            # 为每条报警加上时间和级别中文
            level_cn = {"daily": "日线", "15min": "15分钟"}

            # 大盘概要
            index_summary = {}
            if index_data:
                for code, data in index_data.items():
                    name = data.get("name", code)
                    change = data.get("change_pct", 0)
                    sign = "+" if change > 0 else ""
                    index_summary[name] = f"{sign}{change:.2f}%"

            new_entries = []
            for a in alerts:
                sig_level = a.get("signal_level", "")
                level_label = level_cn.get(sig_level, "")
                new_entries.append({
                    "code": a.get("code", ""),
                    "name": a.get("name", ""),
                    "type": a.get("type", ""),
                    "level": a.get("level", "info"),
                    "message": a.get("message", ""),
                    "price": a.get("price", 0),
                    "score": a.get("score", 0),
                    "signal_level": sig_level,
                    "signal_level_cn": level_label,
                    "action": a.get("action", ""),
                    "time": now.strftime("%H:%M:%S"),
                    "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
                })

            # 合并：新报警放前面
            all_alerts = new_entries + existing
            all_alerts = all_alerts[:max_alerts]

            data = {
                "updated_at": now.strftime("%H:%M:%S"),
                "update_time": now.strftime("%Y-%m-%d %H:%M:%S"),
                "indices": index_summary,
                "alert_count": len(new_entries),
                "total_alerts": len(all_alerts),
                "alerts": all_alerts,
            }

            with open(notif_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

        except Exception as e:
            logger.warning(f"写入通知文件失败: {e}")

    def _print_summary(self, realtime_data, index_data, analyses):
        """打印扫描摘要"""
        if index_data:
            parts = []
            for code, data in index_data.items():
                name = data.get("name", code)
                change = data.get("change_pct", 0)
                sign = "+" if change > 0 else ""
                parts.append(f"{name} {sign}{change:.2f}%")
            logger.info(f"大盘: {' | '.join(parts)}")

        # 持仓盈亏
        total_pnl = 0
        for pos in self.positions:
            code = pos.get("股票代码", "")
            cost = pos.get("成本价", 0)
            shares = pos.get("持股数量", 0)
            rt = realtime_data.get(code, {})
            price = rt.get("price", 0)
            if price and cost:
                total_pnl += (price - cost) * shares
        logger.info(f"持仓总盈亏: {total_pnl:,.0f}元")

        # 缠论信号
        buy_count = sum(1 for a in analyses.values() if a.get("chanlun") and a["chanlun"].get("signals"))
        logger.info(f"有信号的股票: {buy_count} 只")

    def run_forever(self, specific_codes: List[str] = None):
        interval = self.config.get("schedule", {}).get("interval_seconds", 60)
        run_outside = self.config.get("schedule", {}).get("run_outside_hours", False)

        logger.info("=" * 50)
        logger.info("盯盘系统启动（交易联动版）")
        logger.info(f"持仓股票: {len(self.positions)} 只")
        logger.info(f"自选股: {len(self.watchlist_codes)} 只")
        logger.info(f"总计监控: {len(self.all_codes)} 只")
        logger.info(f"扫描间隔: {interval} 秒")
        chanlun_status = "不可用"
        if HAS_CHANLUN:
            chanlun_status = "多级别联立分析" if HAS_MULTI_LEVEL else "单级别分析"
        logger.info(f"缠论分析: {chanlun_status}")
        logger.info("=" * 50)

        # 启动通知
        pos_summary = f"持仓{len(self.positions)}只 | 自选{len(self.watchlist_codes)}只"
        self.notifier.send_text(f"🟢 盯盘系统已启动\n\n{pos_summary}\n扫描间隔: {interval}秒")

        while self.running:
            try:
                if is_trading_hours() or run_outside:
                    self.scan_once(specific_codes)
                else:
                    status = get_market_status()
                    logger.info(f"非交易时段 ({status})，等待...")

                time.sleep(interval)
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"扫描异常: {e}", exc_info=True)
                time.sleep(interval)

        self.notifier.send_text("🔴 盯盘系统已停止")
        logger.info("盯盘系统已停止")

    def get_status(self) -> Dict:
        uptime = datetime.now(_CST) - self.start_time
        hours, remainder = divmod(int(uptime.total_seconds()), 3600)
        minutes, _ = divmod(remainder, 60)

        return {
            "state": "运行中" if self.running else "已停止",
            "market_status": get_market_status(),
            "position_count": len(self.positions),
            "watchlist_count": len(self.watchlist_codes),
            "total_count": len(self.all_codes),
            "scan_count": self.scan_count,
            "uptime": f"{hours}小时{minutes}分",
            "chanlun": "多级别联立分析" if HAS_MULTI_LEVEL else ("单级别分析" if HAS_CHANLUN else "不可用"),
        }


def main():
    parser = argparse.ArgumentParser(description="盯盘系统（交易联动版）")
    parser.add_argument("--config", type=str, help="配置文件路径")
    parser.add_argument("--once", action="store_true", help="扫描一次后退出")
    parser.add_argument("--test", action="store_true", help="测试模式")
    parser.add_argument("--status", action="store_true", help="查看状态")
    parser.add_argument("--stocks", type=str, help="只扫描指定股票，逗号分隔")
    args = parser.parse_args()

    config = load_config(args.config)
    if args.test:
        config.setdefault("schedule", {})["run_outside_hours"] = True

    dog = Watchdog(config)

    if args.status:
        print(json.dumps(dog.get_status(), ensure_ascii=False, indent=2))
        return

    def signal_handler(sig, frame):
        dog.running = False

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    specific = args.stocks.split(",") if args.stocks else None

    if args.once:
        dog.scan_once(specific)
    else:
        dog.run_forever(specific)


if __name__ == "__main__":
    main()
