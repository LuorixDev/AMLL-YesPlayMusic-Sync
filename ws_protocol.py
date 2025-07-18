import struct
from enum import IntEnum
from typing import List, Dict, Any, Callable

# 协议中定义的 Magic Number，使用 IntEnum 更清晰
class MessageType(IntEnum):
    PING = 0
    PONG = 1
    SET_MUSIC_INFO = 2
    SET_MUSIC_ALBUM_COVER_IMAGE_URI = 3
    SET_MUSIC_ALBUM_COVER_IMAGE_DATA = 4
    ON_PLAY_PROGRESS = 5
    ON_VOLUME_CHANGED = 6
    ON_PAUSED = 7
    ON_RESUMED = 8
    ON_AUDIO_DATA = 9
    SET_LYRIC = 10
    SET_LYRIC_FROM_TTML = 11
    PAUSE = 12
    RESUME = 13
    FORWARD_SONG = 14
    BACKWARD_SONG = 15
    SET_VOLUME = 16
    SEEK_PLAY_PROGRESS = 17

# --- 名称转换映射 ---

# 从 camelCase 字符串到枚举成员的映射
CAMEL_TO_ENUM = {
    'ping': MessageType.PING,
    'pong': MessageType.PONG,
    'setMusicInfo': MessageType.SET_MUSIC_INFO,
    'setMusicAlbumCoverImageURI': MessageType.SET_MUSIC_ALBUM_COVER_IMAGE_URI,
    'setMusicAlbumCoverImageData': MessageType.SET_MUSIC_ALBUM_COVER_IMAGE_DATA,
    'onPlayProgress': MessageType.ON_PLAY_PROGRESS,
    'onVolumeChanged': MessageType.ON_VOLUME_CHANGED,
    'onPaused': MessageType.ON_PAUSED,
    'onResumed': MessageType.ON_RESUMED,
    'onAudioData': MessageType.ON_AUDIO_DATA,
    'setLyric': MessageType.SET_LYRIC,
    'setLyricFromTTML': MessageType.SET_LYRIC_FROM_TTML,
    'pause': MessageType.PAUSE,
    'resume': MessageType.RESUME,
    'forwardSong': MessageType.FORWARD_SONG,
    'backwardSong': MessageType.BACKWARD_SONG,
    'setVolume': MessageType.SET_VOLUME,
    'seekPlayProgress': MessageType.SEEK_PLAY_PROGRESS,
}

# 从枚举成员到 camelCase 字符串的映射
ENUM_TO_CAMEL = {v: k for k, v in CAMEL_TO_ENUM.items()}


# --- 辅助打包函数 ---

def _pack_null_string(s: str) -> bytes:
    """将字符串打包成 NullString (UTF-8 编码 + \0 结尾)"""
    if s is None:
        return b'\x00'
    return s.encode('utf-8') + b'\x00'

def _pack_vec(items: List[Any], item_packer: Callable[[Any], bytes]) -> bytes:
    """将列表打包成 Vec<T> (u32 数量 + T 列表)"""
    if not items:
        return struct.pack('<I', 0)
    
    packed_items = [item_packer(item) for item in items]
    return struct.pack('<I', len(items)) + b''.join(packed_items)

def _pack_u8_vec(data: bytes) -> bytes:
    """专门用于打包 Vec<u8>"""
    return struct.pack('<I', len(data)) + data

def _pack_artist(artist: Dict[str, str]) -> bytes:
    """打包 Artist 结构体"""
    return _pack_null_string(artist['id']) + _pack_null_string(artist['name'])

def _pack_lyric_word(word: Dict[str, Any]) -> bytes:
    """打包 LyricWord 结构体"""
    return (struct.pack('<QQ', word['startTime'], word['endTime']) +
            _pack_null_string(word['word']))

def _pack_lyric_line(line: Dict[str, Any]) -> bytes:
    """打包 LyricLine 结构体"""
    return (struct.pack('<QQ', line['startTime'], line['endTime']) +
            _pack_vec(line.get('words', []), _pack_lyric_word) +
            _pack_null_string(line.get('translatedLyric', '')) +
            _pack_null_string(line.get('romanLyric', '')) +
            struct.pack('<B', line.get('flag', 0)))

