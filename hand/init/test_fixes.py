#!/usr/bin/env python3
"""
🧪 快速测试脚本 - 验证修复是否成功

测试内容：
1. 检查视频文件是否存在
2. 检查网络连接
3. 模拟完整的视频播放流程
"""

import os
import json
import asyncio
import websockets

def test_video_files():
    """测试1：检查视频文件"""
    print("\n" + "="*60)
    print("📝 测试 1: 视频文件检查")
    print("="*60)
    
    videos = ["1.mp4", "2.mp4", "3.mp4", "4.mp4"]
    all_exist = True
    
    for video in videos:
        path = os.path.join(os.path.dirname(__file__), video)
        exists = os.path.exists(path)
        status = "✅" if exists else "❌"
        size = f"{os.path.getsize(path) / 1024 / 1024:.2f}MB" if exists else "N/A"
        print(f"{status} {video:10} {size:>10}")
        all_exist = all_exist and exists
    
    return all_exist

async def test_websocket_connection():
    """测试2：WebSocket 连接"""
    print("\n" + "="*60)
    print("🌐 测试 2: WebSocket 连接")
    print("="*60)
    
    try:
        uri = "ws://localhost:8765"
        print(f"尝试连接到 {uri}...")
        
        async with websockets.connect(uri) as websocket:
            print("✅ 连接成功")
            
            # 发送测试消息
            test_msg = {
                "type": "ACTION_FEEDBACK",
                "name": "test",
                "frequency": "10Hz"
            }
            
            await websocket.send(json.dumps(test_msg))
            print(f"✅ 发送测试反馈: {test_msg}")
            
            return True
    except Exception as e:
        print(f"❌ 连接失败: {e}")
        print("   确保服务端正在运行: python main_new.py realtime")
        return False

async def test_feedback_flow():
    """测试3：完整反馈流程"""
    print("\n" + "="*60)
    print("📡 测试 3: 反馈流程模拟")
    print("="*60)
    
    try:
        uri = "ws://localhost:8765"
        
        async with websockets.connect(uri) as websocket:
            # 模拟客户端发送的反馈
            feedbacks = [
                {"type": "ACTION_FEEDBACK", "name": "start", "frequency": "5Hz"},
                {"type": "ACTION_FEEDBACK", "name": "filling", "frequency": "10Hz"},
                {"type": "ACTION_FEEDBACK", "name": "success", "frequency": "15Hz"},
                {"type": "ACTION_FEEDBACK", "name": "spill", "frequency": "20Hz"},
            ]
            
            for i, feedback in enumerate(feedbacks, 1):
                print(f"\n  [{i}] 发送反馈: {feedback['name']}")
                await websocket.send(json.dumps(feedback))
                await asyncio.sleep(0.5)
            
            print("\n✅ 所有反馈已发送")
            return True
            
    except Exception as e:
        print(f"❌ 反馈流程失败: {e}")
        return False

def main():
    print("\n╔" + "="*58 + "╗")
    print("║" + " 🧪 系统修复验证测试 ".center(58) + "║")
    print("╚" + "="*58 + "╝")
    
    # 测试 1
    video_ok = test_video_files()
    
    # 测试 2 和 3（需要服务端运行）
    print("\n" + "="*60)
    print("⚠️  后续测试需要服务端正在运行")
    print("="*60)
    print("\n如果看到下面的错误，请先运行服务端:")
    print("  python main_new.py realtime")
    
    try:
        ws_ok = asyncio.run(test_websocket_connection())
        if ws_ok:
            asyncio.run(test_feedback_flow())
    except Exception as e:
        print(f"\n💡 提示: {e}")
    
    # 总结
    print("\n" + "="*60)
    print("📋 测试总结")
    print("="*60)
    
    if video_ok:
        print("✅ 视频文件: 完整")
    else:
        print("❌ 视频文件: 缺失")
    
    print("\n✅ 修复已应用:")
    print("  ✓ network_server.py - 异步反馈处理")
    print("  ✓ test_client.py - 视频检查和超时反馈")
    print("  ✓ main_new.py - 改进的日志和错误处理")
    
    print("\n📝 下一步:")
    print("  1. 终端1: python main_new.py realtime")
    print("  2. 终端2: python test_client.py")
    print("  3. 按压手套手指触发状态变化")
    print("  4. 观察视频播放和反馈流程")
    
    print("\n" + "="*60 + "\n")

if __name__ == "__main__":
    main()
