#!/usr/bin/env python3
"""
Crypto Bot - 币圈自动交易机器人启动入口
"""
import sys
import os
import asyncio

# 确保能找到 src 包
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

from src.main import main

if __name__ == "__main__":
    asyncio.run(main())
