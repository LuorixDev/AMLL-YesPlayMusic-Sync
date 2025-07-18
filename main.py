# -*- coding: utf-8 -*-

import asyncio
import json
import logging
import re
import time
from typing import Dict, Any, Optional, List

import aiohttp
import websockets
from websockets.client import WebSocketClientProtocol
from websockets.exceptions import ConnectionClosed

from ws_protocol import to_body, MessageType, ENUM_TO_CAMEL

# --- 配置 ---
# 日志配置
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# API地址
YESPLAY_PLAYER_API = "http://127.0.0.1:27232/player"
YESPLAY_LYRIC_API = "http://127.0.0.1:10754/lyric"
TTML_LYRIC_API_TEMPLATE = "https://amll.mirror.dimeta.top/api/db/ncm-lyrics/{song_id}.ttml"
AMLL_WS_URI = "ws://192.168.1.171:11444"

# 轮询间隔 (秒)
POLL_INTERVAL = 0.01
GET_TIME_WAIT= 0.1  # 获取播放器数据的间隔时间，单位为秒
# --- 状态管理 ---


class PlayerState:
    """用于跟踪当前播放器状态，以避免不必要的重复API请求和WS消息"""

    def __init__(self):
        self.current_track_id: Optional[int] = None
        self.last_progress_sent: float = -1.0
        self.last_pic_url: Optional[str] = None
        self.last_lyric_id: Optional[int] = None

    def reset(self):
        """重置状态"""
        self.current_track_id = None
        self.last_progress_sent = -1.0
        self.last_pic_url = None
        self.last_lyric_id = None

    def is_new_track(self, track_id: int) -> bool:
        """检查是否是新歌曲"""
        if track_id != self.current_track_id:
            self.current_track_id = track_id
            # 新歌曲开始时重置进度和歌词，以确保它们被重新发送
            self.last_progress_sent = -1.0
            self.last_lyric_id = None
            return True
        return False

    def is_new_progress(self, progress: float) -> bool:
        """检查进度是否有足够的变化以值得发送"""
        # 只有当进度变化超过0.5秒时才发送，以减少网络流量
        if abs(progress - self.last_progress_sent) > 0.5:
            self.last_progress_sent = progress
            return True
        return False

    def is_new_album_cover(self, pic_url: str) -> bool:
        """检查专辑封面是否已更新"""
        if pic_url and pic_url != self.last_pic_url:
            self.last_pic_url = pic_url
            return True
        return False

    def is_new_lyric(self, track_id: int) -> bool:
        """检查是否需要为当前歌曲发送歌词"""
        if track_id != self.last_lyric_id:
            self.last_lyric_id = track_id
            return True
        return False
        


# 全局状态实例
player_state = PlayerState()

# --- 网络请求 ---


async def fetch_json(session: aiohttp.ClientSession, url: str) -> Optional[Dict[str, Any]]:
    """异步获取并解析JSON数据"""
    try:
        async with session.get(url, timeout=5) as response:
            if response.status == 200:
                return await response.json()
            logging.warning(f"访问 {url} 失败，状态码: {response.status}")
            return None
    except aiohttp.ClientError as e:
        logging.error(f"请求 {url} 时发生网络错误: {e}")
        return None
    except json.JSONDecodeError:
        logging.error(f"无法解析来自 {url} 的JSON响应")
        return None


async def fetch_text(session: aiohttp.ClientSession, url: str) -> Optional[str]:
    """异步获取文本数据"""
    try:
        async with session.get(url, timeout=5) as response:
            if response.status == 200:
                return await response.text()
            logging.info(f"访问 {url} 无内容或失败，状态码: {response.status}")
            return None
    except aiohttp.ClientError as e:
        logging.error(f"请求 {url} 时发生网络错误: {e}")
        return None

# --- WebSocket 消息发送 ---


