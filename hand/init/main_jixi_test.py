import asyncio
import serial
import json
import time
import os
import threading
import sys
from collections import deque
from protocol_utils import ProtocolUtils
from processor import RadiusEstimator
from network_server import MetaGatewayServer

# ============ 动作元数据 ============
ACTION_METADATA = {
    "1.mp4": {"name": "start", "frequency": "5Hz", "step": 0},
    "2.mp4": {"name": "filling", "frequency": "10Hz", "step": 1},
    "3.mp4": {"name": "success", "frequency": "15Hz", "step": 2},
    "4.mp4": {"name": "spill", "frequency": "20Hz", "step": 2}
}

# ============ 工作模式配置 ============
class WorkMode:
    MODE_TXT = "txt"
    MODE_REALTIME = "realtime"

CONFIG = {
    "mode": WorkMode.MODE_REALTIME,
    "debounce_time": 0.5,
    "state_window_size": 5,
}

# ============ 状态管理器 ============
class StateManager:
    def __init__(self, debounce_time=0.5):
        self.current_state = None
        self.last_state = None
        self.state_change_time = time.time()
        self.debounce_time = debounce_time
    
    def update(self, new_state):
        current_time = time.time()
        if new_state != self.current_state:
            if current_time - self.state_change_time > self.debounce_time:
                self.last_state = self.current_state
                self.current_state = new_state
                self.state_change_time = current_time
                return True, new_state
        return False, self.current_state

    def get_state_duration(self):
        return time.time() - self.state_change_time if self.current_state is not None else 0

# --- 继电器配置与指令 ---
RELAY_COMMANDS = {
    '一': {'on': bytes([0x00, 0xf1, 0xff]), 'off': bytes([0x00, 0x01, 0xff]), 'channel': 1},
    '二': {'on': bytes([0x00, 0xf2, 0xff]), 'off': bytes([0x00, 0x02, 0xff]), 'channel': 2},
    '三': {'on': bytes([0x00, 0xf3, 0xff]), 'off': bytes([0x00, 0x03, 0xff]), 'channel': 3},
    '四': {'on': bytes([0x00, 0xf4, 0xff]), 'off': bytes([0x00, 0x04, 0xff]), 'channel': 4},
    '五': {'on': bytes([0x00, 0xf5, 0xff]), 'off': bytes([0x00, 0x05, 0xff]), 'channel': 5},
    '六': {'on': bytes([0x00, 0xf6, 0xff]), 'off': bytes([0x00, 0x06, 0xff]), 'channel': 6},
}

# 修正后的触觉配置：每个动作对应 6 个通道同步信号
HAPTIC_CONFIG = {
    "start":   {"channels": ["一", "二", "三", "四", "五", "六"], "freq": 5,  "duration": 3},
    "filling": {"channels": ["一", "二", "三", "四", "五", "六"], "freq": 10, "duration": 5},
    "success": {"channels": ["一", "二", "三", "四", "五", "六"], "freq": 15, "duration": 7},
    "spill":   {"channels": ["一", "二", "三", "四", "五", "六"], "freq": 20, "duration": 9}
}

base_values = [None] * 14
base_lock = threading.Lock()

