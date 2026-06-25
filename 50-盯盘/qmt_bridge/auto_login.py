# -*- coding: utf-8 -*-
"""
QMT 全自动启动脚本
===================
流程:
  1. 启动 MiniQMT（带 -auto 参数，自动登录）
  2. 等待3秒后启动 QMT Bridge
  3. 启动 WSL 信号监测

依赖: 无（Python 内置模块）
"""

import subprocess
import sys
import time
import os

def run_detached(cmd_list):
    """在后台运行程序（不显示窗口）"""
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0  # SW_HIDE
    return subprocess.Popen(
        cmd_list,
        startupinfo=startupinfo,
        creationflags=subprocess.CREATE_NO_WINDOW
    )


if __name__ == "__main__":
    print("=" * 50)
    print("QMT 全自动启动")
    print("=" * 50)

    # 1. 启动 MiniQMT（自动登录）
    miniqmt = r"D:\国金QMT交易端模拟\bin.x64\XtMiniQmt.exe"
    if os.path.exists(miniqmt):
        print("[1/3] 启动 MiniQMT...")
        run_detached([miniqmt, "-auto"])
        time.sleep(3)
        print("  [OK] MiniQMT 已启动（自动登录中）")
    else:
        print("  [FAIL] MiniQMT 不存在:", miniqmt)

    # 2. 启动 QMT Bridge
    bridge = r"D:\qmt_bridge\qmt_bridge.py"
    python = sys.executable
    if os.path.exists(bridge):
        print("[2/3] 启动 QMT Bridge...")
        run_detached([python, bridge, "--port", "8890"])
        print("  [OK] Bridge 已启动")
    else:
        print("  [FAIL] Bridge 不存在:", bridge)

    # 3. 启动 WSL 信号监测
    print("[3/3] 启动 WSL 信号监测...")
    run_detached([
        "wsl.exe", "-d", "Ubuntu-24.04", "bash", "-c",
        "cd /home/jiaod/qts && python3 50-盯盘/run_signal_monitor.py &"
    ])
    print("  [OK] 信号监测已启动")

    print("\n[OK] 全部启动完成！")
