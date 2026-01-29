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
    "1.mp4": {"name": "start", "frequency": "5Hz", "step": 0},    # 视频1播放后，step保持0，待反馈推进为1
    "2.mp4": {"name": "filling", "frequency": "10Hz", "step": 1},  # 视频2播放后，step保持1，待反馈推进为2
    "3.mp4": {"name": "success", "frequency": "15Hz", "step": 2},  # 视频3播放后，step保持2，待反馈推进为0
    "4.mp4": {"name": "spill", "frequency": "20Hz", "step": 2}     # 视频4播放后，step保持2，待反馈推进为0
}

# ============ 工作模式配置 ============
class WorkMode:
    """工作模式常量"""
    MODE_TXT = "txt"          # 从data.txt读固定序列
    MODE_REALTIME = "realtime" # 从实时手套传感器读取

# 全局配置
CONFIG = {
    "mode": WorkMode.MODE_REALTIME,  # 当前工作模式
    "debounce_time": 0.5,             # 去抖时间（秒）
    "state_window_size": 5,           # 状态分析时间窗口大小
}

# ============ 状态管理器 ============
class StateManager:
    """
    状态去抖管理器
    防止视频因为传感器噪声频繁切换
    """
    def __init__(self, debounce_time=0.5):
        self.current_state = None
        self.last_state = None
        self.state_change_time = time.time()
        self.debounce_time = debounce_time
        self.state_history = deque(maxlen=50)  # 记录最近50次状态变化
    
    def update(self, new_state):
        """
        更新状态，检测是否有效变化
        参数: new_state - 新的状态ID（None或1-4）
        返回: (is_changed, stable_state) - (状态是否改变, 当前稳定状态)
        """
        current_time = time.time()
        
        if new_state != self.current_state:
            # 检测到状态变化
            if current_time - self.state_change_time > self.debounce_time:
                # 去抖通过：确实是稳定的新状态
                self.last_state = self.current_state
                self.current_state = new_state
                self.state_change_time = current_time
                self.state_history.append((new_state, current_time))
                return True, new_state
            else:
                # 还在去抖期间，忽略
                return False, self.current_state
        else:
            # 状态未变，保持
            return False, self.current_state
    
    def get_state_duration(self):
        """获取当前状态维持时长（秒）"""
        if self.current_state is None:
            return 0
        return time.time() - self.state_change_time

# --- 继电器配置与指令 (来自 jixie.py) ---
RELAY_COMMANDS = {
    '一': {'on': bytes([0x00, 0xf1, 0xff]), 'off': bytes([0x00, 0x01, 0xff]), 'channel': 1},
    '二': {'on': bytes([0x00, 0xf2, 0xff]), 'off': bytes([0x00, 0x02, 0xff]), 'channel': 2},
    '三': {'on': bytes([0x00, 0xf3, 0xff]), 'off': bytes([0x00, 0x03, 0xff]), 'channel': 3},
    '四': {'on': bytes([0x00, 0xf4, 0xff]), 'off': bytes([0x00, 0x04, 0xff]), 'channel': 4},
    '五': {'on': bytes([0x00, 0xf5, 0xff]), 'off': bytes([0x00, 0x05, 0xff]), 'channel': 5},
    '六': {'on': bytes([0x00, 0xf6, 0xff]), 'off': bytes([0x00, 0x06, 0xff]), 'channel': 6},
}

# 动作与触觉参数的映射表
# channels列表中的所有通道将同时接收相同的频率和时长信号
HAPTIC_CONFIG = {
    "start":   {"channels": ["一", "二", "三", "四", "五", "六"], "freq": 3,  "duration": 2},
    "filling": {"channels": ["一", "二", "三", "四", "五", "六"], "freq": 8,  "duration": 2},
    # "success": {"channels": ["一", "二", "三", "四", "五", "六"], "freq": 15, "duration": 2},
    # "spill":   {"channels": ["一", "二", "三", "四", "五", "六"], "freq": 20, "duration": 2}
}
base_values = [None] * 14   # ← 全局基准值初始化
base_lock = threading.Lock()  # 基值锁
plot_ready = threading.Event()

