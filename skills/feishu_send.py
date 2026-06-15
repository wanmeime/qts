#!/usr/bin/env python3
"""
飞书消息发送模块
使用 lark-cli 向飞书群发送文件或消息
"""
import subprocess
import os
import shutil
import json
from typing import Dict, Optional

LARK_CLI = "/home/jiaod/.npm-global/bin/lark-cli"
WORK_DIR = "/home/jiaod/qts"


def send_file_to_feishu(chat_id: str, file_path: str) -> Dict:
    """发送文件到飞书群
    
    Args:
        chat_id: 飞书群 ID (oc_xxxxxxxx)
        file_path: 文件路径（绝对路径或相对路径）
    
    Returns:
        dict: {"ok": True/False, "message_id": "..."}
    """
    # 如果是 Windows 路径，转换为 WSL 路径
    if file_path.startswith("D:\\") or file_path.startswith("D:/"):
        file_path = file_path.replace("D:\\", "/mnt/d/").replace("D:/", "/mnt/d/")
    
    # 获取文件名（lark-cli 需要相对路径）
    file_name = os.path.basename(file_path)
    
    # 复制文件到工作目录（lark-cli 要求相对路径）
    dest = os.path.join(WORK_DIR, file_name)
    shutil.copy2(file_path, dest)
    
    # 发送文件
    cmd = [
        LARK_CLI, "im", "+messages-send",
        "--chat-id", chat_id,
        "--file", file_name,
        "--as", "bot"
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=WORK_DIR)
        
        if result.returncode == 0:
            return json.loads(result.stdout)
        else:
            return {"ok": False, "error": result.stderr}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def send_markdown_to_feishu(chat_id: str, content: str) -> Dict:
    """发送 Markdown 消息到飞书群
    
    Args:
        chat_id: 飞书群 ID
        content: Markdown 格式内容
    
    Returns:
        dict: {"ok": True/False, "message_id": "..."}
    """
    cmd = [
        LARK_CLI, "im", "+messages-send",
        "--chat-id", chat_id,
        "--markdown", content,
        "--as", "bot"
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            return json.loads(result.stdout)
        else:
            return {"ok": False, "error": result.stderr}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# 常用 Chat ID
CHAT_IDS = {
    "QTS市场分析": "oc_d2e8df3c676afa2c352d8ece0a9b6141",
}
