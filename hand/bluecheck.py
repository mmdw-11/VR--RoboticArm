import asyncio
from winsdk.windows.devices.bluetooth import BluetoothAdapter


async def check_hardware():
    print("正在检查硬件能力...")
    adapter = await BluetoothAdapter.get_default_async()

    if not adapter:
        print("❌ 错误：未找到蓝牙适配器！(请检查蓝牙是否开启)")
        return

    print(f"----------------------------------")
    print(f"蓝牙适配器 ID: {adapter.device_id}")
    print(f"✅ BLE (低功耗) 支持: {adapter.is_low_energy_supported}")

    # 关键指标：如果下面这项是 False，你的电脑永远无法作为 BLE 服务端
    print(f"❓ 外设模式 (Server) 支持: {adapter.is_peripheral_role_supported}")

    print(f"❓ 广播卸载支持: {adapter.is_advertisement_offload_supported}")
    print(f"----------------------------------")

    if not adapter.is_peripheral_role_supported:
        print("❌ 致命结论：你的网卡硬件不支持【外设模式】。")
        print("   -> 这意味着这台电脑无法作为 BLE 服务端广播信号。")
        print("   -> 解决方案：请看下文的【架构翻转】方案。")
    else:
        print("✅ 硬件检测通过！如果仍然报错，请检查 Windows 隐私设置。")


if __name__ == "__main__":
    asyncio.run(check_hardware())