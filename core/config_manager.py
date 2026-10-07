# core/config_manager.py
import os
import json
import minecraft_launcher_lib
from constants import DEFAULT_JVM_ARGS


class ConfigManager:
    def __init__(self):
        # 1. Lấy thư mục mẹ của .minecraft tiêu chuẩn
        # Trên Windows: C:\Users\Tên_User\AppData\Roaming\.minecraft
        # Trên Linux: /home/tên_user/.minecraft
        standard_minecraft_dir = minecraft_launcher_lib.utils.get_minecraft_directory()
        system_appdata_dir = os.path.dirname(standard_minecraft_dir)

        # 2. Tạo một thư mục riêng cho Launcher của bạn nằm trong AppData
        # Bạn nên thêm dấu chấm "." ở đầu tên thư mục để nó tự ẩn đi trên Linux/macOS
        self.launcher_root = os.path.join(system_appdata_dir, ".kanako_launcher")
        
        # Đảm bảo thư mục launcher gốc này luôn tồn tại
        os.makedirs(self.launcher_root, exist_ok=True)

        # 3. Định nghĩa lại file config_file nằm trong thư mục AppData mới này
        self.config_file = os.path.join(self.launcher_root, "launcher_profiles_custom.json")

        # Lưu lại đường dẫn .minecraft gốc để dùng làm fallback nếu cần
        self.default_minecraft_dir = standard_minecraft_dir

        self.config = {}
        self.load_profiles()

    def _default_profile_data(self):
        return {
            "name":            "Default",
            "username":        "",
            "remember":        False,
            "version":         "1.20.1",
            # Points to %APPDATA%\.minecraft by default.
            # Once the user changes this in Edit Profile, the new path is
            # saved and becomes fully independent — no relation to AppData.
            "game_dir":        self.default_minecraft_dir,
            "jvm_args":        DEFAULT_JVM_ARGS,
            "java_path":       "",
            "java_manual":     False,
            # Absolute path to a custom background image for this profile
            # ("" = use the bundled banner.png). Only the PATH is stored here;
            # the image itself is read and sent to the UI on demand.
            "banner_path":     "",
            "allow_snapshots": False,
            "allow_beta":      False,
            "allow_alpha":     False,
        }

    def _default_config(self):
        prof = self._default_profile_data()
        prof["name"] = "Default"
        return {
            "current_profile": "Default",
            "profiles": {"Default": prof},
        }

    def load_profiles(self):
        # config_file sits in launcher_root, so dirname may be "".
        # Guard against that before calling makedirs.
        config_dir = os.path.dirname(self.config_file)
        if config_dir:
            os.makedirs(config_dir, exist_ok=True)

        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    self.config = json.load(f)
                # Back-fill any keys added in newer versions of the launcher
                defaults = self._default_profile_data()
                for prof in self.config.get("profiles", {}).values():
                    for key, val in defaults.items():
                        prof.setdefault(key, val)
                return
            except (json.JSONDecodeError, KeyError, TypeError):
                print("[Warning] Config file corrupted — resetting to default.")
        self.config = self._default_config()

    def save_profiles(self):
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
        except OSError as e:
            print(f"[Error] Could not save profiles: {e}")

    def get_current_profile_name(self):
        return self.config.get("current_profile", "Default")

    def set_current_profile_name(self, name):
        self.config["current_profile"] = name

    def get_profile(self, name):
        return self.config["profiles"].get(name)