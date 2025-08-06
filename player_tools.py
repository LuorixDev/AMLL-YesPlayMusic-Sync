# -*- coding: utf-8 -*-

import asyncio
import logging
import platform
import re
from typing import Any, Optional
import subprocess

def get_yesplaymusic_pipewire_id():
    """
    获取 YesPlayMusic 的 PipeWire ID
    返回: str 或 None - 找到时返回 PipeWire ID，未找到时返回 None
    """
    try:
        # 使用 pgrep 获取 YesPlayMusic 进程的 PID
        # -i: 忽略大小写, -f: 匹配完整命令行
        cmd = "pgrep -if yesplaymusic"
        result = subprocess.check_output(cmd, shell=True, text=True)
        pids = result.strip().splitlines()

        if not pids:
            logging.debug("未找到 YesPlayMusic 进程。")
            return None

        # 获取 PipeWire sink-inputs
        cmd = "pactl list sink-inputs"
        result = subprocess.check_output(cmd, shell=True, text=True)
        # 按 "Sink Input #" 分割，方便处理每个 sink input
        sink_sections = result.split("Sink Input #")

        for pid in pids:
            for section in sink_sections[1:]: # 第一个元素是空的
                # 检查进程ID是否在 sink input 的属性中
                if f'application.process.id = "{pid}"' in section:
                    # 从 section 开头提取 sink input ID
                    id_match = re.match(r'(\d+)', section)
                    if id_match:
                        pipewire_id = id_match.group(1)
                        logging.debug(f"找到 YesPlayMusic 的 PipeWire ID: {pipewire_id} (PID: {pid})")
                        return pipewire_id
        
        logging.debug("已找到 YesPlayMusic 进程，但未找到关联的 PipeWire sink input。可能没有在播放。")
        return None
    except subprocess.CalledProcessError:
        logging.debug("查找 YesPlayMusic PipeWire ID 时出错 (pgrep 或 pactl 命令失败)。")
        return None
    except Exception as e:
        logging.error(f"查找 PipeWire ID 时发生未知错误: {e}")
        return None

async def get_player_volume() -> Optional[float]:
    """
    通过 pactl 获取播放器的当前音量。
    此功能仅限于Linux系统。
    
    Returns:
        Optional[float]: 返回播放器音量（0.0到1.0之间），如果获取失败则返回None。
    """
    if platform.system() != "Linux":
        logging.info("非Linux系统，跳过获取音量。")
        return None

    pipewire_id = get_yesplaymusic_pipewire_id()
    if not pipewire_id:
        logging.warning("无法获取 YesPlayMusic 的 PipeWire ID，无法获取音量。可能没有在播放。")
        return None

    try:
        # 使用 pactl 获取指定 sink input 的音量
        cmd = (
            f'pactl list sink-inputs | grep -A20 "Sink Input #{pipewire_id}" | '
            f"grep 'Volume:' | head -n1 | grep -oP '\\d{{1,3}}%' | head -n1"
        )
        process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode == 0 and stdout:
            volume_str = stdout.decode().strip().replace('%', '')
            volume = float(volume_str) / 100.0
            logging.info(f"成功获取到当前音量: {volume}")
            return volume
        else:
            error_message = stderr.decode().strip()
            # 如果没有输出，也认为是错误
            if not error_message and not stdout:
                error_message = "pactl 命令没有返回音量信息。"
            logging.error(f"获取音量失败: {error_message}")
            return None
    except Exception as e:
        logging.error(f"获取音量时发生错误: {e}")
        return None

async def get_player_status() -> Optional[str]:
    """
    通过 D-Bus 获取播放器的当前播放状态。
    此功能仅限于Linux系统。

    Returns:
        Optional[str]: 返回播放状态（例如 "Playing", "Paused"），如果获取失败则返回None。
    """
    if platform.system() != "Linux":
        logging.debug("非Linux系统，跳过获取播放状态。")
        return None

    dbus_command = (
        "dbus-send --print-reply --dest=org.mpris.MediaPlayer2.yesplaymusic "
        "/org/mpris/MediaPlayer2 org.freedesktop.DBus.Properties.Get "
        "string:'org.mpris.MediaPlayer2.Player' string:'PlaybackStatus'"
    )

    try:
        process = await asyncio.create_subprocess_shell(
            dbus_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode == 0 and stdout:
            output = stdout.decode().strip()
            match = re.search(r'string "(Playing|Paused|Stopped)"', output)
            if match:
                status = match.group(1)
                logging.debug(f"成功获取到播放状态: {status}")
                return status
            else:
                logging.warning(f"无法从DBus输出中解析播放状态: {output}")
                return None
        else:
            error_message = stderr.decode().strip()
            if "was not provided by any .service files" in error_message:
                 logging.debug(f"获取播放状态失败，可能是播放器未运行: {error_message}")
            else:
                logging.error(f"获取播放状态失败: {error_message}")
            return None
    except Exception as e:
        logging.error(f"获取播放状态时发生错误: {e}")
        return None

async def control_player(action: str, value: Any = None):
    """
    通过D-Bus或pactl控制音乐播放器。
    支持播放/暂停、下一首、上一首、跳转进度和设置音量。
    此功能仅限于Linux系统。

    Args:
        action (str): 控制动作，如 'playpause', 'next', 'previous', 'seek', 'set_volume'。
        value (Any, optional): 动作需要的参数。例如，'seek'需要进度（毫秒），'set_volume'需要音量（0.0-1.0）。
    """
    if platform.system() != "Linux":
        logging.info(f"接收到 '{action}' 指令，但当前系统 ({platform.system()}) 不支持控制。")
        return

    # 音量控制使用 pactl
    if action == 'set_volume':
        pipewire_id = get_yesplaymusic_pipewire_id()
        if not pipewire_id:
            logging.warning("无法获取 YesPlayMusic 的 PipeWire ID，无法设置音量。可能没有在播放。")
            return
        
        try:
            # 将 0.0-1.0 的音量转换为百分比
            volume_percent = int(float(value) * 100)
            cmd = f"pactl set-sink-input-volume {pipewire_id} {volume_percent}%"
            
            logging.info(f"执行 pactl 命令: {cmd}")
            process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            if process.returncode == 0:
                logging.info(f"成功执行 'set_volume' 操作。")
            else:
                logging.error(f"执行 pactl 命令失败: {stderr.decode().strip()}")
        except Exception as e:
            logging.error(f"执行 pactl 命令时出错: {e}")
        return

    # 其他控制继续使用 D-Bus
    dbus_command = ""
    if action in ['playpause', 'next', 'previous']:
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
        position_micro = int(value * 1000)
        dbus_command = (
            f"dbus-send --print-reply "
            f"--dest=org.mpris.MediaPlayer2.yesplaymusic "
            f"/org/mpris/MediaPlayer2 "
            f"org.mpris.MediaPlayer2.Player.SetPosition "
            f"objpath:/not/used int64:{position_micro}"
        )
    else:
        logging.warning(f"未知的播放器控制动作: {action}")
        return

    try:
        logging.info(f"执行DBus命令: {dbus_command}")
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
