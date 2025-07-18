import subprocess
import re

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

# 使用示例
if __name__ == "__main__":
    pipewire_id = get_yesplaymusic_pipewire_id()
    if pipewire_id:
        print(f"Found PipeWire ID: {pipewire_id}")
    else:
        print("No PipeWire ID found")
