# -*- coding: utf-8 -*-

import json
import re
from typing import Dict, Any, Optional, List

import aiohttp
from logger_config import logger


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


def parse_yrc(yrc_text: str) -> List[Dict[str, Any]]:
    """
    解析YRC（网易云逐字歌词）格式的歌词文本，并将其转换为amll兼容的格式。
    """
    parsed_lines = []
    line_re = re.compile(r'\[(\d+),(\d+)\](.*)')
    word_re = re.compile(r'\((\d+),(\d+),(\d+)\)(.)')

    for line in yrc_text.splitlines():
        line_match = line_re.match(line)
        if not line_match:
            continue

        start_time_ms = int(line_match.group(1))
        duration_ms = int(line_match.group(2))
        end_time_ms = start_time_ms + duration_ms
        words_part = line_match.group(3)

        words = []
        for word_match in word_re.finditer(words_part):
            word_start_time = int(word_match.group(1))
            word_duration_cs = int(word_match.group(2)) # 厘秒
            word_text = word_match.group(4)
            
            word_end_time = word_start_time + word_duration_cs * 10

            words.append({
                "startTime": word_start_time,
                "endTime": word_end_time,
                "word": word_text
            })

        if words:
            parsed_lines.append({
                "startTime": start_time_ms,
                "endTime": end_time_ms,
                "words": words,
                "translatedLyric": "",
                "romanLyric": "",
                "flag": 0,
            })

    return parsed_lines
