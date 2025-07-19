# -*- coding: utf-8 -*-

import json
import re
import sys
from typing import Dict, Any, Optional, List

import aiohttp
from loguru import logger

def colorize_message(message: str) -> str:
    """
    为日志消息中的特定模式添加ANSI颜色代码。
    """
    # 为数字添加黄色
    message = re.sub(r'(\d+)', r'\033[93m\1\033[0m', message)
    # 为URL添加蓝色
    message = re.sub(r'(https?://[^\s]+)', r'\033[94m\1\033[0m', message)
    # 为状态码（如 200 OK）添加特定颜色
    message = re.sub(r'(\b(200|404|500)\b)', r'\033[92m\1\033[0m', message) # Green for 2xx
    message = re.sub(r'(\b(4\d{2})\b)', r'\033[91m\1\033[0m', message) # Red for 4xx
    # 为 "ON_RESUMED", "ON_PAUSED" 等关键字添加品红色
    message = re.sub(r'(ON_RESUMED|ON_PAUSED|ON_VOLUME_CHANGED|ON_PLAY_PROGRESS)', r'\033[95m\1\033[0m', message)
    return message

def setup_logger():
    """
    配置loguru日志记录器，添加彩色输出。
    """
    logger.remove()  # 移除默认的处理器
    # 注意：这里的 `colorize=True` 仅对预设的 `level`, `time` 等生效
    # 消息本身的颜色需要我们手动处理
    logger.add(
        sys.stderr,
        level="INFO",
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
               "<level>{level: <8}</level> | "
               "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        colorize=True,
    )
    # 劫持 logger 的 info, warning, error 方法
    original_info = logger.info
    original_warning = logger.warning
    original_error = logger.error

    def new_info(message, *args, **kwargs):
        original_info(colorize_message(message), *args, **kwargs)

    def new_warning(message, *args, **kwargs):
        original_warning(colorize_message(message), *args, **kwargs)

    def new_error(message, *args, **kwargs):
        original_error(colorize_message(message), *args, **kwargs)

    logger.info = new_info
    logger.warning = new_warning
    logger.error = new_error

    logger.info("日志记录器已初始化。")


async def fetch_json(session: aiohttp.ClientSession, url: str) -> Optional[Dict[str, Any]]:
    """
    异步发送GET请求并获取JSON响应。
    """
    try:
        async with session.get(url, timeout=5) as response:
            if response.status == 200:
                return await response.json()
            logger.warning(f"访问 {url} 失败，状态码: {response.status}")
            return None
    except aiohttp.ClientError as e:
        logger.error(f"请求 {url} 时发生网络错误: {e}")
        return None
    except json.JSONDecodeError:
        logger.error(f"无法解析来自 {url} 的JSON响应")
        return None


async def fetch_text(session: aiohttp.ClientSession, url: str) -> Optional[str]:
    """
    异步发送GET请求并获取文本响应。
    """
    try:
        async with session.get(url, timeout=5) as response:
            if response.status == 200:
                return await response.text()
            logger.info(f"访问 {url} 无内容或失败，状态码: {response.status}")
            return None
    except aiohttp.ClientError as e:
        logger.error(f"请求 {url} 时发生网络错误: {e}")
        return None


def parse_lrc(lrc_text: str) -> List[Dict[str, Any]]:
    """
    解析LRC（.lrc）格式的歌词文本，并将其转换为amll兼容的格式。
    """
    lines = []
    time_tag_re = re.compile(r'\[(\d{2}):(\d{2})\.(\d{2,3})\]')

    for line in lrc_text.splitlines():
        match = time_tag_re.match(line)
        if not match:
            continue
        
        minutes = int(match.group(1))
        seconds = int(match.group(2))
        milliseconds = int(match.group(3))
        
        if len(match.group(3)) == 2:
            milliseconds *= 10

        start_time_ms = (minutes * 60 + seconds) * 1000 + milliseconds
        lyric_content = line[match.end():].strip()

        if lyric_content:
            word = {
                "startTime": start_time_ms,
                "endTime": 0,
                "word": lyric_content
            }
            lines.append({
                "startTime": start_time_ms,
                "endTime": 0,
                "words": [word],
                "translatedLyric": "",
                "romanLyric": "",
                "flag": 0,
            })

    if not lines:
        return []

    for i in range(len(lines)):
        end_time = lines[i+1]["startTime"] if i + 1 < len(lines) else lines[i]["startTime"] + 5000
        lines[i]["endTime"] = end_time
        if lines[i]["words"]:
            lines[i]["words"][0]["endTime"] = end_time

    return lines
