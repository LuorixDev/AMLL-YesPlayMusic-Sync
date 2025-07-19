import subprocess
import re
import tempfile
import os
import wave
import numpy as np
from time import sleep


def get_yesplaymusic_pipewire_id():
    """
    获取 YesPlayMusic 的 PipeWire ID
    返回: str 或 None - 找到时返回 PipeWire ID，未找到时返回 None
    """
    try:
        # 获取 YesPlayMusic 进程的 PID
        cmd = "ps aux | grep -i yesplaymusic | grep -v grep"
        result = subprocess.check_output(cmd, shell=True, text=True)
        pids = [line.split()[1] for line in result.splitlines()]

        if not pids:
            return None

        # 获取 PipeWire ID
        cmd = "pactl list sink-inputs"
        result = subprocess.check_output(cmd, shell=True, text=True)
        sink_sections = result.split("Sink Input #")

        for pid in pids:
            for section in sink_sections[1:]:
                if f'application.process.id = "{pid}"' in section:
                    id_match = re.match(r'(\d+)', section)
                    if id_match:
                        return id_match.group(1)
        return None
    except subprocess.CalledProcessError:
        return None

def record_audio(pipewire_id, duration=0.2):
    """
    录制指定 PipeWire ID 的音频数据
    参数:
        pipewire_id: str - PipeWire ID
        duration: float - 录制时长(秒)
    返回:
        numpy array - PCM数据
    """
    try:
        # 创建临时文件
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
            temp_path = temp_file.name

        # 使用 pw-cat 录制音频
        cmd = f"pw-cat --record --target {pipewire_id} --format=s16 --rate=48000 --channels=2 {temp_path} &"
        subprocess.Popen(cmd, shell=True)
        
        # 等待指定时长
        sleep(duration)
        
        # 停止录制
        subprocess.run("pkill -f pw-cat", shell=True)
        
        # 给一点时间让文件写入完成
        sleep(0.1)

        # 读取录制的原始 PCM 数据
        with open(temp_path, 'rb') as pcm_file:
            frames = pcm_file.read()
            pcm_data = np.frombuffer(frames, dtype=np.int16)
        
        # 删除临时文件
        os.unlink(temp_path)
        
        return pcm_data
    except Exception as e:
        print(f"Error recording audio: {e}")
        return None

# 使用示例
if __name__ == "__main__":
    pipewire_id = get_yesplaymusic_pipewire_id()
    if pipewire_id:
        print(f"Found PipeWire ID: {pipewire_id}")
        pcm_data = record_audio(pipewire_id)
        if pcm_data is not None:
            print(f"Recorded PCM data shape: {pcm_data.shape}")
            print(f"PCM data sample: {pcm_data[:10]}")  # 打印前10个采样点
    else:
        print("No PipeWire ID found")
