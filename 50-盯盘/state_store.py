#!/usr/bin/env python3
"""
状态持久化模块
存储上次价格、已触发报警记录，避免重复推送
"""
import sqlite3
import json
import logging
from typing import Dict, List, Optional
from datetime import datetime, timezone, timedelta

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
