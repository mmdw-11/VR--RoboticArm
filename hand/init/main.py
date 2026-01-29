#1.21最佳
# import asyncio
# import serial
# import json
# import time
# import os
# from protocol_utils import ProtocolUtils
# from processor import RadiusEstimator
# from network_server import MetaGatewayServer

# # 串口配置
# SENSOR_PORT = 'COM3'
# SENSOR_BAUD = 115200
# ROBOT_PORT = 'COM5'
# ROBOT_BAUD = 9600

# # 机械手控制指令库
# ROBOT_COMMANDS = {
#     'close': "5555170306C80001100802990203990204990205990206DC05",
#     'open': "5555170306C800011008021000031000041000051000061000"
# }

# class MainApp:
#     def __init__(self):
#         self.estimator = RadiusEstimator()
#         self.task_queue = []        
#         self.is_executing = False   
        
#         try:
#             self.ser_sensor = serial.Serial(SENSOR_PORT, SENSOR_BAUD, timeout=0.01)
#             print(f"[系统] 传感器串口 {SENSOR_PORT} 已就绪")
#         except Exception as e:
#             print(f"[错误] 无法打开传感器串口: {e}")
#             self.ser_sensor = None

#         try:
#             self.ser_robot = serial.Serial(ROBOT_PORT, ROBOT_BAUD, timeout=0.01)
#             print(f"[系统] 机械手串口 {ROBOT_PORT} 已就绪")
#         except Exception as e:
#             print(f"[错误] 无法打开机械手串口: {e}")
#             self.ser_robot = None

#         # 初始化服务端
#         self.server = MetaGatewayServer(port=8765, on_feedb_received=self.handle_server_feedback)

#     def map_radius_to_id(self, R):
#         if R>14.5:return None
#         if 12.5 < R <= 14.5: return 1
#         if 12.0 < R <= 12.5:  return None
#         if 9.0 < R <= 12:  return 2
#         if R <= 9.0:
#             return 3 if R < 7.0 else 4
#         return None

#     def load_tasks_from_file(self, filename="data.txt"):
#         if not os.path.exists(filename):
#             print(f"\n[错误] 找不到 {filename}")
#             return False

#         extracted_sequence = []
#         last_id = None
#         try:
#             with open(filename, 'r') as f:
#                 for line in f:
#                     parts = line.strip().split()
#                     if len(parts) != 14: continue
#                     raw_data = [float(x) for x in parts]
#                     R = self.estimator.estimate_radius(raw_data)
#                     v_id = self.map_radius_to_id(R)
#                     if v_id is not None and v_id != last_id:
#                         extracted_sequence.append(v_id)
#                         last_id = v_id
            
#             if extracted_sequence in [[1, 2, 3], [1, 2, 4]]:
#                 self.task_queue = extracted_sequence
#                 print(f"[预处理] 成功提取动作序列: {self.task_queue}")
#                 return True
#             else:
#                 print(f"[警告] 提取序列 {extracted_sequence} 不符合 1-2-3 或 1-2-4 逻辑")
#                 return False
#         except Exception as e:
#             print(f"[解析错误] {e}")
#             return False

#     async def execute_next_task(self):
#         if not self.task_queue:
#             self.is_executing = False
#             print("\n[流程结束] 预设任务全部执行完毕。")
#             return

#         v_id = self.task_queue.pop(0)
#         self.is_executing = True
        
#         print(f"\n[任务下发] 正在执行视频 {v_id}.mp4...")
#         payload = {}
#         if v_id in [1, 2]:
#             payload = {"type": "COMMAND", "content": str(v_id)}
#         elif v_id in [3, 4]:
#             val = 1.5 if v_id == 3 else 3.0
#             payload = {"type": "COMPARE_RESULT", "value": val}

#         await self.server.broadcast_data(payload)
        
#         if v_id == 1:
#             self.control_robot("close")
#         elif v_id in [3, 4]:
#             self.control_robot("open")

#     def control_robot(self, action):
#         if self.ser_robot and action in ROBOT_COMMANDS:
#             self.ser_robot.write(bytes.fromhex(ROBOT_COMMANDS[action]))
#             print(f"[硬件联动] 机械手: {action}")

#     def handle_server_feedback(self, raw_input):
#         try:
#             data = json.loads(raw_input)
#             if data.get("type") == "ACTION_FEEDBACK":
#                 print(f"[反馈接收] 动作 '{data.get('name')}' 频率 '{data.get('frequency')}'已完成。")
#                 if self.is_executing:
#                     asyncio.create_task(self.delayed_next_task(0.8))
#         except:
#             pass

#     async def delayed_next_task(self, delay):
#         await asyncio.sleep(delay)
#         await self.execute_next_task()

