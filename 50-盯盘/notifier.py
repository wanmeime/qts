#!/usr/bin/env python3
"""
通知模块
封装飞书推送
"""
import subprocess
import json
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

LARK_CLI = "/home/jiaod/.npm-global/bin/lark-cli"
WORK_DIR = "/home/jiaod/qts"


class Notifier:
    """通知器"""

    def __init__(self, config: dict):
        self.config = config.get("notification", {})
        self.feishu_cfg = self.config.get("feishu", {})
        self.chat_id = self.feishu_cfg.get("chat_id", "oc_d2e8df3c676afa2c352d8ece0a9b6141")

    def send_text(self, text: str) -> bool:
        """发送文本消息"""
        if not self.feishu_cfg.get("enabled", True):
            logger.info("飞书推送未启用，跳过")
            return False

        cmd = [
            LARK_CLI, "im", "+messages-send",
            "--chat-id", self.chat_id,
            "--text", text,
            "--as", "bot"
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=WORK_DIR)
            if result.returncode == 0:
                data = json.loads(result.stdout)
                if data.get("ok"):
                    logger.debug("飞书推送成功")
                    return True
                else:
                    logger.warning(f"飞书推送失败: {data}")
            else:
                logger.warning(f"飞书推送失败: {result.stderr}")
        except Exception as e:
            logger.error(f"飞书推送异常: {e}")

        return False

    def send_markdown(self, content: str) -> bool:
        """发送 Markdown 消息"""
        if not self.feishu_cfg.get("enabled", True):
            logger.info("飞书推送未启用，跳过")
            return False

        cmd = [
            LARK_CLI, "im", "+messages-send",
            "--chat-id", self.chat_id,
            "--markdown", content,
            "--as", "bot"
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=WORK_DIR)
            if result.returncode == 0:
                data = json.loads(result.stdout)
                if data.get("ok"):
                    logger.debug("飞书 Markdown 推送成功")
                    return True
                else:
                    logger.warning(f"飞书 Markdown 推送失败: {data}")
            else:
                logger.warning(f"飞书 Markdown 推送失败: {result.stderr}")
        except Exception as e:
            logger.error(f"飞书 Markdown 推送异常: {e}")

        return False

    def send_alerts(self, message: str) -> bool:
        """发送报警消息"""
        if not message:
            return False
        return self.send_markdown(message)

    def send_card(self, card_json: dict) -> bool:
        """
        发送飞书 interactive 卡片消息

        card_json: Feishu 卡片 JSON 结构（不含外层 msg_type 包装）
        """
        if not self.feishu_cfg.get("enabled", True):
            logger.info("飞书推送未启用，跳过")
            return False

        content = json.dumps(card_json, ensure_ascii=False)
        cmd = [
            LARK_CLI, "im", "+messages-send",
            "--chat-id", self.chat_id,
            "--msg-type", "interactive",
            "--content", content,
            "--as", "bot"
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=WORK_DIR)
            if result.returncode == 0:
                data = json.loads(result.stdout)
                if data.get("ok"):
                    logger.debug("飞书卡片推送成功")
                    return True
                else:
                    logger.warning(f"飞书卡片推送失败: {data}")
            else:
                logger.warning(f"飞书卡片推送失败: {result.stderr}")
        except Exception as e:
            logger.error(f"飞书卡片推送异常: {e}")

        return False

    def send_status_report(self, status: Dict) -> bool:
        """发送状态报告"""
        lines = [
            "## 📊 盯盘系统状态",
            "",
            f"- 运行状态: {status.get('state', '未知')}",
            f"- 市场状态: {status.get('market_status', '未知')}",
            f"- 监控股票: {status.get('stock_count', 0)} 只",
            f"- 本次扫描: {status.get('scan_count', 0)} 只",
            f"- 报警数量: {status.get('alert_count', 0)} 条",
            f"- 运行时长: {status.get('uptime', 'N/A')}",
            f"- 最后扫描: {status.get('last_scan', 'N/A')}",
        ]

        return self.send_markdown("\n".join(lines))
