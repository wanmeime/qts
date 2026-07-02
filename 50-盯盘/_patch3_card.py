#!/usr/bin/env python3
"""Add _build_stop_loss_card method to SignalMonitor class"""
path = "/home/jiaod/qts/50-盯盘/signal_monitor.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# Find the get_current_signals method and insert before it
anchor = "    def get_current_signals(self) -> Dict:"
insert_code = """    def _build_stop_loss_card(self, result: SignalMatchResult) -> dict:
        \"\"\"构建飞书止损通知卡片，带"已收到"按钮\"\"\"
        code = result.stock_code
        name = result.stock_name
        price = result.price
        msg = result.message
        sid = result.signal_id

        # 从消息中提取盈亏百分比
        profit_info = ""
        if "%" in msg:
            parts = msg.split("盈亏 ")
            if len(parts) > 1:
                profit_info = parts[1]

        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": f"\U0001f6a8 止损！{name}({code})"},
                "template": "red",
            },
            "elements": [
                {
                    "tag": "markdown",
                    "content": f"**{name}({code})** 触发止损\\n现价: **{price:.2f}**\\n盈亏: {profit_info}\\n信号ID: `{sid}`",
                },
                {
                    "tag": "hr",
                },
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "\u2705 已收到"},
                            "type": "primary",
                            "multi_url": {
                                "url": f"http://172.31.144.1:8891/api/signal/acknowledge/{sid}",
                                "android_url": "",
                                "ios_url": "",
                                "pc_url": "",
                            },
                        }
                    ],
                },
            ],
        }


"""

if anchor in content:
    content = content.replace(anchor, insert_code + anchor)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("OK: _build_stop_loss_card added")
else:
    print("FAIL: anchor not found")
    idx = content.find("def get_current_signals")
    if idx >= 0:
        print(f"Found at {idx}")