#     # --- 核心改进：专门负责监控连接并触发任务的任务管理协程 ---
#     async def sequence_manager(self):
#         print("\n[系统] 序列任务管理器已启动，正在等待客户端连接...")
#         # 只要没有客户端连接，就一直循环等待
#         while len(self.server.clients) == 0:
#             await asyncio.sleep(0.5)
        
#         print("\n[系统] 检测到客户端已连接，开始执行任务序列！")
#         await self.execute_next_task()

#     async def serial_loop(self):
#         if not self.ser_sensor: return
#         buffer = bytearray()
#         while True:
#             if self.ser_sensor.in_waiting:
#                 data = self.ser_sensor.read(self.ser_sensor.in_waiting)
#                 buffer.extend(data)
#                 while len(buffer) >= 66:
#                     packet = buffer[:66]
#                     buffer = buffer[66:]
#                     if self.is_executing: continue # 执行序列任务时忽略实时干扰
#                     # 实时解析逻辑略...
#             await asyncio.sleep(0.01)

#     async def run(self):
#         """
#         启动流程：使用 gather 并发运行所有模块，互不阻塞 
#         """
#         print("\n" + "="*40)
#         print("北航软件工程 - 交互系统 (任务序列模式)")
#         print("="*40)
        
#         # 尝试加载任务
#         has_tasks = self.load_tasks_from_file("data.txt")
        
#         # 核心：并发启动。不论有没有任务，server.start() 必须立即运行。
#         tasks = [self.server.start(), self.serial_loop()]
        
#         if has_tasks:
#             # 如果有序列任务，把“序列管理器”也加入并发列表
#             tasks.append(self.sequence_manager())
            
#         await asyncio.gather(*tasks)

# if __name__ == "__main__":
#     app = MainApp()
#     try:
#         asyncio.run(app.run())
#     except KeyboardInterrupt:
#         print("\n[系统] 程序停止")

import asyncio
import serial
import json
import time
import os
import threading
from protocol_utils import ProtocolUtils
from processor import RadiusEstimator
from network_server import MetaGatewayServer

# --- 继电器配置与指令 (来自 jixie.py) ---
RELAY_COMMANDS = {
    '一': {'on': bytes([0x00, 0xf1, 0xff]), 'off': bytes([0x00, 0x01, 0xff]), 'channel': 1},
    '二': {'on': bytes([0x00, 0xf2, 0xff]), 'off': bytes([0x00, 0x02, 0xff]), 'channel': 2},
    # ... 其他通道可根据需要保留
}

# 动作与触觉参数的映射表
HAPTIC_CONFIG = {
    "start":   {"channel": "一", "freq": 3,  "duration": 2},
    # "filling": {"channel": "一", "freq": 1, "duration": 2},
    "success": {"channel": "一", "freq": 8, "duration": 2},
    #"spill":   {"channel": "一", "freq": 8, "duration": 2}
}

class RelayController:
    """集成版继电器控制器，负责 COM5 的高精度震动控制"""
    def __init__(self, port='COM5', baudrate=9600):
        self.port = port
        self.baudrate = baudrate
        self.serial_conn = None
        self.lock = threading.Lock()
        self.running = True

    def connect(self):
        try:
            self.serial_conn = serial.Serial(self.port, self.baudrate, timeout=1)
            print(f"[硬件] 触觉反馈系统 (COM5) 已成功连接")
            return True
        except Exception as e:
            print(f"[错误] COM5 连接失败: {e}")
            return False

    def pulse_vibration(self, channel_char, freq, duration):
        """在独立线程中执行震动，不阻塞主程序"""
        def worker():
            if channel_char not in RELAY_COMMANDS or not self.serial_conn: return
            cmd = RELAY_COMMANDS[channel_char]
            interval = 1.0 / freq
            start_time = time.time()
            
            print(f"  └─> [震动开始] 通道 {channel_char} | 频率 {freq}Hz | 预计时长 {duration}s")
            
            while time.time() - start_time < duration and self.running:
                with self.lock:
                    self.serial_conn.write(cmd['on'])
                    time.sleep(0.02) # 保持 20ms 的吸合时间
                    self.serial_conn.write(cmd['off'])
                
                # 计算下一次脉冲的等待时间
                time.sleep(max(0, interval - 0.02))
            print(f"  └─> [震动结束] 通道 {channel_char} 任务完成")

        # 启动非阻塞线程
        threading.Thread(target=worker, daemon=True).start()

