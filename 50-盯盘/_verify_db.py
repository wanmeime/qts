import sqlite3
conn = sqlite3.connect("/home/jiaod/qts/50-盯盘/watchdog.db")
c = conn.cursor()
c.execute('SELECT COUNT(*) FROM signal_templates WHERE status="pending"')
print(f"pending信号数: {c.fetchone()[0]}")
c.execute('SELECT signal_type, COUNT(*) FROM signal_templates WHERE status="pending" GROUP BY signal_type')
for r in c.fetchall():
    print(f"  {r[0]}: {r[1]}")
conn.close()
