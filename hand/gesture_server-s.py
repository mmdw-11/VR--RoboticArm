import serial
import struct
import matplotlib.pyplot as plt
from collections import deque
import numpy as np
import time
import threading
import asyncio
import uuid
import logging
from matplotlib.animation import FuncAnimation

# ==========================================
#   PART ONE: Windows BLE Server (Winsdk)
# ==========================================
from winsdk.windows.devices.bluetooth.genericattributeprofile import (
    GattServiceProvider,
    GattLocalCharacteristicParameters,
    GattProtectionLevel
)
from winsdk.windows.storage.streams import DataWriter

# BLE Configuration
SERVICE_UUID = uuid.UUID("0000ffff-0000-1000-8000-00805f9b34fb")
CHAR_UUID = uuid.UUID("0000ff01-0000-1000-8000-00805f9b34fb")

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("GestureSystem")


class BLEManager:
    def __init__(self):
        self.service_provider = None
        self.characteristic = None
        self.loop = None
        self.last_sent_id = -1  # Used to debounce/deduplicate identical gestures

    def start_background_thread(self):
        """Starts the asyncio loop in a background thread to avoid blocking Matplotlib"""
        t = threading.Thread(target=self._run_loop, daemon=True)
        t.start()

    def _run_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        # Start the BLE service
        self.loop.run_until_complete(self._start_server())
        # Keep the loop running
        self.loop.run_forever()

    async def _start_server(self):
        logger.info("[BLE] Initializing advertising service...")
        try:
            # 1. Create service
            result = await GattServiceProvider.create_async(SERVICE_UUID)
            if result.error.value != 0:
                logger.error(f"[BLE] Failed to create service Error: {result.error}")
                return
            self.service_provider = result.service_provider

            # 2. Create characteristic
            char_params = GattLocalCharacteristicParameters()
            char_params.characteristic_properties = 18  # Read (2) | Notify (16)
            char_params.write_protection_level = GattProtectionLevel.PLAIN
            char_params.user_description = "Gesture Data"

            char_result = await self.service_provider.service.create_characteristic_async(
                CHAR_UUID, char_params
            )
            if char_result.error.value != 0:
                logger.error(f"[BLE] Failed to create characteristic")
                return
            self.characteristic = char_result.characteristic

            # 3. Start advertising
            self.service_provider.start_advertising()
            logger.info(f"[BLE] Advertising started! UUID: {SERVICE_UUID}")
            logger.info(f"[BLE] Waiting for Quest 3 connection...")

        except Exception as e:
            logger.error(f"[BLE] Startup exception: {e}")

    async def _update_value_async(self, gesture_id):
        if not self.characteristic:
            return

        try:
            # Package data
            writer = DataWriter()
            writer.write_byte(gesture_id)
            data_buffer = writer.detach_buffer()

            # Send Notify if a device is subscribed
            if self.characteristic.subscribed_clients.size > 0:
                await self.characteristic.notify_value_async(data_buffer)
                # logger.info(f"[BLE Sent] ID: {gesture_id}") # Enable for debugging
            else:
                # Update local value only
                pass
        except Exception as e:
            logger.error(f"[BLE Send Error] {e}")

    def send_gesture(self, gesture_id):
        """Thread-safe sending interface for the serial thread to call"""
        # Simple deduplication: don't flood BLE if the gesture hasn't changed
        if gesture_id == self.last_sent_id:
            return
        self.last_sent_id = gesture_id

        if self.loop and self.characteristic:
            asyncio.run_coroutine_threadsafe(
                self._update_value_async(gesture_id),
                self.loop
            )


# Global BLE instance
ble_manager = BLEManager()

# ==========================================
#   PART TWO: Serial & Data Processing (User's Original Logic)
# ==========================================

# Configuration parameters
MAX_POINTS = 2000
TIME_WINDOW = 100
UPDATE_INTERVAL = 50
COLORS = plt.cm.tab10(np.linspace(0, 1, 14))
SAVE_FILENAME = "sensor_data_delta.csv"


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


data_buffer = ChannelData()
base_values = [None] * 14
base_lock = threading.Lock()
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
            return None, f"CRC mismatch"

        capacitances = []
        for i in range(14):
            offset = 8 + i * 4
            cap = struct.unpack('<f', packet[offset:offset + 4])[0]
            capacitances.append(round(cap, 3))

        return capacitances, None

    except Exception as e:
        return None, f"Parsing error: {str(e)}"


