# -*- coding: utf-8 -*-
"""
主程序入口
负责初始化、连接WebSocket以及运行主事件循环。
"""

import asyncio
import time

import aiohttp
import websockets
from loguru import logger

# --- 模块导入 ---
# 配置
import config
# 状态管理
from state import player_state
import state as s
# 工具和辅助函数
from utils import fetch_json, setup_logger
from player_tools import get_player_volume
# 事件处理器
from event_handlers import handle_incoming_messages, handle_track_update, send_ws_message
# WebSocket协议
from ws_protocol import MessageType, ENUM_TO_CAMEL

async def main_loop():
    """
    主循环，负责连接和同步播放器状态。
    """
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                logger.info(f"正在连接到 amll WebSocket: {config.AMLL_WS_URI}")
                async with websockets.connect(config.AMLL_WS_URI) as ws:
                    logger.info("成功连接到 amll WebSocket。")
                    player_state.reset()  # 每次重连时重置状态

                    # 并发运行消息监听任务
                    listener_task = asyncio.create_task(handle_incoming_messages(ws))

                    # 初始化时发送当前音量
                    initial_volume = await get_player_volume()
                    if initial_volume is not None:
                        await send_ws_message(ws, ENUM_TO_CAMEL[MessageType.ON_VOLUME_CHANGED], {"volume": initial_volume})

                    # 获取初始播放器数据并初始化时间和进度
                    get_time = time.time()
                    player_data = await fetch_json(session, config.YESPLAY_PLAYER_API)
                    if player_data and 'progress' in player_data:
                        await send_ws_message(ws, ENUM_TO_CAMEL[MessageType.ON_PLAY_PROGRESS], {"progress": int(player_data["progress"] * 1000)})
                        last_time = player_data.get('progress', 0) * 1000
                    else:
                        last_time = 0
                    last_time_clock = time.time()
                    
                    # --- 主循环 ---
                    while True:
                        # 检查监听任务是否已结束（连接断开）
                        if listener_task.done():
                            try:
                                listener_task.result()
                            except Exception as e:
                                logger.error(f"消息监听任务意外终止: {e}")
                            break

                        tmp_is_force_refresh = s.is_force_refresh
                        
                        # 定期或在需要时刷新播放器数据
                        if time.time() - get_time > config.GET_TIME_WAIT or s.is_force_refresh:
                            get_time = time.time()
                            player_data = await fetch_json(session, config.YESPLAY_PLAYER_API)
                            
                            if s.is_force_refresh:
                                s.is_force_refresh = False
                                if player_data and 'progress' in player_data:
                                    last_time = player_data['progress'] * 1000
                                    last_time_clock = time.time()
                                    await send_ws_message(ws, ENUM_TO_CAMEL[MessageType.ON_PLAY_PROGRESS], {"progress": int(last_time)})

                        # 根据播放器数据更新播放状态
                        if player_data and 'progress' in player_data:
                            current_time = player_data['progress'] * 1000
                            if current_time != last_time:
                                last_time = current_time
                                last_time_clock = time.time()
                                if not s.playing and not s.is_ui_stop and not(s.is_force_refresh):
                                    s.is_send_go = True
                                s.is_ui_stop = False
                            else:
                                # 如果进度长时间未变，则判断为暂停
                                if time.time() - last_time_clock > 1.2 and s.playing:
                                    s.is_send_stop = True

                        # 根据状态标志发送播放/暂停消息
                        if s.is_send_go:
                            s.is_send_go = False
                            s.playing = True
                            await send_ws_message(ws, ENUM_TO_CAMEL[MessageType.ON_RESUMED], {"progress": last_time})
                            logger.info(f"发送: ON_RESUMED, 进度: {last_time} ms")

                            # 播放开始时，尝试更新音量信息
                            current_volume = await get_player_volume()
                            if current_volume is not None:
                                await send_ws_message(ws, ENUM_TO_CAMEL[MessageType.ON_VOLUME_CHANGED], {"volume": current_volume})
                                logger.info(f"播放状态变更，更新音量为: {current_volume}")

                        if s.is_send_stop:
                            s.is_send_stop = False
                            s.playing = False
                            await send_ws_message(ws, ENUM_TO_CAMEL[MessageType.ON_PAUSED], {})
                            logger.info("发送: ON_PAUSED")

                        # 如果正在播放，平滑地计算并发送进度更新
                        if s.playing:
                            smoothtime = int((time.time() - last_time_clock) * 1000 + last_time)
                            if tmp_is_force_refresh:
                                smoothtime = int(last_time)
                            await send_ws_message(ws, ENUM_TO_CAMEL[MessageType.ON_PLAY_PROGRESS], {"progress": smoothtime})
                        # 如果是强制刷新或播放器状态有变化，则发送当前进度，即便未播放
                        if tmp_is_force_refresh:
                            await send_ws_message(ws, ENUM_TO_CAMEL[MessageType.ON_PLAY_PROGRESS], {"progress": int(last_time)})

                        # 如果有歌曲数据，则处理歌曲信息更新
                        if player_data and player_data.get('currentTrack'):
                            await handle_track_update(session, ws, player_data)

                        await asyncio.sleep(config.POLL_INTERVAL)

                    # 确保监听任务在退出循环时被取消
                    if not listener_task.done():
                        listener_task.cancel()
                        await asyncio.gather(listener_task, return_exceptions=True)

            except websockets.exceptions.ConnectionClosedError:
                logger.warning("与 amll 的 WebSocket 连接断开。将在5秒后尝试重连...")
            except ConnectionRefusedError:
                logger.error(f"无法连接到 {config.AMLL_WS_URI}。请确保 amll 服务正在运行。将在5秒后尝试重连...")
            except Exception as e:
                logger.error(f"主循环发生未知错误: {e}。将在5秒后尝试重连...")

            await asyncio.sleep(5)

if __name__ == "__main__":
    setup_logger()
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        logger.info("程序已手动停止。")