class RelayController:
    """集成版继电器控制器，负责 COM5 的高精度多通道震动控制"""
    def __init__(self, port='COM5', baudrate=9600):
        self.port = port
        self.baudrate = baudrate
        self.serial_conn = None
        self.lock = threading.Lock()
        self.running = True

    def connect(self):
        try:
            self.serial_conn = serial.Serial(self.port, self.baudrate, timeout=1)
            print(f"[硬件] 触觉反馈系统 ({self.port}) 已就绪")
            return True
        except Exception as e:
            print(f"[错误] {self.port} 连接失败: {e}")
            return False

    def pulse_vibration(self, channels, freq, duration):
        """核心修复：在独立线程中执行 6 通道同步震动"""
        if isinstance(channels, str): channels = [channels]
        
        def worker():
            if not self.serial_conn or not self.serial_conn.is_open: return
            
            valid_channels = [ch for ch in channels if ch in RELAY_COMMANDS]
            interval = 1.0 / freq
            start_time = time.time()
            cycles = 0
            
            print(f"  └─> [震动激活] 通道:{'/'.join(valid_channels)} | 频率:{freq}Hz | 时长:{duration}s")
            
            while time.time() - start_time < duration and self.running:
                try:
                    with self.lock:
                        # 6通道同步 ON
                        for ch in valid_channels:
                            self.serial_conn.write(RELAY_COMMANDS[ch]['on'])
                        time.sleep(0.020) # 保持20ms吸合
                        # 6通道同步 OFF
                        for ch in valid_channels:
                            self.serial_conn.write(RELAY_COMMANDS[ch]['off'])
                    
                    cycles += 1
                    elapsed = time.time() - start_time
                    next_cycle = cycles * interval
                    sleep_time = next_cycle - elapsed - 0.020
                    if sleep_time > 0: time.sleep(sleep_time)
                except: break
            print(f"  └─> [震动停止] {len(valid_channels)}路信号传输完毕")

        threading.Thread(target=worker, daemon=True).start()

