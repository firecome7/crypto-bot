#!/usr/bin/env python3
"""
Crypto Bot - 币圈自动交易机器人启动入口
"""
import sys
import os

# 确保能找到 src 包
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.main import main

if __name__ == "__main__":
    main()
