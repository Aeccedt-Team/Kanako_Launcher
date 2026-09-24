# core/game_runner.py
import os
import re
import time
import shutil
import uuid
import json
import platform
import subprocess
import traceback
import minecraft_launcher_lib
from constants import JAVA_PATHS
from core.patches import _normalize_arg_item
from core.bypass.activate import activate_bypass

# ──────────────────────────────────────────────────────────────────────────
# Missing-mod detection
#
# NeoForge (1.20.2+) no longer reliably prints the old FML-style
#     Mod ID: 'x', Requested by: 'y', Expected range: 'z', Actual version: '[MISSING]'
# line to stdout the way old Forge did. The dependency-loading failure is
# now raised as a ModLoadingCrashException and rendered as a structured
# crash report on disk (<minecraft_dir>/crash-reports/crash-*.txt), and/or
# on the in-game crash GUI — not always as one clean parseable stdout line.
#
# So we do two things:
#   1. Keep scanning stdout live for the old-style line (works on old Forge,
#      and on some NeoForge builds that still emit it).
#   2. As a fallback, if the process exits non-zero and nothing matched in
#      stdout, read the newest crash report file written during this run
#      and re-run the patterns against its full text, which is far more
#      complete than stdout.
#
# IMPORTANT: I have not verified the *exact* current NeoForge 1.21.1 wording
# against a real crash report from your setup. The patterns below cover the
# old Forge format plus a generic "X requires Y" fallback phrasing. If a
# missing-mod crash still doesn't produce a popup, paste me the actual
# crash-reports/*.txt (or the console text) from that run and I'll tighten
# these patterns to match your real output exactly.
# ──────────────────────────────────────────────────────────────────────────

DEP_PATTERNS = [
    # Old Forge / FML dependency-report line
    re.compile(
        r"Mod ID:\s*'([^']*)',\s*Requested by:\s*'([^']*)',\s*Expected range:\s*'([^']*)',"
        r"\s*Actual version:\s*'\[MISSING\]'"
    ),
    # Generic "modid requires otherid [range]" phrasing seen in newer crash
    # report "Details" sections and mod-mismatch screens.
    re.compile(
        r"[\"']?([\w\-.]+)[\"']?\s+requires\s+[\"']?([\w\-.]+)[\"']?"
        r"(?:\s*(@?\s*[\[\(][^\]\)]*[\]\)]))?"
        r"\s*(?:to be present|to run|but it'?s? missing|which is missing|or above)",
        re.IGNORECASE,
    ),
]


def _find_latest_crash_report(minecraft_dir: str, after_ts: float):
    """Return the newest crash-report .txt written after after_ts, or None."""
    crash_dir = os.path.join(minecraft_dir, "crash-reports")
    if not os.path.isdir(crash_dir):
        return None
    candidates = []
    for fname in os.listdir(crash_dir):
        if not fname.lower().endswith(".txt"):
            continue
        fpath = os.path.join(crash_dir, fname)
        try:
            if os.path.getmtime(fpath) >= after_ts - 2:  # small buffer
                candidates.append(fpath)
        except OSError:
            continue
    if not candidates:
        return None
    candidates.sort(key=os.path.getmtime, reverse=True)
    return candidates[0]


def _extract_missing_mods(text: str):
    """Run all DEP_PATTERNS against text, dedupe, return list of dicts."""
    found = []
    seen = set()
    for pattern in DEP_PATTERNS:
        for match in pattern.finditer(text):
            mod_id = match.group(1) or ""
            requested_by = match.group(2) or ""
            expected_range = ""
            if match.lastindex and match.lastindex >= 3:
                expected_range = match.group(3) or ""
            key = (mod_id.lower(), requested_by.lower())
            if key in seen or not mod_id:
                continue
            seen.add(key)
            found.append({
                "mod_id": mod_id,
                "requested_by": requested_by,
                "expected_range": expected_range,
            })
    return found

def java_major_for_version(version_str: str) -> int:
    """
    Map a Minecraft version string to the Java major version it requires.

    1.0 – 1.16.5  → Java 8
    1.17 – 1.20.4 → Java 17
    1.20.5+       → Java 21
    """
    try:
        match = re.search(r'\b1\.(\d+)(?:\.(\d+))?\b', version_str)
        if match:
            minor = int(match.group(1))
            patch = int(match.group(2)) if match.group(2) else 0
            v = (1, minor, patch)
            if v <= (1, 16, 5):
                return 8
            elif v < (1, 20, 5):
                return 17
            else:
                return 21
    except Exception:
        pass
    return 21