# --- 主 API 函数 ---

def to_body(body: Dict[str, Any]) -> bytes:
    """
    将一个代表消息的字典序列化为二进制数据。
    遵循 JS 接口的结构: { type: "messageName", value: { ... } }
    """
    type_str = body['type']
    value = body.get('value')
    
    message_type = CAMEL_TO_ENUM.get(type_str)
    if message_type is None:
        raise ValueError(f"未知的消息类型: {type_str}")

    # 所有消息都以 u16 的 Magic Number 开头
    payload = struct.pack('<H', message_type.value)

    # 根据消息类型附加数据
    if message_type in [MessageType.PING, MessageType.PONG, MessageType.ON_PAUSED, 
                        MessageType.ON_RESUMED, MessageType.PAUSE, MessageType.RESUME, 
                        MessageType.FORWARD_SONG, MessageType.BACKWARD_SONG]:
        # 这些消息没有额外数据
        pass
    elif message_type == MessageType.SET_MUSIC_INFO:
        payload += _pack_null_string(value['musicId'])
        payload += _pack_null_string(value['musicName'])
        payload += _pack_null_string(value.get('albumId', ''))
        payload += _pack_null_string(value.get('albumName', ''))
        payload += _pack_vec(value.get('artists', []), _pack_artist)
        payload += struct.pack('<Q', value['duration'])
    elif message_type == MessageType.SET_MUSIC_ALBUM_COVER_IMAGE_URI:
        payload += _pack_null_string(value['imgUrl'])
    elif message_type == MessageType.SET_MUSIC_ALBUM_COVER_IMAGE_DATA:
        payload += _pack_u8_vec(value['data'])
    elif message_type == MessageType.ON_PLAY_PROGRESS:
        payload += struct.pack('<Q', value['progress'])
    elif message_type == MessageType.ON_VOLUME_CHANGED:
        payload += struct.pack('<d', value['volume'])
    elif message_type == MessageType.ON_AUDIO_DATA:
        payload += _pack_u8_vec(value['data'])
    elif message_type == MessageType.SET_LYRIC:
        payload += _pack_vec(value.get('data', []), _pack_lyric_line)
    elif message_type == MessageType.SET_LYRIC_FROM_TTML:
        payload += _pack_null_string(value['data'])
    elif message_type == MessageType.SET_VOLUME:
        payload += struct.pack('<d', value['volume'])
    elif message_type == MessageType.SEEK_PLAY_PROGRESS:
        payload += struct.pack('<Q', value['progress'])
    else:
        raise ValueError(f"消息类型 '{type_str}' 的打包逻辑未实现")

    return payload

# --- 辅助解包函数 ---

class BytesReader:
    """一个简单的字节流读取器，帮助进行偏移管理"""
    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0

    def read(self, size: int) -> bytes:
        if self.offset + size > len(self.data):
            raise ValueError("读取超出字节范围")
        chunk = self.data[self.offset:self.offset + size]
        self.offset += size
        return chunk

    def read_struct(self, fmt: str) -> tuple:
        size = struct.calcsize(fmt)
        return struct.unpack(fmt, self.read(size))

    @property
    def is_eof(self) -> bool:
        return self.offset >= len(self.data)

def _unpack_null_string(reader: BytesReader) -> str:
    """从读取器中解包 NullString"""
    end_index = reader.data.find(b'\x00', reader.offset)
    if end_index == -1:
        raise ValueError("无效的 NullString，找不到结尾 '\\0'")
    
    s = reader.data[reader.offset:end_index].decode('utf-8')
    reader.offset = end_index + 1
    return s

def _unpack_vec(reader: BytesReader, item_unpacker: Callable[[BytesReader], Any]) -> List[Any]:
    """从读取器中解包 Vec<T>"""
    count, = reader.read_struct('<I')
    return [item_unpacker(reader) for _ in range(count)]

def _unpack_u8_vec(reader: BytesReader) -> bytes:
    """从读取器中解包 Vec<u8>"""
    count, = reader.read_struct('<I')
    return reader.read(count)

