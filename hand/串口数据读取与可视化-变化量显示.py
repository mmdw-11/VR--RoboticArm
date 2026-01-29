import serial
import struct
import matplotlib.pyplot as plt
from collections import deque
import numpy as np
import time
import threading
from matplotlib.animation import FuncAnimation

# 配置参数
MAX_POINTS = 2000  # 每个通道最大显示点数
TIME_WINDOW = 100  # 显示时间窗口（秒）
UPDATE_INTERVAL = 50  # 图形刷新间隔（毫秒）
COLORS = plt.cm.tab10(np.linspace(0, 1, 14))  # 使用tab10颜色映射
SAVE_FILENAME = "sensor_data_delta1.1.csv"  # 保存文件名（修改为.csv扩展名）


# 全局数据存储（使用线程安全结构）
class ChannelData:
    def __init__(self):
        self.time = deque(maxlen=MAX_POINTS)
        self.values = [deque(maxlen=MAX_POINTS) for _ in range(14)]
        self.lock = threading.Lock()

    def append(self, timestamp, values):
        with self.lock:
            self.time.append(timestamp)
            for i, val in enumerate(values):
                self.values[i].append(val)

            # 全局变量


data_buffer = ChannelData()
base_values = [None] * 14  # 14个通道的基值存储
base_lock = threading.Lock()  # 基值锁
plot_ready = threading.Event()
fig = None
ax = None
lines = []
start_time = None


def crc16(data):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc >>= 1
                crc ^= 0xA001
            else:
                crc >>= 1
    return crc.to_bytes(2, 'little')


def parse_packet(packet):
    try:
        if len(packet) != 66:
            return None, f"Invalid length: {len(packet)}"
        if packet[0] != 0x55 or packet[1] != 0xAA:
            return None, "Invalid header"

        data_section = packet[8:8 + 14 * 4]
        calculated_crc = crc16(data_section)
        received_crc = packet[-2:]

        if calculated_crc != received_crc:
            return None, f"CRC错配: 计算值={calculated_crc.hex()} 接收值={received_crc.hex()}"

        capacitances = []
        for i in range(14):
            offset = 8 + i * 4
            cap = struct.unpack('<f', packet[offset:offset + 4])[0]
            capacitances.append(round(cap, 3))

        return capacitances, None

    except Exception as e:
        return None, f"解析错误: {str(e)}"


def init_plot():
    global fig, ax, lines
    plt.ioff()
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.set_xlabel('Time (s)')
    ax.set_ylabel('Capacitance Delta (pF)')
    ax.grid(True, linestyle='--', alpha=0.7)

    global lines
    lines = []
    for i in range(14):
        line, = ax.plot([], [],
                        color=COLORS[i],
                        lw=1,
                        label=f'Ch{i + 1} Delta',
                        animated=True)
        lines.append(line)

    ax.legend(loc='upper right', ncol=2)
    ax.set_xlim(0, TIME_WINDOW)
    ax.set_ylim(-0.5, 0.5)  # 初始范围设置为±0.5pF
    return fig


def update_plot(frame):
    global data_buffer

    with data_buffer.lock:
        current_time = time.time() - start_time
        time_data = list(data_buffer.time)

        for i, line in enumerate(lines):
            values = list(data_buffer.values[i])
            line.set_data(time_data, values)

        all_values = []
        for vals in data_buffer.values:
            all_values.extend(vals)
        if all_values:
            y_min = min(all_values)
            y_max = max(all_values)
            range_val = y_max - y_min
            margin = 0.1 * range_val if range_val > 0 else 0.1
            ax.set_ylim(y_min - margin, y_max + margin)

        if time_data:
            x_min = max(0, current_time - TIME_WINDOW)
            ax.set_xlim(x_min, current_time + 1)

    return lines


def save_to_file(filename):
    """将缓冲区数据保存到CSV文件"""
    global data_buffer, start_time, base_values

    with open(filename, 'w') as f:
        # 写入CSV表头
        f.write("Time(s),Ch1,Ch2,Ch3,Ch4,Ch5,Ch6,Ch7,Ch8,Ch9,Ch10,Ch11,Ch12,Ch13,Ch14\n")

        # 同步时间戳（确保所有通道数据对齐）
        valid_lengths = [len(v) for v in data_buffer.values]
        min_length = min(valid_lengths) if valid_lengths else 0

        for i in range(min_length):
            # 获取时间戳（使用第一个通道的时间戳）
            timestamp = data_buffer.time[i]

            # 构建数据行
            data_row = [f"{timestamp:.3f}"]  # 时间保留3位小数
            for ch in range(14):
                data_row.append(f"{data_buffer.values[ch][i]:.6f}")  # 电容值保留6位小数

            # 使用逗号分隔写入文件
            f.write(",".join(data_row) + "\n")


def data_thread(ser, stop_event):
    global data_buffer, base_values, base_lock, plot_ready
    buffer = bytearray()

    while not stop_event.is_set():
        data = ser.read(64)
        if not data:
            continue

        buffer.extend(data)

        while len(buffer) >= 2:
            if buffer[0] == 0x55 and buffer[1] == 0xAA:
                break
            buffer.pop(0)

        while len(buffer) >= 66:
            packet = buffer[:66]
            buffer = buffer[66:]

            parsed = parse_packet(packet)
            if parsed is None:
                continue

            capacitances, error = parsed
            if error:
                print(f"[错误] {error}")
                continue

            current_time = time.time() - start_time
            print(f"[{current_time:.3f}] {capacitances}")
            # 计算变化量
            with base_lock:
                if any(val is None for val in base_values):  # 首次接收数据，设置基值
                    base_values = capacitances.copy()
                    delta = [0.0] * 14  # 首次数据点变化量为0
                else:
                    delta = [cap - base for cap, base in zip(capacitances, base_values)]
                print(f"[{current_time:.3f}] 变化量: {delta}")
                data_buffer.append(current_time, delta)
                plot_ready.set()


def main():
    global start_time, fig

    ser = serial.Serial(
        port='COM4',
        baudrate=115200,
        timeout=1
    )

    init_plot()
    start_time = time.time()

    stop_event = threading.Event()
    data_thread_instance = threading.Thread(
        target=data_thread,
        args=(ser, stop_event),
        daemon=True
    )
    data_thread_instance.start()

    ani = FuncAnimation(
        fig,
        update_plot,
        blit=True,
        interval=UPDATE_INTERVAL,
        cache_frame_data=False
    )

    try:
        print(f"实时数据可视化中... 按Ctrl+C停止并保存数据到 {SAVE_FILENAME}")
        plt.show()
    except KeyboardInterrupt:
        print("\n用户中断，正在保存数据...")
    finally:
        stop_event.set()
        ser.close()
        plt.close()

        save_to_file(SAVE_FILENAME)
        print(f"数据已保存至：{SAVE_FILENAME}")


if __name__ == "__main__":
    main()
