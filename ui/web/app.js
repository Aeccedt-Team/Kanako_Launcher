// ui/web/app.js

let selectedVersion = "";

// ==========================================
// 1. CALLBACKS CALLED BY PYTHON VIA evaluate_js
// ==========================================

window.onVersionsLoaded = function(versionsList, savedVersion) {
    renderVersions(versionsList, savedVersion);
};

window.updateStatus = function(message, color) {
    const el = document.getElementById("status");
    if (el) { el.innerText = message; el.style.color = color; }

    const level = (color === "#E74C3C" || color === "red")    ? "error"
                : (color === "#E67E22" || color === "orange")  ? "warn"
                : "info";
    appendLog(`[${level.toUpperCase()}] ${message}`, level);

    // Re-enable the Play button once launching reaches a terminal state:
    // either the success message, or any error status (so a failed launch
    // doesn't leave the button stuck disabled).
    if (message === "Launched successfully! Have fun." || level === "error") {
        setPlayButtonLaunching(false);
    }
};

// ==========================================
// PLAY BUTTON LAUNCHING STATE
// ==========================================

function setPlayButtonLaunching(isLaunching) {
    const btn = document.getElementById("btn-play");
    if (!btn) return;
    if (isLaunching) {
        btn.disabled = true;
        btn.innerText = "Launching...";
    } else {
        btn.disabled = false;
        btn.innerText = "PLAY";
    }
}

window.updateProgress = function(percentage) {
    const container = document.getElementById("progress-container");
    const bar       = document.getElementById("progress-bar");
    if (container) container.classList.remove("hidden");
    if (bar)       bar.style.width = percentage + "%";
};

window.launchSuccess = function() {
    window.updateStatus("Launched successfully! Have fun.", "#2ECC71");
};

// ==========================================
// 2. TAB SWITCHING
// ==========================================

function switchTab(name) {
    document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
    document.getElementById("tab-" + name).classList.add("active");
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    document.getElementById("tbtn-" + name).classList.add("active");

    // Console search box: hide (not close) when leaving the console tab,
    // and restore it if it was left open when coming back. Search text /
    // filter state is untouched either way.
    const searchBox = document.getElementById("console-search-box");
    if (searchBox) {
        if (name === "console") {
            if (window.consoleSearchOpen) {
                searchBox.classList.remove("hidden");
            }
        } else {
            searchBox.classList.add("hidden");
        }
    }
}

// ==========================================
// 3. CONSOLE LOGGING
// ==========================================

