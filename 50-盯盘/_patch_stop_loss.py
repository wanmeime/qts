#!/usr/bin/env python3
"""Update signal_monitor.py: stop_loss repeat until acknowledged"""
path = "/home/jiaod/qts/50-盯盘/signal_monitor.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

old_block = """        # 止损 → 一次性通知，从缓存移除防重复
        if stop_loss and price <= stop_loss:
            self.state_store.update_signal_status(rec["id"], "activated", {
                "triggered_at": datetime.now(_CST).strftime("%Y-%m-%d %H:%M:%S"),
                "triggered_price": price,
            })
            self._remove_signal_from_cache("position_risk", rec["id"])
            return SignalMatchResult(
                signal_id=rec["id"], stock_code=code,
                stock_name=data.get("stock_name", code),
                signal_type="position_risk", label=None,
                action="stop_loss",
                message=f"🚨 止损！{data.get('stock_name', code)} 现价 {price:.2f}，跌破止损 {stop_loss:.2f}，盈亏 {profit_pct:.1f}%  (ID:{rec['id']} 确认: http://172.31.144.1:8891/api/signal/acknowledge/{rec['id']})",
                price=price,
            )"""

new_block = """        # 止损 → 重复通知（5分钟间隔）直到用户点"已收到"
        if stop_loss and price <= stop_loss:
            # 查DB看用户是否已确认
            db_records = self.state_store.load_signal_templates(signal_type="position_risk", stock_code=code)
            for r in db_records:
                if r["id"] == rec["id"] and r["status"] in ("acknowledged", "completed"):
                    self._remove_signal_from_cache("position_risk", rec["id"])
                    return None

            # 去重：5分钟内不重复发
            if self.state_store.was_alerted(code, "stop_loss", 300):
                return None

            self.state_store.update_signal_status(rec["id"], "activated", {
                "triggered_at": datetime.now(_CST).strftime("%Y-%m-%d %H:%M:%S"),
                "triggered_price": price,
            })
            self.state_store.record_alert(code, "stop_loss", f"止损{stop_loss}", price)
            return SignalMatchResult(
                signal_id=rec["id"], stock_code=code,
                stock_name=data.get("stock_name", code),
                signal_type="position_risk", label=None,
                action="stop_loss",
                message=f"🚨 止损！{data.get('stock_name', code)} 现价 {price:.2f}，跌破止损 {stop_loss:.2f}，盈亏 {profit_pct:.1f}%  (ID:{rec['id']})",
                price=price,
            )"""

if old_block in content:
    content = content.replace(old_block, new_block)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("OK: signal_monitor.py stop_loss logic updated")
else:
    print("FAIL: old_block not found")
    # debug: find stop_loss
    idx = content.find("remove_signal_from_cache")
    if idx >= 0:
        print(f"Found at {idx}: ...{content[idx-30:idx+80]}...")
