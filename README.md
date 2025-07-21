# AMLL YesPlayMusic Sync

这是一个将 [YesPlayMusic](https://github.com/qier222/YesPlayMusic) 播放器状态与 [amll (applemusic-like-lyrics)](https://github.com/Steve-xmh/applemusic-like-lyrics) 服务进行同步的Python工具。

> **旨在为Linux和安卓（容器）的用户提供本地的网易云在线歌曲播放支持。同时Win也可用。**


> NOTICE：**安卓容器**的用户可能需要使用本仓库release中的YesPlayMusic Fix版本，否则可能遇到运行Yesplaymusic提示非法指令错误。
> 
> 经测试，部分环境fix版本仍然可能报错，可尝试本地编译。（请自备git,nodejs16,yarn环境，不会的话问GPT)
> 
> 1.git clone https://github.com/qier222/YesPlayMusic
> 
> 2.yarn add electron@27.3.2
>
> 3. cp .env.example .env
> 
> 4.yarn electron:build --linux dir
> 
> 5.在dist_electron 中找到yesplaymusic
> 
> 6.运行 yesplaymusic --no-sandbox
> 
> 7.正常运行

它会实时获取 YesPlayMusic 的播放状态，包括当前曲目、播放进度、音量和播放/暂停状态，并通过 WebSocket 将这些信息发送给 `amll` 服务。这使得 `amll` 能够以精美的 Apple Music 风格展示实时歌词。

## ✨ 功能特性

- **实时同步**: 实时将 YesPlayMusic 的播放状态同步到 `amll`。
- **丰富的状态信息**: 同步包括曲目信息（歌名、歌手、专辑、封面）、播放进度、播放/暂停状态以及音量变化。
- **断线重连**: 能够自动检测与 `amll` WebSocket 服务的连接中断，并进行自动重连。
- **状态平滑**: 通过平滑处理播放进度，提供更流畅的状态更新。
- **配置简单**: 主要配置项集中在 `config.py` 文件中，方便修改和使用。

## 🚀 如何开始

### 1. 先决条件

在运行此脚本之前，请确保你已准备好：

- **Python 3.7+**
- 一个正在运行的 **YesPlayMusic** 实例，并确保其API可以访问。
- 一个正在运行的 **amll** 服务实例。

### 2. 安装依赖

你可以通过 `pip` 安装所需的依赖库：

```bash
pip install websockets aiohttp loguru requests
```

### 3. 配置

打开 `config.py` 文件，根据你的实际环境修改以下配置：

- `YESPLAY_PLAYER_API`: 你的 YesPlayMusic 播放器 API 地址。
  - 示例: `"http://localhost:7878/player"`
- `AMLL_WS_URI`: 你的 `amll` 服务的 WebSocket 地址。
  - 示例: `"ws://localhost:11444"`

### 4. 运行

完成配置后，直接运行主程序即可：

```bash
python main.py
```

程序启动后，它将自动连接到 `amll` 服务并开始同步 YesPlayMusic 的播放状态。

## 📁 项目结构

```
.
├── main.py             # 主程序入口，负责连接和主循环
├── config.py           # 配置文件，用于设置API和WebSocket地址
├── state.py            # 全局状态管理，保存播放器状态
├── event_handlers.py   # 事件处理器，处理来自amll的消息和播放器数据更新
├── player_tools.py     # 播放器相关的辅助工具
├── utils.py            # 通用辅助函数
├── ws_protocol.py      # 定义了与amll通信的WebSocket消息协议
└── README.md           # 本文档
```

## 📄 许可证

本项目采用 **GNU General Public License v3.0** 许可证。详情请参阅 [LICENSE](https://www.gnu.org/licenses/gpl-3.0.html) 文件。

