import asyncio
import websockets
import time
import random
from ws_protocol import to_body

# WebSocket 服务器地址
WEBSOCKET_URI = "ws://localhost:11444"

# 模拟的歌曲信息
SONG_DURATION_MS = 30 * 1000  # 30 秒

async def simulate_playback():
    """连接到 WebSocket 服务器并模拟一首歌的播放流程"""
    try:
        async with websockets.connect(WEBSOCKET_URI) as websocket:
            print(f"成功连接到 {WEBSOCKET_URI}")

            # 1. 设置歌曲信息 (SetMusicInfo)
            print("发送: SetMusicInfo")
            music_info = {
                "type": "setMusicInfo",
                "value": {
                    "musicId": "song-123",
                    "musicName": "Cline's Demo Song",
                    "albumId": "album-456",
                    "albumName": "The Code Symphony",
                    "artists": [
                        {"id": "artist-789", "name": "The Virtual Singers"}
                    ],
                    "duration": SONG_DURATION_MS,
                },
            }
            await websocket.send(to_body(music_info))
            await asyncio.sleep(0.1)

            # 2. 设置专辑封面 (SetMusicAlbumCoverImageURI)
            print("发送: SetMusicAlbumCoverImageURI")
            cover_info = {
                "type": "setMusicAlbumCoverImageURI",
                "value": {
                    # 使用一个公共的占位图
                    "imgUrl": "https://via.placeholder.com/300"
                }
            }
            await websocket.send(to_body(cover_info))
            await asyncio.sleep(0.1)

            # 3. 设置歌词 (SetLyric)
            print("发送: SetLyric")
            lyric_info = {
                "type": "setLyric",
                "value": {
                    "data": [
                        {
                            "startTime": 1000, "endTime": 4000,
                            "words": [{"startTime": 1500, "endTime": 3500, "word": "Hello, world"}],
                            "translatedLyric": "你好，世界", "romanLyric": "", "flag": 0
                        },
                        {
                            "startTime": 5000, "endTime": 8000,
                            "words": [{"startTime": 5500, "endTime": 7500, "word": "This is a test"}],
                            "translatedLyric": "这是一个测试", "romanLyric": "", "flag": 0
                        },
                         {
                            "startTime": 9000, "endTime": 15000,
                            "words": [{"startTime": 9500, "endTime": 14500, "word": "Simulating music playback"}],
                            "translatedLyric": "正在模拟音乐播放", "romanLyric": "", "flag": 0
                        },
                        {
                            "startTime": 16000, "endTime": 29000,
                            "words": [{"startTime": 16500, "endTime": 28500, "word": "Enjoy the show!"}],
                            "translatedLyric": "欣赏表演吧！", "romanLyric": "", "flag": 1
                        },
                    ]
                }
            }
            await websocket.send(to_body(lyric_info))
            await asyncio.sleep(0.1)

            # 4. 恢复/开始播放 (OnResumed)
            print("发送: OnResumed")
            await websocket.send(to_body({"type": "onResumed"}))

            # 5. 模拟播放进度 (OnPlayProgress)
            print("开始模拟播放进度...")
            start_time = time.time()
            current_progress = 0
            while current_progress < SONG_DURATION_MS:
                elapsed_s = time.time() - start_time
                current_progress = int(elapsed_s * 1000)
                
                progress_update = {
                    "type": "onPlayProgress",
                    "value": {"progress": min(current_progress, SONG_DURATION_MS)}
                }
                print(f"  -> 发送进度: {progress_update['value']['progress']} ms")
                await websocket.send(to_body(progress_update))
                
                # 等待1秒再发送下一次更新
                await asyncio.sleep(1)
            
            # 6. 暂停播放 (OnPaused)
            print("发送: OnPaused (播放结束)")
            await websocket.send(to_body({"type": "onPaused"}))

            print("模拟播放完成。")

    except (websockets.exceptions.ConnectionClosedError, ConnectionRefusedError) as e:
        print(f"连接失败: {e}")
        print("请确保 WebSocket 服务器正在 ws://localhost:11444 上运行。")
    except Exception as e:
        print(f"发生了一个错误: {e}")

if __name__ == "__main__":
    # 提示: 运行此脚本前，请确保已安装 websockets 库
    # pip install websockets
    print("准备开始模拟播放...")
    asyncio.run(simulate_playback())
