#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
最小化网络测试 - 检查客户端和服务端的连接是否正常
"""
import asyncio
import websockets
import json
import threading

# ============ 客户端代码 ============
async def client_test():
    """最小化客户端 - 连接、接收命令、发送反馈"""
    uri = "ws://localhost:8765"
    try:
        print("[客户端] 正在连接到服务端...")
        async with websockets.connect(uri) as websocket:
            print("[客户端] ✅ 已连接")
            
            # 等待服务端消息（模拟主循环）
            try:
                async for message in websocket:
                    print(f"[客户端] 收到消息: {message}")
                    data = json.loads(message)
                    
                    if data.get("type") == "COMMAND":
                        video = data.get("content")
                        print(f"[客户端] 收到播放命令: {video}.mp4")
                        
                        # 模拟播放延迟 2 秒
                        await asyncio.sleep(2)
                        
                        # 发送完成反馈
                        feedback = {"type": "ACTION_FEEDBACK", "name": "success", "frequency": 8}
                        await websocket.send(json.dumps(feedback))
                        print(f"[客户端] ✅ 已发送反馈: {feedback}")
            except Exception as e:
                print(f"[客户端] 接收处理异常: {e}")
    except Exception as e:
        print(f"[客户端] 连接异常: {e}")

# ============ 服务端代码 ============
class SimpleServer:
    def __init__(self):
        self.clients = set()
        
    async def handler(self, websocket):
        self.clients.add(websocket)
        print(f"[服务端] ✅ 客户端已连接 ({len(self.clients)})")
        
        try:
            async for message in websocket:
                print(f"[服务端] 收到反馈: {message}")
                data = json.loads(message)
                if data.get("type") == "ACTION_FEEDBACK":
                    print(f"[服务端] ✅ 反馈处理完成")
        except Exception as e:
            print(f"[服务端] 消息处理异常: {e}")
        finally:
            self.clients.discard(websocket)
            print(f"[服务端] 客户端已断开")
    
    async def broadcast_command(self, video_num):
        """发送播放命令给所有客户端"""
        message = {"type": "COMMAND", "content": str(video_num)}
        if not self.clients:
            print("[服务端] ⚠️  没有连接的客户端")
            return
        
        msg_str = json.dumps(message)
        print(f"[服务端] 发送命令: {msg_str}")
        await asyncio.gather(*[client.send(msg_str) for client in self.clients])
    
    async def start(self):
        async with websockets.serve(self.handler, "0.0.0.0", 8765):
            print("[服务端] ✅ WebSocket 服务已启动 (port 8765)")
            await asyncio.Future()  # 永远等待

async def test_flow():
    """测试完整流程"""
    server = SimpleServer()
    
    # 启动服务端
    server_task = asyncio.create_task(server.start())
    
    # 等待服务端启动
    await asyncio.sleep(1)
    
    # 启动客户端
    client_task = asyncio.create_task(client_test())
    
    # 等待客户端连接
    await asyncio.sleep(1)
    
    # 发送播放命令
    await server.broadcast_command("1")
    
    # 等待反馈处理
    await asyncio.sleep(5)
    
    print("\n[测试] ✅ 流程测试完成，关闭服务")
    server_task.cancel()
    client_task.cancel()

if __name__ == "__main__":
    asyncio.run(test_flow())
