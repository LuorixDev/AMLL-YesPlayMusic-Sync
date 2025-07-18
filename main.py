# -*- coding: utf-8 -*-

import asyncio
import json
import logging
import platform
import re
import time
from typing import Dict, Any, Optional, List

import aiohttp
import websockets
from websockets.client import WebSocketClientProtocol
from websockets.exceptions import ConnectionClosed

from ws_protocol import to_body, MessageType, ENUM_TO_CAMEL, parse_body

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
            
        #新歌的进度发送
        await send_ws_message(ws, ENUM_TO_CAMEL[MessageType.ON_PLAY_PROGRESS], {"progress": int(track_data["progress"] * 1000)})

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


async def get_player_volume() -> Optional[float]:
    """通过DBus获取播放器的当前音量。仅限Linux。"""
    if platform.system() != "Linux":
        return None

    dbus_command = (
        "dbus-send --print-reply --dest=org.mpris.MediaPlayer2.yesplaymusic "
        "/org/mpris/MediaPlayer2 org.freedesktop.DBus.Properties.Get "
        "string:org.mpris.MediaPlayer2.Player string:Volume"
    )
    try:
        process = await asyncio.create_subprocess_shell(
            dbus_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        if process.returncode == 0:
            output = stdout.decode().strip()
            # 匹配 "double 0.5" 这样的输出
            match = re.search(r'double\s+([0-9.]+)', output)
            if match:
                volume = float(match.group(1))
                logging.info(f"成功获取到当前音量: {volume}")
                return volume
            else:
                logging.warning(f"无法从DBus响应中解析音量: {output}")
        else:
            logging.error(f"获取音量失败: {stderr.decode().strip()}")
        return None
    except Exception as e:
        logging.error(f"获取音量时发生错误: {e}")
        return None


async def control_player(action: str, value: Any = None):
    """
    控制音乐播放器。
    在Linux上使用DBus，其他系统则记录不支持。
    """
    if platform.system() == "Linux":
        dbus_command = ""
        if action in ['playpause', 'next', 'previous']:
            command = ""
            if action == 'playpause':
                command = "PlayPause"
            elif action == 'next':
                command = "Next"
            elif action == 'previous':
                command = "Previous"
            dbus_command = (
                f"dbus-send --print-reply "
                f"--dest=org.mpris.MediaPlayer2.yesplaymusic "
                f"/org/mpris/MediaPlayer2 "
                f"org.mpris.MediaPlayer2.Player.{command}"
            )
        elif action == 'seek':
            # MPRIS SetPosition 使用微秒 (microseconds)
            position_micro = int(value * 1000)
            dbus_command = (
                f"dbus-send --print-reply "
                f"--dest=org.mpris.MediaPlayer2.yesplaymusic "
                f"/org/mpris/MediaPlayer2 "
                f"org.mpris.MediaPlayer2.Player.SetPosition "
                f"objpath:/not/used int64:{position_micro}"
            )
        elif action == 'set_volume':
            # MPRIS Volume 是 0.0 到 1.0 的 double
            volume = float(value)
            dbus_command = (
                f"dbus-send --print-reply "
                f"--dest=org.mpris.MediaPlayer2.yesplaymusic "
                f"/org/mpris/MediaPlayer2 "
                f"org.freedesktop.DBus.Properties.Set "
                f"string:org.mpris.MediaPlayer2.Player "
                f"string:Volume variant:double:{volume}"
            )
        else:
            logging.warning(f"未知的播放器控制动作: {action}")
            return
        try:
            logging.info(f"执行DBus命令: {dbus_command}")
            # 使用 asyncio.create_subprocess_shell 来异步执行命令
            process = await asyncio.create_subprocess_shell(
                dbus_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            if process.returncode == 0:
                logging.info(f"成功执行 '{action}' 操作。")
            else:
                logging.error(
                    f"执行DBus命令失败: {stderr.decode().strip()}")
        except Exception as e:
            logging.error(f"执行DBus命令时出错: {e}")
    else:
        logging.info(
            f"接收到 '{action}' 指令，但当前系统 ({platform.system()}) 不支持DBus控制。")


async def handle_incoming_messages(ws: WebSocketClientProtocol):
    """监听并处理来自 amll 的传入消息"""
    global playing, is_send_go, is_send_stop, is_ui_stop
    try:
        async for message in ws:
            try:
                parsed_msg = parse_body(message)
                msg_type_str = parsed_msg.get('type')
                logging.info(f"收到消息: {msg_type_str}")

                if msg_type_str in [ENUM_TO_CAMEL[MessageType.PAUSE], ENUM_TO_CAMEL[MessageType.RESUME]]:
                    await control_player('playpause')
                    if msg_type_str == ENUM_TO_CAMEL[MessageType.RESUME]:
                        is_send_go = True
                    else:
                        #print("暂停")
                        is_ui_stop=True
                        is_send_stop = True
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
playing = False
is_send_go = False
is_send_stop = False
is_ui_stop = False  # 用于UI控制，是否暂停
async def main_loop():
    """主循环，连接并同步播放器状态"""
    global playing, is_send_go, is_send_stop,is_ui_stop
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                logging.info(f"正在连接到 amll WebSocket: {AMLL_WS_URI}")
                async with websockets.connect(AMLL_WS_URI) as ws:
                    logging.info("成功连接到 amll WebSocket。")
                    player_state.reset()  # 每次重连时重置状态

                    # 并发运行消息监听任务和状态发送任务
                    listener_task = asyncio.create_task(
                        handle_incoming_messages(ws))

                    # 初始化时发送当前音量
                    initial_volume = await get_player_volume()
                    if initial_volume is not None:
                        await send_ws_message(ws, ENUM_TO_CAMEL[MessageType.ON_VOLUME_CHANGED], {"volume": initial_volume})

                    get_time = time.time()
                    player_data = await fetch_json(session, YESPLAY_PLAYER_API)
                    await send_ws_message(ws, ENUM_TO_CAMEL[MessageType.ON_PLAY_PROGRESS], {"progress": int(player_data["progress"] * 1000)})
                    last_time = player_data.get('progress', 0) * 1000
                    last_time_clock = time.time()
                    

                    while True:
                        # 检查监听任务是否已结束，如果结束则意味着连接可能已断开
                        if listener_task.done():
                            try:
                                # 如果任务异常结束，结果会在这里抛出
                                listener_task.result()
                            except Exception as e:
                                logging.error(f"消息监听任务意外终止: {e}")
                            logging.info("监听任务结束，退出当前连接循环。")
                            break  # 退出内层循环以重新连接

                        if time.time() - get_time > GET_TIME_WAIT:
                            get_time = time.time()
                            player_data = await fetch_json(
                                session, YESPLAY_PLAYER_API)

                        if player_data and 'progress' in player_data:
                            current_time = player_data['progress'] * 1000
                            if current_time != last_time:
                                if is_ui_stop:
                                    is_ui_stop = False
                                    last_time = current_time
                                    last_time_clock = time.time()
                                else:
                                    if not playing:
                                        is_send_go = True
                                    last_time = current_time
                                    last_time_clock = time.time()
                            else:
                                if time.time() - last_time_clock > 1.2:
                                    if playing:
                                        is_send_stop = True

                        if is_send_go:
                            is_send_go = False
                            playing = True
                            smoothtime = float(
                                (time.time() - last_time_clock) * 1000 + last_time)
                            await send_ws_message(ws, ENUM_TO_CAMEL[MessageType.ON_RESUMED], {"progress": smoothtime})
                            logging.info(
                                f"发送: ON_PLAYING, 进度: {last_time} ms")

                        if is_send_stop:
                            is_send_stop = False
                            playing = False
                            await send_ws_message(ws, ENUM_TO_CAMEL[MessageType.ON_PAUSED], {})
                            logging.info("发送: ON_PAUSED (播放已暂停)")

                        if playing:
                            smoothtime = int(
                                (time.time() - last_time_clock) * 1000 + last_time)
                            await send_ws_message(ws, ENUM_TO_CAMEL[MessageType.ON_PLAY_PROGRESS], {"progress": smoothtime})

                        if player_data and player_data.get('currentTrack'):
                            await handle_track_update(session, ws, player_data)
                            #print(1)
                            #await send_ws_message(ws, ENUM_TO_CAMEL[MessageType.ON_PLAY_PROGRESS], {"progress": int(player_data["progress"] * 1000)})

                        await asyncio.sleep(POLL_INTERVAL)

                    # 确保监听任务在退出循环时被取消
                    if not listener_task.done():
                        listener_task.cancel()
                        await asyncio.gather(listener_task, return_exceptions=True)

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
