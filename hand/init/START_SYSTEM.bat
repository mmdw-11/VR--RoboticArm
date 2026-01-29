@echo off
REM 系统启动脚本 - 按正确顺序启动服务端和客户端

REM 配置
setlocal enabledelayedexpansion
cd /d %~dp0

echo.
echo ================================================
echo   ✓ 机械手套触觉反馈系统启动脚本
echo ================================================
echo.

REM 检查Python环境
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ 错误：未检测到 Python
    echo 请确保已安装 Python 并添加到 PATH
    pause
    exit /b 1
)

echo ✓ Python 环境正常

REM 启动客户端（前台运行）
echo.
echo ================================================
echo   启动客户端 (test_client.py)
echo ================================================
echo.
echo 📝 提示：客户端是视频播放和反馈发送的核心
echo    按 Ctrl+C 关闭客户端
echo.

start "服务端" cmd /k "python main_new.py realtime"
timeout /t 2 /nobreak

start "客户端" cmd /k "python test_client.py"

echo.
echo ✓ 系统启动完成
echo   服务端: python main_new.py realtime
echo   客户端: python test_client.py
echo.
pause