def _release_file_major_version(java_home: str):
    """
    Read JAVA_HOME/release (the standard JDK metadata file, present on
    JDK 9+ and most modern JDK 8 builds) for an exact major version.
    Far more reliable than guessing from the folder name.
    """
    release_path = os.path.join(java_home, "release")
    if not os.path.isfile(release_path):
        return None
    try:
        with open(release_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.startswith("JAVA_VERSION="):
                    ver = line.split("=", 1)[1].strip().strip('"')
                    # Legacy scheme "1.8.0_501" -> 8 ; modern scheme "17.0.9" -> 17
                    m = re.match(r"1\.(\d+)", ver) or re.match(r"(\d+)", ver)
                    if m:
                        return int(m.group(1))
    except OSError:
        pass
    return None


def _major_from_dirname(name: str):
    """Best-effort fallback: guess the major version from the folder name
    itself, for the rare install with no 'release' file (e.g. bare JRE 8)."""
    lname = name.lower()
    m = re.search(r"1\.(\d+)", lname)                               # jre1.8.0_503, jdk-1.8
    if m:
        return int(m.group(1))
    m = re.search(r"(?:jdk|jre|java)[\-_]?(\d{1,2})\b", lname)      # jdk-17, jdk21, corretto-21
    if m:
        return int(m.group(1))
    return None


def _java_executable_in(java_home: str):
    for exe in ("javaw.exe", "java.exe", "java"):
        candidate = os.path.join(java_home, "bin", exe)
        if os.path.isfile(candidate):
            return candidate
    return None


def _common_java_install_roots() -> list[str]:
    """Every place a Java install commonly lives, per OS/vendor."""
    system = platform.system()
    roots = []
    if system == "Windows":
        roots += [
            r"C:\Program Files\Java",
            r"C:\Program Files (x86)\Java",
            r"C:\Program Files\Eclipse Adoptium",
            r"C:\Program Files\Zulu",
            r"C:\Program Files\Amazon Corretto",
            r"C:\Program Files\Microsoft",
            r"C:\Program Files\BellSoft",
        ]
    elif system == "Darwin":
        roots.append("/Library/Java/JavaVirtualMachines")
    else:  # Linux and other Unix-likes
        roots += ["/usr/lib/jvm", "/opt/java", os.path.expanduser("~/.sdkman/candidates/java")]
    return [r for r in roots if os.path.isdir(r)]


_JAVA_SCAN_CACHE = None

def scan_installed_javas(force_rescan: bool = False) -> dict:
    """
    Scan common install locations on this machine for every Java found and
    return {major_version: best_executable_path}. Cached after the first
    call in this process (cheap directory listing, but no need to repeat
    it on every launch) -- pass force_rescan=True to refresh.
    """
    global _JAVA_SCAN_CACHE
    if _JAVA_SCAN_CACHE is not None and not force_rescan:
        return _JAVA_SCAN_CACHE

    found = {}  # major -> (dirname, exe_path), so newer-looking names win ties
    for root in _common_java_install_roots():
        try:
            entries = os.listdir(root)
        except OSError:
            continue
        for entry in entries:
            java_home = os.path.join(root, entry)
            if platform.system() == "Darwin":
                java_home = os.path.join(java_home, "Contents", "Home")
            if not os.path.isdir(java_home):
                continue

            major = _release_file_major_version(java_home) or _major_from_dirname(entry)
            if major is None:
                continue
            exe = _java_executable_in(java_home)
            if not exe:
                continue

            if major not in found or entry > found[major][0]:
                found[major] = (entry, exe)

    _JAVA_SCAN_CACHE = {major: exe for major, (_, exe) in found.items()}
    if _JAVA_SCAN_CACHE:
        print(f"[Java Detect] Found installed Java versions: {_JAVA_SCAN_CACHE}")
    return _JAVA_SCAN_CACHE


def _prefer_windowless_java(java_path: str) -> str:
    """
    On Windows, java.exe is a console-subsystem binary -- launching it
    makes Windows auto-allocate a visible console window for the game
    process (and our SW_SHOWNORMAL flag below, needed to make LWJGL 2's
    window visible on 1.12.2 and older, forces that console to show too).
    javaw.exe is the exact same JVM built as a GUI-subsystem binary, so no
    console is ever created for it. If java_path resolved to java.exe and
    a javaw.exe sits right next to it (true for virtually every real
    JDK/JRE), silently prefer that instead -- same JVM, no popup console.
    Applied once here, after get_suitable_java(), so it covers every
    detection path (manual, bundled runtime, local scan, hardcoded,
    system PATH) uniformly instead of relying on each one picking right.
    """
    if platform.system() != "Windows" or not java_path:
        return java_path
    if os.path.basename(java_path).lower() == "java.exe":
        candidate = os.path.join(os.path.dirname(java_path), "javaw.exe")
        if os.path.isfile(candidate):
            return candidate
    return java_path


def _required_java_component(version_str: str, minecraft_dir: str, _seen: set = None) -> str:
    """
    Read this version's manifest for the exact runtime component (e.g.
    'jre-legacy', 'java-runtime-gamma') it needs.

    Modded loader version jsons (Forge, NeoForge, Fabric, Quilt) almost
    never carry their own 'javaVersion' -- they use 'inheritsFrom' to
    inherit it (and most other metadata) from the vanilla parent version.
    So if this version's own json doesn't specify one, walk up the
    inheritance chain to the parent that does, instead of assuming Java 8
    ('jre-legacy'). Only truly falls back to 'jre-legacy' if the json is
    missing entirely or the chain never specifies a component -- which is
    correct for genuinely old, pre-Java-version-field versions.
    """
    _seen = _seen or set()
    if version_str in _seen:          # guard against a circular inheritsFrom chain
        return "jre-legacy"
    _seen.add(version_str)

    try:
        json_path = os.path.join(minecraft_dir, "versions", version_str, f"{version_str}.json")
        if not os.path.isfile(json_path):
            return "jre-legacy"

        with open(json_path, "r", encoding="utf-8") as f:
            vdata = json.load(f)

        component = vdata.get("javaVersion", {}).get("component")
        if component:
            return component

        parent = vdata.get("inheritsFrom")
        if parent:
            return _required_java_component(parent, minecraft_dir, _seen)
    except Exception:
        pass
    return "jre-legacy"


def get_suitable_java(version_str: str, prof_data: dict) -> str:
    """
    Return the Java executable to use for this version.

    Priority:
    1. Manual override from profile settings.
    2. The runtime Mojang's own version manifest says THIS EXACT version
       needs (e.g. "jre-legacy" for old Forge, "java-runtime-gamma" for
       modern releases) — already auto-downloaded by
       install_minecraft_version() into <minecraft_dir>/runtime/.
       This must run AFTER install_minecraft_version() has been called,
       so the version json and runtime files are guaranteed to exist.
       This works for every version, including Java-8-era ones — Mojang
       has shipped a matching bundled runtime for those too since the
       Electron launcher, it was just never being looked at here before.
    3. A Java matching the required major version, auto-discovered by
       scanning common install locations on THIS machine (see
       scan_installed_javas()) -- adapts to whatever the user actually
       has installed and wherever it lives, instead of a fixed path.
    4. Hardcoded path from constants.JAVA_PATHS, as an explicit pin/
       override for a specific known-good install, if you want one.
    5. System 'java' on PATH (logged loudly — this may be the wrong
       major version and silently produces crashes like Forge 1.12.2's
       ClassCastException on Java 9+).
    """
    # 1. Manual override
    if prof_data.get("java_manual") and prof_data.get("java_path"):
        manual = prof_data["java_path"].strip()
        if manual:
            return manual

    minecraft_dir = prof_data.get("game_dir", "")

    # 2. Bundled runtime matching what this version's own manifest requires.
    if minecraft_dir:
        try:
            component = _required_java_component(version_str, minecraft_dir)
            exe = minecraft_launcher_lib.runtime.get_executable_path(component, minecraft_dir)
            if exe and os.path.isfile(exe):
                return exe
            print(f"[Java Detect] Bundled runtime '{component}' not found on disk for {version_str} "
                  f"(get_executable_path returned {exe!r}).")
        except Exception as e:
            print(f"[Java Detect] Bundled runtime lookup failed for {version_str}: {e}")

    java_major = java_major_for_version(version_str)

    # 3. Auto-scan common install locations on this machine for a Java
    #    matching the exact major version needed.
    scanned = scan_installed_javas().get(java_major)
    if scanned and os.path.isfile(scanned):
        return scanned

    # 4. Hardcoded path -- fallback / explicit override for a specific
    #    known-good install (edit constants.JAVA_PATHS if this doesn't match
    #    your machine).
    hardcoded = JAVA_PATHS.get(java_major, JAVA_PATHS[21])
    if os.path.exists(hardcoded):
        return hardcoded

    # 5. System java -- last resort, may be the wrong major version.
    fallback = shutil.which("java")
    if fallback:
        print(f"[Java Detect] WARNING: no bundled or hardcoded Java {java_major} found for "
              f"{version_str} -- falling back to system PATH java, which may be the wrong version.")
        return fallback
    return hardcoded


def _os_runtime_folder() -> str:
    """Return the OS subfolder name used by Mojang's runtime downloads."""
    system = platform.system()
    machine = platform.machine().lower()
    if system == "Windows":
        return "windows-arm64" if "arm" in machine or "aarch64" in machine else "windows-x64"
    if system == "Darwin":
        return "mac-os-arm64" if "arm" in machine or "aarch64" in machine else "mac-os"
    return "linux"


def sanitize_version_json(version: str, minecraft_dir: str):
    """Scan and fix mod-loader argument quirks inside a .minecraft directory."""
    json_path = os.path.join(minecraft_dir, "versions", version, f"{version}.json")
    if not os.path.exists(json_path):
        return
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        modified = False
        if "arguments" in data:
            for arg_type in ("jvm", "game"):
                args_list = data["arguments"].get(arg_type)
                if not isinstance(args_list, list):
                    continue
                cleaned = [_normalize_arg_item(i) for i in args_list]
                if any(c != o for c, o in zip(cleaned, args_list)):
                    data["arguments"][arg_type] = cleaned
                    modified = True

        if modified:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"[JSON Scan] Error: {e}")


