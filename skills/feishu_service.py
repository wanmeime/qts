#!/usr/bin/env python3
"""
飞书消息监听服务
后台运行，收到消息后自动响应
"""
import sys
import os
import json
import time
import signal
import subprocess
from datetime import datetime

sys.path.insert(0, '/home/jiaod/qts')

LARK_CLI = "/home/jiaod/.npm-global/bin/lark-cli"
CHAT_ID = "oc_d2e8df3c676afa2c352d8ece0a9b6141"
WORK_DIR = "/home/jiaod/qts"
POLL_INTERVAL = 15  # 秒

# 全局状态
running = True
last_message_id = None

def signal_handler(sig, frame):
    global running
    print("\n收到停止信号，正在退出...")
    running = False

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def get_recent_messages(limit=3):
    """获取最近消息"""
    cmd = [
        LARK_CLI, "im", "+chat-messages-list",
        "--chat-id", CHAT_ID,
        "--as", "bot",
        "--page-size", str(limit),
        "--sort", "desc"
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=WORK_DIR)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return data.get("data", {}).get("messages", [])
    except Exception as e:
        log(f"获取消息失败: {e}")
    return []

def send_message(content, msg_type="markdown"):
    """发送消息"""
    cmd = [
        LARK_CLI, "im", "+messages-send",
        "--chat-id", CHAT_ID,
        f"--{msg_type}", content,
        "--as", "bot"
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=WORK_DIR)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return data.get("ok", False)
    except Exception as e:
        log(f"发送消息失败: {e}")
    return False

def send_file(file_path):
    """发送文件"""
    import shutil
    file_name = os.path.basename(file_path)
    dest = os.path.join(WORK_DIR, file_name)
    shutil.copy2(file_path, dest)
    
    cmd = [
        LARK_CLI, "im", "+messages-send",
        "--chat-id", CHAT_ID,
        "--file", file_name,
        "--as", "bot"
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=WORK_DIR)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return data.get("ok", False)
    except Exception as e:
        log(f"发送文件失败: {e}")
    return False

def log(msg):
    """日志输出"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {msg}")

def handle_command(content):
    """处理命令"""
    content = content.strip().lower()
    
    # 生成报告
    if "生成报告" in content or "generate" in content:
        return cmd_generate_report()
    
    # 发送报告
    if "发送报告" in content or "send" in content:
        return cmd_send_report()
    
    # 帮助
    if "帮助" in content or "help" in content:
        return cmd_help()
    
    # 状态
    if "状态" in content or "status" in content:
        return cmd_status()
    
    return None

def cmd_generate_report():
    """生成报告命令"""
    try:
        log("开始生成报告...")
        send_message("⏳ 正在生成市场报告，请稍候...")
        
        from skills.market_report import generate_report
        
        # 检查是否有最新的 Markdown 报告
        md_file = "/tmp/latest_report.md"
        if not os.path.exists(md_file):
            # 尝试从 API 获取
            import requests
            try:
                resp = requests.get("http://localhost:8000/v1/market/insight", timeout=120)
                if resp.status_code == 200:
                    with open(md_file, "w", encoding="utf-8") as f:
                        f.write(resp.text)
                else:
                    return "❌ 无法获取市场数据"
            except:
                return "❌ TradingAgents 服务未运行"
        
        output_file = f"{WORK_DIR}/report_{datetime.now().strftime('%Y%m%d_%H%M')}.html"
        generate_report(md_file, output_file, datetime.now().strftime('%Y年%m月%d日'))
        
        log(f"报告已生成: {output_file}")
        return f"✅ 报告已生成\n文件: {os.path.basename(output_file)}"
    except Exception as e:
        log(f"生成报告失败: {e}")
        return f"❌ 生成报告失败: {e}"

def cmd_send_report():
    """发送报告命令"""
    try:
        import glob
        reports = glob.glob(f"{WORK_DIR}/report_*.html")
        if not reports:
            return "❌ 未找到 HTML 报告，请先执行"生成报告"命令"
        
        latest_report = max(reports, key=os.path.getctime)
        log(f"发送报告: {latest_report}")
        
        if send_file(latest_report):
            return f"✅ 报告已发送\n文件: {os.path.basename(latest_report)}"
        else:
            return "❌ 发送失败"
    except Exception as e:
        log(f"发送报告失败: {e}")
        return f"❌ 发送报告失败: {e}"

def cmd_help():
    """帮助命令"""
    return """📋 **可用命令**

| 命令 | 功能 |
|------|------|
| 生成报告 | 生成最新的市场洞察报告 |
| 发送报告 | 将报告发送到飞书群 |
| 状态 | 查看系统状态 |
| 帮助 | 显示此帮助信息 |

💡 直接发送文本消息即可触发命令"""

def cmd_status():
    """状态命令"""
    import glob
    reports = glob.glob(f"{WORK_DIR}/report_*.html")
    latest = max(reports, key=os.path.getctime) if reports else "无"
    
    return f"""📊 **系统状态**

- Docker 容器: 运行中
- 报告数量: {len(reports)} 份
- 最新报告: {os.path.basename(latest)}
- 监听状态: 运行中
- 轮询间隔: {POLL_INTERVAL}秒"""

def process_message(message):
    """处理消息"""
    global last_message_id
    
    content = message.get("content", "")
    msg_type = message.get("msg_type", "")
    sender = message.get("sender", {})
    msg_id = message.get("message_id")
    
    # 跳过已处理的消息
    if msg_id == last_message_id:
        return
    
    # 只处理文本消息，忽略 bot 消息
    if msg_type != "text" or sender.get("sender_type") == "app":
        last_message_id = msg_id
        return
    
    # 处理命令
    response = handle_command(content)
    if response:
        log(f"收到命令: {content[:50]}")
        send_message(response)
    
    last_message_id = msg_id

def main():
    """主函数"""
    log("=" * 50)
    log("飞书消息监听服务启动")
    log(f"监听群组: {CHAT_ID}")
    log(f"轮询间隔: {POLL_INTERVAL}秒")
    log("=" * 50)
    
    # 获取初始消息 ID
    messages = get_recent_messages(limit=1)
    if messages:
        global last_message_id
        last_message_id = messages[0].get("message_id")
        log(f"初始消息 ID: {last_message_id}")
    
    # 发送启动通知
    send_message("🟢 **飞书监听服务已启动**\n\n发送"帮助"查看可用命令")
    
    # 主循环
    while running:
        try:
            messages = get_recent_messages(limit=3)
            for msg in messages:
                process_message(msg)
        except Exception as e:
            log(f"轮询出错: {e}")
        
        time.sleep(POLL_INTERVAL)
    
    log("服务已停止")
    send_message("🔴 **飞书监听服务已停止**")

if __name__ == "__main__":
    main()