class MainApp:
    def __init__(self, mode=WorkMode.MODE_REALTIME):
        self.estimator = RadiusEstimator()
        self.work_mode = mode
        self.task_queue = []
        self.is_executing = False
        self.step = 0 
        self.last_played_video_id = None
        
        self.state_manager = StateManager(debounce_time=CONFIG["debounce_time"])
        self.raw_data_queue = asyncio.Queue(maxsize=100)
        self.baseline_samples = []
        self.baseline_ready = False
        self.baseline_count = 5 
        
        try:
            self.ser_sensor = serial.Serial('COM4', 115200, timeout=0.01)
            print(f"[系统] 传感器串口 COM4 已就绪")
        except: self.ser_sensor = None

        self.relay = RelayController(port='COM5')
        self.relay.connect()

        self.server = MetaGatewayServer(port=8765, on_feedb_received=self.handle_server_feedback)

    
    def map_radius_to_id(self, R):
        """
        基于step状态机的半径映射逻辑
        ⭐ 重要：此函数只判断不修改step，step仅由客户端反馈更新
        """
        print(f"[判断] 半径R={R:.2f}, 当前step={self.step}")

        # step=0: 等待视频1的范围
        # if self.step == 0:
        if 12.15 <= R and self.step == 0:
            print(f"  → 匹配视频1范围，返回ID=1")
            return 1
        
        # step=1: 等待视频2的范围
        elif R>12.15 and self.step == 1:
            print(f"  → 匹配视频2范围，返回ID=2")
            return 2
        
        # step=2: 根据R值区分视频3或视频4
        elif self.step == 2:
            if R > 12.3:
                print(f"  → 匹配视频3范围(R>12.35)，返回ID=3")
                return 3
            else:
                print(f"  → 匹配视频4范围(R≤12.35)，返回ID=4")
                return 4
        
        return None

    def handle_server_feedback(self, raw_input):
        """核心闭环：反馈 -> 触觉 -> 状态步进"""
        try:
            data = json.loads(raw_input)
            if data.get("type") == "ACTION_FEEDBACK":
                action_name = data.get("name")
                print(f"\n✅ [反馈接收] 动作 '{action_name}' 播放完成")

                # 1. 触发 6 通道同步触觉反馈
                if action_name in HAPTIC_CONFIG:
                    conf = HAPTIC_CONFIG[action_name]
                    self.relay.pulse_vibration(conf['channels'], conf['freq'], conf['duration'])

                # 2. 状态机步进逻辑 
                if self.step == 0: self.step = 1
                elif self.step == 1: self.step = 2
                elif self.step == 2: self.step = 0 # 循环结束，重置
                
                print(f"   [状态转移] 下一个任务阶段: step {self.step}")
                self.is_executing = False
        except Exception as e: print(f"[反馈解析错误] {e}")

    async def serial_loop(self):
        if not self.ser_sensor: return
        buffer = bytearray()
        while True:
            if self.ser_sensor.in_waiting:
                buffer.extend(self.ser_sensor.read(self.ser_sensor.in_waiting))
                while len(buffer) >= 66:
                    packet = buffer[:66]; buffer = buffer[66:]
                    cap_data = ProtocolUtils.parse_packet(packet)
                    if cap_data:
                        with base_lock:
                            if not self.baseline_ready:
                                self.baseline_samples.append(cap_data)
                                if len(self.baseline_samples) >= self.baseline_count:
                                    global base_values
                                    base_values = [sum(ch)/len(ch) for ch in zip(*self.baseline_samples)]
                                    self.baseline_ready = True
                                    print(f"[校准] 基准电容值已建立")
                                continue
                            delta = [c - b for c, b in zip(cap_data, base_values)]
                            try: self.raw_data_queue.put_nowait(delta)
                            except: pass
            await asyncio.sleep(0.001)

    async def state_analyzer(self):
        window_data = []
        while True:
            try:
                cap_data = await asyncio.wait_for(self.raw_data_queue.get(), timeout=0.1)
                window_data.append(cap_data)
                if len(window_data) >= CONFIG["state_window_size"]:
                    if self.is_executing: 
                        window_data = []; continue
                    
                    radii = [self.estimator.estimate_radius(d) for d in window_data]
                    avg_R = sum(radii) / len(radii)
                    state_id = self.map_radius_to_id(avg_R)
                    
                    changed, stable_state = self.state_manager.update(state_id)
                    if changed and state_id is not None:
                        print(f"🔔 [状态匹配] 捕获新动作: 视频ID={state_id}")
                        self.task_queue.append(state_id)
                    
                    window_data = window_data[len(window_data)//2:]
            except asyncio.TimeoutError: pass
            except Exception as e: print(f"[分析错误] {e}"); await asyncio.sleep(0.1)

    async def sequence_manager(self):
        print("[管理] 等待客户端连接...")
        while len(self.server.clients) == 0: await asyncio.sleep(0.5)
        print("[管理] 通讯链路已建立")
        
        while True:
            if not self.task_queue:
                await asyncio.sleep(0.2); continue
            
            v_id = self.task_queue.pop(0)
            self.is_executing = True
            
            payload = {"type": "COMMAND", "content": str(v_id)}
            await self.server.broadcast_data(payload)
            print(f"\n[下发] 启动视频 {v_id}.mp4")
            
            timeout = 0
            while self.is_executing and timeout < 30: # 15秒超时保护
                await asyncio.sleep(0.5); timeout += 1
            if self.is_executing:
                print(f"[警告] 视频{v_id}反馈超时，强制释放")
                self.is_executing = False

    async def load_tasks_from_file(self, filename="data.txt"):
        if not os.path.exists(filename): return False
        seq, last_id = [], None
        with open(filename, 'r') as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) == 14:
                    R = self.estimator.estimate_radius([float(x) for x in parts])
                    v_id = self.map_radius_to_id(R)
                    if v_id is not None and v_id != last_id:
                        seq.append(v_id); last_id = v_id
        if seq: self.task_queue = seq; return True
        return False

    async def run(self):
        print(f"\n[启动] 模式: {self.work_mode.upper()}")
        common = [self.server.start()]
        if self.work_mode == WorkMode.MODE_TXT:
            if await self.load_tasks_from_file():
                tasks = common + [self.sequence_manager()]
            else: return
        else:
            tasks = common + [self.serial_loop(), self.state_analyzer(), self.sequence_manager()]
        await asyncio.gather(*tasks)

if __name__ == "__main__":
    mode = sys.argv[1].lower() if len(sys.argv) > 1 else "realtime"
    app = MainApp(mode=mode)
    try: asyncio.run(app.run())
    except KeyboardInterrupt: print("\n[停止] 程序已手动关闭")