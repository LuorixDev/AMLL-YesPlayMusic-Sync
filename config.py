# -*- coding: utf-8 -*-
"""
配置文件
存放项目的所有静态配置，例如API地址、轮询间隔等。
"""

# API地址
YESPLAY_PLAYER_API = "http://127.0.0.1:27232/player"
YESPLAY_LYRIC_API = "http://127.0.0.1:10754/lyric"
YESPLAY_YRC_LYRIC_API = "http://127.0.0.1:3000/lyric/new"
TTML_LYRIC_API_TEMPLATES = [
    "https://amll.mirror.dimeta.top/api/db/ncm-lyrics/{song_id}.ttml",
]
AMLL_WS_URI = "ws://192.168.1.172:11444"

# 轮询和时间间隔 (秒)
POLL_INTERVAL = 0.01          # 主循环的轮询间隔
GET_TIME_WAIT= 0.1            # 获取播放器数据的间隔时间
