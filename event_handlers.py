# -*- coding: utf-8 -*-
"""
事件处理模块
包含所有处理来自播放器或amll WebSocket消息的函数。
"""

from typing import Dict, Any

import aiohttp
from websockets.client import WebSocketClientProtocol
from websockets.exceptions import ConnectionClosed

from logger_config import logger
from ws_protocol import to_body, MessageType, ENUM_TO_CAMEL, parse_body
from player_tools import control_player
from utils import fetch_json, fetch_text, parse_lrc, parse_yrc
from state import player_state
import state as s
import config

async def send_ws_message(ws: WebSocketClientProtocol, message_type: str, value: Dict[str, Any]):
    """
    构建并发送WebSocket消息。

    Args:
        ws (WebSocketClientProtocol): WebSocket连接实例。
        message_type (str): 消息类型。
        value (Dict[str, Any]): 消息体。
    """
    try:
        body = {"type": message_type, "value": value}
        packed_body = to_body(body)
        await ws.send(packed_body)
    except ConnectionClosed:
        logger.warning("WebSocket 连接已关闭，无法发送消息。")
    except Exception as e:
        logger.error(f"发送WebSocket消息时出错: {e}")

async def handle_track_update(session: aiohttp.ClientSession, ws: WebSocketClientProtocol, track_data: Dict[str, Any]):
    """
    处理歌曲更新事件，获取详细信息并发送到amll。

    Args:
        session (aiohttp.ClientSession): aiohttp会话对象。
        ws (WebSocketClientProtocol): WebSocket连接实例。
        track_data (Dict[str, Any]): 从播放器API获取的原始数据。
    """
    track_info = track_data.get('currentTrack')
    if not track_info or 'id' not in track_info:
        logger.info("播放器数据中无有效歌曲信息。")
        player_state.reset()
        return

    track_id = track_info['id']

    # 1. 如果是新歌，发送歌曲基本信息
    if player_state.is_new_track(track_id):
        logger.info(
            f"检测到新歌曲: {track_info.get('name', '未知')} (ID: {track_id})")

        artists = [{"id": str(artist.get('id', '')), "name": artist.get('name', '')}
                   for artist in track_info.get('ar', [])]

        music_info = {
            "musicId": str(track_id),
            "musicName": track_info.get('name', ''),
            "albumId": str(track_info.get('al', {}).get('id', '')),
            "albumName": track_info.get('al', {}).get('name', ''),
            "artists": artists,
            "duration": track_info.get('dt', 0),
        }
        await send_ws_message(ws, ENUM_TO_CAMEL[MessageType.SET_MUSIC_INFO], music_info)

        # 2. 发送专辑封面
        pic_url = track_info.get('al', {}).get('picUrl')
        if pic_url and player_state.is_new_album_cover(pic_url):
            await send_ws_message(ws, ENUM_TO_CAMEL[MessageType.SET_MUSIC_ALBUM_COVER_IMAGE_URI], {"imgUrl": pic_url})

        # 3. 发送歌词
        if player_state.is_new_lyric(track_id):
            import asyncio
            # 创建一个新的歌词获取任务，并保存它以便在需要时可以取消
            player_state.current_lyric_task = asyncio.create_task(
                handle_lyrics(session, ws, track_id)
            )
            
        # 4. 发送新歌的初始进度
        await send_ws_message(ws, ENUM_TO_CAMEL[MessageType.ON_PLAY_PROGRESS], {"progress": int(track_data["progress"] * 1000)})


import asyncio

