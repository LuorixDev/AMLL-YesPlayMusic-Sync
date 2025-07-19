# -*- coding: utf-8 -*-

import asyncio
import logging
import platform
import re
from typing import Any, Optional

async def get_player_volume() -> Optional[float]:
    """
    通过D-Bus获取播放器的当前音量。
    此功能仅限于Linux系统。
    
    Returns:
        Optional[float]: 返回播放器音量（0.0到1.0之间），如果非Linux系统或获取失败则返回None。
    """
    # 检查当前操作系统是否为Linux
    if platform.system() != "Linux":
        logging.info("非Linux系统，跳过通过DBus获取音量。")
        return None

    # 构建D-Bus命令以获取音量属性
    dbus_command = (
        "dbus-send --print-reply --dest=org.mpris.MediaPlayer2.yesplaymusic "
        "/org/mpris/MediaPlayer2 org.freedesktop.DBus.Properties.Get "
        "string:org.mpris.MediaPlayer2.Player string:Volume"
    )
    try:
        # 异步执行shell命令
        process = await asyncio.create_subprocess_shell(
            dbus_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        # 等待命令执行完成并获取输出
        stdout, stderr = await process.communicate()

        # 检查命令是否成功执行
        if process.returncode == 0:
            output = stdout.decode().strip()
            # 使用正则表达式从输出中解析音量值
            match = re.search(r'double\s+([0-9.]+)', output)
            if match:
                volume = float(match.group(1))
                logging.info(f"成功获取到当前音量: {volume}")
                return volume
            else:
                logging.warning(f"无法从DBus响应中解析音量: {output}")
        else:
            # 如果命令执行失败，记录错误信息
            logging.error(f"获取音量失败: {stderr.decode().strip()}")
        return None
    except Exception as e:
        logging.error(f"获取音量时发生错误: {e}")
        return None


async def control_player(action: str, value: Any = None):
    """
    通过D-Bus控制音乐播放器。
    支持播放/暂停、下一首、上一首、跳转进度和设置音量。
    此功能仅限于Linux系统。

    Args:
        action (str): 控制动作，如 'playpause', 'next', 'previous', 'seek', 'set_volume'。
        value (Any, optional): 动作需要的参数。例如，'seek'需要进度（毫秒），'set_volume'需要音量（0.0-1.0）。
    """
    # 检查当前操作系统是否为Linux
    if platform.system() != "Linux":
        logging.info(f"接收到 '{action}' 指令，但当前系统 ({platform.system()}) 不支持DBus控制。")
        return

    dbus_command = ""
    # 根据不同的action构建相应的D-Bus命令
    if action in ['playpause', 'next', 'previous']:
        # 播放控制命令
        command_map = {
            'playpause': 'PlayPause',
            'next': 'Next',
            'previous': 'Previous'
        }
        command = command_map.get(action)
        dbus_command = (
            f"dbus-send --print-reply "
            f"--dest=org.mpris.MediaPlayer2.yesplaymusic "
            f"/org/mpris/MediaPlayer2 "
            f"org.mpris.MediaPlayer2.Player.{command}"
        )
    elif action == 'seek':
        # 跳转播放进度，MPRIS规范要求使用微秒（microseconds）
        position_micro = int(value * 1000)
        dbus_command = (
            f"dbus-send --print-reply "
            f"--dest=org.mpris.MediaPlayer2.yesplaymusic "
            f"/org/mpris/MediaPlayer2 "
            f"org.mpris.MediaPlayer2.Player.SetPosition "
            f"objpath:/not/used int64:{position_micro}"
        )
    elif action == 'set_volume':
        # 设置音量，MPRIS规范要求音量是0.0到1.0之间的double类型
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
        # 异步执行shell命令
        process = await asyncio.create_subprocess_shell(
            dbus_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        if process.returncode == 0:
            logging.info(f"成功执行 '{action}' 操作。")
        else:
            logging.error(f"执行DBus命令失败: {stderr.decode().strip()}")
    except Exception as e:
        logging.error(f"执行DBus命令时出错: {e}")
