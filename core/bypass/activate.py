# core/bypass/activate.py
import os
import sys

def activate_bypass(mc_command: list):
    try:
        # 1. Ép tham số userType về legacy và sửa accessToken thành chuỗi giả JWT
        dummy_jwt = (
            "eyJhbGciOiJSUzI1NiJ9."
            "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ."
            "XfG_p8_S472NlzvO8_Bv3M7X4B4J9w8mH7W2l_wO6P4X9Y8zK7gV9b6M2v_X4N7_b8v9M_wO6X4"
        )
        
        for idx, arg in enumerate(mc_command):
            if arg == "--userType" and idx + 1 < len(mc_command):
                mc_command[idx + 1] = "legacy"
            if arg == "--accessToken" and idx + 1 < len(mc_command):
                mc_command[idx + 1] = dummy_jwt

        # 2. Xử lý đường dẫn linh hoạt giữa môi trường .PY và .EXE
        if getattr(sys, 'frozen', False):
            # Khi chạy từ file .EXE (PyInstaller xả vào sys._MEIPASS)
            bypass_dir = os.path.join(sys._MEIPASS, "core", "bypass")
        else:
            # Khi chạy file .PY thông thường (định vị ngay tại thư mục chứa activate.py)
            bypass_dir = os.path.dirname(os.path.abspath(__file__))

        agent_path = os.path.join(bypass_dir, "multiplayer_patch.jar")
        lib_path = os.path.join(bypass_dir, "javassist.jar")

        # 3. Tiến hành nạp chuỗi kép vào JVM
        if os.path.exists(agent_path) and os.path.exists(lib_path):
            mc_command.insert(1, f"-Xbootclasspath/a:{lib_path}")
            mc_command.insert(2, f"-javaagent:{agent_path}")
            print(f"[Launcher Agent] Armed successfully! Path: {agent_path}")
        else:
            print(f"[Launcher Agent] WARNING: Missing agent or javassist JAR files! Checked: {agent_path}")
                
    except Exception as e:
        print(f"[Launcher Agent] Error injecting agent setup: {e}")