class RelayController:
    """集成版继电器控制器，负责 COM5 的高精度震动控制"""
    def __init__(self, port='COM5', baudrate=9600):
        self.port = port
        self.baudrate = baudrate
        self.serial_conn = None
        self.lock = threading.Lock()
        self.running = False   #**************************************************************

    def connect(self):
        try:
            self.serial_conn = serial.Serial(self.port, self.baudrate, timeout=1)
            print(f"[硬件] 触觉反馈系统 (COM5) 已成功连接")
            return True
        except Exception as e:
            print(f"[错误] COM5 连接失败: {e}")
            return False


    def control_channel(self, channel_char, frequency, duration=10):
        """控制单个通道以指定频率运行指定时间（秒）"""
        if channel_char not in RELAY_COMMANDS:
            print(f"错误：无效的通道 '{channel_char}'")
            return False

        channel_info = RELAY_COMMANDS[channel_char]
        channel_num = channel_info['channel']
        interval = 1.0 / frequency  # 每次开关的间隔时间（秒）
        cycle_time = interval * 2  # 每次开关循环的时间（开+关）

        print(f"通道 {channel_num} 开始运行，频率 {frequency}Hz")

        start_time = time.time()
        cycles = 0

        while self.running:
            try:
                # 计算是否已经达到总运行时间
                if time.time() - start_time >= duration:
                    break

                with self.lock:
                    if not self.serial_conn or not self.serial_conn.is_open:
                        print(f"通道 {channel_num}: 串口连接已断开")
                        return False

                    # 发送开启命令
                    self.serial_conn.write(channel_info['on'])
                    time.sleep(0.020)  # 保持20ms
                    self.serial_conn.write(channel_info['off'])

                cycles += 1

                # 计算剩余等待时间（考虑处理延迟）
                elapsed = time.time() - start_time
                next_cycle_time = cycles * cycle_time
                sleep_time = (next_cycle_time - elapsed) - 0.020  # 减去开关时间

                if sleep_time > 0:
                    time.sleep(sleep_time)

            except Exception as e:
                print(f"通道 {channel_num} 控制出错: {e}")
                return False

        print(f"通道 {channel_num} 完成运行，共完成 {cycles} 次循环")
        return True
    
    def pulse_vibration(self, channels, freq, duration=10):
        """在独立线程中执行震动（支持多通道），不阻塞主程序
        
        参数:
            channels: 单个通道(str)或通道列表(list) - 例如 "一" 或 ["一", "二", "三"]
            freq: 震动频率 (Hz)
            duration: 震动时长 (秒)
        """
        # 统一处理：将单通道转换为列表
        if isinstance(channels, str):
            channels = [channels]
        
        def worker():
            if not channels:
                print("错误：未指定任何通道")
                return

            self.running = True
            threads = []

            # 为每个通道创建并启动线程
            for channel_char in channels:
                if channel_char in RELAY_COMMANDS:
                    t = threading.Thread(
                        target=self.control_channel,
                        args=(channel_char, freq, duration),
                        daemon=True
                    )
                    threads.append(t)
                    t.start()
                else:
                    print(f"警告：跳过无效通道 '{channel_char}'")

            # 等待所有线程完成
            for t in threads:
                t.join()

            print("所有通道控制已完成")
            
            
        # 启动非阻塞线程
        threading.Thread(target=worker, daemon=True).start()

