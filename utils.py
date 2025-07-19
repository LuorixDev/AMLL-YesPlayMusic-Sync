# -*- coding: utf-8 -*-

import json
import logging
import re
from typing import Dict, Any, Optional, List

import aiohttp

async def fetch_json(session: aiohttp.ClientSession, url: str) -> Optional[Dict[str, Any]]:
    """
    异步发送GET请求并获取JSON响应。

    Args:
        session (aiohttp.ClientSession): aiohttp会话对象。
        url (str): 请求的目标URL。

    Returns:
        Optional[Dict[str, Any]]: 解析后的JSON数据（如果成功），否则返回None。
    """
    try:
        async with session.get(url, timeout=5) as response:
            if response.status == 200:
                return await response.json()
            # 对于非200状态码，记录警告
            logging.warning(f"访问 {url} 失败，状态码: {response.status}")
            return None
    except aiohttp.ClientError as e:
        # 捕获并记录网络相关的错误
        logging.error(f"请求 {url} 时发生网络错误: {e}")
        return None
    except json.JSONDecodeError:
        # 捕获并记录JSON解析错误
        logging.error(f"无法解析来自 {url} 的JSON响应")
        return None


async def fetch_text(session: aiohttp.ClientSession, url: str) -> Optional[str]:
    """
    异步发送GET请求并获取文本响应。

    Args:
        session (aiohttp.ClientSession): aiohttp会话对象。
        url (str): 请求的目标URL。

    Returns:
        Optional[str]: 响应的文本内容（如果成功），否则返回None。
    """
    try:
        async with session.get(url, timeout=5) as response:
            if response.status == 200:
                return await response.text()
            # 对于非200状态码，记录提示信息
            logging.info(f"访问 {url} 无内容或失败，状态码: {response.status}")
            return None
    except aiohttp.ClientError as e:
        # 捕获并记录网络相关的错误
        logging.error(f"请求 {url} 时发生网络错误: {e}")
        return None


def parse_lrc(lrc_text: str) -> List[Dict[str, Any]]:
    """
    解析LRC（.lrc）格式的歌词文本，并将其转换为amll兼容的格式。

    Args:
        lrc_text (str): 包含LRC歌词的字符串。

    Returns:
        List[Dict[str, Any]]: 一个列表，其中每个字典代表一句歌词，
                                 包含起止时间、歌词内容等信息。
    """
    lines = []
    # 用于匹配LRC时间标签（如 [00:12.34] 或 [00:12.345]）的正则表达式
    time_tag_re = re.compile(r'\[(\d{2}):(\d{2})\.(\d{2,3})\]')

    for line in lrc_text.splitlines():
        match = time_tag_re.match(line)
        if not match:
            continue

        # 从匹配结果中提取时间分量
        minutes = int(match.group(1))
        seconds = int(match.group(2))
        milliseconds = int(match.group(3))
        
        # 将毫秒部分规范化为3位数（例如 .34 变为 340）
        if len(match.group(3)) == 2:
            milliseconds *= 10

        # 计算总的开始时间（以毫秒为单位）
        start_time_ms = (minutes * 60 + seconds) * 1000 + milliseconds

        # 歌词内容是时间标签之后的部分
        lyric_content = line[match.end():].strip()

        if lyric_content:
            # amll协议需要每个词的起止时间，但LRC只提供行时间。
            # 这里我们做一个简化，将整行歌词视为一个 "word"。
            word = {
                "startTime": start_time_ms,
                "endTime": 0,  # 结束时间稍后填充
                "word": lyric_content
            }

            # 构建amll格式的歌词行对象
            lines.append({
                "startTime": start_time_ms,
                "endTime": 0,  # 结束时间稍后填充
                "words": [word],
                "translatedLyric": "",  # 翻译歌词（暂无）
                "romanLyric": "",       # 罗马音（暂无）
                "flag": 0,
            })

    # 如果没有解析到任何歌词行，直接返回空列表
    if not lines:
        return []

    # 再次遍历，填充每句歌词的结束时间
    for i in range(len(lines)):
        # 将下一句歌词的开始时间作为当前句的结束时间
        # 如果是最后一句，则估算一个持续时间（例如5秒）
        end_time = lines[i+1]["startTime"] if i + 1 < len(lines) else lines[i]["startTime"] + 5000
        lines[i]["endTime"] = end_time
        # 同时更新该行中 "word" 的结束时间
        if lines[i]["words"]:
            lines[i]["words"][0]["endTime"] = end_time

    return lines