async def handle_lyrics(session: aiohttp.ClientSession, ws: WebSocketClientProtocol, track_id: int):
    """
    并发获取所有歌词源，并根据优先级动态更新。
    优先级: AMLL (3) > YRC (2) > LRC (1)
    """
    shared_state = {'priority': 0}

    async def fetch_lrc():
        """获取并处理LRC歌词（优先级1）"""
        lrc_url = f"{config.YESPLAY_LYRIC_API}?id={track_id}"
        logger.debug(f"LRC: 正在从 {lrc_url} 获取")
        lrc_data = await fetch_json(session, lrc_url)
        if lrc_data is not None and lrc_data.get('lrc', {}).get('lyric'):
            logger.debug("LRC: 已收到数据，正在解析...")
            parsed = parse_lrc(lrc_data['lrc']['lyric'])
            if parsed:
                if shared_state['priority'] < 1:
                    shared_state['priority'] = 1
                    logger.info(f"LRC: 优先级足够，正在为歌曲 {track_id} 发送逐句歌词。")
                    start_time = parsed[0]['startTime'] if parsed else 3000
                    parsed.insert(0, {"startTime": 0, "endTime": start_time, "words": [{"startTime": 0, "endTime": start_time, "word": "From：网易云逐句"}], "translatedLyric": "", "romanLyric": "", "flag": 0})
                    await send_ws_message(ws, ENUM_TO_CAMEL[MessageType.SET_LYRIC], {"data": parsed})
                else:
                    logger.debug(f"LRC: 已找到歌词，但当前优先级 ({shared_state['priority']}) 更高，跳过更新。")
            else:
                logger.debug("LRC: 歌词解析失败。")
        else:
            logger.debug("LRC: 响应中未找到歌词数据。")

    async def fetch_yrc():
        """获取并处理YRC歌词（优先级2）"""
        yrc_url = f"{config.YESPLAY_YRC_LYRIC_API}?id={track_id}"
        logger.debug(f"YRC: 正在从 {yrc_url} 获取")
        yrc_data = await fetch_json(session, yrc_url)
        if yrc_data is not None and yrc_data.get('yrc', {}).get('lyric'):
            logger.debug("YRC: 已收到数据，正在解析...")
            parsed = parse_yrc(yrc_data['yrc']['lyric'])
            if parsed:
                if shared_state['priority'] < 2:
                    shared_state['priority'] = 2
                    logger.info(f"YRC: 优先级足够，正在为歌曲 {track_id} 发送逐字歌词。")
                    start_time = parsed[0]['startTime'] if parsed else 3000
                    parsed.insert(0, {"startTime": 0, "endTime": start_time, "words": [{"startTime": 0, "endTime": start_time, "word": "From：网易云逐字"}], "translatedLyric": "", "romanLyric": "", "flag": 0})
                    await send_ws_message(ws, ENUM_TO_CAMEL[MessageType.SET_LYRIC], {"data": parsed})
                else:
                    logger.debug(f"YRC: 已找到歌词，但当前优先级 ({shared_state['priority']}) 更高，跳过更新。")
            else:
                logger.debug("YRC: 歌词解析失败。")
        else:
            logger.debug("YRC: 响应中未找到歌词数据。")

    async def fetch_ttml():
        """获取并处理TTML歌词（优先级3）"""
        for template in config.TTML_LYRIC_API_TEMPLATES:
            ttml_url = template.format(song_id=track_id)
            logger.debug(f"TTML: 正在从 {ttml_url} 获取")
            ttml_lyrics = await fetch_text(session, ttml_url)
            if ttml_lyrics:
                if shared_state['priority'] < 3:
                    shared_state['priority'] = 3
                    logger.info(f"TTML: 优先级足够，正在为歌曲 {track_id} 发送TTML歌词。")
                    await send_ws_message(ws, ENUM_TO_CAMEL[MessageType.SET_LYRIC], {"data": []})
                    await send_ws_message(ws, ENUM_TO_CAMEL[MessageType.SET_LYRIC_FROM_TTML], {"data": ttml_lyrics})
                    return  # 找到一个就够了
                else:
                    logger.debug(f"TTML: 已找到歌词，但当前优先级 ({shared_state['priority']}) 更高，跳过更新。")
            else:
                logger.debug(f"TTML: 在 {ttml_url} 未找到歌词数据。")

    tasks = [
        asyncio.create_task(fetch_lrc()),
        asyncio.create_task(fetch_yrc()),
        asyncio.create_task(fetch_ttml())
    ]

    try:
        await asyncio.gather(*tasks)
        logger.info(f"歌曲 {track_id} 的所有歌词获取任务已完成。")
    except asyncio.CancelledError:
        for task in tasks:
            task.cancel()
        logger.info(f"歌曲 {track_id} 的歌词获取任务已被取消。")
    except Exception:
        logger.error(f"处理歌曲 {track_id} 歌词时发生未知错误。", exc_info=True)


async def handle_incoming_messages(ws: WebSocketClientProtocol):
    """
    监听并处理来自amll WebSocket的传入消息。
    """
    try:
        async for message in ws:
            try:
                parsed_msg = parse_body(message)
                msg_type_str = parsed_msg.get('type')
                logger.info(f"收到消息: {msg_type_str}")

                if msg_type_str in [ENUM_TO_CAMEL[MessageType.PAUSE], ENUM_TO_CAMEL[MessageType.RESUME]]:
                    await control_player('playpause')
                    s.is_force_refresh = True
                    if msg_type_str == ENUM_TO_CAMEL[MessageType.RESUME]:
                        s.is_send_go = True
                    else:
                        s.is_ui_stop = True
                        s.is_send_stop = True
                elif msg_type_str == ENUM_TO_CAMEL[MessageType.FORWARD_SONG]:
                    await control_player('next')
                elif msg_type_str == ENUM_TO_CAMEL[MessageType.BACKWARD_SONG]:
                    await control_player('previous')
                elif msg_type_str == ENUM_TO_CAMEL[MessageType.SEEK_PLAY_PROGRESS]:
                    progress_ms = parsed_msg.get('value', {}).get('progress')
                    if progress_ms is not None:
                        await control_player('seek', value=progress_ms)
                elif msg_type_str == ENUM_TO_CAMEL[MessageType.SET_VOLUME]:
                    volume = parsed_msg.get('value', {}).get('volume')
                    if volume is not None:
                        await control_player('set_volume', value=volume)

            except ValueError as e:
                logger.error(f"解析或处理收到的消息时出错: {e}")
            except Exception as e:
                logger.error(f"处理传入消息时发生未知错误: {e}")
    except ConnectionClosed:
        logger.info("监听任务因连接关闭而停止。")
