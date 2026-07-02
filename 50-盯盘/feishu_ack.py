#!/usr/bin/env python3
"""
飞书消息监听模块 —— 识别用户回复的"确认 {id}"并自动处理确认。

通过 lark-cli 定时轮询飞书群消息，匹配用户回复的确认指令。
"""
import json
import logging
import re
import subprocess
import time
import threading
from typing import Optional, Set

logger = logging.getLogger(__name__)

LARK_CLI = "/home/jiaod/.npm-global/bin/lark-cli"
CHAT_ID = "oc_d2e8df3c676afa2c352d8ece0a9b6141"
POLL_INTERVAL = 30  # 每30秒检查一次


class FeishuAckListener:
    """飞书确认指令监听器"""

    def __init__(self, state_store=None):
        self.state_store = state_store
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._processed_ids: Set[str] = set()  # 已处理的消息ID，防重复

    def start(self):
        """启动监听线程"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="feishu-ack")
        self._thread.start()
        logger.info("飞书确认监听已启动")

    def stop(self):
        """停止监听"""
        self._running = False
        logger.info("飞书确认监听已停止")

    def _poll_loop(self):
        """轮询主循环"""
        while self._running:
            try:
                self._check_messages()
            except Exception as e:
                logger.error(f"飞书消息检查异常: {e}")
            time.sleep(POLL_INTERVAL)

    def _check_messages(self):
        """检查最新消息，匹配确认指令"""
        try:
            result = subprocess.run(
                [LARK_CLI, "im", "+chat-messages-list",
                 "--chat-id", CHAT_ID, "--page-size", "10",
                 "--as", "bot", "--json"],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode != 0:
                return

            data = json.loads(result.stdout)
            if not data.get("ok"):
                return

            messages = data.get("data", {}).get("messages", [])
            for msg in messages:
                self._process_message(msg)

        except subprocess.TimeoutExpired:
            logger.debug("飞书消息列表超时")
        except Exception as e:
            logger.debug(f"飞书消息检查失败: {e}")

    def _process_message(self, msg: dict):
        """处理单条消息"""
        msg_id = msg.get("message_id", "")
        if msg_id in self._processed_ids:
            return

        # 只处理用户发送的消息，忽略机器人自己的
        sender = msg.get("sender", {})
        if sender.get("sender_type") == "app":
            self._processed_ids.add(msg_id)
            return

        content = msg.get("content", "")
        # 消息内容可能是JSON格式（如text类型），也可能是纯文本
        try:
            parsed = json.loads(content)
            content = parsed.get("text", content)
        except (json.JSONDecodeError, TypeError):
            pass

        # 匹配 "确认 123" 格式，或单独的信号ID数字（如 1782455808339）
        match = re.search(r"确认\s*(\d+)", content)
        if not match:
            # 也接受单独的数字（至少8位，避免误匹配日常小数字）
            match = re.search(r"^\s*(\d{8,})\s*$", content.strip())
        if not match:
            self._processed_ids.add(msg_id)
            return

        signal_id = int(match.group(1))
        logger.info(f"收到确认指令: 消息={msg_id}, 信号ID={signal_id}")

        # 调用 acknowledge
        if self.state_store:
            ok = self.state_store.acknowledge_signal(signal_id, notes="飞书回复确认")
            if ok:
                logger.info(f"信号确认成功: ID={signal_id}")
                # 回复用户确认成功
                self._reply_message(msg_id, f"✅ 信号 #{signal_id} 已确认，不再重复通知")
            else:
                logger.warning(f"信号确认失败: ID={signal_id}（可能已确认或不存在）")
                self._reply_message(msg_id, f"⚠️ 信号 #{signal_id} 确认失败，可能已被确认过")

        self._processed_ids.add(msg_id)

    def _reply_message(self, reply_to_msg_id: str, text: str):
        """回复指定消息"""
        try:
            subprocess.run(
                [LARK_CLI, "im", "+messages-reply",
                 "--message-id", reply_to_msg_id,
                 "--text", text,
                 "--as", "bot"],
                capture_output=True, text=True, timeout=10,
            )
        except Exception as e:
            logger.debug(f"回复消息失败: {e}")
