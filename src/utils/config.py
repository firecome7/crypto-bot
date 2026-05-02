"""
配置加载模块
"""
import yaml
import os
from pathlib import Path

DEFAULT_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "config.yaml"


def load_config(path: str = None) -> dict:
    if path is None:
        path = str(DEFAULT_CONFIG_PATH)
    with open(path, "r") as f:
        cfg = yaml.safe_load(f)
    return cfg
