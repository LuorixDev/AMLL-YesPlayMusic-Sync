# -*- coding: utf-8 -*-
"""
事件处理模块
包含所有处理来自播放器或amll WebSocket消息的函数。
"""

import logging
from typing import Dict, Any

import aiohttp
from websockets.client import WebSocketClientProtocol
from websockets.exceptions import ConnectionClosed

from ws_protocol import to_body, MessageType, ENUM_TO_CAMEL, parse_body
from player_tools import control_player
from utils import fetch_json, fetch_text, parse_lrc
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
        logging.warning("WebSocket 连接已关闭，无法发送消息。")
    except Exception as e:
        logging.error(f"发送WebSocket消息时出错: {e}")

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
        logging.info("播放器数据中无有效歌曲信息。")
        player_state.reset()
        return

    track_id = track_info['id']

    # 1. 如果是新歌，发送歌曲基本信息
    if player_state.is_new_track(track_id):
        logging.info(
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
            await handle_lyrics(session, ws, track_id)
            
        # 4. 发送新歌的初始进度
        await send_ws_message(ws, ENUM_TO_CAMEL[MessageType.ON_PLAY_PROGRESS], {"progress": int(track_data["progress"] * 1000)})


async def handle_lyrics(session: aiohttp.ClientSession, ws: WebSocketClientProtocol, track_id: int):
    """
    获取并发送歌词，优先使用TTML格式，失败则回退到LRC。

    Args:
        session (aiohttp.ClientSession): aiohttp会话对象。
        ws (WebSocketClientProtocol): WebSocket连接实例。
        track_id (int): 歌曲ID。
    """
    # 尝试获取TTML歌词
    ttml_url = config.TTML_LYRIC_API_TEMPLATE.format(song_id=track_id)
    ttml_lyrics = await fetch_text(session, ttml_url)

    if ttml_lyrics:
        logging.info(f"成功获取歌曲 {track_id} 的TTML歌词。")
        await send_ws_message(ws, ENUM_TO_CAMEL[MessageType.SET_LYRIC_FROM_TTML], {"data": ttml_lyrics})
        return

    # 回退到LRC歌词
    logging.info(f"未找到歌曲 {track_id} 的TTML歌词，回退到LRC格式。")
    lyric_url = f"{config.YESPLAY_LYRIC_API}?id={track_id}"
    lyric_data = await fetch_json(session, lyric_url)

    if lyric_data and lyric_data.get('lrc', {}).get('lyric'):
        lrc_text = lyric_data['lrc']['lyric']
        parsed_lyrics = parse_lrc(lrc_text)
        if parsed_lyrics:
            logging.info(f"成功解析歌曲 {track_id} 的LRC歌词。")
            await send_ws_message(ws, ENUM_TO_CAMEL[MessageType.SET_LYRIC], {"data": parsed_lyrics})
        else:
            logging.warning(f"解析歌曲 {track_id} 的LRC歌词失败。")
    else:
        logging.warning(f"获取歌曲 {track_id} 的LRC歌词也失败了。")


async def handle_incoming_messages(ws: WebSocketClientProtocol):
    """
    监听并处理来自amll WebSocket的传入消息。
    """
    try:
        async for message in ws:
            try:
                parsed_msg = parse_body(message)
                msg_type_str = parsed_msg.get('type')
                logging.info(f"收到消息: {msg_type_str}")

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
                logging.error(f"解析或处理收到的消息时出错: {e}")
            except Exception as e:
                logging.error(f"处理传入消息时发生未知错误: {e}")
    except ConnectionClosed:
        logging.info("监听任务因连接关闭而停止。")
