#!/usr/bin/env python3
"""
飞书消息监听模块
定期检查飞书群消息，支持命令响应
"""
import subprocess
import json
import time
import sys
import os
from typing import Dict, List, Optional, Callable
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

LARK_CLI = "/home/jiaod/.npm-global/bin/lark-cli"
WORK_DIR = "/home/jiaod/qts"


class FeishuListener:
    """飞书消息监听器（支持群聊和私聊）"""
    
    def __init__(self, chat_id: str = None, user_id: str = None, poll_interval: int = 30):
        """
        Args:
            chat_id: 飞书群 ID（群聊）
            user_id: 用户 open_id（私聊）
            poll_interval: 轮询间隔（秒）
        """
        if not chat_id and not user_id:
            raise ValueError("必须提供 chat_id 或 user_id")
        
        self.chat_id = chat_id
        self.user_id = user_id
        self.poll_interval = poll_interval
        self.last_message_id = None
        self.command_handlers: Dict[str, Callable] = {}
        
    def register_command(self, command: str, handler: Callable):
        """注册命令处理函数
        
        Args:
            command: 命令名称（如 "生成报告"）
            handler: 处理函数，接收 message 字典，返回响应文本
        """
        self.command_handlers[command] = handler
        
    def get_recent_messages(self, limit: int = 5) -> List[Dict]:
        """获取最近消息（支持群聊和私聊）"""
        cmd = [
            LARK_CLI, "im", "+chat-messages-list",
            "--as", "bot",
            "--page-size", str(limit),
            "--sort", "desc"
        ]
        
        # 根据 chat_id 或 user_id 添加参数
        if self.chat_id:
            cmd.extend(["--chat-id", self.chat_id])
        else:
            cmd.extend(["--user-id", self.user_id])
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=WORK_DIR)
            if result.returncode == 0:
                data = json.loads(result.stdout)
                return data.get("data", {}).get("messages", [])
        except Exception as e:
            print(f"获取消息失败: {e}")
        return []
    
    def send_message(self, content: str, msg_type: str = "text") -> bool:
        """发送消息（支持群聊和私聊）
        
        Args:
            content: 消息内容
            msg_type: 消息类型 (text/markdown)
        """
        cmd = [
            LARK_CLI, "im", "+messages-send",
            f"--{msg_type}", content,
            "--as", "bot"
        ]
        
        # 根据 chat_id 或 user_id 添加参数
        if self.chat_id:
            cmd.extend(["--chat-id", self.chat_id])
        else:
            cmd.extend(["--user-id", self.user_id])
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=WORK_DIR)
            if result.returncode == 0:
                data = json.loads(result.stdout)
                return data.get("ok", False)
        except Exception as e:
            print(f"发送消息失败: {e}")
        return False
    
    def process_message(self, message: Dict) -> Optional[str]:
        """处理单条消息
        
        Args:
            message: 消息字典
        
        Returns:
            响应文本，如果不需要响应则返回 None
        """
        content = message.get("content", "")
        msg_type = message.get("msg_type", "")
        sender = message.get("sender", {})
        
        # 只处理文本消息，忽略 bot 自己的消息
        if msg_type != "text" or sender.get("sender_type") == "app":
            return None
        
        # 解析命令
        content = content.strip()
        
        # 检查是否匹配注册的命令
        for command, handler in self.command_handlers.items():
            if command in content:
                try:
                    return handler(message)
                except Exception as e:
                    return f"命令执行失败: {e}"
        
        # 默认响应
        if "报告" in content:
            return self._handle_report_command(content)
        elif "帮助" in content or "help" in content.lower():
            return self._handle_help_command()
        
        return None
    
    def _handle_report_command(self, content: str) -> str:
        """处理报告相关命令"""
        if "生成" in content:
            return "正在生成市场报告，请稍候..."
        elif "发送" in content:
            return "正在发送报告到飞书群..."
        else:
            return "可用命令：生成报告、发送报告、帮助"
    
    def _handle_help_command(self) -> str:
        """返回帮助信息"""
        return """📋 可用命令：
- 生成报告：生成最新的市场洞察报告
- 发送报告：将报告发送到飞书群
- 帮助：显示此帮助信息"""
    
    def poll_once(self) -> List[str]:
        """执行一次轮询，处理新消息
        
        Returns:
            处理的响应列表
        """
        messages = self.get_recent_messages(limit=3)
        responses = []
        
        for msg in messages:
            msg_id = msg.get("message_id")
            
            # 跳过已处理的消息
            if msg_id == self.last_message_id:
                break
            
            # 处理消息
            response = self.process_message(msg)
            if response:
                self.send_message(response)
                responses.append(response)
            
            # 更新最后处理的消息 ID
            if not self.last_message_id:
                self.last_message_id = msg_id
                break
        
        return responses
    
    def start_polling(self):
        """开始轮询监听"""
        print(f"开始监听飞书群 {self.chat_id}")
        print(f"轮询间隔: {self.poll_interval}秒")
        print("按 Ctrl+C 停止")
        
        # 获取初始消息 ID
        messages = self.get_recent_messages(limit=1)
        if messages:
            self.last_message_id = messages[0].get("message_id")
        
        try:
            while True:
                self.poll_once()
                time.sleep(self.poll_interval)
        except KeyboardInterrupt:
            print("\n停止监听")


