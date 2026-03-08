@echo off
:: 设置字符集为 UTF-8 防止中文乱码
chcp 65001 > nul

echo =======================================
echo     正在启动 AI Prompt Gallery
echo =======================================
echo.

:: 1. 启动 Meilisearch 搜索引擎
echo [1/2] 正在启动 Meilisearch 搜索引擎...
:: 使用 start /MIN 可以在后台“最小化”打开一个新的黑框运行引擎，不会卡住当前脚本
:: 【注意】：如果你的 meilisearch.exe 放在了其他文件夹，请把下面的 meilisearch.exe 换成绝对路径
start /MIN "Meilisearch Service" meilisearch.exe --master-key="你的MasterKey"

:: 暂停 2 秒钟，给 Meilisearch 一点时间启动并准备好接收请求
timeout /t 2 /nobreak > nul

:: 2. 启动 Django Web 服务
echo [2/2] 正在启动 Django Web 服务...
echo.
python manage.py runserver 0.0.0.0:8000

:: 如果 Django 意外退出，暂停窗口看报错
pause