#!/usr/bin/env python3
"""
🔍 串口诊断工具 - 帮助排查CRC错误和数据格式问题
"""

import serial
import struct
import time

class PortDiagnostic:
    """串口诊断工具类"""
    
    @staticmethod
    def crc16(data):
        """CRC16计算"""
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
    
    @staticmethod
    def check_com4():
        """检查COM4连接状态"""
        print("="*70)
        print("🔌 COM4 (传感器) 诊断")
        print("="*70)
        
        try:
            ser = serial.Serial('COM4', 115200, timeout=0.1)
            print("✅ COM4 已连接")
            
            # 读取一些数据包
            print("\n📊 读取原始数据包...\n")
            
            for i in range(5):
                data = ser.read(66)  # 读取66字节
                
                if len(data) < 66:
                    print(f"⚠️  包{i+1}: 数据不足 ({len(data)}/66 字节)")
                    continue
                
                # 检查帧头
                if data[0] == 0x55 and data[1] == 0xAA:
                    print(f"✅ 包{i+1}: 帧头正确 [0x55 0xAA]")
                else:
                    print(f"❌ 包{i+1}: 帧头错误 [0x{data[0]:02X} 0x{data[1]:02X}]")
                    continue
                
                # 检查CRC
                data_section = data[8:64]  # 56字节数据
                calculated_crc = PortDiagnostic.crc16(data_section)
                received_crc = data[64:66]
                
                if calculated_crc == received_crc:
                    print(f"   ✅ CRC校验通过")
                else:
                    print(f"   ❌ CRC校验失败")
                    print(f"      计算值: 0x{calculated_crc.hex()}")
                    print(f"      接收值: 0x{received_crc.hex()}")
                
                # 尝试解析电容数据
                try:
                    capacitances = []
                    for j in range(14):
                        offset = 8 + j * 4
                        cap = struct.unpack('<f', data[offset:offset + 4])[0]
                        capacitances.append(cap)
                    
                    # 检查数据范围
                    min_cap = min(capacitances)
                    max_cap = max(capacitances)
                    avg_cap = sum(capacitances) / len(capacitances)
                    
                    print(f"   数据范围: {min_cap:.2f} - {max_cap:.2f} (平均: {avg_cap:.2f})")
                    
                    if min_cap < -1000 or max_cap > 1000:
                        print(f"   ⚠️  警告：数据值异常！")
                except Exception as e:
                    print(f"   ❌ 解析失败: {e}")
                
                print()
                time.sleep(0.1)
            
            ser.close()
            print("✅ COM4 检查完成\n")
            return True
            
        except Exception as e:
            print(f"❌ COM4 连接失败: {e}\n")
            return False
    
    @staticmethod
    def check_com5():
        """检查COM5连接状态"""
        print("="*70)
        print("🔌 COM5 (继电器) 诊断")
        print("="*70)
        
        try:
            ser = serial.Serial('COM5', 9600, timeout=0.1)
            print("✅ COM5 已连接")
            print("   ℹ️  继电器通常只接收命令，不发送数据")
            ser.close()
            print("✅ COM5 检查完成\n")
            return True
            
        except Exception as e:
            print(f"❌ COM5 连接失败: {e}\n")
            return False
    
    @staticmethod
    def analyze_crc_pattern():
        """分析CRC校验的正确位置"""
        print("="*70)
        print("🔬 CRC校验模式分析")
        print("="*70)
        
        try:
            ser = serial.Serial('COM4', 115200, timeout=0.1)
            
            print("尝试读取1个数据包，分析CRC校验位置...\n")
            data = ser.read(66)
            
            if len(data) != 66:
                print(f"❌ 数据不足 ({len(data)}/66)")
                ser.close()
                return
            
            print(f"原始数据（前20字节）: {' '.join(f'{b:02X}' for b in data[:20])}")
            print(f"原始数据（后10字节）: {' '.join(f'{b:02X}' for b in data[-10:])}")
            print()
            
            # 尝试多种CRC校验范围
            crc_tests = [
                ("整个数据包", data[:64]),
                ("帧头后", data[2:64]),
                ("数据段", data[8:64]),
                ("数据段前", data[8:62]),
            ]
            
            for name, test_data in crc_tests:
                calc_crc = PortDiagnostic.crc16(test_data)
                recv_crc = data[64:66]
                match = "✅" if calc_crc == recv_crc else "❌"
                print(f"{match} {name}: 计算=0x{calc_crc.hex()}, 接收=0x{recv_crc.hex()}")
            
            ser.close()
            print()
            
        except Exception as e:
            print(f"❌ 分析失败: {e}\n")

def main():
    print("\n╔" + "="*68 + "╗")
    print("║" + " 🔧 串口诊断工具 ".center(68) + "║")
    print("╚" + "="*68 + "╝\n")
    
    # 检查COM4
    com4_ok = PortDiagnostic.check_com4()
    
    # 检查COM5
    com5_ok = PortDiagnostic.check_com5()
    
    # 分析CRC
    if com4_ok:
        PortDiagnostic.analyze_crc_pattern()
    
    # 总结
    print("="*70)
    print("📋 诊断总结")
    print("="*70)
    print(f"COM4 (传感器): {'✅ 正常' if com4_ok else '❌ 异常'}")
    print(f"COM5 (继电器): {'✅ 正常' if com5_ok else '❌ 异常'}")
    
    if not com4_ok or not com5_ok:
        print("\n⚠️  建议:")
        if not com4_ok:
            print("  1. 检查COM4串口连接")
            print("  2. 检查传感器是否开启")
            print("  3. 检查波特率是否为115200")
        if not com5_ok:
            print("  1. 检查COM5串口连接")
            print("  2. 检查继电器是否开启")
            print("  3. 检查波特率是否为9600")
    
    print("\n" + "="*70)

if __name__ == "__main__":
    main()