function createColorCodedSpan(text, baseLevel, forceContinuation) {
    const container = document.createElement("span");
    container.className = "log-" + baseLevel;

    // Chèn khoảng trắng ẩn (zero-width space) ngay sau các ký tự phân tách
    // đường dẫn/URL ('/', '\', ':') để trình duyệt ưu tiên xuống dòng tại
    // các vị trí này, thay vì cắt ngang giữa từ (vd: ".mcassetsroot")
    function insertSoftBreaks(str) {
        return str.replace(/([\/\\:])/g, "$1\u200B");
    }

    // Bỏ qua các mã màu/định dạng Minecraft (§7, &#RRGGBB, ...) đứng ở đầu dòng
    // trước khi kiểm tra dấu "[", để không bị nhận nhầm thành dòng phụ (continuation)
    const leadingCodeRegex = /^(§#[0-9a-fA-F]{6}|&#[0-9a-fA-F]{6}|§[0-9a-fk-or])+/;
    const strippedForCheck = text.trim().replace(leadingCodeRegex, "");
    if (forceContinuation || !strippedForCheck.startsWith("[")) {
        container.classList.add("log-continuation");
    }

    // Giữ cờ /g ở đây để split chuỗi văn bản ra chuẩn xác
    const colorRegex = /(§#[0-9a-fA-F]{6}|&#[0-9a-fA-F]{6}|§[0-9a-fk-or])/g;
    const parts = text.split(colorRegex);

    // Regex kiểm tra đơn lẻ: Tuyệt đối KHÔNG dùng cờ /g để tránh lỗi lastIndex
    const singleColorRegex = /^(§#[0-9a-fA-F]{6}|&#[0-9a-fA-F]{6}|§[0-9a-fk-or])$/;

    const mcColors = {
        '0': '#000000', '1': '#0000AA', '2': '#00AA00', '3': '#00AAAA',
        '4': '#AA0000', '5': '#AA00AA', '6': '#FFAA00', '7': '#AAAAAA',
        '8': '#555555', '9': '#5555FF', 'a': '#55FF55', 'b': '#55FFFF',
        'c': '#FF5555', 'd': '#FF55FF', 'e': '#FFFF55', 'f': '#FFFFFF'
    };

    let currentColor = null;
    let isBold = false;
    let isItalic = false;
    let isUnderline = false;
    let isStrikethrough = false;

    for (let i = 0; i < parts.length; i++) {
        const part = parts[i];
        if (!part) continue;

        if (singleColorRegex.test(part)) {
            // Xử lý mã màu / mã định dạng thương hiệu Minecraft
            if (part.startsWith('§#') || part.startsWith('&#')) {
                currentColor = part.substring(2); 
            } else {
                const code = part.charAt(1).toLowerCase();
                if (mcColors[code] !== undefined) {
                    currentColor = mcColors[code];
                } else if (code === 'r') { 
                    currentColor = null;
                    isBold = isItalic = isUnderline = isStrikethrough = false;
                } else if (code === 'l') isBold = true;
                else if (code === 'o') isItalic = true;
                else if (code === 'n') isUnderline = true;
                else if (code === 'm') isStrikethrough = true;
            }
        } else {
            // Đóng gói phần text vào span con
            const textNode = document.createElement("span");
            textNode.textContent = insertSoftBreaks(part);
            if (currentColor) textNode.style.color = currentColor;
            if (isBold) textNode.style.fontWeight = "bold";
            if (isItalic) textNode.style.fontStyle = "italic";
            
            let decorations = [];
            if (isUnderline) decorations.push("underline");
            if (isStrikethrough) decorations.push("line-through");
            if (decorations.length > 0) textNode.style.textDecoration = decorations.join(" ");

            container.appendChild(textNode);
        }
    }

    if (container.children.length === 0) {
        container.textContent = insertSoftBreaks(text);
    }
    return container;
}

let _consoleLineCount = 1;

function appendLog(text, level) {
    const box = document.getElementById("console-output");
    if (!box) return;

    if (!level) {
        const t = text.toUpperCase();
        level = t.includes("[ERROR]") || t.includes("[CRITICAL]") ? "error"
              : t.includes("[WARN]")  || t.includes("[WARNING]")  ? "warn"
              : t.includes("[DEBUG]")                              ? "debug"
              : "info";
    }

    // Gọi hàm tạo thẻ span đã phân tách màu sắc
    const span = createColorCodedSpan(text, level);
    box.appendChild(span);
    box.appendChild(document.createTextNode("\n"));

    _consoleLineCount++;
    const counter = document.getElementById("console-line-count");
    if (counter) counter.textContent =
        _consoleLineCount === 1 ? "1 line" : _consoleLineCount + " lines";

    // Đồng bộ: Nếu hộp tìm kiếm đang hoạt động, áp dụng bộ lọc trực tiếp lên dòng log mới
    const searchInput = document.getElementById("console-search-input");
    const searchBox = document.getElementById("console-search-box");
    if (searchBox && !searchBox.classList.contains("hidden") && searchInput) {
        const query = searchInput.value.toLowerCase();
        if (query && !span.textContent.toLowerCase().includes(query)) {
            span.style.display = "none";
        }
    }

    if (box.scrollTop + box.clientHeight >= box.scrollHeight - 60) {
        box.scrollTop = box.scrollHeight;
    }
}

function clearConsole() {
    const box = document.getElementById("console-output");
    if (box) box.innerHTML = "";
    _consoleLineCount = 0;
    const counter = document.getElementById("console-line-count");
    if (counter) counter.textContent = "0 lines";
}

// ==========================================
// 4. INITIALISE & SYNC PROFILE DATA
// ==========================================

function initializeLauncher() {
    if (!window.pywebview || !window.pywebview.api) return;

    return window.pywebview.api.get_initial_data().then(data => {
        // 4.1  Rebuild profile dropdown and select the active profile
        _rebuildProfileDropdown(data.profiles_list, data.current_profile);

        // 4.2  Username + remember checkbox
        const txtUsername = document.getElementById("username");
        const chkRemember = document.getElementById("remember-username");
        if (txtUsername) txtUsername.value   = data.profile_data.username || "";
        if (chkRemember) chkRemember.checked = data.profile_data.remember || false;

        // 4.3  Persistent checkboxes (localStorage)
        _initCheckboxFromStorage("keep-launcher-open", "keepLauncherOpen", false);

        // 4.4  Segoe UI font toggle
        const chkUseSegoe = document.getElementById("use-segoe-font");
        if (chkUseSegoe) {
            const useSegoe = localStorage.getItem("useSegoeFont") === "true";
            chkUseSegoe.checked = useSegoe;
            document.body.classList.toggle("segoe-active", useSegoe);
            chkUseSegoe.onchange = function() {
                localStorage.setItem("useSegoeFont", this.checked);
                document.body.classList.toggle("segoe-active", this.checked);
            };
        }

        // 4.5  Version list
        if (data.versions_ready) {
            renderVersions(data.versions, data.profile_data.version);
        } else {
            const btnVersion = document.getElementById("version-select-btn");
            if (btnVersion) btnVersion.innerText = "⏳ Fetching versions from Mojang...";
        }

        // 4.6  Banner (game + console tab backgrounds)
        applyBanner(data.profile_data.banner_data_uri);

    }).catch(err => {
        appendLog("[ERROR] Launcher init error: " + err, "error");
    });
}

/**
 * Rebuild the profile <select> with a fresh list and select the given profile.
 * Kept as a standalone helper so saveProfileSettings, createNewProfile, and
 * removeCurrentProfile can all use it without calling full initializeLauncher.
 */
function _rebuildProfileDropdown(profilesList, activeProfile) {
    const profileSelect = document.getElementById("profile-select");
    if (!profileSelect || !profilesList) return;
    profileSelect.innerHTML = profilesList
        .map(p => `<option value="${p}" ${p === activeProfile ? "selected" : ""}>${p}</option>`)
        .join("");
}

function _initCheckboxFromStorage(elementId, storageKey, defaultValue) {
    const chk = document.getElementById(elementId);
    if (!chk) return;
    const saved = localStorage.getItem(storageKey);
    chk.checked = saved !== null ? saved === "true" : defaultValue;
    chk.onchange = function() { localStorage.setItem(storageKey, this.checked); };
}

/**
 * Apply a profile's banner (or revert to the bundled default) to both
 * places that use it: the game tab background and the console tab
 * background. Passing null/undefined clears the inline override, which
 * falls back to the CSS default (url('banner.png')).
 */
function applyBanner(dataUri) {
    const gameBg     = document.getElementById("game-background");
    const consoleTab = document.getElementById("tab-console");
    const cssValue   = dataUri ? `url("${dataUri}")` : "";
    if (gameBg)     gameBg.style.backgroundImage     = cssValue;
    if (consoleTab) consoleTab.style.backgroundImage = cssValue;
}

if (window.pywebview) {
    initializeLauncher();
} else {
    window.addEventListener("pywebviewready", initializeLauncher);
}

// ==========================================
// 5. VERSION LIST RENDERING
// ==========================================

function renderVersions(versionsList, savedVersion) {
    const dropdown   = document.getElementById("version-dropdown");
    const btnVersion = document.getElementById("version-select-btn");
    if (!btnVersion) return;

    if (!versionsList || versionsList.length === 0) {
        btnVersion.innerText = "⚠️ No versions available";
        return;
    }

    const firstId = typeof versionsList[0] === "object" ? versionsList[0].id : versionsList[0];
    selectedVersion = savedVersion || firstId;
    btnVersion.innerText = `📦 ${selectedVersion}`;

    if (dropdown) {
        dropdown.innerHTML = versionsList.map(ver => {
            const id           = typeof ver === "object" ? ver.id           : ver;
            const isDownloaded = typeof ver === "object" ? ver.is_downloaded : false;
            let   type         = typeof ver === "object" ? ver.type          : "vanilla";

            const idLower = id.toLowerCase();
            if (idLower.includes("forge") || idLower.includes("neoforge")) type = "modded";

            let color, icon;
            if (type === "modded")      { color = "#F39C12"; icon = "🛠️"; }
            else if (!isDownloaded)     { color = "#718096"; icon = "📥"; }
            else                        { color = "#FFFFFF"; icon = "✅"; }

            return `<div class="version-item" style="color:${color};" onclick="selectVersion('${id}')">${icon}  ${id}</div>`;
        }).join("");
    }
}

function selectVersion(versionStr) {
    selectedVersion = versionStr;
    const btnVersion = document.getElementById("version-select-btn");
    const dropdown   = document.getElementById("version-dropdown");
    if (btnVersion) btnVersion.innerText = `📦 ${versionStr}`;
    if (dropdown)   dropdown.classList.add("hidden");
}

function toggleVersionMenu() {
    const dropdown = document.getElementById("version-dropdown");
    if (!dropdown) return;
    if (window.event) window.event.stopPropagation();
    dropdown.classList.toggle("hidden");
}

function refreshVersions() {
    window.updateStatus("Refreshing versions from Mojang...", "#94a3b8");
    window.pywebview.api.refresh_versions();
}

// ==========================================
// 6. PLAY BUTTON
// ==========================================

function handlePlayClick() {
    const txtUsername = document.getElementById("username");
    if (!txtUsername) return;

    const username         = txtUsername.value.trim();
    const version          = selectedVersion;
    const remember         = document.getElementById("remember-username")?.checked  || false;
    const keepLauncherOpen = document.getElementById("keep-launcher-open")?.checked || false;

    if (!username) {
        window.updateStatus("Please enter a username!", "#E74C3C");
        return;
    }
    setPlayButtonLaunching(true);
    window.updateStatus("Preparing to launch...", "#3498DB");
    window.pywebview.api.launch_game(username, version, remember, keepLauncherOpen);
}

// ==========================================
// 7. PROFILE SWITCHING
// ==========================================

let profileStatusTimeout = null;

function handleProfileChange() {
    const profileSelect = document.getElementById("profile-select");
    if (!profileSelect) return;
    const selectedProfile = profileSelect.value;

    if (profileStatusTimeout) clearTimeout(profileStatusTimeout);
    window.updateStatus(`Switching to profile: ${selectedProfile}...`, "#94a3b8");

    window.pywebview.api.switch_profile(selectedProfile).then(data => {
        if (!data) return;
        const txtUsername = document.getElementById("username");
        const chkRemember = document.getElementById("remember-username");
        if (txtUsername) txtUsername.value   = data.profile_data.username || "";
        if (chkRemember) chkRemember.checked = data.profile_data.remember || false;

        if (data.versions_ready) renderVersions(data.versions, data.profile_data.version);

        applyBanner(data.profile_data.banner_data_uri);

        window.updateStatus(`Switched to profile: ${selectedProfile}`, "#2ECC71");
        profileStatusTimeout = setTimeout(() => window.updateStatus("Ready.", "#94a3b8"), 2000);
    });
}

// ==========================================
// 8. CREATE / EDIT / REMOVE PROFILE
// ==========================================

async function createNewProfile() {
    try {
        window.updateStatus("Creating new profile...", "#94a3b8");
        const newProfileName = await window.pywebview.api.web_create_profile();
        // Full reinit so the dropdown and all fields are in sync
        await initializeLauncher();
        // Then select the newly created profile in the dropdown
        const profileSelect = document.getElementById("profile-select");
        if (profileSelect) profileSelect.value = newProfileName;
        _initCheckboxFromStorage("keep-launcher-open", "keepLauncherOpen", false);
        window.updateStatus("New profile created! Please customize it.", "#2ECC71");
    } catch (err) {
        appendLog("[ERROR] createNewProfile: " + err, "error");
        window.updateStatus("Error creating profile!", "#E74C3C");
    }
}

// Tracks the key used to open the modal so we can pass it to Python on save.
// Updated to the NEW name after a successful rename so the edit button works
// again without reopening the launcher.
let currentEditingOldId = "";

function editProfile() {
    const profileSelect = document.getElementById("profile-select");
    if (!profileSelect) return;

    // Always read the current dropdown value — after a rename the dropdown
    // already shows the new name (we update it on save), so this is correct.
    currentEditingOldId = profileSelect.value;

    window.pywebview.api.get_profile_details(currentEditingOldId).then(prof => {
        if (!prof) {
            appendLog("[ERROR] editProfile: profile not found — " + currentEditingOldId, "error");
            return;
        }
        document.getElementById("edit-profile-name").value     = prof.name      || currentEditingOldId;
        document.getElementById("edit-game-dir").value         = prof.game_dir  || "";
        document.getElementById("edit-jvm-args").value         = prof.jvm_args  || "";
        document.getElementById("edit-java-manual").checked    = prof.java_manual || false;
        document.getElementById("edit-java-path").value        = prof.java_path  || "";
        document.getElementById("edit-allow-snapshot").checked = prof.allow_snapshots || false;
        document.getElementById("edit-allow-beta").checked     = prof.allow_beta     || false;
        document.getElementById("edit-allow-alpha").checked    = prof.allow_alpha    || false;

        const bannerPreview = document.getElementById("edit-banner-preview");
        const bannerPathBox = document.getElementById("edit-banner-path");
        if (bannerPathBox) bannerPathBox.value = prof.banner_path || "";
        if (bannerPreview) bannerPreview.src   = prof.banner_data_uri || "banner.png";

        toggleJavaInputVisibility();
        document.getElementById("edit-modal").classList.remove("hidden");
    }).catch(err => appendLog("[ERROR] editProfile: " + err, "error"));

    document.getElementById("delete-game-files").checked = false;
    document.getElementById("delete-warning-text").classList.add("hidden");
}

function closeEditModal() {
    document.getElementById("edit-modal").classList.add("hidden");
}

function toggleJavaInputVisibility() {
    const isManual  = document.getElementById("edit-java-manual").checked;
    const pathInput = document.getElementById("edit-java-path");
    const browseBtn = document.getElementById("btn-browse-java");
    pathInput.disabled      = !isManual;
    browseBtn.disabled      = !isManual;
    pathInput.style.opacity = isManual ? "1" : "0.4";
    browseBtn.style.opacity = isManual ? "1" : "0.4";
}

function browseGameDir() {
    window.pywebview.api.web_browse_directory().then(path => {
        if (path) document.getElementById("edit-game-dir").value = path;
    }).catch(err => appendLog("[ERROR] browseGameDir: " + err, "error"));
}

function browseJavaPath() {
    window.pywebview.api.web_browse_file().then(path => {
        if (path) document.getElementById("edit-java-path").value = path;
    }).catch(err => appendLog("[ERROR] browseJavaPath: " + err, "error"));
}

function openGameFolderNative() {
    const path = document.getElementById("edit-game-dir").value.trim();
    window.pywebview.api.web_open_folder(path);
}

// ==========================================
// PROFILE BANNER
// ==========================================

function browseBannerImage() {
    window.pywebview.api.web_choose_banner_image().then(result => {
        if (!result) return; // dialog cancelled
        const pathInput = document.getElementById("edit-banner-path");
        const preview    = document.getElementById("edit-banner-preview");
        if (pathInput) pathInput.value = result.path;
        if (preview)   preview.src     = result.banner_data_uri || "banner.png";
    });
}

function resetBannerToDefault() {
    // Purely local — clearing the path field is enough; it's committed
    // (or discarded) along with everything else when Save is clicked.
    const pathInput = document.getElementById("edit-banner-path");
    const preview    = document.getElementById("edit-banner-preview");
    if (pathInput) pathInput.value = "";
    if (preview)   preview.src     = "banner.png";
}

async function saveProfileSettings() {
    const newName       = document.getElementById("edit-profile-name").value.trim();
    const gameDir       = document.getElementById("edit-game-dir").value.trim();
    const jvmArgs       = document.getElementById("edit-jvm-args").value.trim();
    const javaManual    = document.getElementById("edit-java-manual").checked;
    const javaPath      = document.getElementById("edit-java-path").value.trim();
    const bannerPath    = document.getElementById("edit-banner-path").value.trim();
    const allowSnapshot = document.getElementById("edit-allow-snapshot").checked;
    const allowBeta     = document.getElementById("edit-allow-beta").checked;
    const allowAlpha    = document.getElementById("edit-allow-alpha").checked;

    // The effective new name (falls back to old if left blank)
    const resolvedName = newName || currentEditingOldId;

    window.updateStatus("Saving profile settings...", "#94a3b8");

    try {
        await window.pywebview.api.web_save_profile(
            currentEditingOldId, newName, gameDir, jvmArgs,
            javaManual, javaPath, bannerPath, allowSnapshot, allowBeta, allowAlpha
        );

        // FIX 1: Update currentEditingOldId to the new name immediately so
        // the edit button works again without a launcher restart.
        currentEditingOldId = resolvedName;

        closeEditModal();

        // FIX 2: Ask Python for the fresh profile list and rebuild the
        // dropdown — this is the only place that was missing after a rename.
        const data = await window.pywebview.api.switch_profile(resolvedName);
        if (data) {
            // Rebuild the dropdown with the updated list and select new name
            _rebuildProfileDropdown(
                await _fetchProfilesList(),
                resolvedName
            );

            const txtUsername = document.getElementById("username");
            const chkRemember = document.getElementById("remember-username");
            if (txtUsername) txtUsername.value   = data.profile_data.username || "";
            if (chkRemember) chkRemember.checked = data.profile_data.remember || false;
            if (data.versions_ready) renderVersions(data.versions, data.profile_data.version);
            applyBanner(data.profile_data.banner_data_uri);
        }

        window.updateStatus("Profile saved successfully!", "#2ECC71");

    } catch (err) {
        appendLog("[ERROR] saveProfileSettings: " + err, "error");
        window.updateStatus("Error saving profile!", "#E74C3C");
    }
}

/**
 * Fetch the current profiles list from Python without doing a full reinit.
 * Used after save so we can rebuild just the dropdown.
 */
async function _fetchProfilesList() {
    const data = await window.pywebview.api.get_initial_data();
    return data ? data.profiles_list : [];
}

// ==========================================
// 9. REMOVE PROFILE
// ==========================================

function toggleDeleteWarning() {
    const isChecked   = document.getElementById("delete-game-files").checked;
    const warningText = document.getElementById("delete-warning-text");
    warningText.classList.toggle("hidden", !isChecked);
}

async function removeCurrentProfile() {
    if (!currentEditingOldId) return;
    const deleteFiles = document.getElementById("delete-game-files").checked;
    let confirmMsg = `Are you sure you want to completely REMOVE the profile "${currentEditingOldId}"?`;
    if (deleteFiles) confirmMsg += "\n\n⚠️ WARNING: YOU SELECTED TO DELETE ALL DATA FILES! THIS WILL WIPE OUT THE GAME FOLDER FOREVER!";

    const confirmed = await showMCConfirm(confirmMsg, {
        title: "REMOVE PROFILE",
        okText: "REMOVE",
        cancelText: "CANCEL",
        danger: true,
    });
    if (!confirmed) return;

    window.updateStatus("Processing profile removal...", "#94a3b8");

    try {
        // FIX 3: await the removal before doing anything else — previously
        // the success status was set synchronously before the promise resolved,
        // and handleProfileChange fired before the dropdown was rebuilt.
        await window.pywebview.api.web_remove_profile(currentEditingOldId, deleteFiles);
        closeEditModal();
        currentEditingOldId = "";

        // Full reinit rebuilds the dropdown with the surviving profiles
        await initializeLauncher();

        // Now it's safe to trigger profile-change logic on whatever is selected
        handleProfileChange();

        window.updateStatus("Profile removed successfully!", "#2ECC71");
    } catch (err) {
        appendLog("[ERROR] removeCurrentProfile: " + err, "error");
        window.updateStatus("Error trying to remove profile!", "#E74C3C");
    }
}

// ==========================================
// 10. CLOSE VERSION DROPDOWN ON OUTSIDE CLICK
// ==========================================

document.addEventListener("click", function(event) {
    const dropdown   = document.getElementById("version-dropdown");
    const btnVersion = document.getElementById("version-select-btn");
    if (!dropdown || !btnVersion) return;
    if (!btnVersion.contains(event.target) && !dropdown.contains(event.target)) {
        dropdown.classList.add("hidden");
    }
});

// ==========================================
// 11. SHORTCUTS & SEARCH FEATURE (CTRL+F / DELETE)
// ==========================================

document.addEventListener("DOMContentLoaded", initConsoleShortcutsAndSearch);
if (document.readyState === "complete" || document.readyState === "interactive") {
    initConsoleShortcutsAndSearch();
}

function initConsoleShortcutsAndSearch() {
    if (document.getElementById("console-search-box")) return;

    const searchBox = document.createElement("div");
    searchBox.id = "console-search-box";
    searchBox.classList.add("hidden");
    
    // ĐỒNG BỘ STYLE: Sử dụng thiết kế phẳng, vuông vức và mã màu giống tab-bar/button của launcher
    searchBox.style.position = "fixed";
    searchBox.style.top = "35px"; 
    searchBox.style.right = "20px";
    searchBox.style.background = "#2b2b2b";
    searchBox.style.border = "2px solid #000";
    searchBox.style.padding = "4px 10px";
    searchBox.style.borderRadius = "0px"; // Không bo góc theo đúng phong cách card-frame/tab-btn
    searchBox.style.zIndex = "9999";
    searchBox.style.display = "flex";
    searchBox.style.alignItems = "center";
    searchBox.style.gap = "10px";
    searchBox.style.boxShadow = "inset 1px 1px 0 #555, inset -1px -1px 0 #111, 0 4px 12px rgba(0,0,0,0.6)";
    searchBox.style.fontFamily = "'VVMAyuMincho', sans-serif";

    searchBox.innerHTML = `
        <input type="text" id="console-search-input" placeholder="LỌC / TÌM LOG..." 
               style="background:#1a1a1a; color:#e8e8e8; border:1px solid #444; padding:4px 8px; outline:none; font-size:11px; width:180px; font-family:'VVMAyuMincho', sans-serif;">
        <span id="console-search-count" style="color:#888; font-size:11px; min-width:70px; text-align:center;">0 TÌM THẤY</span>
        <button id="console-search-close" style="background:#2b2b2b; border:1px solid #444; color:#FF5555; cursor:pointer; font-weight:bold; font-size:11px; padding:2px 6px; box-shadow: inset 1px 1px 0 #555, inset -1px -1px 0 #111; font-family:'VVMAyuMincho', sans-serif;">✕</button>
    `;

    const searchStyle = document.createElement('style');
    searchStyle.innerHTML = `
        #console-search-box.hidden { display: none !important; }
        
        /* Hiệu ứng dòng log đang được chọn bằng phím mũi tên */
        .log-item-selected {
            background-color: rgba(56, 189, 248, 0.2) !important; /* Màu xanh cyan mờ đồng bộ màu active tab */
            outline: 1px dashed #38BDF8;
            display: inline-block;
            width: 100%;
        }
        #console-search-close:hover {
            color: #FFFF55 !important;
            border-color: #fff !important;
        }
    `;
    document.head.appendChild(searchStyle);

    document.body.appendChild(searchBox);

    const input = document.getElementById("console-search-input");
    const countSpan = document.getElementById("console-search-count");
    const closeBtn = document.getElementById("console-search-close");

    // Các biến phục vụ việc điều hướng bằng phím mũi tên
    let visibleLines = [];
    let selectedIndex = -1;

    function closeSearch() {
        searchBox.classList.add("hidden");
        input.value = "";
        removeCurrentSelection();
        resetLogVisibility();
        input.blur();
        visibleLines = [];
        selectedIndex = -1;
        window.consoleSearchOpen = false;
    }

    function removeCurrentSelection() {
        if (selectedIndex >= 0 && visibleLines[selectedIndex]) {
            visibleLines[selectedIndex].classList.remove("log-item-selected");
        }
    }

    closeBtn.onclick = closeSearch;

    // Xử lý bộ lọc tìm kiếm
    input.oninput = function() {
        const query = input.value.trim().toLowerCase();
        const box = document.getElementById("console-output");
        if (!box) return;

        removeCurrentSelection();
        const lines = box.querySelectorAll("span[class^='log-']");
        visibleLines = [];

        if (!query) {
            resetLogVisibility();
            countSpan.textContent = "0 TÌM THẤY";
            selectedIndex = -1;
            return;
        }

        lines.forEach(line => {
            if (line.textContent.toLowerCase().includes(query)) {
                line.style.display = ""; 
                visibleLines.push(line); // Lưu lại các dòng thỏa mãn để bấm nút di chuyển
            } else {
                line.style.display = "none"; 
            }
        });

        countSpan.textContent = `${visibleLines.length} TÌM THẤY`;
        selectedIndex = -1; // Reset lại vị trí lựa chọn mỗi khi từ khóa thay đổi
    };

    // HỖ TRỢ PHÍM MŨI TÊN LÊN / XUỐNG ĐỂ DI CHUYỂN GIỮA CÁC MỤC LOG KHI ĐANG TRONG INPUT
    input.onkeydown = function(e) {
        if (e.key === "ArrowDown" || e.key === "ArrowUp") {
            if (visibleLines.length === 0) return;
            e.preventDefault(); // Ngăn hành vi cuộn trang mặc định hoặc di chuyển con trỏ chữ trong input

            removeCurrentSelection();

            if (e.key === "ArrowDown") {
                selectedIndex++;
                if (selectedIndex >= visibleLines.length) {
                    selectedIndex = 0; // Vòng lặp lại dòng đầu tiên nếu đi quá danh sách
                }
            } else if (e.key === "ArrowUp") {
                selectedIndex--;
                if (selectedIndex < 0) {
                    selectedIndex = visibleLines.length - 1; // Vòng lên dòng cuối cùng nếu bấm Lên ở vị trí đầu
                }
            }

            // Gắn class highlight và tự động cuộn màn hình đến dòng đang chọn
            const currentLine = visibleLines[selectedIndex];
            if (currentLine) {
                currentLine.classList.add("log-item-selected");
                currentLine.scrollIntoView({ behavior: "smooth", block: "nearest" });
            }
        }
    };

    function resetLogVisibility() {
        const box = document.getElementById("console-output");
        if (!box) return;
        box.querySelectorAll("span[class^='log-']").forEach(line => {
            line.style.display = "";
        });
    }

    // THAY THẾ TOÀN BỘ ĐOẠN LISTENER "KEYDOWN" CŨ BẰNG ĐOẠN NÀY:
    window.addEventListener("keydown", function(e) {
        const consoleTab = document.getElementById("tab-console");
        const isConsoleTabActive = consoleTab && consoleTab.classList.contains("active");

        // 1. ƯU TIÊN KIỂM TRA CTRL + F TRƯỚC
        if (e.ctrlKey && e.key.toLowerCase() === "f") {
            if (isConsoleTabActive) {
                e.preventDefault(); // Chặn hộp tìm kiếm mặc định của trình duyệt
                window.consoleSearchOpen = true;
                searchBox.classList.remove("hidden");
                input.focus();
                input.select();
                if (input.value.trim()) {
                    input.oninput(); // Kích hoạt lại bộ lọc nếu đang có sẵn từ khóa cũ
                }
            }
            return; // Thoát sớm để không bị ảnh hưởng bởi logic bên dưới
        }

        // 2. Nếu đang ở tab khác, không xử lý Escape/Delete bên dưới.
        // Việc ẩn/hiện hộp tìm kiếm khi đổi tab đã do switchTab() đảm nhiệm,
        // nên KHÔNG tự động ẩn/đóng ở đây nữa.
        if (!isConsoleTabActive) {
            return;
        }

        // 3. Xử lý phím Escape để đóng hẳn hộp tìm kiếm (xóa luôn từ khóa/bộ lọc)
        if (e.key === "Escape" && !searchBox.classList.contains("hidden")) {
            closeSearch();
        }

        // 4. Xử lý phím Delete để xóa nhanh log (chỉ hoạt động khi không viết chữ trong input tìm kiếm)
        if (e.key === "Delete" && document.activeElement !== input) {
            e.preventDefault();
            if (typeof clearConsole === "function") clearConsole();
        }
    });
}

// Hàm hiển thị hộp thoại
function openMCBox() {
    document.getElementById("mcMessageBox").classList.add("active");
}

// Được gọi từ bridge.py (qua evaluate_js) sau khi game thoát với mã lỗi khác 0.
// payload = { mods: [{mod_id, requested_by, expected_range}, ...], summary, crashReportPath }
window.showMissingMods = function (payload) {
    payload = payload || {};
    const mods = Array.isArray(payload.mods) ? payload.mods : [];

    const titleEl = document.querySelector("#mcMessageBox .mc-modal-title");
    const bodyEl  = document.querySelector("#mcMessageBox .mc-modal-body");
    if (!titleEl || !bodyEl) return;

    if (mods.length > 0) {
        titleEl.textContent = "MISSING MODS";
        let html = "<p>The game closed because the following mods are missing:</p><ul class=\"mc-missing-mod-list\">";
        mods.forEach(dep => {
            const modId       = escapeHtml(dep.mod_id || "?");
            const requestedBy = escapeHtml(dep.requested_by || "?");
            const range        = dep.expected_range ? ` (${escapeHtml(dep.expected_range)})` : "";
            html += `<li><b>${modId}</b>${range} — required by <i>${requestedBy}</i></li>`;
        });
        html += "</ul>";
        bodyEl.innerHTML = html;
    } else {
        // Không tách được danh sách mod cụ thể (có thể do định dạng log của
        // NeoForge đã đổi) — vẫn hiển thị popup thay vì im lặng, kèm vài
        // dòng log cuối để không bắt người dùng phải tự lục console.
        titleEl.textContent = "GAME EXITED WITH AN ERROR";
        const summary = escapeHtml(payload.summary || "Unknown cause. Please check the CONSOLE.");
        let html = `<p>The game closed unexpectedly. Latest log:</p><pre class="mc-crash-summary">${summary}</pre>`;
        if (payload.crashReportPath) {
            html += `<p class="hint-text">Crash report: ${escapeHtml(payload.crashReportPath)}</p>`;
        }
        bodyEl.innerHTML = html;
    }

    openMCBox();
};

function escapeHtml(str) {
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

// Hàm đóng hộp thoại
function closeMCBox() {
    document.getElementById("mcMessageBox").classList.remove("active");
}

// Copies whatever's currently shown in the box's body (the crash log or
// the missing-mods list) as plain text -- innerText strips the HTML tags
// for us, so this works for either content type without extra bookkeeping.
function copyMCBoxLog() {
    const bodyEl = document.querySelector("#mcMessageBox .mc-modal-body");
    if (!bodyEl) return;
    const text = bodyEl.innerText;

    function flashCopied() {
        const btn = document.getElementById("btn-copy-mcbox");
        if (!btn) return;
        const original = btn.textContent;
        btn.textContent = "✔ Copied!";
        setTimeout(() => { btn.textContent = original; }, 1200);
    }

    function fallbackCopy() {
        const ta = document.createElement("textarea");
        ta.value = text;
        ta.style.position = "fixed";
        ta.style.left = "-9999px";
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        try { document.execCommand("copy"); flashCopied(); } catch (e) { /* clipboard unavailable */ }
        document.body.removeChild(ta);
    }

    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(flashCopied).catch(fallbackCopy);
    } else {
        fallbackCopy();
    }
}

// ==========================================
// HỘP THOẠI XÁC NHẬN (thay thế confirm() mặc định của trình duyệt)
// ==========================================

let _mcConfirmResolver = null;

/**
 * showMCConfirm(message, opts) -> Promise<boolean>
 * opts: { title, okText, cancelText, danger }
 * Dùng thay cho window.confirm(): await showMCConfirm("Bạn có chắc...?")
 */
function showMCConfirm(message, opts) {
    opts = opts || {};

    document.getElementById("mcConfirmTitle").textContent = opts.title || "XÁC NHẬN";

    const bodyEl = document.getElementById("mcConfirmBody");
    // Giữ format xuống dòng như confirm() gốc, vẫn escape để tránh injection
    bodyEl.innerHTML = `<p>${escapeHtml(message).replace(/\n/g, "<br>")}</p>`;

    const okBtn = document.getElementById("mcConfirmOkBtn");
    okBtn.textContent = opts.okText || "XÁC NHẬN";
    okBtn.classList.toggle("mc-btn-danger", opts.danger !== false);

    const cancelBtn = document.querySelector("#mcConfirmBox .mc-btn-gray");
    if (cancelBtn) cancelBtn.textContent = opts.cancelText || "HỦY";

    document.getElementById("mcConfirmBox").classList.add("active");

    return new Promise(resolve => {
        _mcConfirmResolver = resolve;
    });
}

// Được gọi bởi nút HỦY / XÁC NHẬN / nút X / phím Esc
function mcConfirmResolve(result) {
    document.getElementById("mcConfirmBox").classList.remove("active");
    if (_mcConfirmResolver) {
        const resolve = _mcConfirmResolver;
        _mcConfirmResolver = null;
        resolve(result);
    }
}

// LẮNG NGHE SỰ KIỆN BẤM PHÍM ESC TRÊN BÀN PHÍM
window.addEventListener("keydown", function (event) {
    // Nếu phím bấm là Escape (Esc)
    if (event.key === "Escape" || event.keyCode === 27) {
        // Kiểm tra xem hộp thoại có đang hiển thị không thì mới đóng
        const modal = document.getElementById("mcMessageBox");
        if (modal.classList.contains("active")) {
            closeMCBox();
        }
        const confirmBox = document.getElementById("mcConfirmBox");
        if (confirmBox.classList.contains("active")) {
            mcConfirmResolve(false); // Esc = Hủy
        }
    }
});