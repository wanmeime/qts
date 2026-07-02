# -*- coding: utf-8 -*-
"""
QMT 全自动启动脚本
===================
流程:
  1. 等待 MiniQMT 就绪（注册表 QMT_MiniQMT 已带 -auto 参数自动启动）
  2. 启动 QMT Bridge（用 MiniQMT 自带 Python，确保 xtquant 模块可用）
  3. 启动 WSL 信号监测

依赖: 无（Python 内置模块）
"""

import subprocess
import sys
import time
import os
import ctypes


def run_detached(cmd_list, cwd=None, no_window=True):
    """在后台运行程序（不显示窗口）"""
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0  # SW_HIDE
    kwargs = {"cwd": cwd, "startupinfo": startupinfo}
    if no_window:
        CREATE_NO_WINDOW = 0x08000000  # Python 3.6 (3.7+ 有 subprocess.CREATE_NO_WINDOW)
        kwargs["creationflags"] = CREATE_NO_WINDOW
    return subprocess.Popen(cmd_list, **kwargs)


def is_miniqmt_running():
    """检查 MiniQMT 进程是否已在运行（兼容 Python 3.6）"""
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", "IMAGENAME eq XtMiniQmt.exe", "/NH"],
            startupinfo=subprocess.STARTUPINFO(),
            text=True,
        )
        return "XtMiniQmt" in out
    except Exception:
        pass
    # 备用：wmic
    try:
        out = subprocess.check_output(
            ["wmic", "process", "where", "name='XtMiniQmt.exe'", "get", "ProcessId"],
            startupinfo=subprocess.STARTUPINFO(),
            text=True,
        )
        return "ProcessId" in out and len(out.strip().splitlines()) > 1
    except Exception:
        return False


def wait_for_miniqmt(timeout=20):
    """等待 MiniQMT 进程出现（注册表已先启动）"""
    for i in range(timeout):
        if is_miniqmt_running():
            return True
        time.sleep(1)
    return False


if __name__ == "__main__":
    print("=" * 50)
    print("QMT 全自动启动")
    print("=" * 50)

    # 等待 MiniQMT 就绪（注册表已带 -auto 启动）
    miniqmt_path = r"D:\国金QMT交易端模拟\bin.x64\XtMiniQmt.exe"
    miniqmt_dir = r"D:\国金QMT交易端模拟\bin.x64"
    print("[1/3] 等待 MiniQMT 就绪...")
    if not is_miniqmt_running():
        print("  -> MiniQMT 未运行，手动启动...")
        if os.path.exists(miniqmt_path):
            run_detached([miniqmt_path, "-auto"])
            time.sleep(5)
        else:
            print("  [FAIL] MiniQMT 不存在:", miniqmt_path)
    else:
        print("  [OK] MiniQMT 已在运行")
    time.sleep(2)

    # 2. 启动 QMT Bridge（用 MiniQMT 自带的 Python，确保 xtquant 模块可用）
    bridge = r"D:\qmt_bridge\qmt_bridge.py"
    qmt_python = r"D:\国金QMT交易端模拟\bin.x64\python.exe"
    if os.path.exists(bridge):
        print("[2/3] 启动 QMT Bridge...")
        if os.path.exists(qmt_python):
            run_detached([qmt_python, bridge, "--port", "8890"], cwd=miniqmt_dir)
            print("  [OK] Bridge 已启动（MiniQMT Python）")
        else:
            run_detached([sys.executable, bridge, "--port", "8890"])
            print("  [WARN] MiniQMT Python 不存在，用系统 Python 启动")
    else:
        print("  [FAIL] Bridge 不存在:", bridge)

    # 3. 启动 WSL 盯盘系统（含 Dashboard :8891 + 信号监测）
    # 注意：wsl.exe 需要控制台，不能用 CREATE_NO_WINDOW
    print("[3/3] 启动 WSL 盯盘系统...")
    run_detached(
        [
            "wsl.exe", "-d", "Ubuntu-24.04", "bash", "-c",
            "cd /home/jiaod/qts && nohup python3 50-盯盘/watchdog.py >/dev/null 2>&1 &",
        ],
        no_window=False,
    )
    print("  [OK] 盯盘系统已启动 (Dashboard http://localhost:8891)")

    print("\n[OK] 全部启动完成！")