def handle_generate_report(message: Dict) -> str:
    """生成报告命令处理"""
    try:
        from skills.market_report import generate_report
        
        # 获取最新的 Markdown 报告
        md_file = "/tmp/latest_report.md"
        if not os.path.exists(md_file):
            return "❌ 未找到最新的 Markdown 报告，请先运行市场分析"
        
        output_file = f"/home/jiaod/qts/report_{datetime.now().strftime('%Y%m%d_%H%M')}.html"
        generate_report(md_file, output_file, datetime.now().strftime('%Y年%m月%d日'))
        
        return f"✅ 报告已生成: {os.path.basename(output_file)}"
    except Exception as e:
        return f"❌ 生成报告失败: {e}"


def handle_send_report(message: Dict) -> str:
    """发送报告命令处理"""
    try:
        from skills.feishu_send import send_file_to_feishu
        
        # 查找最新的 HTML 报告
        import glob
        reports = glob.glob("/home/jiaod/qts/report_*.html")
        if not reports:
            return "❌ 未找到 HTML 报告，请先执行生成报告命令"
        
        latest_report = max(reports, key=os.path.getctime)
        result = send_file_to_feishu("oc_d2e8df3c676afa2c352d8ece0a9b6141", latest_report)
        
        if result.get("ok"):
            return f"✅ 报告已发送到飞书群"
        else:
            return f"❌ 发送失败: {result.get('error', '未知错误')}"
    except Exception as e:
        return f"❌ 发送报告失败: {e}"


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="飞书消息监听器")
    parser.add_argument("--chat-id", help="飞书群 ID（群聊）")
    parser.add_argument("--user-id", help="用户 open_id（私聊）")
    parser.add_argument("--interval", type=int, default=30, help="轮询间隔（秒）")
    args = parser.parse_args()
    
    if not args.chat_id and not args.user_id:
        # 默认使用群聊
        args.chat_id = "oc_d2e8df3c676afa2c352d8ece0a9b6141"
    
    listener = FeishuListener(
        chat_id=args.chat_id,
        user_id=args.user_id,
        poll_interval=args.interval
    )
    
    # 注册命令
    listener.register_command("生成报告", handle_generate_report)
    listener.register_command("发送报告", handle_send_report)
    
    # 开始监听
    mode = "群聊" if args.chat_id else "私聊"
    print(f"开始监听飞书{mode}消息")
    listener.start_polling()


if __name__ == "__main__":
    main()
