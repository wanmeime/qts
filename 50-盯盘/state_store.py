#!/usr/bin/env python3
"""
状态持久化模块
存储上次价格、已触发报警记录，避免重复推送
"""
import sqlite3
import json
import logging
from typing import Dict, List, Optional, Any, Union
from dataclasses import asdict
from datetime import datetime, timezone, timedelta

# 信号模板导入
from signal_templates import (
    BottomFractalSignal, TopFractalSignal,
    DivergenceZoneSignal, PositionRiskSignal,
    SignalStatus, DivergenceStatus, RiskLevel,
    BuySellLabel,
)

logger = logging.getLogger(__name__)

_CST = timezone(timedelta(hours=8))


class StateStore:
    """状态存储（SQLite）"""

    def __init__(self, db_path: str = "/home/jiaod/qts/50-盯盘/watchdog.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """初始化数据库"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 上次价格表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS last_prices (
                code TEXT PRIMARY KEY,
                name TEXT,
                price REAL,
                change_pct REAL,
                volume REAL,
                updated_at TEXT
            )
        """)

        # 报警记录表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS alert_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT,
                alert_type TEXT,
                message TEXT,
                price REAL,
                created_at TEXT
            )
        """)

        # 每日行情快照
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_snapshot (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT,
                name TEXT,
                price REAL,
                change_pct REAL,
                volume REAL,
                snapshot_date TEXT,
                snapshot_time TEXT
            )
        """)

        # 信号模板表（统一存储4类信号，用 signal_type 区分）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS signal_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_type TEXT NOT NULL,
                stock_code TEXT NOT NULL,
                data JSON NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_signal_type_code
            ON signal_templates (signal_type, stock_code)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_signal_status
            ON signal_templates (status)
        """)

        conn.commit()
        conn.close()

    def update_prices(self, prices: Dict[str, Dict]):
        """批量更新价格"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        now = datetime.now(_CST).strftime("%Y-%m-%d %H:%M:%S")

        for code, data in prices.items():
            cursor.execute("""
                INSERT OR REPLACE INTO last_prices (code, name, price, change_pct, volume, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                code,
                data.get("name", ""),
                data.get("price", 0),
                data.get("change_pct", 0),
                data.get("volume", 0),
                now,
            ))

        conn.commit()
        conn.close()

    def get_last_price(self, code: str) -> Optional[Dict]:
        """获取上次价格"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM last_prices WHERE code = ?", (code,))
        row = cursor.fetchone()
        conn.close()

        if row:
            return {
                "code": row[0],
                "name": row[1],
                "price": row[2],
                "change_pct": row[3],
                "volume": row[4],
                "updated_at": row[5],
            }
        return None

    def was_alerted(self, code: str, alert_type: str, window_seconds: int = 300) -> bool:
        """检查是否已在时间窗口内触发过同类报警"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cutoff = (datetime.now(_CST) - timedelta(seconds=window_seconds)).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("""
            SELECT COUNT(*) FROM alert_history
            WHERE code = ? AND alert_type = ? AND created_at > ?
        """, (code, alert_type, cutoff))

        count = cursor.fetchone()[0]
        conn.close()
        return count > 0

    def record_alert(self, code: str, alert_type: str, message: str, price: float = 0):
        """记录报警"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        now = datetime.now(_CST).strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute("""
            INSERT INTO alert_history (code, alert_type, message, price, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (code, alert_type, message, price, now))

        conn.commit()
        conn.close()

    def save_snapshot(self, prices: Dict[str, Dict]):
        """保存行情快照"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        now = datetime.now(_CST)
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%S")

        for code, data in prices.items():
            cursor.execute("""
                INSERT INTO daily_snapshot (code, name, price, change_pct, volume, snapshot_date, snapshot_time)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                code,
                data.get("name", ""),
                data.get("price", 0),
                data.get("change_pct", 0),
                data.get("volume", 0),
                date_str,
                time_str,
            ))

        conn.commit()
        conn.close()

    # ================================================================
    # 信号模板 CRUD
    # ================================================================

    def save_signal_templates(self, signals: List[Any]):
        """
        批量保存信号模板（先清空同一 analysis_date 的旧数据再写入）
        signals 是 BottomFractalSignal / TopFractalSignal / 等 dataclass 列表
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        for sig in signals:
            sig_dict = asdict(sig)
            # 将枚举类型转为字符串
            sig_dict = self._serialize_enums(sig_dict)
            signal_type = self._signal_type_name(sig)
            cursor.execute("""
                INSERT INTO signal_templates (signal_type, stock_code, data, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                signal_type,
                sig.stock_code,
                json.dumps(sig_dict, ensure_ascii=False),
                sig_dict.get("status", "pending"),
                sig_dict.get("created_at", ""),
                sig_dict.get("updated_at", ""),
            ))

        conn.commit()
        conn.close()

    @staticmethod
    def _serialize_enums(d: dict) -> dict:
        """递归将字典中的枚举值转为字符串"""
        result = {}
        for k, v in d.items():
            if isinstance(v, dict):
                result[k] = StateStore._serialize_enums(v)
            elif hasattr(v, 'value'):  # Enum
                result[k] = v.value
            else:
                result[k] = v
        return result

    def clear_signal_templates(self, signal_type: Optional[str] = None, stock_code: Optional[str] = None):
        """清除信号模板（盘后重跑前调用）"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        conditions = []
        params = []
        if signal_type:
            conditions.append("signal_type = ?")
            params.append(signal_type)
        if stock_code:
            conditions.append("stock_code = ?")
            params.append(stock_code)

        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        cursor.execute(f"DELETE FROM signal_templates{where}", params)
        conn.commit()
        conn.close()

    def load_signal_templates(
        self,
        signal_type: Optional[str] = None,
        status: Optional[str] = None,
        stock_code: Optional[str] = None,
    ) -> List[Dict]:
        """
        按条件查询信号模板
        返回 dict 列表（data 字段已解析）
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        conditions = []
        params = []
        if signal_type:
            conditions.append("signal_type = ?")
            params.append(signal_type)
        if status:
            conditions.append("status = ?")
            params.append(status)
        if stock_code:
            conditions.append("stock_code = ?")
            params.append(stock_code)

        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        cursor.execute(f"SELECT id, signal_type, stock_code, data, status, created_at, updated_at FROM signal_templates{where} ORDER BY id", params)

        results = []
        for row in cursor.fetchall():
            results.append({
                "id": row[0],
                "signal_type": row[1],
                "stock_code": row[2],
                "data": json.loads(row[3]),
                "status": row[4],
                "created_at": row[5],
                "updated_at": row[6],
            })

        conn.close()
        return results

    def update_signal_status(self, signal_id: int, new_status: str, extra: Optional[Dict] = None):
        """
        更新单个信号模板的状态

        参数：
          - signal_id: 信号模板的 id
          - new_status: 新状态（pending/activated/invalidated/expired）
          - extra: 附加字段（如 triggered_at, triggered_price 等，合并到 data 字段）
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        now = datetime.now(_CST).strftime("%Y-%m-%d %H:%M:%S")

        # 先读取当前 data
        cursor.execute("SELECT data FROM signal_templates WHERE id = ?", (signal_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return

        data = json.loads(row[0])
        data["status"] = new_status
        data["updated_at"] = now
        if extra:
            data.update(extra)

        cursor.execute("""
            UPDATE signal_templates SET data = ?, status = ?, updated_at = ?
            WHERE id = ?
        """, (json.dumps(data, ensure_ascii=False), new_status, now, signal_id))

        conn.commit()
        conn.close()

    def get_pending_signals(self, stock_code: Optional[str] = None) -> List[Dict]:
        """获取所有 PENDING 状态的信号模板"""
        return self.load_signal_templates(status="pending", stock_code=stock_code)

    @staticmethod
    def _signal_type_name(signal_obj: Any) -> str:
        """根据 dataclass 类型返回信号类型名称"""
        type_map = {
            BottomFractalSignal: "bottom_fractal",
            TopFractalSignal: "top_fractal",
            DivergenceZoneSignal: "divergence_zone",
            PositionRiskSignal: "position_risk",
        }
        return type_map.get(type(signal_obj), "unknown")

    def cleanup_old_data(self, retention_days: int = 30):
        """清理过期数据"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cutoff = (datetime.now(_CST) - timedelta(days=retention_days)).strftime("%Y-%m-%d")

        cursor.execute("DELETE FROM alert_history WHERE created_at < ?", (cutoff,))
        cursor.execute("DELETE FROM daily_snapshot WHERE snapshot_date < ?", (cutoff,))

        conn.commit()
        conn.close()

    def get_alert_stats(self, days: int = 7) -> Dict:
        """获取报警统计"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cutoff = (datetime.now(_CST) - timedelta(days=days)).strftime("%Y-%m-%d")

        cursor.execute("""
            SELECT alert_type, COUNT(*) as cnt
            FROM alert_history
            WHERE created_at > ?
            GROUP BY alert_type
            ORDER BY cnt DESC
        """, (cutoff,))

        stats = {}
        for row in cursor.fetchall():
            stats[row[0]] = row[1]

        conn.close()
        return stats
