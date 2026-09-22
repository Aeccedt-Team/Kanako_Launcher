# ui/bridge.py
import os
import threading
import minecraft_launcher_lib
import shutil
import json
import webview
import subprocess
import platform

from core.config_manager import ConfigManager
from core.game_runner import run_launch_process


class LauncherBridgeAPI:
    def __init__(self):
        self._config_manager     = ConfigManager()
        self._version_manager    = None
        self._window             = None
        self._versions_ready     = False
        self._sanitized_versions = set()

        threading.Thread(target=self._async_load_versions, daemon=True).start()

    # ------------------------------------------------------------------
    # Internal helper
    # ------------------------------------------------------------------

    def _get_local_version_ids(self, minecraft_dir: str) -> list[str]:
        """
        Return version IDs already downloaded inside a specific .minecraft dir.
        Each profile has its own versions/ folder, so we scan the dir that
        belongs to the currently active profile.
        """
        try:
            vers = minecraft_launcher_lib.utils.get_installed_versions(minecraft_dir)
            return [v["id"] for v in vers]
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Background version fetch
    # ------------------------------------------------------------------

    def _async_load_versions(self):
        try:
            from core.version_manager import VersionManager
            self._version_manager = VersionManager()
            self._versions_ready  = True
            print("[Python Backend] Version list loaded successfully.")

            if self._window:
                prof_name    = self._config_manager.get_current_profile_name()
                prof_data    = self._config_manager.get_profile(prof_name)
                minecraft_dir = prof_data["game_dir"]

                version_list = self._version_manager.build_display_list(
                    prof_data, self._get_local_version_ids(minecraft_dir)
                )
                version_list_json = json.dumps(version_list)
                safe_js = f"""
                if (typeof onVersionsLoaded === 'function') {{
                    onVersionsLoaded({version_list_json}, '{prof_data.get('version', '')}');
                }}
                """
                self._window.evaluate_js(safe_js)

        except Exception as e:
            print(f"[Python Error] Failed to load versions in background: {e}")

    # ------------------------------------------------------------------
    # Public API — called from JavaScript
    # ------------------------------------------------------------------

    def get_initial_data(self):
        current_prof  = self._config_manager.get_current_profile_name()
        profiles_list = list(self._config_manager.config.get("profiles", {}).keys())
        profile_data  = self._config_manager.get_profile(current_prof)
        minecraft_dir  = profile_data["game_dir"]

        versions_ready = (
            self._version_manager is not None
            and len(self._version_manager.all_versions.get("release", [])) > 0
        )
        version_list = []
        if versions_ready:
            version_list = self._version_manager.build_display_list(
                profile_data, self._get_local_version_ids(minecraft_dir)
            )

        return {
            "current_profile": current_prof,
            "profiles_list":   profiles_list,
            "profile_data":    profile_data,
            "versions_ready":  versions_ready,
            "versions":        version_list,
        }

    def switch_profile(self, profile_name):
        try:
            self._config_manager.set_current_profile_name(profile_name)
            self._config_manager.save_profiles()

            profile_data  = self._config_manager.get_profile(profile_name)
            minecraft_dir  = profile_data["game_dir"]

            version_list = self._version_manager.build_display_list(
                profile_data, self._get_local_version_ids(minecraft_dir)
            ) if self._version_manager else []

            return {
                "profile_data":   profile_data,
                "versions_ready": self._version_manager is not None,
                "versions":       version_list,
            }
        except Exception as e:
            print(f"[Bridge Error] switch_profile failed: {e}")
            return None

    def launch_game(self, username, version, remember, keep_launcher_open=False):
        try:
            current_prof_name = self._config_manager.get_current_profile_name()
            prof_data         = self._config_manager.get_profile(current_prof_name)

            prof_data["version"] = version
            if remember:
                prof_data["username"] = username
                prof_data["remember"] = True
            else:
                prof_data["username"] = ""
                prof_data["remember"] = False

            self._config_manager.save_profiles()

            def progress_cb(pct):
                if self._window:
                    self._window.evaluate_js(f"window.updateProgress({int(pct * 100)})")

            def btn_cb(state, text):
                pass

            # --- THAY ĐỔI: Chuyển từ destroy() sang hide() để chạy ngầm ---
            def success_cb():
                if self._window:
                    self._window.evaluate_js("window.launchSuccess()")
                if not keep_launcher_open:
                    print("Game started — hiding launcher window.")
                    if self._window:
                        self._window.hide()  # Ẩn tạm thời thay vì xóa sổ window
                else:
                    print("Game started — keeping launcher alive.")

            def status_cb(msg, color_name_or_hex):
                colour_map = {"red": "#E74C3C", "green": "#2ECC71", "orange": "#E67E22"}
                hex_color  = colour_map.get(color_name_or_hex, color_name_or_hex)
                safe_msg   = json.dumps(msg)
                if self._window:
                    self._window.evaluate_js(
                        f"window.updateStatus({safe_msg}, '{hex_color}')"
                    )

            log_state = {"last_level": "info"}

            def game_log_cb(line):
                stripped = line.strip()
                if not stripped:
                    return

                is_stack = (
                    line.startswith("\tat ")
                    or line.lstrip().startswith("at ")
                    or stripped.startswith("Caused by:")
                    or stripped.startswith("...")
                )

                if "/ERROR]" in stripped or "/FATAL]" in stripped or "Exception in thread" in stripped:
                    level = "error"
                elif "/WARN]" in stripped:
                    level = "warn"
                elif "/DEBUG]" in stripped:
                    level = "debug"
                elif is_stack:
                    level = "error"
                elif log_state["last_level"] == "error" and not stripped.startswith("["):
                    level = "error"
                else:
                    level = "info"

                log_state["last_level"] = level
                display_msg = (
                    line if (is_stack or (level == "error" and not stripped.startswith("[")))
                    else f"[GAME] {line}"
                )
                self.console_log(display_msg, level)

            # --- BỔ SUNG: Callback hiển thị popup mod bị thiếu (thay cho tkinter) ---
            def missing_mods_cb(missing_dependencies, crash_summary, crash_report_path):
                if not self._window:
                    return
                payload = {
                    "mods": missing_dependencies,          # [] if nothing was parsed
                    "summary": crash_summary,               # tail of log, only if mods == []
                    "crashReportPath": crash_report_path,    # None if no file was found
                }
                safe_payload = json.dumps(payload)
                # Bring the launcher window back to front so the popup is visible
                # even if it was hidden after a successful-looking launch.
                self._window.show()
                self._window.evaluate_js(f"window.showMissingMods({safe_payload})")

            # --- BỔ SUNG: Callback xử lý khi tiến trình game kết thúc ---
            def game_exit_cb(return_code):
                print(f"[Launcher Backend] Game exited with code: {return_code}")
                
                if not keep_launcher_open:
                    if return_code != 0:
                        # TRƯỜNG HỢP 1: Game bị crash đột ngột -> Hiện lại launcher và bật tab console
                        if self._window:
                            self._window.show()
                            self._window.evaluate_js("switchTab('console');")
                            self.console_log(f"[LAUNCHER] Game đã bị crash đột ngột với mã lỗi (Exit Code): {return_code}.", "error")
                            self.console_log("[LAUNCHER] Tự động hiển thị tab Console để kiểm tra nhật ký lỗi.", "warn")
                    else:
                        # TRƯỜNG HỢP 2: Người chơi thoát game bình thường -> Đóng hẳn launcher
                        print("[Launcher Backend] Game exited normally. Closing launcher completely.")
                        if self._window:
                            self._window.destroy()
                else:
                    # Nếu người chơi có tick chọn Keep launcher open thì launcher vốn đang mở sẵn, chỉ cần bắn thông báo kết quả vào log
                    if return_code != 0:
                        self.console_log(f"[LAUNCHER] Game bị crash (Exit Code: {return_code}).", "error")
                    else:
                        self.console_log(f"[LAUNCHER] Game đã đóng bình thường.", "info")

            threading.Thread(
                target=run_launch_process,
                args=(
                    username, prof_data,
                    status_cb, progress_cb, btn_cb, success_cb,
                    self._sanitized_versions,
                    game_log_cb,
                    None,
                    game_exit_cb,     # exit_cb
                    missing_mods_cb,  # <-- popup báo mod thiếu, thay cho tkinter messagebox
                ),
                daemon=True,
            ).start()

        except Exception as e:
            print(f"[Bridge Error] Failed to start launch thread: {e}")

    def get_profile_details(self, profile_name):
        return self._config_manager.get_profile(profile_name)

    def web_browse_directory(self):
        try:
            result = self._window.create_file_dialog(webview.FOLDER_DIALOG)
            if result:
                return os.path.normpath(result[0])
            return ""
        except Exception as e:
            print(f"[Bridge Error] web_browse_directory failed: {e}")
            return ""

    def web_browse_file(self):
        try:
            result = self._window.create_file_dialog(
                webview.OPEN_DIALOG,
                file_types=("Java executable (*.exe)", "All files (*.*)"),
            )
            if result:
                return os.path.normpath(result[0])
            return ""
        except Exception as e:
            print(f"[Bridge Error] web_browse_file failed: {e}")
            return ""

    def web_open_folder(self, path):
        if not path:
            return
        os.makedirs(path, exist_ok=True)
        if platform.system() == "Windows":
            os.startfile(path)
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])

    def web_save_profile(self, old_id, new_name, game_dir, jvm_args,
                         java_manual, java_path,
                         allow_snapshots, allow_beta, allow_alpha):
        try:
            if not new_name:
                new_name = old_id

            prof = self._config_manager.config["profiles"][old_id]
            prof["game_dir"]        = game_dir
            prof["jvm_args"]        = jvm_args
            prof["java_manual"]     = java_manual
            prof["java_path"]       = java_path if java_manual else ""
            prof["allow_snapshots"] = allow_snapshots
            prof["allow_beta"]      = allow_beta
            prof["allow_alpha"]     = allow_alpha

            if new_name != old_id:
                base, counter = new_name, 1
                while new_name in self._config_manager.config["profiles"]:
                    new_name = f"{base}_{counter}"
                    counter += 1
                self._config_manager.config["profiles"][new_name] = \
                    self._config_manager.config["profiles"].pop(old_id)
                self._config_manager.config["profiles"][new_name]["name"] = new_name
                self._config_manager.set_current_profile_name(new_name)
            else:
                prof["name"] = old_id

            self._config_manager.save_profiles()
            return {"success": True}
        except Exception as e:
            print(f"[Bridge Error] web_save_profile failed: {e}")
            raise

    def web_create_profile(self):
        """
        Create a new profile.  Its game_dir defaults to a NEW sub-folder
        inside the launcher directory so it starts life completely independent
        of AppData — the user can later point it anywhere via Edit Profile.
        """
        try:
            base_name = "New Profile"
            new_name  = base_name
            counter   = 1
            while new_name in self._config_manager.config["profiles"]:
                new_name = f"{base_name}_{counter}"
                counter += 1

            default_data = self._config_manager._default_profile_data()
            default_data["name"] = new_name

            # New profiles default to a dedicated folder next to the launcher,
            # NOT to AppData.  Only the built-in "Default" profile starts at
            # AppData so existing Mojang-launcher users keep their data.
            launcher_root = os.getcwd()
            default_data["game_dir"] = os.path.join(
                launcher_root, "instances", new_name
            )

            self._config_manager.config["profiles"][new_name] = default_data
            self._config_manager.set_current_profile_name(new_name)
            self._config_manager.save_profiles()
            return new_name
        except Exception as e:
            print(f"[Bridge Error] web_create_profile failed: {e}")
            raise

    def web_remove_profile(self, profile_name, delete_files):
        try:
            profiles = self._config_manager.config.get("profiles", {})
            if profile_name not in profiles:
                return {"success": False, "error": "Profile does not exist"}

            game_dir = profiles[profile_name].get("game_dir", "")
            del self._config_manager.config["profiles"][profile_name]

            if self._config_manager.get_current_profile_name() == profile_name:
                remaining = list(self._config_manager.config["profiles"].keys())
                if remaining:
                    self._config_manager.set_current_profile_name(remaining[0])
                else:
                    default_prof = self._config_manager._default_profile_data()
                    default_prof["name"] = "Default"
                    self._config_manager.config["profiles"]["Default"] = default_prof
                    self._config_manager.set_current_profile_name("Default")

            self._config_manager.save_profiles()

            if delete_files and game_dir and os.path.exists(game_dir):
                # Safety guard: refuse to delete very short paths
                if len(os.path.abspath(game_dir)) > 10:
                    try:
                        shutil.rmtree(game_dir, ignore_errors=True)
                        print(f"[Remove Profile] Deleted: {game_dir}")
                    except Exception as folder_err:
                        print(f"[Warning] Could not fully delete game folder: {folder_err}")

            return {"success": True}
        except Exception as e:
            print(f"[Bridge Error] web_remove_profile failed: {e}")
            raise

    def console_log(self, message: str, level: str = "info"):
        if not self._window:
            return
        safe_levels = {"info", "warn", "error", "debug"}
        lvl      = level.lower() if level.lower() in safe_levels else "info"
        safe_msg = json.dumps(str(message))
        safe_lvl = json.dumps(lvl)
        try:
            self._window.evaluate_js(f"appendLog({safe_msg}, {safe_lvl})")
        except Exception:
            pass