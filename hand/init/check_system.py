#!/usr/bin/env python3
"""
🔍 系统状态检查脚本

用途：验证 main_new.py 是否正确实现了超时机制和连续任务执行
"""

import sys
import re

def check_file(filepath):
    """检查文件中的关键代码"""
    
    print("="*70)
    print(f"📋 检查文件: {filepath}")
    print("="*70)
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        print(f"❌ 无法读取文件: {e}")
        return False
    
    checks = [
        # (检查项名称, 正则表达式, 是否是警告)
        ("sequence_manager 使用 while True", r"async def sequence_manager.*?while True", True),
        ("task_queue.pop(0)", r"self\.task_queue\.pop\(0\)", False),
        ("feedback_timeout < 20", r"feedback_timeout < 20", False),
        ("is_executing 超时检查", r"if self\.is_executing:.*?自动跳过", True),
        ("handle_server_feedback 设置 is_executing=False", r"def handle_server_feedback.*?self\.is_executing = False", False),
        ("StateManager 防抖", r"class StateManager", False),
        ("state_analyzer 状态分析", r"async def state_analyzer", False),
        ("serial_loop 数据采集", r"async def serial_loop", False),
    ]
    
    results = []
    for check_name, pattern, is_warning in checks:
        if re.search(pattern, content, re.DOTALL | re.IGNORECASE):
            symbol = "✅" if not is_warning else "⚠️"
            print(f"{symbol} {check_name}")
            results.append((check_name, True))
        else:
            symbol = "❌" if not is_warning else "⚠️"
            print(f"{symbol} {check_name} - 未找到")
            results.append((check_name, False))
    
    print()
    
    # 统计
    success = sum(1 for _, passed in results if passed)
    total = len(results)
    
    if success == total:
        print(f"🎉 全部检查通过! ({success}/{total})")
        return True
    else:
        print(f"⚠️  部分检查未通过 ({success}/{total})")
        if total - success <= 2:
            print("   这可能不影响功能，但建议检查")
        return False

def check_syntax(filepath):
    """检查Python语法"""
    print("="*70)
    print("🐍 Python 语法检查")
    print("="*70)
    
    import py_compile
    try:
        py_compile.compile(filepath, doraise=True)
        print("✅ 语法正确")
        return True
    except py_compile.PyCompileError as e:
        print(f"❌ 语法错误: {e}")
        return False

def check_imports(filepath):
    """检查必要的导入"""
    print("\n" + "="*70)
    print("📦 必要导入检查")
    print("="*70)
    
    required_imports = [
        ("asyncio", "异步编程"),
        ("json", "JSON处理"),
        ("serial", "串口通信"),
        ("websockets", "WebSocket"),
    ]
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        all_ok = True
        for module, desc in required_imports:
            if re.search(rf"^import {module}|^from {module}", content, re.MULTILINE):
                print(f"✅ {module:20} - {desc}")
            else:
                print(f"⚠️  {module:20} - {desc} (未导入)")
                all_ok = False
        
        return all_ok
    except Exception as e:
        print(f"❌ 检查失败: {e}")
        return False

def analyze_sequence_manager(filepath):
    """深度分析 sequence_manager 函数"""
    print("\n" + "="*70)
    print("🔬 sequence_manager 深度分析")
    print("="*70)
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # 找到 sequence_manager 函数
        start_idx = None
        for i, line in enumerate(lines):
            if 'async def sequence_manager' in line:
                start_idx = i
                break
        
        if start_idx is None:
            print("❌ 未找到 sequence_manager 函数")
            return False
        
        # 找到函数结束（下一个 async def）
        end_idx = len(lines)
        for i in range(start_idx + 1, len(lines)):
            if re.match(r'\s{0,4}(async )?def ', lines[i]):
                end_idx = i
                break
        
        func_lines = lines[start_idx:end_idx]
        func_text = ''.join(func_lines)
        
        print(f"函数位置: 第 {start_idx+1} 行")
        print(f"函数长度: {end_idx - start_idx} 行")
        print()
        
        # 检查关键要素
        checks = [
            ("while True", "无限循环"),
            ("task_queue.pop", "任务弹出"),
            ("is_executing = True", "执行标记"),
            ("broadcast_data", "发送任务"),
            ("feedback_timeout", "超时计数"),
            ("feedback_timeout < 20", "10秒超时（20×0.5s）"),
            ("if self.is_executing", "超时检查"),
            ("print", "日志输出"),
        ]
        
        for keyword, desc in checks:
            if keyword in func_text:
                print(f"✅ 包含: {keyword:30} - {desc}")
            else:
                print(f"❌ 缺少: {keyword:30} - {desc}")
        
        # 检查循环结构
        if 'while True' in func_text and 'await asyncio.sleep' in func_text:
            print("\n✅ 循环结构正确（包含异步sleep）")
        else:
            print("\n❌ 循环结构不完整")
        
        return True
        
    except Exception as e:
        print(f"❌ 分析失败: {e}")
        return False

def main():
    if len(sys.argv) < 2:
        filepath = "main_new.py"
    else:
        filepath = sys.argv[1]
    
    print("\n")
    print("╔" + "="*68 + "╗")
    print("║" + " 🔧 系统状态检查工具 ".center(68) + "║")
    print("╚" + "="*68 + "╝")
    print()
    
    # 运行所有检查
    syntax_ok = check_syntax(filepath)
    imports_ok = check_imports(filepath)
    code_ok = check_file(filepath)
    seq_ok = analyze_sequence_manager(filepath)
    
    # 最终结果
    print("\n" + "="*70)
    print("📊 最终检查结果")
    print("="*70)
    
    results = [
        ("Python 语法检查", syntax_ok),
        ("必要导入检查", imports_ok),
        ("代码结构检查", code_ok),
        ("sequence_manager 分析", seq_ok),
    ]
    
    for name, passed in results:
        symbol = "✅" if passed else "❌"
        print(f"{symbol} {name:30} {'通过' if passed else '未通过'}")
    
    all_passed = all(passed for _, passed in results)
    
    print("\n" + "="*70)
    if all_passed:
        print("🎉 所有检查通过！系统已准备好运行")
        print()
        print("下一步: 运行以下命令")
        print("  python main_new.py realtime")
        print("="*70)
        return 0
    else:
        print("⚠️  部分检查未通过，请检查代码")
        print("="*70)
        return 1

if __name__ == "__main__":
    sys.exit(main())
