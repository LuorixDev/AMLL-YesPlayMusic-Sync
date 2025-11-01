# -*- coding: utf-8 -*-
import sys
from loguru import logger

# 移除默认的处理器，以便完全自定义
logger.remove()

# 添加一个新的处理器，配置我们需要的格式和级别
logger.add(
    sys.stderr,
    level="DEBUG",  # 设置最低级别为DEBUG
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
           "<level>{level: <8}</level> | "
           "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
           "<level>{message}</level>",
    colorize=True,  # 启用loguru的内置颜色支持
)

logger.info("日志记录器已初始化。")

# 导出配置好的logger实例
__all__ = ["logger"]
