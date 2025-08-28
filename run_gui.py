#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
启动脚本 - 运行 Streamlit GUI
"""

import subprocess
import sys
from pathlib import Path


def main():
    """启动 Streamlit GUI"""
    # 获取项目根目录
    project_root = Path(__file__).parent

    # GUI 文件路径
    gui_file = project_root / "src" / "app" / "ui" / "gui.py"

    if not gui_file.exists():
        print(f"错误: GUI 文件不存在: {gui_file}")
        sys.exit(1)

    # 启动 Streamlit (使用环境变量解决 Python 3.13 free-threading 兼容性问题)
    import os

    env = os.environ.copy()
    env["PYTHON_GIL"] = "1"  # 强制启用 GIL

    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(gui_file),
        "--server.port",
        "8501",
        "--server.address",
        "localhost",
        "--browser.gatherUsageStats",
        "false",
    ]

    print(f"启动 Streamlit GUI: {gui_file}")
    print("访问地址: http://localhost:8501")
    print("按 Ctrl+C 停止服务")

    try:
        subprocess.run(cmd, cwd=project_root, env=env)
    except KeyboardInterrupt:
        print("\n服务已停止")
    except Exception as e:
        print(f"启动失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
