# -*- coding: utf-8 -*-
"""
状态管理模块
包含PlayerState类和所有全局共享的状态变量。
"""

from typing import Optional

class PlayerState:
    """
    用于跟踪当前播放器状态，以避免不必要的重复API请求和WS消息。
    """

    def __init__(self):
        self.current_track_id: Optional[int] = None
        self.last_progress_sent: float = -1.0
        self.last_pic_url: Optional[str] = None
        self.last_lyric_id: Optional[int] = None

    def reset(self):
        """重置所有状态，通常在重新连接时调用。"""
        self.current_track_id = None
        self.last_progress_sent = -1.0
        self.last_pic_url = None
        self.last_lyric_id = None

    def is_new_track(self, track_id: int) -> bool:
        """检查是否是新歌曲。如果是，则更新状态。"""
        if track_id != self.current_track_id:
            self.current_track_id = track_id
            # 新歌曲开始时重置进度和歌词，以确保它们被重新发送
            self.last_progress_sent = -1.0
            self.last_lyric_id = None
            return True
        return False

    def is_new_progress(self, progress: float) -> bool:
        """检查进度是否有足够的变化以值得发送。"""
        # 只有当进度变化超过0.5秒时才发送，以减少网络流量
        if abs(progress - self.last_progress_sent) > 0.5:
            self.last_progress_sent = progress
            return True
        return False

    def is_new_album_cover(self, pic_url: str) -> bool:
        """检查专辑封面是否已更新。"""
        if pic_url and pic_url != self.last_pic_url:
            self.last_pic_url = pic_url
            return True
        return False

    def is_new_lyric(self, track_id: int) -> bool:
        """检查是否需要为当前歌曲重新获取和发送歌词。"""
        if track_id != self.last_lyric_id:
            self.last_lyric_id = track_id
            return True
        return False

# --- 全局状态实例 ---
player_state = PlayerState()

# --- 播放控制相关的全局标志位 ---
# 这些变量在主循环和事件处理器之间共享，用于控制播放状态的同步

playing = False             # 当前是否正在播放
is_send_go = False          # 是否需要发送“开始/恢复播放”的信号
is_send_stop = False        # 是否需要发送“暂停”的信号
is_ui_stop = False          # UI是否触发了暂停（用于区分是本地暂停还是远程暂停）
is_force_refresh = False    # 是否需要强制刷新播放器状态（例如在歌曲切换或远程控制后）