def _unpack_artist(reader: BytesReader) -> Dict[str, str]:
    """从读取器中解包 Artist"""
    return {"id": _unpack_null_string(reader), "name": _unpack_null_string(reader)}

def _unpack_lyric_word(reader: BytesReader) -> Dict[str, Any]:
    """从读取器中解包 LyricWord"""
    start_time, end_time = reader.read_struct('<QQ')
    word = _unpack_null_string(reader)
    return {"startTime": start_time, "endTime": end_time, "word": word}

def _unpack_lyric_line(reader: BytesReader) -> Dict[str, Any]:
    """从读取器中解包 LyricLine"""
    start_time, end_time = reader.read_struct('<QQ')
    words = _unpack_vec(reader, _unpack_lyric_word)
    translated_lyric = _unpack_null_string(reader)
    roman_lyric = _unpack_null_string(reader)
    flag, = reader.read_struct('<B')
    return {
        "startTime": start_time,
        "endTime": end_time,
        "words": words,
        "translatedLyric": translated_lyric,
        "romanLyric": roman_lyric,
        "flag": flag
    }

def parse_body(data: bytes) -> Dict[str, Any]:
    """
    将二进制数据反序列化为代表消息的字典。
    """
    reader = BytesReader(data)
    magic, = reader.read_struct('<H')
    
    try:
        message_type = MessageType(magic)
    except ValueError:
        raise ValueError(f"未知的 Magic Number: {magic}")
        
    type_str = ENUM_TO_CAMEL.get(message_type)
    if type_str is None:
         raise ValueError(f"无法将枚举 {message_type.name} 转换为 camelCase 字符串")

    result: Dict[str, Any] = {"type": type_str}
    value = {}

    if message_type in [MessageType.PING, MessageType.PONG, MessageType.ON_PAUSED, 
                        MessageType.ON_RESUMED, MessageType.PAUSE, MessageType.RESUME, 
                        MessageType.FORWARD_SONG, MessageType.BACKWARD_SONG]:
        pass # No value
    elif message_type == MessageType.SET_MUSIC_INFO:
        value['musicId'] = _unpack_null_string(reader)
        value['musicName'] = _unpack_null_string(reader)
        value['albumId'] = _unpack_null_string(reader)
        value['albumName'] = _unpack_null_string(reader)
        value['artists'] = _unpack_vec(reader, _unpack_artist)
        value['duration'], = reader.read_struct('<Q')
        result['value'] = value
    elif message_type == MessageType.SET_MUSIC_ALBUM_COVER_IMAGE_URI:
        value['imgUrl'] = _unpack_null_string(reader)
        result['value'] = value
    elif message_type == MessageType.SET_MUSIC_ALBUM_COVER_IMAGE_DATA:
        value['data'] = _unpack_u8_vec(reader)
        result['value'] = value
    elif message_type == MessageType.ON_PLAY_PROGRESS:
        value['progress'], = reader.read_struct('<Q')
        result['value'] = value
    elif message_type == MessageType.ON_VOLUME_CHANGED:
        value['volume'], = reader.read_struct('<d')
        result['value'] = value
    elif message_type == MessageType.ON_AUDIO_DATA:
        value['data'] = _unpack_u8_vec(reader)
        result['value'] = value
    elif message_type == MessageType.SET_LYRIC:
        value['data'] = _unpack_vec(reader, _unpack_lyric_line)
        result['value'] = value
    elif message_type == MessageType.SET_LYRIC_FROM_TTML:
        value['data'] = _unpack_null_string(reader)
        result['value'] = value
    elif message_type == MessageType.SET_VOLUME:
        value['volume'], = reader.read_struct('<d')
        result['value'] = value
    elif message_type == MessageType.SEEK_PLAY_PROGRESS:
        value['progress'], = reader.read_struct('<Q')
        result['value'] = value
    else:
        raise ValueError(f"消息类型 '{message_type.name}' 的解包逻辑未实现")

    return result