# ------------------------------------------------
# [Key Modification] Gesture Recognition Algorithm Interface
# ------------------------------------------------
def detect_gesture(deltas):
    """
    Input: List of 14 capacitance delta values [d1, d2, ... d14]
    Output: Gesture ID (0-16). Implements all 11 IDs from user's list.

    NOTE: Channels 0-4 map to Thumb(0), Index(1), Middle(2), Ring(3), Pinky(4).
    """
    # 定义手势识别所需的三个主要阈值
    CLOSING_THRESHOLD = 0.15  # 判定手指完全闭合或大幅度弯曲的最小 Delta 值 (pF)
    PARTIAL_THRESHOLD = 0.10  # 判定手指部分弯曲或轻微闭合的最小 Delta 值 (pF)
    IDLE_THRESHOLD = 0.05  # 判定手指静止/张开的最大 Delta 变化 (pF)

    # 辅助函数：检查一组通道是否完全闭合
    def is_closing(channels, threshold=CLOSING_THRESHOLD):
        return all(deltas[i] > threshold for i in channels)

    # 辅助函数：检查一组通道是否部分闭合
    def is_partial(channels, threshold=PARTIAL_THRESHOLD):
        return all(deltas[i] > threshold and deltas[i] < CLOSING_THRESHOLD for i in channels)

    # 辅助函数：检查一组通道是否静止/张开
    def is_idle(channels, threshold=IDLE_THRESHOLD):
        return all(abs(deltas[i]) < threshold for i in channels)

    # --- 1. ID 0 (Fist / 握拳) - 最高优先级 ---
    # 所有 5 个手指都在大幅度闭合
    if is_closing(range(5)):
        return 0

    # --- 2. ID 5 (Open / 张开 / Idle) - 稳定状态 ---
    # 默认静止状态：所有手指都静止/张开
    if is_idle(range(5)):
        return 5

    # --- 3. ID 10 (Thumbs Up / 点赞) ---
    # 大拇指闭合，其他手指静止/张开
    if is_closing([0]) and is_idle(range(1, 5)):
        return 10

    # --- 4. ID 2 (Index Point / 食指点) ---
    # 食指闭合，其他手指静止/张开
    if is_closing([1]) and is_idle([0, 2, 3, 4]):
        return 2

    # --- 5. ID 6 ("L" Shape / Thumb & Index Closed) ---
    # 大拇指(0), 食指(1) 闭合；中指(2), 无名指(3), 小指(4) 静止/张开
    if is_closing([0, 1]) and is_idle([2, 3, 4]):
        return 6

    # --- 6. ID 7 (Peace Sign / Two Fingers Up) ---
    # 食指(1), 中指(2) 静止/张开；大拇指(0), 无名指(3), 小指(4) 闭合
    if is_idle([1, 2]) and is_closing([0, 3, 4]):
        return 7

    # --- 7. ID 16 (San Gesture / Custom) ---
    # 大拇指(0), 无名指(3), 小指(4) 闭合；食指(1), 中指(2) 静止/张开
    if is_closing([0, 3, 4]) and is_idle([1, 2]):
        return 16

    # --- 8. ID 4 (Index/Middle/Ring Up) ---
    # 大拇指(0), 小指(4) 闭合；食指(1), 中指(2), 无名指(3) 静止/张开
    if is_closing([0, 4]) and is_idle([1, 2, 3]):
        return 4

    # --- 9. ID 3 (OK Sign / Three Fingers Up) ---
    # 中指(2), 无名指(3), 小指(4) 闭合；大拇指(0), 食指(1) 静止/张开
    if is_closing([2, 3, 4]) and is_idle([0, 1]):
        return 3

    # --- 10. ID 1 (Partial Close/Cylinder Grasp) ---
    # 大拇指(0), 食指(1) 闭合；中指(2) 部分闭合；无名指(3), 小指(4) 静止/张开
    if is_closing([0, 1]) and is_partial([2]) and is_idle([3, 4]):
        return 1

    # --- 11. ID 8 (Tripod Grasp/Key Grasp) ---
    # 大拇指(0), 食指(1), 中指(2) 部分闭合；无名指(3), 小指(4) 静止/张开
    if is_partial([0, 1, 2]) and is_idle([3, 4]):
        return 8

    # --- 12. ID 9 (Hook Grasp) ---
    # 大拇指(0) 静止；其他四个手指(1, 2, 3, 4) 部分闭合
    if is_idle([0]) and is_partial([1, 2, 3, 4]):
        return 9

    # --- Fallback ---
    # 如果以上都不是，返回默认张开状态 ID 5
    return 5


