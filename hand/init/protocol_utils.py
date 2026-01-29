import struct


class ProtocolUtils:
    @staticmethod
    def crc16(data):
        """标准 CRC16 校验逻辑 (Modbus RTU)"""
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
    def parse_packet(packet):
        """不同协议的传感器 解析 14 通道电容数据包"""
        if len(packet) != 66:
            print("数据包长度错误")
            return None
        if packet[0] != 0x55 or packet[1] != 0xAA:
            print("数据包开头格式错误")
            return None

        # 数据段: 第8字节开始，56字节 (14通道 * 4字节浮点数)
        data_section = packet[8:8 + 56]

        # 校验数据段
        calculated_crc = ProtocolUtils.crc16(data_section)
        received_crc = packet[-2:]

        if calculated_crc != received_crc:
            print("数据包校验错误")
            return None

        # 解析浮点数
        capacitances = []
        for i in range(14):
            offset = 8 + i * 4
            cap = struct.unpack('<f', packet[offset:offset + 4])[0]
            capacitances.append(round(cap, 3))
        return capacitances