class MainApp:
    def __init__(self, mode=WorkMode.MODE_REALTIME):
        self.estimator = RadiusEstimator()
        self.work_mode = mode
        self.task_queue = []
        self.is_executing = False
        self.step = int(0)  # ← 新增：step状态机初始化
        self.last_played_video_id = None  # ← 新增：追踪上次播放的视频，避免重复播放
        
        # 状态管理
        self.state_manager = StateManager(debounce_time=CONFIG["debounce_time"])
        
        # 原始数据队列：存储未处理的14维传感器数据
        self.raw_data_queue = asyncio.Queue(maxsize=100)
        
        # 基准校准相关（新增）
        self.baseline_samples = []  # 用于校准的数据样本
        self.baseline_ready = False  # 基准是否校准完成
        self.baseline_count = 5      # 校准用的样本数量
        
        # 1. 初始化传感器串口 (COM4)
        try:
            self.ser_sensor = serial.Serial('COM4', 115200, timeout=0.01)
            print(f"[系统] 传感器串口 COM4 已就绪")
        except Exception as e:
            print(f"[警告] COM4 连接失败: {e}")
            self.ser_sensor = None

        # 2. 初始化继电器控制器 (COM5)
        self.relay = RelayController(port='COM5')
        self.relay.connect()

        # 3. 初始化网络服务
        self.server = MetaGatewayServer(port=8765, on_feedb_received=self.handle_server_feedback)
        
        print(f"[系统] 工作模式: {self.work_mode}")

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
        """
        核心反馈处理逻辑：解析反馈 -> 触发震动 -> 准备继续
        
        改进：
        1. 从客户端反馈中提取 step 值（同步状态）
        2. 验证 step 值是否正确
        3. 触发触觉反馈
        4. 重置 step 为 0，等待下一个手势
        """
        try:
            data = json.loads(raw_input)
            print(f"[服务端] 收到客户端消息: {data}")
            if data.get("type") == "ACTION_FEEDBACK":
                action_name = data.get("name")
                frequency = data.get("frequency", "unknown")
                feedback_step = data.get("step", None)  # ← 获取客户端返回的 step 值
                
                print(f"\n✅ [反馈] 动作 '{action_name}' 播放完成 (频率: {frequency}, step: {feedback_step})")

                # 1. 验证 step 值是否与服务端预期相符
                #if feedback_step is not None and feedback_step != self.step:
                print(f"   ⚠️  [警告] Step 不匹配: 服务端={self.step}, 客户端={feedback_step}")
                # 同步到客户端的 step 值
                self.step = feedback_step
                print(f"   [同步] 已更新 step 为 {feedback_step}")

                # 2. 触发触觉反馈
                if action_name in HAPTIC_CONFIG:
                    conf = HAPTIC_CONFIG[action_name]
                    channels = conf.get('channels', ["一"])
                    print(f"   [震动] 触发通道 {'/'.join(channels)}, 频率{conf['freq']}Hz, 时长{conf['duration']}s")
                    self.relay.pulse_vibration(channels, conf['freq'], conf['duration'])
                else:
                    print(f"   [警告] 未知的动作类型: {action_name}")

                # 3. 更新上次播放的视频ID（从metadata获取视频编号）
                video_id = None
                for vid, meta in ACTION_METADATA.items():
                    if meta.get('name') == action_name:
                        video_id = int(vid.split('.')[0])  # 从"1.mp4"提取1
                        self.last_played_video_id = video_id
                        print(f"   [记录] 已播放过的视频ID = {video_id}")
                        break
                
                # 4. 标记任务已完成
                self.is_executing = False
                print(f"   [状态转移] is_executing = False，准备执行下一个任务")
                
                # 5. step状态递进：step=0→1（视频1完），step=1→2（视频2完），step=2→0（视频3或4完，重置）
                print(f"   [步进] 当前step={self.step}")
                # if self.step == 0:
                #     # 视频1完成后，step推进到1
                #     self.step = 1
                #     print(f"   [状态升级] 视频1播放完成 → step=1（准备侦测视频2范围）")
                # elif self.step == 1:
                #     # 视频2完成后，step推进到2
                #     self.step = 2
                #     print(f"   [状态升级] 视频2播放完成 → step=2（准备侦测视频3/4范围）")
                # elif self.step == 2:
                #     # 视频3或4完成后，step重置到0，准备新的循环
                #     self.step = 0
                #     print(f"   [状态重置] 视频{video_id}播放完成 → step=0（一个完整倒水循环结束，准备下一个）")
                
            else:
                print(f"[警告] 收到非反馈类型消息: {data.get('type')}")
        except Exception as e:
            print(f"[回调错误] {e}")

    async def execute_next_task(self):
        """
        执行单个任务（已被sequence_manager()的循环替代）
        保留此方法以兼容旧代码
        """
        if not self.task_queue:
            self.is_executing = False
            print("\n[流程结束] 任务序列执行完毕")
            return

        v_id = self.task_queue.pop(0)
        self.is_executing = True
        
        # 封装下发包
        payload = {"type": "COMMAND", "content": str(v_id)} if v_id in [1, 2] else \
                  {"type": "COMPARE_RESULT", "value": (1.5 if v_id == 3 else 3.0)}
        
        await self.server.broadcast_data(payload)
        print(f"\n[指令] 下发视频 {v_id}.mp4 (旧方法，已被循环替代)")

    async def delayed_next_task(self, delay):
        await asyncio.sleep(delay)
        await self.execute_next_task()

    def load_tasks_from_file(self, filename="data.txt"):
        """
        [模式1] 从txt文件加载固定任务序列
        每行应包含14个浮点数（电容值）
        返回: bool - 是否成功加载
        """
        if not os.path.exists(filename):
            print(f"[错误] 文件不存在: {filename}")
            return False
        
        seq, last_id = [], None
        try:
            with open(filename, 'r') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    
                    parts = line.split()
                    if len(parts) != 14:
                        print(f"[警告] 第{line_num}行数据不完整: {len(parts)}个值，需要14个")
                        continue
                    
                    try:
                        cap_data = [float(x) for x in parts]
                        R = self.estimator.estimate_radius(cap_data)
                        print(f"[txt预处理] 第{line_num}行 → 半径: {R:.2f}mm")
                        
                        v_id = self.map_radius_to_id(R)
                        
                        # 只有状态改变时才加入队列
                        if v_id is not None and v_id != last_id:
                            seq.append(v_id)
                            last_id = v_id
                            print(f"  └─> 加入任务: 视频ID={v_id}")
                    except ValueError:
                        print(f"[警告] 第{line_num}行数据格式错误")
                        continue
            
            if seq:
                self.task_queue = seq
                print(f"\n[txt模式] 加载完成，任务序列: {self.task_queue}")
                return True
            else:
                print(f"[警告] 从{filename}提取不出有效任务序列")
                return False
                
        except Exception as e:
            print(f"[txt加载错误] {e}")
            return False

    async def serial_loop(self):
        """
        [核心改进] 传感器数据采集循环
        仅负责：读取 → 解析 → 存队列
        不负责：状态映射（由state_analyzer负责）
        """
        if not self.ser_sensor:
            print("[错误] 传感器未连接，serial_loop退出")
            return
        
        buffer = bytearray()
        packet_count = 0
        
        while True:
            try:
                if self.ser_sensor.in_waiting:
                    # 读取新数据
                    chunk = self.ser_sensor.read(self.ser_sensor.in_waiting)
                    buffer.extend(chunk)
                    #打印看看也没有数据
                    
                    # 尝试解析完整包（66字节）
                    while len(buffer) >= 66:
                        packet = buffer[:66]
                        buffer = buffer[66:]
                        # print(f"读取到的数据：{buffer}")

                        # 使用ProtocolUtils解析数据包
                        cap_data = ProtocolUtils.parse_packet(packet)
                        with base_lock:
                            # ======== 基准校准阶段 ========
                            if not self.baseline_ready:
                                # 还在校准阶段：累积样本
                                if cap_data is not None:
                                    self.baseline_samples.append(cap_data)
                                    
                                    if len(self.baseline_samples) >= self.baseline_count:
                                        # 校准完成：求平均作为基准
                                        global base_values  # ← 重要：声明全局变量
                                        avg_baseline = [sum(ch_vals) / len(ch_vals) 
                                                       for ch_vals in zip(*self.baseline_samples)]
                                        base_values = avg_baseline
                                        self.baseline_ready = True
                                        print(f"[校准] 基准值已设置 (基于{self.baseline_count}个样本)")
                                continue  # 校准阶段不产出数据
                            
                            # ======== 正常工作阶段 ========
                            if cap_data is not None:
                                # 计算变化量
                                delta = [cap - base for cap, base in zip(cap_data, base_values)]
                                
                                # print(f"解析到的数据：{cap_data}")

                            if delta is not None:
                                # 成功解析，存入原始数据队列
                                try:
                                    self.raw_data_queue.put_nowait(delta)
                                    packet_count += 1
                                    
                                    if packet_count <= self.baseline_count:
                                        print(f"[校准] 采样 {packet_count}/{self.baseline_count}")
                                    
                                    # 每100个包打印一次统计
                                    if packet_count % 100 == 0:
                                        queue_size = self.raw_data_queue.qsize()
                                        print(f"[采集] 已处理{packet_count}个包, 队列大小: {queue_size}")
                                except asyncio.QueueFull:
                                    # 队列满，丢弃（不应该发生）
                                    pass
                            else:
                                # 解析失败，尝试同步（寻找下一个有效的帧头）
                                # 尝试在buffer中寻找下一个帧头 0x55 0xAA
                                found = False
                                for i in range(1, min(len(buffer), 10)):
                                    if i + 1 < len(buffer) and buffer[i] == 0x55 and buffer[i+1] == 0xAA:
                                        buffer = buffer[i:]
                                        found = True
                                        break
                                
                                if not found:
                                    # 未找到有效帧头，清空部分buffer
                                    if len(buffer) > 100:
                                        buffer = buffer[50:]
                            plot_ready.set()
                await asyncio.sleep(0.001)
                
            except Exception as e:
                print(f"[serial_loop错误] {e}")
                await asyncio.sleep(0.1)

    async def state_analyzer(self):
        """
        [核心改进] 后台状态分析器
        负责：从原始队列提取数据 → 计算平均状态 → 去抖检测 → 只有变化才放入任务队列
        
        工作流程:
        1. 积累N个原始数据点
        2. 计算这个窗口的平均半径
        3. 映射到状态ID
        4. 与上次状态比较（去抖）
        5. 只有状态改变才加入任务队列
        """
        window_data = []
        window_size = CONFIG["state_window_size"]  # 每次分析的数据点数
        analysis_count = 0
        
        print(f"[分析器] 已启动，窗口大小={window_size}数据点")
        
        while True:
            try:
                # 从原始队列读数据（非阻塞，0.1秒超时）
                cap_data = await asyncio.wait_for(
                    self.raw_data_queue.get(), 
                    timeout=0.1
                )
                window_data.append(cap_data)
                
                # 当窗口满足分析条件
                if len(window_data) >= window_size:
                    # ⭐ 重要：如果正在播放视频，暂停处理数据
                    if self.is_executing:
                        print(f"[分析] 视频播放中（is_executing=True），暂停数据处理，清空窗口")
                        window_data = []  # ← 清空窗口，避免混入播放期间的数据
                        continue
                    
                    # 计算窗口内的平均半径
                    radii = [self.estimator.estimate_radius(d) for d in window_data]
                    avg_radius = sum(radii) / len(radii)
                    std_radius = (sum((r - avg_radius) ** 2 for r in radii) / len(radii)) ** 0.5
                    
                    # 映射到状态ID
                    state_id = self.map_radius_to_id(avg_radius)
                    
                    # 去抖检测：检查状态是否真正改变
                    changed, stable_state = self.state_manager.update(state_id)
                    
                    analysis_count += 1
                    
                    if analysis_count % 10 == 0:  # 每10次分析打印一次
                        duration = self.state_manager.get_state_duration()
                        print(f"[分析] #{analysis_count} 半径={avg_radius:.2f}±{std_radius:.2f}mm → 状态={state_id} | "
                              f"当前稳定状态={stable_state} (维持{duration:.2f}s)")
                    
                    if changed and state_id is not None:
                        # 状态确实改变，且与上次播放的视频ID不同，才加入任务队列
                        if state_id != self.last_played_video_id:
                            print(f"🔔 [状态转移] {self.state_manager.last_state} → {state_id} | "
                                  f"将视频ID={state_id}加入任务队列")
                            self.task_queue.append(state_id)
                        else:
                            print(f"[过滤] 检测到视频{state_id}范围，但已是上次播放的视频，跳过重复加入")
                    
                    
                    # 滑动窗口（每次移动50%）
                    window_data = window_data[window_size // 2:]
                
            except asyncio.TimeoutError:
                # 队列空，继续等待
                pass
            except Exception as e:
                print(f"[分析器错误] {e}")
                await asyncio.sleep(0.1)

    async def sequence_manager(self):
        """
        等待客户端连接，然后顺序执行任务队列中的视频
        
        改进：
        1. 添加超时机制（10秒无反馈则自动跳过）
        2. 支持任务队列动态增长
        """
        print("[任务管理] 等待客户端连接...")
        while len(self.server.clients) == 0:
            await asyncio.sleep(0.5)
        
        print("[任务管理] 客户端已连接，开始执行任务队列")
        
        # 循环执行任务队列
        while True:
            # 1. 等待任务队列非空（最多等待30秒）
            timeout_count = 0
            while not self.task_queue and timeout_count < 60:
                await asyncio.sleep(0.5)
                timeout_count += 1
            
            if not self.task_queue:
                print("[任务管理] 30秒内未收到新任务，等待中...")
                continue
            
            # 2. 执行任务
            v_id = self.task_queue.pop(0)
            self.is_executing = True
            
            # 3. 构建发送包（统一为COMMAND类型，所有视频1,2,3,4都用COMMAND）
            payload = {"type": "COMMAND", "content": str(v_id)}
            
            # 4. 发送给客户端
            await self.server.broadcast_data(payload)
            print(f"\n[指令] 下发视频 {v_id}.mp4")
            
            # 5. 等待反馈（超时10秒自动跳过）
            feedback_timeout = 0
            while self.is_executing and feedback_timeout < 20:
                await asyncio.sleep(0.5)
                feedback_timeout += 1
            
            if self.is_executing:
                # 10秒后仍未收到反馈，说明客户端出问题了
                print(f"\n[超时] 视频{v_id}播放超过10秒未收到反馈，自动跳过")
                self.is_executing = False
            
            # 6. 继续下一个任务（等待0.5秒避免过快）
            await asyncio.sleep(0.5)

    async def run(self):
        """
        根据工作模式选择任务执行方式
        
        [txt模式] 从data.txt加载固定任务序列
        [实时模式] 从传感器实时采集数据，后台分析状态变化
        """
        print("\n" + "="*60)
        print(f"[系统启动] 工作模式: {self.work_mode.upper()}")
        print("="*60 + "\n")
        
        # 公共任务：启动WebSocket服务
        common_tasks = [self.server.start()]
        
        if self.work_mode == WorkMode.MODE_TXT:
            # === TXT模式 ===
            print("[txt模式] 从data.txt加载任务序列...")
            has_tasks = self.load_tasks_from_file("data.txt")
            
            if not has_tasks:
                print("[错误] 无法加载txt任务序列，程序退出")
                return
            
            print(f"[txt模式] 任务队列已准备: {self.task_queue}")
            
            # txt模式只需要：网络服务 + 任务执行
            tasks = common_tasks + [self.sequence_manager()]
        
        else:
            # === 实时模式 ===
            print("[实时模式] 启动传感器采集 + 后台分析...")
            
            if not self.ser_sensor:
                print("[错误] 传感器未连接，无法启动实时模式")
                return
            
            # 实时模式需要：网络服务 + 数据采集 + 状态分析 + 任务执行
            tasks = common_tasks + [
                self.serial_loop(),      # 从COM4读取传感器数据
                self.state_analyzer(),   # 后台状态分析和去抖
                self.sequence_manager()  # 任务执行
            ]
        
        print("\n[系统] 所有服务已启动，按Ctrl+C退出\n")
        
        try:
            await asyncio.gather(*tasks)
        except KeyboardInterrupt:
            print("\n[系统] 收到退出信号")
        except Exception as e:
            print(f"\n[系统错误] {e}")

if __name__ == "__main__":
    # 支持命令行指定工作模式
    # 用法: python main.py [txt|realtime]
    mode = WorkMode.MODE_REALTIME  # 默认为实时模式
    
    if len(sys.argv) > 1:
        mode_arg = sys.argv[1].lower()
        if mode_arg == "txt":
            mode = WorkMode.MODE_TXT
        elif mode_arg == "realtime":
            mode = WorkMode.MODE_REALTIME
        else:
            print(f"[错误] 未知模式: {mode_arg}")
            print(f"用法: python main.py [txt|realtime]")
            sys.exit(1)
    
    # 创建应用实例
    app = MainApp(mode=mode)
    
    try:
        asyncio.run(app.run())
    except KeyboardInterrupt:
        print("\n[系统] 已停止")
    except Exception as e:
        print(f"\n[系统] 致命错误: {e}")