# ------------------------------------------------

def data_thread(ser, stop_event):
    global data_buffer, base_values, base_lock, plot_ready
    buffer = bytearray()

    logger.info("[Serial] Serial thread started, reading data...")

    while not stop_event.is_set():
        try:
            data = ser.read(64)
            if not data:
                continue

            buffer.extend(data)

            # Look for start header
            while len(buffer) >= 2:
                if buffer[0] == 0x55 and buffer[1] == 0xAA:
                    break
                buffer.pop(0)

            # Parse data packet
            while len(buffer) >= 66:
                packet = buffer[:66]
                buffer = buffer[66:]

                parsed = parse_packet(packet)
                if parsed is None:
                    continue

                capacitances, error = parsed
                if error:
                    # print(f"[Error] {error}") # Reduce console spam
                    continue

                current_time = time.time() - start_time

                # Calculate Delta and process gesture
                with base_lock:
                    if any(val is None for val in base_values):
                        base_values = capacitances.copy()
                        delta = [0.0] * 14
                    else:
                        delta = [cap - base for cap, base in zip(capacitances, base_values)]

                    # 1. Store in Buffer for plotting
                    data_buffer.append(current_time, delta)
                    plot_ready.set()

                    # 2. [NEW] Recognize gesture and send to Quest 3
                    gesture_id = detect_gesture(delta)

                    # Call BLE manager to send (this is thread-safe)
                    ble_manager.send_gesture(gesture_id)

        except serial.SerialException:
            logger.error("Serial read exception")
            break
        except Exception as e:
            logger.error(f"Unknown error: {e}")


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
                        label=f'Ch{i + 1}',
                        animated=True)
        lines.append(line)

    ax.legend(loc='upper right', ncol=2, fontsize='small')
    ax.set_xlim(0, TIME_WINDOW)
    ax.set_ylim(-0.5, 0.5)
    return fig


def update_plot(frame):
    global data_buffer
    with data_buffer.lock:
        current_time = time.time() - start_time
        time_data = list(data_buffer.time)
        for i, line in enumerate(lines):
            values = list(data_buffer.values[i])
            line.set_data(time_data, values)

        # Auto-scale Y axis
        all_values = []
        for vals in data_buffer.values:
            all_values.extend(vals)
        if all_values:
            y_min = min(all_values)
            y_max = max(all_values)
            range_val = y_max - y_min
            if range_val > 0:
                margin = 0.1 * range_val
                ax.set_ylim(y_min - margin, y_max + margin)

        if time_data:
            x_min = max(0, current_time - TIME_WINDOW)
            ax.set_xlim(x_min, current_time + 1)
    return lines


def save_to_file(filename):
    logger.info(f"Saving data to {filename} ...")
    global data_buffer, start_time
    try:
        with open(filename, 'w') as f:
            f.write("Time(s),Ch1,Ch2,Ch3,Ch4,Ch5,Ch6,Ch7,Ch8,Ch9,Ch10,Ch11,Ch12,Ch13,Ch14\n")
            valid_lengths = [len(v) for v in data_buffer.values]
            if not valid_lengths: return
            min_length = min(valid_lengths)

            for i in range(min_length):
                if i < len(data_buffer.time):
                    timestamp = data_buffer.time[i]
                    data_row = [f"{timestamp:.3f}"]
                    for ch in range(14):
                        data_row.append(f"{data_buffer.values[ch][i]:.6f}")
                    f.write(",".join(data_row) + "\n")
    except Exception as e:
        logger.error(f"Save failed: {e}")


def main():
    global start_time, fig

    # 1. Start BLE background thread
    ble_manager.start_background_thread()

    # 2. Open serial port
    try:
        ser = serial.Serial(port='COM3', baudrate=115200, timeout=1)  # Please verify COM port
    except Exception as e:
        logger.error(f"Could not open serial port COM3: {e}")
        return

    init_plot()
    start_time = time.time()

    stop_event = threading.Event()

    # 3. Start data reading thread
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
        print("系统运行中... [Matplotlib 窗口] 显示波形, [BLE] 广播中...")
        plt.show()  # Blocks the main thread
    except KeyboardInterrupt:
        print("\n用户中断...")
    finally:
        stop_event.set()
        ser.close()
        save_to_file(SAVE_FILENAME)
        print("程序结束")


if __name__ == "__main__":
    main()