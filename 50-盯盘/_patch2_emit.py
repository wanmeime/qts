#!/usr/bin/env python3
"""Modify _emit_result in signal_monitor.py to send Feishu card for stop_loss"""
path = "/home/jiaod/qts/50-盯盘/signal_monitor.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

old = """    def _emit_result(self, result: SignalMatchResult):
        \"\"\"输出信号结果\"\"\"
        notification = result.to_notification()

        # 回调
        if self.on_signal:
            try:
                self.on_signal(result)
            except Exception as e:
                logger.error(f\"信号回调异常: {e}\")

        # 通知
        if self.notifier:
            try:
                self.notifier.send(notification)
            except Exception as e:
                logger.error(f\"发送通知异常: {e}\")"""

new = """    def _emit_result(self, result: SignalMatchResult):
        \"\"\"输出信号结果\"\"\"
        notification = result.to_notification()

        # 回调
        if self.on_signal:
            try:
                self.on_signal(result)
            except Exception as e:
                logger.error(f\"信号回调异常: {e}\")

        # 通知
        if self.notifier:
            try:
                # 止损信号发飞书互动卡片（带"已收到"按钮）
                if result.action == \"stop_loss\":
                    card = self._build_stop_loss_card(result)
                    self.notifier.send_card(card)
                else:
                    self.notifier.send(notification)
            except Exception as e:
                logger.error(f\"发送通知异常: {e}\")"""

if old in content:
    content = content.replace(old, new)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("OK: _emit_result updated")
else:
    print("FAIL: _emit_result not found")
    idx = content.find("def _emit_result")
    if idx >= 0:
        print(f"Found at {idx}")
        print(content[idx:idx+500])