async def send_ws_message(ws: WebSocketClientProtocol, message_type: str, value: Dict[str, Any]):
    """构建并发送WebSocket消息"""
    try:
        body = {"type": message_type, "value": value}
        packed_body = to_body(body)
        await ws.send(packed_body)
        #logging.info(f"已发送消息: {message_type}, 数据: {value}")
    except ConnectionClosed:
        logging.warning("WebSocket 连接已关闭，无法发送消息。")
    except Exception as e:
        logging.error(f"发送WebSocket消息时出错: {e}")


# --- 核心逻辑 ---
async def handle_track_update(session: aiohttp.ClientSession, ws: WebSocketClientProtocol, track_data: Dict[str, Any]):
    """处理歌曲更新，获取详细信息并发送到amll"""
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

        # 从YesPlay API数据中提取所需信息
        artists = [{"id": str(artist.get('id', '')), "name": artist.get('name', '')}
                   for artist in track_info.get('ar', [])]

        music_info = {
            "musicId": str(track_id),
            "musicName": track_info.get('name', ''),
            "albumId": str(track_info.get('al', {}).get('id', '')),
            "albumName": track_info.get('al', {}).get('name', ''),
            "artists": artists,
            "duration": track_info.get('dt', 0),  # 持续时间，单位毫秒
        }
        await send_ws_message(ws, ENUM_TO_CAMEL[MessageType.SET_MUSIC_INFO], music_info)

        # 2. 发送专辑封面
        pic_url = track_info.get('al', {}).get('picUrl')
        if pic_url and player_state.is_new_album_cover(pic_url):
            await send_ws_message(ws, ENUM_TO_CAMEL[MessageType.SET_MUSIC_ALBUM_COVER_IMAGE_URI], {"imgUrl": pic_url})

        # 3. 发送歌词 (TTML优先)
        if player_state.is_new_lyric(track_id):
            await handle_lyrics(session, ws, track_id)

    # 4. 发送播放进度
    #progress_ms = int(track_data.get('progress', 0) * 1000)  # 将秒转为毫秒
    #if player_state.is_new_progress(progress_ms):
    #    await send_ws_message(ws, ENUM_TO_CAMEL[MessageType.ON_PLAY_PROGRESS], {"progress": progress_ms})


async def handle_lyrics(session: aiohttp.ClientSession, ws: WebSocketClientProtocol, track_id: int):
    """获取并发送歌词，优先使用TTML格式"""
    # 尝试获取TTML歌词
    ttml_url = TTML_LYRIC_API_TEMPLATE.format(song_id=track_id)
    ttml_lyrics = await fetch_text(session, ttml_url)

    if ttml_lyrics:
        logging.info(f"成功获取歌曲 {track_id} 的TTML歌词。")
        await send_ws_message(ws, ENUM_TO_CAMEL[MessageType.SET_LYRIC_FROM_TTML], {"data": ttml_lyrics})
        return

    # 如果TTML获取失败，则回退到从YesPlay获取LRC歌词作为备选
    logging.info(f"未找到歌曲 {track_id} 的TTML歌词，回退到LRC格式。")
    lyric_url = f"{YESPLAY_LYRIC_API}?id={track_id}"
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


def parse_lrc(lrc_text: str) -> List[Dict[str, Any]]:
    """
    解析LRC格式的歌词文本。
    返回一个符合 amll SET_LYRIC 消息格式的列表。
    """
    lines = []
    # LRC时间标签的正则表达式，例如 [00:12.34]
    time_tag_re = re.compile(r'\[(\d{2}):(\d{2})\.(\d{2,3})\]')

    for line in lrc_text.splitlines():
        match = time_tag_re.match(line)
        if not match:
            continue

        minutes = int(match.group(1))
        seconds = int(match.group(2))
        milliseconds = int(match.group(3))
        # 根据是2位还是3位毫秒进行调整
        if len(match.group(3)) == 2:
            milliseconds *= 10

        start_time_ms = (minutes * 60 + seconds) * 1000 + milliseconds

        # 歌词内容是标签之后的部分
        lyric_content = line[match.end():].strip()

        if lyric_content:
            # amll协议需要行和字的起止时间。
            # 对于LRC这种只有行时间的格式，我们进行简化：
            # - 将行的结束时间设为下一行的开始时间（或一个估算值）
            # 对于LRC，我们将整行歌词作为一个 "word"
            word = {
                "startTime": start_time_ms,
                "endTime": 0,  # 稍后填充
                "word": lyric_content
            }

            lines.append({
                "startTime": start_time_ms,
                "endTime": 0,  # 稍后填充
                "words": [word],
                "translatedLyric": "",
                "romanLyric": "",
                "flag": 0,
            })

    # 填充每句歌词的结束时间
    if not lines:
        return []

    for i in range(len(lines)):
        # 设置行和单词的结束时间
        # 如果是最后一行，则估算一个持续时间（例如5秒）
        end_time = lines[i+1]["startTime"] if i + \
            1 < len(lines) else lines[i]["startTime"] + 5000
        lines[i]["endTime"] = end_time
        if lines[i]["words"]:
            lines[i]["words"][0]["endTime"] = end_time

    return lines