def _bootstrap_minecraft_dir(minecraft_dir: str, current_version: str = "1.20.1"):
    """
    Pre-create the sub-folders and launcher_profiles.json Minecraft expects.
    """
    subdirs = [
        "saves", "resourcepacks", "shaderpacks",
        "mods", "config", "screenshots", "logs", "crash-reports",
    ]
    for sub in subdirs:
        os.makedirs(os.path.join(minecraft_dir, sub), exist_ok=True)

    profiles_path = os.path.join(minecraft_dir, "launcher_profiles.json")
    if not os.path.exists(profiles_path):
        dummy_profiles = {
            "profiles": {
                "default-profile": {
                    "name": "Default",
                    "type": "custom",
                    "lastVersionId": current_version,
                }
            },
            "settings": {"crashAssistance": True},
            "version": 3,
        }
        try:
            with open(profiles_path, "w", encoding="utf-8") as f:
                json.dump(dummy_profiles, f, indent=4, ensure_ascii=False)
            print(f"[Bootstrap] Created dummy launcher_profiles.json at {profiles_path}")
        except Exception as e:
            print(f"[Bootstrap] Error creating launcher_profiles.json: {e}")



def run_launch_process(username: str, current_prof: dict,
                       status_cb, progress_cb, btn_cb, success_cb,
                       sanitized_versions: set, log_cb=None, post_install_cb=None, exit_cb=None,
                       missing_mods_cb=None):
    """
    Launch Minecraft in fully self-contained, per-profile mode.

    Architecture
    ────────────
    Each profile owns one directory that acts as a complete, independent
    .minecraft folder — it holds versions, assets, libraries, saves, mods,
    resourcepacks, and options.txt all in one place.

    profile["game_dir"]  IS  the .minecraft dir for that profile.
    It is passed as BOTH:
        • the minecraft_dir argument to install_minecraft_version()
          → versions/assets/libraries are downloaded there
        • the minecraft_dir argument to get_minecraft_command()
          → the JVM classpath resolves from there
        • the "gameDirectory" option
          → --gameDir points there and all runtime writes land there

    This means every profile is 100 % self-sufficient and completely
    independent of every other profile and of %APPDATA%\\.minecraft.

    Native library handling
    ───────────────────────
    minecraft_launcher_lib already handles natives correctly for all versions:

    • Legacy (≤ 1.18): install_minecraft_version() extracts DLLs into
      <minecraft_dir>/versions/<ver>/natives/ and get_minecraft_command()
      emits -Djava.library.path pointing there.

    • Modern (1.19+): native JARs sit on the -cp classpath. LWJGL 3 reads
      -Dorg.lwjgl.system.SharedLibraryExtractPath (emitted by the library)
      and self-extracts DLLs at runtime — no folder extraction required.

    We must NOT inject extra -Djava.library.path / -Dorg.lwjgl.librarypath
    arguments, because that overrides what the library already set up and
    points LWJGL at an empty directory → "Failed to locate library: lwjgl.dll".
    """
    
    version       = current_prof["version"]
    minecraft_dir = current_prof["game_dir"]

    os.makedirs(minecraft_dir, exist_ok=True)
    _bootstrap_minecraft_dir(minecraft_dir, version)

    # ──[ ĐOẠN SỬA ĐỔI TÀI KHOẢN OFFLINE CHUẨN ]──────────────────────────────
    import hashlib

    # 1. Tạo UUID chuẩn offline theo thuật toán của Minecraft
    offline_player_str = f"OfflinePlayer:{username}"
    hash_bytes = hashlib.md5(offline_player_str.encode('utf-8')).digest()
    hash_list = list(hash_bytes)
    hash_list[6] = (hash_list[6] & 0x0f) | 0x30  # Set version 3
    hash_list[8] = (hash_list[8] & 0x3f) | 0x80  # Set variant
    player_uuid = str(uuid.UUID(bytes=bytes(hash_list)))

    options = {
        "username":       username,
        "uuid":           player_uuid,
        "token":          player_uuid, # Đổi thành chuỗi 32 số 0 thuần túy
        "userType":       "legacy",    
        # Do NOT pass jvmArguments here — the library would embed them inside
        # the generated command between the fixed JVM flags it owns
        # (e.g. -Djava.library.path, -Dorg.lwjgl.system.SharedLibraryExtractPath).
        # We insert user args manually at position 1 below, which is safe
        # because position 0 is always the java executable.        
        # executablePath is filled in below, once install_minecraft_version()
        # has actually downloaded the version json and its matching bundled
        # runtime -- get_suitable_java() needs those to exist on disk.
        "executablePath": None,
        "gameDirectory":  minecraft_dir,
    }

    status_cb(f"Checking/downloading {version}...", "orange")

    current_max = [0]

    def set_status(text):
        status_cb(text, "orange")

    def set_progress(value):
        if current_max[0] > 0:
            pct = max(0.0, min(1.0, value / current_max[0]))
            progress_cb(pct)

    def set_max(value):
        current_max[0] = value

    launcher_callback = {
        "setStatus":   set_status,
        "setProgress": set_progress,
        "setMax":      set_max,
    }

    # Download/verify versions, assets, libraries (and natives for legacy) into
    # this profile's own directory.
    try:
        minecraft_launcher_lib.install.install_minecraft_version(
            version, minecraft_dir, callback=launcher_callback
        )
        if post_install_cb:
            post_install_cb(minecraft_dir)
    except Exception as e:
        print(f"[Install Error] {e}")

    # Explicitly make sure this version's required Java runtime is present.
    # install_minecraft_version() is documented to handle this itself, but
    # we don't rely on that alone -- if it's missing (partial install,
    # a version json with no javaVersion field, a previous run that
    # predates this logic, etc.) get_suitable_java() below would otherwise
    # silently fall through to whatever Java happens to be on the system,
    # which can be the wrong major version.
    try:
        component = _required_java_component(version, minecraft_dir)
        if not minecraft_launcher_lib.runtime.get_executable_path(component, minecraft_dir):
            status_cb(f"Fetching Java runtime ({component})...", "orange")
            minecraft_launcher_lib.runtime.install_jvm_runtime(
                component, minecraft_dir, callback=launcher_callback
            )
    except Exception as e:
        print(f"[Java Detect] Could not ensure bundled runtime is installed: {e}")

    progress_cb(1.0)

    # Fix mod-loader JSON quirks (e.g. Forge using 'values' instead of 'value')
    if version not in sanitized_versions:
        sanitize_version_json(version, minecraft_dir)
        sanitized_versions.add(version)

    # Now that install_minecraft_version() has downloaded the version json
    # and its matching bundled runtime, we can reliably detect which Java
    # executable this exact version needs.
    java_path = get_suitable_java(version, current_prof)
    java_path = _prefer_windowless_java(java_path)
    options["executablePath"] = java_path
    # Surface this in the console tab (not just the terminal) so a wrong
    # pick -- e.g. an old Java version on a modern Minecraft version -- is
    # visible to the user immediately instead of showing up as a cryptic
    # JVM crash after the fact.
    status_cb(f"Using Java: {java_path}", "#3498DB")

    try:
        # Build the launch command — minecraft_launcher_lib handles ALL JVM flags
        mc_command = minecraft_launcher_lib.command.get_minecraft_command(
            version, minecraft_dir, options
        )

        # ──[ bypass ]───────────────────
        activate_bypass(mc_command)

        # ──[ Native DLL extraction (all versions) ]────────────────────────────
        # minecraft_launcher_lib already set -Djava.library.path to the
        # 'natives' folder and added the native JARs to -cp.  However for
        # modern LWJGL 3 (1.19+) the self-extractor sometimes fails in
        # third-party launchers (permission issues, missing temp dir, etc.).
        # The safest approach for every version is to extract DLLs ourselves
        # from the classpath JARs into the natives folder the library declared.
        import zipfile

        # Read the natives path directly from the command the library built —
        # this is always correct regardless of version or OS.
        natives_dir = ""
        for arg in mc_command:
            if arg.startswith("-Djava.library.path="):
                natives_dir = arg.split("=", 1)[1]
                break

        if not natives_dir:
            # Fallback: use the standard location
            natives_dir = os.path.join(minecraft_dir, "versions", version, "natives")

        os.makedirs(natives_dir, exist_ok=True)

        # Only extract if the folder has no DLLs yet (skip on re-launch)
        already_extracted = any(
            f.endswith((".dll", ".so", ".dylib"))
            for f in os.listdir(natives_dir)
        )
        if not already_extracted:
            classpath_str = ""
            for i, arg in enumerate(mc_command):
                if arg in ("-cp", "-classpath") and i + 1 < len(mc_command):
                    classpath_str = mc_command[i + 1]
                    break

            extracted_count = 0
            if classpath_str:
                for jar_path in classpath_str.split(os.path.pathsep):
                    if not (jar_path.endswith(".jar") and os.path.exists(jar_path)):
                        continue
                    try:
                        with zipfile.ZipFile(jar_path, "r") as jar:
                            for fi in jar.infolist():
                                fname = fi.filename
                                if "META-INF" in fname or fname.endswith("/"):
                                    continue
                                if fname.endswith((".dll", ".so", ".dylib")):
                                    basename = os.path.basename(fname)
                                    if not basename:
                                        continue
                                    target = os.path.join(natives_dir, basename)
                                    with jar.open(fi) as src, open(target, "wb") as dst:
                                        shutil.copyfileobj(src, dst)
                                    extracted_count += 1
                    except Exception as ex:
                        print(f"[Natives] Could not read {os.path.basename(jar_path)}: {ex}")

            print(f"[Natives] Extracted {extracted_count} files to {natives_dir}")

        # ──[ Inject user JVM args (-Xmx, GC flags, etc.) ]────────────────────
        # Find the insertion point: after the java executable (index 0) and
        # after any -Djava.library.path / -D* flags the library already placed,
        # but BEFORE -cp and the main class.  This keeps the library's flags
        # in their original positions so LWJGL can find its natives.
        insert_at = 1
        for idx, arg in enumerate(mc_command[1:], start=1):
            if arg in ("-cp", "-classpath") or not arg.startswith("-"):
                insert_at = idx
                break

        # ÉP JVM ĐẦU RA PHẢI LÀ UTF-8 ĐỂ KHÔNG BỊ LỖI PHÔNG TIẾNG VIỆT
        if "-Dfile.encoding=UTF-8" not in mc_command:
            mc_command.insert(insert_at, "-Dfile.encoding=UTF-8")
            insert_at += 1

        user_jvm_args = [a.strip() for a in current_prof.get("jvm_args", "").split() if a.strip()]
        for arg in reversed(user_jvm_args):
            mc_command.insert(insert_at, arg)

        # ──[ Launch ]───────────────────────────────────────────────────────────
        popen_kwargs: dict = {
            "cwd":      minecraft_dir,
            "stdout":   subprocess.PIPE,
            "stderr":   subprocess.STDOUT,
            "text":     True,
            "encoding": "utf-8",
            "errors":   "replace",
        }

        if platform.system() == "Windows":
            startupinfo = subprocess.STARTUPINFO()
            # SW_SHOWNORMAL = 1: show the game window normally.
            # Without this, LWJGL 2 (1.12.2 and older) creates an invisible window.
            startupinfo.dwFlags    |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 1
            popen_kwargs["startupinfo"]   = startupinfo
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

        launch_started_at = time.time()
        process = subprocess.Popen(mc_command, **popen_kwargs)

        status_cb("Launched successfully! Have fun.", "green")
        success_cb()

        missing_dependencies = []
        recent_lines = []  # keep a short tail for a generic crash summary fallback

        if process.stdout:
            for line in process.stdout:
                stripped_line = line.strip()
                if log_cb:
                    log_cb(stripped_line)

                if stripped_line:
                    recent_lines.append(stripped_line)
                    if len(recent_lines) > 60:
                        recent_lines.pop(0)

                # Quét trực tiếp trong stdout (bắt được format Forge cũ,
                # và một số build NeoForge vẫn in ra dòng tương tự)
                for dep in _extract_missing_mods(stripped_line):
                    if dep not in missing_dependencies:
                        missing_dependencies.append(dep)

        # Đợi cho đến khi tiến trình game kết thúc hoàn toàn (hoặc crash hẳn)
        return_code = process.wait()

        # Nếu game crash và không bắt được gì từ stdout, thử đọc file
        # crash-report mà NeoForge/Forge ghi ra ổ đĩa — nội dung ở đó đầy đủ
        # và ổn định hơn nhiều so với chờ đúng một dòng log trong stdout.
        crash_report_path = None
        if return_code != 0 and not missing_dependencies:
            crash_report_path = _find_latest_crash_report(minecraft_dir, launch_started_at)
            if crash_report_path:
                try:
                    with open(crash_report_path, "r", encoding="utf-8", errors="replace") as f:
                        report_text = f.read()
                    missing_dependencies = _extract_missing_mods(report_text)
                except OSError:
                    pass

        # Báo cho lớp giao diện (bridge.py -> app.js) hiển thị popup, thay vì
        # dùng tkinter native dialog tách rời khỏi giao diện webview.
        if return_code != 0 and missing_mods_cb:
            crash_summary = None
            if not missing_dependencies:
                # Không parse được mod cụ thể nào -> vẫn hiển thị popup với
                # vài dòng log cuối để người dùng không phải tự mò console.
                crash_summary = "\n".join(recent_lines[-15:])
            missing_mods_cb(missing_dependencies, crash_summary, crash_report_path)

        # KÍCH HOẠT CALLBACK: Báo cáo lại mã lỗi (return_code) về cho phía Bridge xử lý giao diện
        if exit_cb:
            exit_cb(return_code)

    except KeyError as e:
        traceback.print_exc()
        msg = ("Mod JSON structure error (unhandled 'value' key)!"
               if "value" in str(e) else f"Structure error: {e}")
        status_cb(msg, "red")
        btn_cb("normal", "PLAY")
        if exit_cb: exit_cb(-1) # Gọi exit_cb báo lỗi cấu trúc JSON nếu có
    except Exception as e:
        status_cb(f"Launch failed: {e}", "red")
        btn_cb("normal", "PLAY")
        if exit_cb: exit_cb(-1) # Gọi exit_cb báo lỗi khởi chạy nếu có

    except KeyError as e:
        traceback.print_exc()
        msg = ("Mod JSON structure error (unhandled 'value' key)!"
               if "value" in str(e) else f"Structure error: {e}")
        status_cb(msg, "red")
        btn_cb("normal", "PLAY")
    except Exception as e:
        status_cb(f"Launch failed: {e}", "red")
        btn_cb("normal", "PLAY")