@echo off
chcp 65001 >nul
:: 设置当前目录为脚本所在目录，防止因管理员权限运行导致路径错误

cd /d %~dp0



title SmartInvest 智能定投系统启动器

color 0A



echo ========================================================

echo        🚀 正在启动 SmartInvest 智能定投系统

echo ========================================================

echo.



:: 1. 启动后端 (Python/FastAPI)

:: 使用 start 开启新窗口

:: "SmartInvest Backend" 是窗口标题，方便你在任务栏找到它

:: cmd /k 意思是执行完命令后保留窗口，方便你看日志和报错

echo [1/3] 正在唤醒后端大脑 (Port: 8000)...

start "SmartInvest Backend [Python]" cmd /k "cd backend && venv\Scripts\activate && python main.py"



:: 2. 启动前端 (React/Vite)

echo [2/3] 正在加载可视化界面 (Port: 5173)...

start "SmartInvest Frontend [React]" cmd /k "cd frontend && npm run dev"



:: 3. 打开浏览器

echo [3/3] 等待服务就绪，即将自动打开浏览器...

:: 等待 4 秒，给后端一点启动时间

timeout /t 4 >nul



:: 启动默认浏览器访问

start http://localhost:5173



echo.

echo ========================================================

echo      ✅ 启动完成！

echo.

echo      [操作指南]

echo      1. 如果需要【重启后端】：

echo         切换到 "SmartInvest Backend" 窗口，按 Ctrl+C 停止，

echo         然后按 "向上箭头" 键找到启动命令，回车即可。

echo.

echo      2. 如果需要【重启前端】：

echo         切换到 "SmartInvest Frontend" 窗口，同上操作。

echo.

echo      3. 祝你投资顺利，收益长红！ 📈

echo ========================================================

echo.

pause