async def main_loop():
    """主循环，连接并同步播放器状态"""
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                logging.info(f"正在连接到 amll WebSocket: {AMLL_WS_URI}")
                async with websockets.connect(AMLL_WS_URI) as ws:
                    logging.info("成功连接到 amll WebSocket。")
                    player_state.reset()  # 每次重连时重置状态
                    
                    
                    get_time=time.time()
                    player_data = await fetch_json(session, YESPLAY_PLAYER_API)
                    last_time = player_data['progress'] * 1000
                    last_time_clock=time.time()
                    playing=False
                    is_send_go=False
                    is_send_stop=False
                    while True:
                        if time.time()-get_time>GET_TIME_WAIT:
                            get_time=time.time()
                            player_data = await fetch_json(session, YESPLAY_PLAYER_API)
                        #print(f"获取到播放器数据: {player_data["progress"]} 秒")
                        
                        #smooth进度逻辑
                        if player_data and 'progress' in player_data:
                            current_time = player_data['progress'] * 1000
                            if current_time != last_time:
                                if not playing:
                                    is_send_go=True
                                last_time = current_time
                                last_time_clock=time.time()
                            else:
                                #print(time.time()-last_time_clock)
                                if time.time()-last_time_clock>1.2:#1秒的yesplay延迟+0.6秒的平滑延迟
                                    if playing:
                                        is_send_stop=True
                        if is_send_go:
                            is_send_go=False
                            playing=True
                            # 发送开始播放消息
                            # 计算平滑时间
                            smoothtime = float(
                                (time.time() - last_time_clock) * 1000 + last_time)
                            await send_ws_message(ws, ENUM_TO_CAMEL[MessageType.ON_RESUMED], {"progress": smoothtime})
                            logging.info(f"发送: ON_PLAYING, 进度: {last_time} ms")
                        if is_send_stop:
                            is_send_stop=False
                            playing=False
                            # 发送暂停消息
                            await send_ws_message(ws, ENUM_TO_CAMEL[MessageType.ON_PAUSED], {})
                            logging.info("发送: ON_PAUSED (播放已暂停)")
                        
                        if playing:
                            smoothtime = int(
                                (time.time() - last_time_clock) * 1000 + last_time)
                            #print(smoothtime,type(smoothtime))
                            await send_ws_message(ws, ENUM_TO_CAMEL[MessageType.ON_PLAY_PROGRESS], {"progress": smoothtime})

                        
                        if player_data and player_data.get('currentTrack'):
                            await handle_track_update(session, ws, player_data)
                        
                        await asyncio.sleep(POLL_INTERVAL)

            except websockets.exceptions.ConnectionClosedError:
                logging.warning("与 amll 的 WebSocket 连接断开。将在5秒后尝试重连...")
            except ConnectionRefusedError:
                logging.error(
                    f"无法连接到 {AMLL_WS_URI}。请确保 amll 服务正在运行。将在5秒后尝试重连...")
            except Exception as e:
                logging.error(f"发生未知错误: {e}。将在5秒后尝试重连...")

            await asyncio.sleep(5)

if __name__ == "__main__":
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        logging.info("程序已手动停止。")
