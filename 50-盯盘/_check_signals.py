import sqlite3, json
conn = sqlite3.connect("/home/jiaod/qts/50-盯盘/watchdog.db")
c = conn.cursor()
c.execute("SELECT id, signal_type, stock_code, status, data FROM signal_templates ORDER BY id")
for r in c.fetchall():
    print(f"ID={r[0]} type={r[1]} code={r[2]} status={r[3]}")
    d = json.loads(r[4])
    for k, v in d.items():
        print(f"  {k}={v}")
    print()
conn.close()
