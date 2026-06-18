$QMT = "D:\国金QMT交易端模拟\bin.x64\XtMiniQmt.exe"
$PWD = "585444"

# 1. 启动
if (-not (Get-Process -Name XtMiniQmt -ErrorAction SilentlyContinue)) {
    Start-Process -FilePath $QMT -WindowStyle Minimized
    Start-Sleep 20
}

# 2. 强制窗口激活（多重保障）
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class W32 {
    [DllImport("user32.dll")] public static extern IntPtr FindWindow(string c, string w);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
    [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);
    [DllImport("user32.dll")] public static extern bool SetActiveWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll")] public static extern uint AttachThreadInput(uint id, uint id2, bool a);
    public const int SW_RESTORE = 9;
    public const int SW_MINIMIZE = 6;
}
"@

$hwnd = [W32]::FindWindow("Qt5QWindowIcon", "XtMiniQmt")
if ($hwnd -eq [IntPtr]::Zero) { Write-Host "No window"; exit 1 }

Write-Host "Activating..."
# 最暴力的激活方式
[W32]::ShowWindow($hwnd, [W32]::SW_RESTORE)
Start-Sleep -Milliseconds 200
[W32]::SetForegroundWindow($hwnd)
Start-Sleep -Milliseconds 200
[W32]::BringWindowToTop($hwnd)
Start-Sleep -Milliseconds 200
[W32]::SetActiveWindow($hwnd)
Start-Sleep -Milliseconds 200

# 连按两次 Alt 确保焦点
$wshell = New-Object -ComObject wscript.shell
$wshell.SendKeys("%")  # Alt key
Start-Sleep -Milliseconds 200
$wshell.SendKeys("%")  # Alt key
Start-Sleep -Milliseconds 500

# 现在焦点应该在登录窗口的第一个控件上
# Tab 到密码框：账户(已填) → Tab → 验证码(已填) → Tab → 密码
Write-Host "Sending password..."
$wshell.SendKeys("{TAB}")
Start-Sleep -Milliseconds 300
$wshell.SendKeys("{TAB}")  
Start-Sleep -Milliseconds 300
$wshell.SendKeys($PWD)
Start-Sleep -Milliseconds 500
$wshell.SendKeys("{ENTER}")
Start-Sleep -Milliseconds 500

# 如果 Enter 没触发（焦点不在登录按钮），再尝试 Tab+Enter
$wshell.SendKeys("{TAB}")
Start-Sleep -Milliseconds 200
$wshell.SendKeys("{ENTER}")

Write-Host "Done, minimizing..."
Start-Sleep 3
[W32]::ShowWindow($hwnd, [W32]::SW_MINIMIZE)
