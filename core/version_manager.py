# core/version_manager.py
import minecraft_launcher_lib
from constants import (
    VERSION_TYPE_RELEASE, VERSION_TYPE_SNAPSHOT,
    VERSION_TYPE_BETA, VERSION_TYPE_ALPHA
)

class VersionManager:
    def __init__(self):
        self.all_versions = self._fetch_all_versions()

    def _fetch_all_versions(self) -> dict[str, list[str]]:
        print("Fetching version list from Mojang...")
        result = {
            VERSION_TYPE_RELEASE:  [],
            VERSION_TYPE_SNAPSHOT: [],
            VERSION_TYPE_BETA:     [],
            VERSION_TYPE_ALPHA:    [],
        }
        try:
            for v in minecraft_launcher_lib.utils.get_version_list():
                vtype = v["type"]
                if vtype in result:
                    result[vtype].append(v["id"])
        except Exception:
            print("No network. Using fallback version list.")
            result[VERSION_TYPE_RELEASE] = ["1.21.1", "1.20.1", "1.19.4", "1.16.5", "1.12.2", "1.8.9", "1.7.10"]
        return result

    def build_display_list(self, prof_data: dict, local_versions: list[str]) -> list[dict]:
        releases  = self.all_versions[VERSION_TYPE_RELEASE]
        snapshots = self.all_versions[VERSION_TYPE_SNAPSHOT]    if prof_data.get("allow_snapshots")     else []
        betas     = self.all_versions[VERSION_TYPE_BETA]        if prof_data.get("allow_beta")          else []
        alphas    = self.all_versions[VERSION_TYPE_ALPHA]       if prof_data.get("allow_alpha")         else []

        all_official = set(releases) | set(snapshots) | set(betas) | set(alphas)
        mod_versions = [v for v in local_versions if v not in all_official]

        ordered_strings = snapshots + releases + betas + alphas + mod_versions

        # Tối ưu hóa tốc độ kiểm tra bằng cách chuyển sang set
        local_versions_set = set(local_versions) 
        
        # 2. Tiến hành chuyển đổi từ list[str] sang list[dict] cho Web UI nhận diện
        final_list = []
        for vid in ordered_strings:
            # Nếu tên phiên bản nằm trong thư mục local thì is_downloaded = True
            is_downloaded = vid in local_versions_set
            
            # Phân loại: Nếu nằm trong mod_versions thì gán là 'modded', ngược lại là 'vanilla'
            version_type = "modded" if vid in mod_versions else "vanilla"
            
            final_list.append({
                "id": vid,
                "is_downloaded": is_downloaded,
                "type": version_type
            })

        return final_list

    def get_version_types_map(self):
        type_of = {}
        for vtype, vlist in self.all_versions.items():
            for vid in vlist:
                type_of[vid] = vtype
        return type_of