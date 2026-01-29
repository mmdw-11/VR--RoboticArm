import serial
import time
import threading

# 继电器通道控制命令（确保使用英文引号）
relay_commands = {
    '一': {'on': bytes([0x00, 0xf1, 0xff]), 'off': bytes([0x00, 0x01, 0xff]), 'channel': 1},
    '二': {'on': bytes([0x00, 0xf2, 0xff]), 'off': bytes([0x00, 0x02, 0xff]), 'channel': 2},
    '三': {'on': bytes([0x00, 0xf3, 0xff]), 'off': bytes([0x00, 0x03, 0xff]), 'channel': 3},
    '四': {'on': bytes([0x00, 0xf4, 0xff]), 'off': bytes([0x00, 0x04, 0xff]), 'channel': 4},
    '五': {'on': bytes([0x00, 0xf5, 0xff]), 'off': bytes([0x00, 0x05, 0xff]), 'channel': 5},
    '六': {'on': bytes([0x00, 0xf6, 0xff]), 'off': bytes([0x00, 0x06, 0xff]), 'channel': 6},
}


class RelayController:
    def __init__(self, port='COM5', baudrate=9600):
        self.port = port
        self.baudrate = baudrate
        self.serial_conn = None
        self.lock = threading.Lock()
        self.running = False

    def connect(self):
        try:
            self.serial_conn = serial.Serial(self.port, self.baudrate, timeout=1)
            print(f"已成功连接到 {self.port}")
            return True
        except serial.SerialException as e:
            print(f"串口连接失败: {e}")
            return False

    def disconnect(self):
        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.close()
            print("串口连接已关闭")

    def control_channel(self, channel_char, frequency, duration=10):
        """控制单个通道以指定频率运行指定时间（秒）"""
        if channel_char not in relay_commands:
            print(f"错误：无效的通道 '{channel_char}'")
            return False

        channel_info = relay_commands[channel_char]
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

    def start_control(self, channel_settings, duration=10):
        """
        启动多通道控制
        :param channel_settings: 字典，格式为 {'一': 2, '二': 5, ...} 表示通道一2Hz，通道二5Hz
        :param duration: 每个通道运行的总时间（秒）
        """
        if not channel_settings:
            print("错误：未指定任何通道")
            return

        self.running = True
        threads = []

        # 为每个通道创建并启动线程
        for channel_char, freq in channel_settings.items():
            if channel_char in relay_commands:
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

    def stop_control(self):
        """停止所有通道控制"""
        self.running = False
        print("正在停止所有通道...")


def parse_input(input_str):
    """
    解析用户输入，格式如 "一-2 二-5 三-3"
    返回字典 {'一': 2, '二': 5, '三': 3}
    """
    settings = {}
    parts = input_str.split()

    for part in parts:
        if '-' in part:
            channel, freq = part.split('-', 1)
            if channel in relay_commands:
                try:
                    settings[channel] = int(freq)
                except ValueError:
                    print(f"警告：'{part}' 中的频率必须是整数，已跳过")
        else:
            print(f"警告：'{part}' 格式不正确，应使用 '通道-频率' 格式，已跳过")

    return settings


def main():
    print("多通道继电器控制程序")
    print("功能: 可以同时控制多个通道，每个通道可以设置不同频率")
    print("输入格式示例: '一-2 二-5 三-3' 表示通道一2Hz，通道二5Hz，通道三3Hz")
    print("输入'退出'可结束程序\n")

    controller = RelayController()
    if not controller.connect():
        return

    try:
        while True:
            # 获取用户输入
            while True:
                user_input = input("请输入通道和频率设置(如'一-2 二-3')，或输入'退出'结束: ").strip()

                if user_input == '退出':
                    if controller.running:
                        controller.stop_control()
                    print("程序结束")
                    return

                if not user_input:
                    print("请输入有效内容")
                    continue

                # 解析输入
                channel_settings = parse_input(user_input)
                if not channel_settings:
                    print("错误：未指定任何有效通道设置")
                    continue

                # 获取运行时间
                while True:
                    try:
                        duration = float(input("请输入每个通道的运行时间(秒): "))
                        if duration > 0:
                            break
                        else:
                            print("请输入大于0的数字")
                    except ValueError:
                        print("请输入有效的数字")

                break

            # 启动控制
            controller.start_control(channel_settings, duration)

    finally:
        controller.disconnect()


if __name__ == "__main__":
    main()