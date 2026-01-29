import asyncio
import sys
import logging
import uuid  # <--- 新增：winsdk 需要标准 UUID 对象

# 引入 Windows 原生 API
from winsdk.windows.devices.bluetooth.genericattributeprofile import (
    GattServiceProvider,
    GattLocalCharacteristicParameters,
    GattProtectionLevel,
    # GattUserDescriptionAttribute  <--- 已删除此错误引用
)
from winsdk.windows.storage.streams import DataWriter

# --- 1. 配置 UUID ---
# 务必使用 uuid.UUID() 将字符串转换为对象，否则 winsdk 会报错
SERVICE_UUID = uuid.UUID("0000ffff-0000-1000-8000-00805f9b34fb")
CHAR_UUID = uuid.UUID("0000ff01-0000-1000-8000-00805f9b34fb")

# 手势映射表
GESTURE_MAP = {
    1: "握拳 (Fist)",
    2: "耶 (Victory)",
    3: "捏合 (Pinch)",
    4: "挥手 (Wave)",
    5: "点赞 (ThumbUp)"
}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("WinBLE")


class WindowsBLEServer:
    def __init__(self):
        self.service_provider = None
        self.characteristic = None

    async def start(self):
        logger.info("正在初始化 Windows BLE 服务...")

        # 1. 创建服务提供者
        # winsdk.windows.foundation.Guid 也可以自动接受 uuid.UUID 对象
        result = await GattServiceProvider.create_async(SERVICE_UUID)

        if result.error.value != 0:  # 0 means Success
            logger.error(f"创建服务失败，错误代码: {result.error}")
            logger.error("请检查：1.电脑蓝牙已开启  2.Windows 设置中允许应用使用蓝牙")
            return

        self.service_provider = result.service_provider

        # 2. 定义特征值参数
        char_params = GattLocalCharacteristicParameters()
        # 设置属性：Read (2) | Notify (16) = 18
        char_params.characteristic_properties = 18
        char_params.write_protection_level = GattProtectionLevel.PLAIN

        # 直接赋值字符串即可，无需导入额外类
        char_params.user_description = "Gesture Control ID"

        # 3. 创建特征值
        char_result = await self.service_provider.service.create_characteristic_async(
            CHAR_UUID,
            char_params
        )

        if char_result.error.value != 0:
            logger.error(f"创建特征值失败: {char_result.error}")
            return

        self.characteristic = char_result.characteristic
        logger.info(f"特征值已创建: {CHAR_UUID}")

        # 4. 启动广播
        # 开启广播
        self.service_provider.start_advertising()
        logger.info(">>> 蓝牙广播已开启！ <<<")
        logger.info(">>> 请在 Quest 3 扫描并连接 <<<")

    def stop(self):
        if self.service_provider:
            self.service_provider.stop_advertising()
            logger.info("广播已停止")

    async def update_gesture(self, gesture_id):
        if not self.characteristic:
            return

        # 封装数据
        writer = DataWriter()
        writer.write_byte(gesture_id)
        data_buffer = writer.detach_buffer()

        # 推送 Notify
        # 这里的 subscribed_clients 包含了当前连接并订阅的所有设备
        # 注意：如果没有设备订阅 Notify，notify_value_async 可能会抛出异常或无操作，所以加个 try
        try:
            if self.characteristic.subscribed_clients.size > 0:
                await self.characteristic.notify_value_async(data_buffer)
                print(f"-> [Notify] 已发送: [{gesture_id}] {GESTURE_MAP.get(gesture_id, '未知')}")
            else:
                # 即使没人订阅，也可以更新本地缓存值（可选）
                print(f"-> [无客户端] 仅更新: {gesture_id} (等待 Quest 连接...)")
        except Exception as e:
            logger.error(f"发送失败: {e}")


async def main():
    server = WindowsBLEServer()
    await server.start()

    print("\n--------- 控制台 ---------")
    print("输入 1-5 发送手势，输入 0 退出")
    print("--------------------------\n")

    loop = asyncio.get_running_loop()

    try:
        while True:
            # 异步读取输入
            user_input = await loop.run_in_executor(None, sys.stdin.readline)
            cmd = user_input.strip()

            if not cmd.isdigit():
                # 处理空行
                if cmd: print("请输入数字！")
                continue

            val = int(cmd)
            if val == 0:
                break

            if 1 <= val <= 5:
                await server.update_gesture(val)
            else:
                print("无效 ID，请输入 1-5")

    except KeyboardInterrupt:
        pass
    finally:
        server.stop()


if __name__ == "__main__":
    asyncio.run(main())