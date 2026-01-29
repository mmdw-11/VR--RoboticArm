
import asyncio
import websockets
import json
import time
import cv2
import queue
import threading
import os
import numpy as np

WINDOW_NAME = 'Haptic System - Continuous Video'
video_queue = queue.Queue()
state_lock = {"after_video_2": False}

ACTION_METADATA = {
    "1.mp4": {"name": "start", "frequency": "5Hz", "step": 1},    
    "2.mp4": {"name": "filling", "frequency": "10Hz", "step": 2},  
    "3.mp4": {"name": "success", "frequency": "15Hz", "step": 3},  
    "4.mp4": {"name": "spill", "frequency": "20Hz", "step": 4}    
}

websocket_handle = None

def start_async_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

async def receive_handler(websocket):
    global websocket_handle
    websocket_handle = websocket 
    try:
        async for message in websocket:
            data = json.loads(message)
            m_type = data.get("type")
            video_name = ""

            if m_type == "COMMAND":
                content = data.get("content")
                video_name = f"{content}.mp4"
                print(f"[网络] 收到播放指令: 视频{content}")
            
            if video_name:
                base_dir = os.path.dirname(os.path.abspath(__file__))
                full_path = os.path.join(base_dir, video_name)
                video_queue.put((video_name, full_path))
    except Exception as e:
        print(f"[网络异常] {e}")

async def connect_to_server():
    uri = "ws://localhost:8765"
    while True:
        try:
            async with websockets.connect(uri) as websocket:
                print("[网络] 已连接到服务端")
                await receive_handler(websocket)
        except Exception as e:
            print(f"[网络错误] 连接失败: {e}")
            await asyncio.sleep(2)

if __name__ == "__main__":
    network_loop = asyncio.new_event_loop()
    threading.Thread(target=start_async_loop, args=(network_loop,), daemon=True).start()
    asyncio.run_coroutine_threadsafe(connect_to_server(), network_loop)

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_AUTOSIZE)
    current_cap = None
    last_frame = None
    current_video_name = ""
    
    # 初始化占位图（蓝色背景）
    placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
    placeholder[:] = (120, 50, 50) # 深蓝色
    cv2.putText(placeholder, "WAITING FOR SERVER...", (140, 240), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)

    try:
        while True:
            try:
                if not video_queue.empty():
                    v_name, v_path = video_queue.get_nowait()
                    
                    # 检查视频文件是否存在
                    if not os.path.exists(v_path):
                        print(f"[警告] 视频文件不存在: {v_path}")
                        # 立即发送错误反馈给服务端
                        if websocket_handle and v_name in ACTION_METADATA:
                            meta = ACTION_METADATA[v_name]
                            feedback = {"type": "ACTION_FEEDBACK", "name": meta["name"], "frequency": meta["frequency"], "step": meta["step"]}
                            try:
                                asyncio.run_coroutine_threadsafe(websocket_handle.send(json.dumps(feedback)), network_loop)
                                print(f"[客户端] 发送反馈 (文件缺失): {meta['name']}, step={meta['step']}")
                            except Exception as e:
                                print(f"[错误] 无法发送反馈: {e}")
                        continue
                    
                    if current_cap: current_cap.release()
                    current_cap = cv2.VideoCapture(v_path)
                    if not current_cap.isOpened():
                        print(f"[错误] 无法打开视频: {v_path}")
                        current_cap = None
                        continue
                    current_video_name = v_name
                    
                    # --- 解决黑屏的关键：预读并强制刷新渲染 ---
                    ret, first_frame = current_cap.read()
                    if ret:
                        last_frame = first_frame
                        cv2.imshow(WINDOW_NAME, last_frame)
                        cv2.waitKey(1) # 强制给窗口 1ms 时间处理绘制事件
            except queue.Empty:
                pass

            if current_cap and current_cap.isOpened():
                ret, frame = current_cap.read()
                if ret:
                    last_frame = frame
                    cv2.imshow(WINDOW_NAME, frame)
                else:
                    # 播放完成回传
                    if websocket_handle and current_video_name in ACTION_METADATA:
                        meta = ACTION_METADATA[current_video_name]
                        feedback = {"type": "ACTION_FEEDBACK", "name": meta["name"], "frequency": meta["frequency"], "step": meta["step"]}
                        try:
                            asyncio.run_coroutine_threadsafe(websocket_handle.send(json.dumps(feedback)), network_loop)
                            print(f"[客户端] 发送反馈: {meta['name']} (视频播放完成), step={meta['step']}")
                        except Exception as e:
                            print(f"[错误] 无法发送反馈: {e}")
                    current_cap.release()
                    current_cap = None
            else:
                # 保持显示末帧或占位图 
                img = last_frame if last_frame is not None else placeholder
                cv2.imshow(WINDOW_NAME, img)

            if cv2.waitKey(25) & 0xFF == ord('q'):
                break
    finally:
        cv2.destroyAllWindows()