class MainApp:
    def __init__(self):
        self.estimator = RadiusEstimator()
        self.task_queue = []
        self.is_executing = False
        
        # 1. 初始化传感器串口 (COM3)
        try:
            self.ser_sensor = serial.Serial('COM4', 115200, timeout=0.01)
            print(f"[系统] 传感器串口 COM4 已就绪")
        except: self.ser_sensor = None

        # 2. 初始化继电器控制器 (COM5)
        self.relay = RelayController(port='COM5')
        self.relay.connect()

        # 3. 初始化网络服务
        self.server = MetaGatewayServer(port=8765, on_feedb_received=self.handle_server_feedback)
        self.step = 0

    def map_radius_to_id(self, R):
        """带‘死区’的半径映射逻辑"""
        # if R > 14.5: return None 
        # if 12.1 < R <= 14.5: return 1
        # if 12.0 < R <= 12.5: return None # 维持死区
        # if 9.0 < R <= 12.0:  return 2 # 加力阶段
        # if R <= 9.0: return 3 if R < 7.0 else 4
        if R<12.1: return None
        if 12.1<= R <= 12.2: 
            self.step = 1
            return 1
        if 12.2 < R <= 12.5: 
            if self.step == 1:
                self.step = 2
                return 2
        if 12.5 < R : 
            self.step = 3
            return 3
        if 12.5> R : 
            self.step = 4
            return 4
        return None

    def handle_server_feedback(self, raw_input):
        """核心闭环逻辑：解析反馈 -> 触发震动 -> 调度下一视频 """
        try:
            data = json.loads(raw_input)
            if data.get("type") == "ACTION_FEEDBACK":
                action_name = data.get("name")
                print(f"\n[反馈] 动作 '{action_name}' 播放完成")

                # 1. 触发触觉反馈
                if action_name in HAPTIC_CONFIG:
                    conf = HAPTIC_CONFIG[action_name]
                    self.relay.pulse_vibration(conf['channel'], conf['freq'], conf['duration'])

                # 2. 调度下一个视频任务
                if self.is_executing:
                    asyncio.create_task(self.delayed_next_task(0.8))
        except Exception as e:
            print(f"[回调错误] {e}")

    async def execute_next_task(self):
        if not self.task_queue:
            self.is_executing = False
            print("\n[流程结束] data.txt 任务序列执行完毕")
            return

        v_id = self.task_queue.pop(0)
        self.is_executing = True
        
        # 封装下发包
        payload = {"type": "COMMAND", "content": str(v_id)} if v_id in [1, 2] else \
                  {"type": "COMPARE_RESULT", "value": (1.5 if v_id == 3 else 3.0)}
        
        await self.server.broadcast_data(payload)
        print(f"\n[指令] 下发视频 {v_id}.mp4")

    async def delayed_next_task(self, delay):
        await asyncio.sleep(delay)
        await self.execute_next_task()

    def load_tasks_from_file(self, filename="data.txt"):
        if not os.path.exists(filename): return False
        seq, last_id = [], None
        # with open(filename, 'r') as f:
        #     for line in f:
        #         parts = line.strip().split()
        #         if len(parts) != 14: continue
        #         R = self.estimator.estimate_radius([float(x) for x in parts])
        #         print(f"[估算] 视频序列 {R}")
        #         v_id = self.map_radius_to_id(R)
        #         if v_id is not None and v_id != last_id:
        #             seq.append(v_id); last_id = v_id

        # if seq in [[1, 2, 3], [1, 2, 4]]:
        #     self.task_queue = seq
        #     print(f"[预处理] 提取序列: {self.task_queue}")
        #     return True
        if not self.ser_sensor: return
        buffer = bytearray()
        while True:
            if self.ser_sensor.in_waiting:
                buffer.extend(self.ser_sensor.read(self.ser_sensor.in_waiting))
                while len(buffer) >= 66:
                    packet = buffer[:66]; buffer = buffer[66:]
                    # 序列任务执行期间屏蔽实时数据干扰
                    print(f"[传感器] {packet}")
                    parts = line.strip().split()
                    if len(parts) != 14: continue
                    R = self.estimator.estimate_radius([float(x) for x in parts])
                    print(f"[估算] 视频序列 {R}")
                    v_id = self.map_radius_to_id(R)
                    if v_id is not None and v_id != last_id:
                        seq.append(v_id); last_id = v_id
            asyncio.sleep(0.01)
        return False

    async def sequence_manager(self):
        while len(self.server.clients) == 0: await asyncio.sleep(0.5)
        await self.execute_next_task()

    async def serial_loop(self):
        if not self.ser_sensor: return
        buffer = bytearray()
        while True:
            if self.ser_sensor.in_waiting:
                buffer.extend(self.ser_sensor.read(self.ser_sensor.in_waiting))
                while len(buffer) >= 66:
                    packet = buffer[:66]; buffer = buffer[66:]
                    # 序列任务执行期间屏蔽实时数据干扰
                    print(f"[传感器] {packet}")
            await asyncio.sleep(0.01)



    async def run(self):
        has_tasks = self.load_tasks_from_file("data.txt")
        tasks = [self.server.start(), self.serial_loop()]
        if has_tasks: 
            tasks.append(self.sequence_manager())
        await asyncio.gather(*tasks)

if __name__ == "__main__":
    app = MainApp()
    try: asyncio.run(app.run())
    except KeyboardInterrupt: print("\n[系统] 已停止")