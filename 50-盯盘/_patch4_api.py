#!/usr/bin/env python3
"""Update dashboard_server.py: make acknowledge API support GET+POST"""
path = "/home/jiaod/qts/50-盯盘/dashboard_server.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

old = '@app.post("/api/signal/acknowledge/{signal_id}")\ndef acknowledge_signal(signal_id: int, notes: str = ""):'

new = '@app.api_route("/api/signal/acknowledge/{signal_id}", methods=["GET", "POST"])\ndef acknowledge_signal(signal_id: int, notes: str = ""):'

if old in content:
    content = content.replace(old, new)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("OK: acknowledge API updated")
else:
    print("FAIL: not found")
    idx = content.find("api/signal/acknowledge")
    if idx >= 0:
        print(f"Found at {idx}: {content[idx:idx+100]}")
