import asyncio
import json
import websockets
import sys
from processor import RadiusEstimator

class MetaGatewayServer:
    def __init__(self, port=8765, on_feedb_received=None):
        self.port = port
        self.clients = set()
        self.estimator = RadiusEstimator()
        self.current_stage = 0
        self.on_feedb_received = on_feedb_received 

    async def handler(self, websocket):
        self.clients.add(websocket)
        print(f"[网络] 客户端已连接。当前总连接数: {len(self.clients)}")
        try:
            async for message in websocket:
                # 收到客户端反馈，传给 MainApp 处理 
                if self.on_feedb_received:
                    try:
                        # 同步调用反馈处理（避免线程安全问题）
                        self.on_feedb_received(message)
                    except Exception as e:
                        print(f"[反馈处理错误] {e}")
        except Exception as e:
            print(f"[网络错误] {e}")
        finally:
            self.clients.discard(websocket)
            print("[网络] 客户端断开连接")


    async def broadcast_data(self, data_dict):
        if not self.clients: return
        message = json.dumps(data_dict)
        # 并发发送给所有已连接的客户端
        await asyncio.gather(*[client.send(message) for client in self.clients])

    async def start(self):
        # 启动 WebSocket 服务
        async with websockets.serve(self.handler, "0.0.0.0", self.port):
            # 保持服务运行 (这里不运行 terminal_input_loop 以免干扰 main.py 的文件逻辑)
            await asyncio.Future()