# --- 使用示例 ---
if __name__ == '__main__':
    print("--- 序列化 (to_body) 示例 ---")
    # 示例 1: SetMusicInfo (来自文档)
    set_music_info_body = {
        "type": "setMusicInfo",
        "value": {
            "musicId": "1",
            "musicName": "2",
            "albumId": "3",
            "albumName": "4",
            "artists": [
                {"id": "5", "name": "6"}
            ],
            "duration": 7,
        },
    }
    encoded_music_info = to_body(set_music_info_body)
    print(f"SetMusicInfo 编码后 ({len(encoded_music_info)} bytes): {encoded_music_info.hex(' ')}")

    # 预期输出 (根据文档中的二进制示例反推):
    # 02 00 (magic) 31 00 (id) 32 00 (name) 33 00 (albumId) 34 00 (albumName) 
    # 01 00 00 00 (artist count) 35 00 (artist id) 36 00 (artist name)
    # 07 00 00 00 00 00 00 00 (duration)
    expected_hex = "02 00 31 00 32 00 33 00 34 00 01 00 00 00 35 00 36 00 07 00 00 00 00 00 00 00"
    print(f"预期 Hex: {expected_hex}")
    print(f"是否匹配: {encoded_music_info.hex(' ') == expected_hex}")
    print("-" * 20)

    # 示例 2: Pause (无额外数据)
    pause_body = {"type": "pause"}
    encoded_pause = to_body(pause_body)
    print(f"Pause 编码后 ({len(encoded_pause)} bytes): {encoded_pause.hex(' ')}")
    # 预期: Magic Number 12 (0x0c)
    print(f"预期 Hex: 0c 00")
    print(f"是否匹配: {encoded_pause.hex(' ') == '0c 00'}")
    print("-" * 20)

    # 示例 3: SetVolume
    set_volume_body = {
        "type": "setVolume",
        "value": {
            "volume": 0.5
        }
    }
    encoded_volume = to_body(set_volume_body)
    print(f"SetVolume(0.5) 编码后 ({len(encoded_volume)} bytes): {encoded_volume.hex(' ')}")
    # 预期: Magic Number 16 (0x10) + 0.5 as f64
    expected_volume_hex = "10 00 " + struct.pack('<d', 0.5).hex(' ')
    print(f"预期 Hex: {expected_volume_hex}")
    print(f"是否匹配: {encoded_volume.hex(' ') == expected_volume_hex}")
    print("-" * 20)

    print("\n--- 反序列化 (parse_body) 与双向测试 ---")
    
    # 测试 1: SetMusicInfo
    print("测试 SetMusicInfo...")
    decoded_music_info = parse_body(encoded_music_info)
    print(f"解码后: {decoded_music_info}")
    # 检查原始字典和解码后的字典是否深度相等
    print(f"双向转换是否一致: {set_music_info_body == decoded_music_info}")
    print("-" * 20)

    # 测试 2: Pause
    print("测试 Pause...")
    decoded_pause = parse_body(encoded_pause)
    print(f"解码后: {decoded_pause}")
    print(f"双向转换是否一致: {pause_body == decoded_pause}")
    print("-" * 20)
    
    # 测试 3: SetVolume
    print("测试 SetVolume...")
    decoded_volume = parse_body(encoded_volume)
    print(f"解码后: {decoded_volume}")
    print(f"双向转换是否一致: {set_volume_body == decoded_volume}")
    print("-" * 20)
    
    # 测试 4: SetLyric (更复杂的结构)
    print("测试 SetLyric...")
    set_lyric_body = {
        "type": "setLyric",
        "value": {
            "data": [
                {
                    "startTime": 1000, "endTime": 2000,
                    "words": [{"startTime": 1100, "endTime": 1900, "word": "Hello"}],
                    "translatedLyric": "你好",
                    "romanLyric": "Konnichiwa",
                    "flag": 1
                }
            ]
        }
    }
    encoded_lyric = to_body(set_lyric_body)
    print(f"SetLyric 编码后 ({len(encoded_lyric)} bytes): {encoded_lyric.hex(' ')}")
    decoded_lyric = parse_body(encoded_lyric)
    print(f"解码后: {decoded_lyric}")
    print(f"双向转换是否一致: {set_lyric_body == decoded_lyric}")
    print("-" * 20)
