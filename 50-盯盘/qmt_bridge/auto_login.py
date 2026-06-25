# -*- coding: utf-8 -*-
"""
MiniQMT 自动登录脚本（使用 SendInput Win32 API）
=============================================
依赖: Python 自带 ctypes，无需任何第三方库
原理: 通过 SendInput 模拟硬件级别的键盘输入，
      比 SendKeys 可靠得多（不依赖窗口焦点、不经过消息队列）

用法: python D:\qmt_bridge\auto_login.py [--password 585444]
"""

import ctypes
import ctypes.wintypes
import time
import sys

# ── Windows API 常量 ──
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008

# ── Windows API 结构 ──
class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.c_ulong)]

class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", ctypes.c_ulong), ("wParamL", ctypes.c_ushort),
                ("wParamH", ctypes.c_ushort)]

class INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("union", INPUT_UNION)]


def send_key(vk_code, press=True):
    """发送单个按键"""
    flags = 0
    if not press:
        flags |= KEYEVENTF_KEYUP
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.union.ki.wVk = vk_code
    inp.union.ki.dwFlags = flags
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


def send_unicode_char(char):
    """发送 Unicode 字符（直接输入字符，不依赖键盘布局）"""
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.union.ki.wScan = ord(char)
    inp.union.ki.dwFlags = KEYEVENTF_UNICODE
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
    # Key up
    inp.union.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


def send_text(text):
    """发送字符串（逐字符，每个字符前后加10ms间隔）"""
    for ch in text:
        send_unicode_char(ch)
        time.sleep(0.01)


def find_window(title_keyword, class_keyword=None, timeout=30):
    """等待窗口出现（最多等 timeout 秒）"""
    user32 = ctypes.windll.user32
    start = time.time()
    while time.time() - start < timeout:
        hwnd = user32.FindWindowW(class_keyword, None) if class_keyword else 0
        if hwnd:
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            if title_keyword in buf.value:
                return hwnd
        # 用 EnumWindows 遍历
        hwnds = []
        def enum_proc(h, _):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(h, buf, 256)
            if title_keyword in buf.value:
                hwnds.append(h)
            return True
        ENUM_WND_PROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
        user32.EnumWindows(ENUM_WND_PROC(enum_proc), 0)
        if hwnds:
            return hwnds[0]
        time.sleep(1)
    return None


def activate_window(hwnd):
    """激活窗口到前台"""
    user32 = ctypes.windll.user32
    # ShowWindow + SetForegroundWindow
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    time.sleep(0.3)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.3)
    # 再 Alt 键确保焦点
    send_key(0x12)  # VK_MENU
    time.sleep(0.05)
    send_key(0x12, False)
    time.sleep(0.2)


def auto_login(password, retries=3):
    """
    自动登录 MiniQMT

    步骤:
    1. 等待 MiniQMT 登录窗口出现（最多等60秒）
    2. 激活窗口
    3. Tab 到密码框 → 输入密码 → Enter
    4. 重试机制：失败后等5秒重试
    """
    VK_TAB = 0x09
    VK_RETURN = 0x0D

    for attempt in range(retries):
        print(f"[尝试 {attempt+1}/{retries}] 等待 MiniQMT 登录窗口...")

        # 1. 找窗口（类名 Qt5QWindowIcon，标题 XtMiniQmt）
        hwnd = find_window("XtMiniQmt", timeout=60)
        if not hwnd:
            print("  [FAIL] 未找到 MiniQMT 登录窗口")
            time.sleep(5)
            continue

        print(f"  [OK] 找到窗口: {hwnd}")

        # 2. 激活
        activate_window(hwnd)
        time.sleep(1)

        # 3. 当前焦点可能在账号框
        # 按 Tab 到密码框（通常2次Tab：从账号→密码）
        print("  定位密码框...")
        for _ in range(2):
            send_key(VK_TAB)
            time.sleep(0.1)

        # 4. 输入密码
        print(f"  输入密码...")
        send_text(password)
        time.sleep(0.3)

        # 5. 按 Enter 登录
        print("  按 Enter 登录...")
        send_key(VK_RETURN)
        time.sleep(0.1)
        send_key(VK_RETURN, False)

        # 6. 等待2秒确认是否成功
        time.sleep(3)

        # 检查登录窗口是否还在（如果还在，说明登录失败）
        hwnd2 = find_window("XtMiniQmt", timeout=2)
        if not hwnd2:
            print(f"  [OK] 登录成功！")
            return True
        else:
            print(f"  [?] 登录可能失败，重试...")
            time.sleep(5)

    return False


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--password", default="585444")
    args = parser.parse_args()

    print("=" * 50)
    print("MiniQMT 自动登录")
    print("=" * 50)

    success = auto_login(args.password)
    if success:
        print("\n[OK] 登录成功！")
        # 自动启动 QMT Bridge
        print("启动 QMT Bridge...")
        import subprocess
        bridge_cmd = [
            sys.executable,
            r"D:\qmt_bridge\qmt_bridge.py",
            "--port", "8890"
        ]
        subprocess.Popen(bridge_cmd, creationflags=subprocess.CREATE_NO_WINDOW)
        print("[OK] Bridge 已启动")

        # 启动 WSL 信号监测
        print("启动 WSL 信号监测...")
        wsl_cmd = ["wsl.exe", "-d", "Ubuntu-24.04", "bash", "-c",
                    "cd /home/jiaod/qts && python3 50-盯盘/run_signal_monitor.py &"]
        subprocess.Popen(wsl_cmd, creationflags=subprocess.CREATE_NO_WINDOW)
        print("[OK] 信号监测已启动")
        sys.exit(0)
    else:
        print("\n[FAIL] 登录失败，请手动输入")
        sys.exit(1)
