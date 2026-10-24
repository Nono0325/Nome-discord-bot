/**
 * Nome Bot Control Console & Monitoring Dashboard
 * Frontend Application Logic (Vanilla JavaScript)
 */

// Application State
let currentGuildId = null;
let guildsList = [];
let logFilterLevel = "ALL";
let logSearchQuery = "";
let isMusicPlaying = false;
let logEventSource = null;

// Initialize on DOM Ready
document.addEventListener("DOMContentLoaded", () => {
    initTabs();
    initQuickActions();
    initMusicControls();
    initLogStream();
    
    // Initial Data Fetches
    fetchStatus();
    fetchGuilds();
    loadRecordingsList();

    // Regular Polling Intervals
    setInterval(fetchStatus, 2000);
    setInterval(pollMusicPlayer, 1000);
    setInterval(pollRecordingStatus, 3000);
});

/* ==========================================================================
   Tab Navigation
   ========================================================================== */
function initTabs() {
    const tabs = document.querySelectorAll(".nav-tab");
    tabs.forEach(tab => {
        tab.addEventListener("click", () => {
            const targetId = tab.getAttribute("data-tab");
            switchTab(targetId);
        });
    });
}

function switchTab(tabId) {
    document.querySelectorAll(".nav-tab").forEach(t => {
        t.classList.toggle("active", t.getAttribute("data-tab") === tabId);
    });
    document.querySelectorAll(".tab-pane").forEach(p => {
        p.classList.toggle("active", p.id === tabId);
    });

    if (tabId === "tab-music") {
        pollMusicPlayer();
    } else if (tabId === "tab-recording") {
        pollRecordingStatus();
        loadRecordingsList();
    } else if (tabId === "tab-logs") {
        scrollLogToBottom();
    }
}

/* ==========================================================================
   Toast Notification System
   ========================================================================== */
function showToast(message, type = "info") {
    const container = document.getElementById("toast-container");
    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    
    let icon = "fa-circle-info";
    if (type === "success") icon = "fa-circle-check";
    if (type === "error") icon = "fa-circle-exclamation";
    if (type === "warning") icon = "fa-triangle-exclamation";

    toast.innerHTML = `<i class="fa-solid ${icon}"></i> <span>${message}</span>`;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = "0";
        toast.style.transform = "translateX(50px)";
        toast.style.transition = "all 0.3s ease";
        setTimeout(() => toast.remove(), 300);
    }, 3500);
}

/* ==========================================================================
   1. Global Status & System Metrics
   ========================================================================== */
async function fetchStatus() {
    try {
        const res = await fetch("/api/status");
        if (!res.ok) return;
        const data = await res.json();

        // Update Bot Header
        if (data.bot) {
            document.getElementById("bot-name").textContent = `${data.bot.name}#${data.bot.discriminator}`;
            document.getElementById("bot-id-tag").textContent = `ID: ${data.bot.id}`;
            if (data.bot.avatar) {
                document.getElementById("bot-avatar").src = data.bot.avatar;
            }
        }

        // Header Metrics
        document.getElementById("header-ping").textContent = `${data.latency_ms} ms`;
        document.getElementById("header-uptime").textContent = data.system.uptime_str;
        document.getElementById("header-mem").textContent = `${data.system.memory_mb} MB`;

        // Tab 1 Overview Cards
        document.getElementById("stat-ping").textContent = `${data.latency_ms} ms`;
        document.getElementById("stat-uptime").textContent = data.system.uptime_str;
        document.getElementById("stat-uptime-sec").textContent = `${data.system.uptime_seconds} 秒連續運行`;
        document.getElementById("stat-voice-count").textContent = data.voice_clients_count;
        document.getElementById("stat-playing-count").textContent = data.playing_count;
        document.getElementById("stat-guilds-count").textContent = data.guilds_count;

        // System Specs Panel
        document.getElementById("spec-threads").textContent = `${data.system.threads} 個執行緒`;
        document.getElementById("spec-memory").textContent = `${data.system.memory_mb} MB`;
        document.getElementById("spec-python").textContent = `Python ${data.system.python_version}`;

        // Active Voice Overview
        renderActiveVoiceList(data.playing_guilds);

    } catch (err) {
        console.error("fetchStatus error:", err);
    }
}

function renderActiveVoiceList(playingGuilds) {
    const container = document.getElementById("overview-voice-list");
    const badge = document.getElementById("active-voice-badge");
    
    if (!playingGuilds || playingGuilds.length === 0) {
        badge.textContent = "0 個播歌中";
        badge.className = "badge badge-secondary";
        container.innerHTML = `
            <div class="empty-placeholder">
                <i class="fa-solid fa-volume-xmark"></i>
                <p>目前所有語音頻道皆處於閒置或未播放狀態</p>
                <button class="btn btn-primary btn-sm" onclick="switchTab('tab-music')">前往音樂控制中心點播</button>
            </div>
        `;
        return;
    }

    badge.textContent = `${playingGuilds.length} 個伺服器播歌中`;
    badge.className = "badge badge-success";
    
    let html = "";
    playingGuilds.forEach(pg => {
        html += `
            <div class="voice-session-card">
                <div class="voice-session-info">
                    <h4><i class="fa-solid fa-compact-disc ${pg.is_paused ? '' : 'fa-spin text-accent'}"></i> ${pg.guild_name}</h4>
                    <p>正在播放: <strong>${pg.title || "未知曲目"}</strong> (${pg.duration})</p>
                </div>
                <button class="btn btn-secondary btn-sm" onclick="selectGuildAndOpenMusic('${pg.guild_id}')">
                    <i class="fa-solid fa-sliders"></i> 控制
                </button>
            </div>
        `;
    });
    container.innerHTML = html;
}

function selectGuildAndOpenMusic(guildId) {
    currentGuildId = guildId;
    const select = document.getElementById("music-guild-select");
    if (select) select.value = guildId;
    switchTab("tab-music");
}

/* ==========================================================================
   2. Guilds & Channels Management
   ========================================================================== */
async function fetchGuilds() {
    try {
        const res = await fetch("/api/guilds");
        if (!res.ok) return;
        guildsList = await res.json();

        // Update Guilds Dropdown in Music Tab
        const select = document.getElementById("music-guild-select");
        const prevValue = select.value;
        select.innerHTML = "";

        if (guildsList.length === 0) {
            select.innerHTML = '<option value="">未加入任何伺服器</option>';
            return;
        }

        guildsList.forEach(g => {
            const opt = document.createElement("option");
            opt.value = g.id;
            opt.textContent = `${g.name} ${g.voice_connected ? '🔊 (' + g.current_voice_channel + ')' : ''}`;
            select.appendChild(opt);
        });

        if (prevValue && guildsList.some(g => g.id === prevValue)) {
            select.value = prevValue;
            currentGuildId = prevValue;
        } else {
            // 優先選擇已連線語音的伺服器
            const activeGuild = guildsList.find(g => g.voice_connected) || guildsList[0];
            select.value = activeGuild.id;
            currentGuildId = activeGuild.id;
        }

        select.onchange = () => {
            currentGuildId = select.value;
            pollMusicPlayer();
            pollRecordingStatus();
        };

        // Update Tab 5 Guilds List
        renderGuildsCards();

    } catch (err) {
        console.error("fetchGuilds error:", err);
    }
}

function renderGuildsCards() {
    const grid = document.getElementById("guilds-cards-grid");
    document.getElementById("guilds-total-pill").textContent = `共 ${guildsList.length} 個伺服器`;

    if (guildsList.length === 0) {
        grid.innerHTML = '<div class="empty-placeholder"><p>機器人目前未加入任何 Discord 伺服器</p></div>';
        return;
    }

    let html = "";
    guildsList.forEach(g => {
        const icon = g.icon || "https://cdn.discordapp.com/embed/avatars/0.png";
        let vcHtml = "";
        
        if (g.voice_channels && g.voice_channels.length > 0) {
            g.voice_channels.forEach(vc => {
                const isCurrent = g.voice_connected && g.current_voice_channel_id === vc.id;
                vcHtml += `
                    <div class="guild-vc-row">
                        <span class="vc-name"><i class="fa-solid fa-volume-high"></i> ${vc.name} (${vc.members}人)</span>
                        ${isCurrent ? 
                            `<button class="btn btn-danger btn-xs" onclick="leaveVoice('${g.id}')"><i class="fa-solid fa-phone-slash"></i> 退出</button>` :
                            `<button class="btn btn-secondary btn-xs" onclick="joinVoice('${g.id}', '${vc.id}')"><i class="fa-solid fa-right-to-bracket"></i> 加入</button>`
                        }
                    </div>
                `;
            });
        } else {
            vcHtml = '<span class="text-dim text-xs">無可用的語音頻道</span>';
        }

        html += `
            <div class="guild-card">
                <div class="guild-card-header">
                    <img src="${icon}" class="guild-icon" alt="${g.name}">
                    <div>
                        <h3 class="guild-card-title">${g.name}</h3>
                        <span class="guild-card-members">${g.member_count} 位成員 ${g.voice_connected ? '&bull; <span class="text-success">連線中: ' + g.current_voice_channel + '</span>' : ''}</span>
                    </div>
                </div>
                <div class="guild-voice-channels">
                    ${vcHtml}
                </div>
            </div>
        `;
    });
    grid.innerHTML = html;
}

async function joinVoice(guildId, channelId) {
    try {
        const res = await fetch(`/api/voice/${guildId}/action`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action: "join", channel_id: channelId })
        });
        const data = await res.json();
        if (data.success) {
            showToast(`已成功連線至語音頻道: ${data.channel_name}`, "success");
            fetchGuilds();
        } else {
            showToast(`加入語音失敗: ${data.error}`, "error");
        }
    } catch (e) {
        showToast(`操作失敗: ${e}`, "error");
    }
}

async function leaveVoice(guildId) {
    try {
        const res = await fetch(`/api/voice/${guildId}/action`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action: "leave" })
        });
        const data = await res.json();
        if (data.success) {
            showToast("已退出語音頻道", "info");
            fetchGuilds();
        } else {
            showToast(`退出失敗: ${data.error}`, "error");
        }
    } catch (e) {
        showToast(`操作失敗: ${e}`, "error");
    }
}

/* ==========================================================================
   3. Music Controller Actions
   ========================================================================== */
function initMusicControls() {
    // Add Song Form
    const addForm = document.getElementById("form-add-song");
    addForm.addEventListener("submit", async () => {
        const queryInput = document.getElementById("input-song-query");
        const query = queryInput.value.trim();
        if (!query || !currentGuildId) return;

        showToast(`正在搜尋並載入: ${query}...`, "info");
        try {
            const res = await fetch(`/api/player/${currentGuildId}/action`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ action: "play", query })
            });
            const data = await res.json();
            if (data.success) {
                showToast(`已加入播放清單: ${data.first_song || query}`, "success");
                queryInput.value = "";
                pollMusicPlayer();
            } else {
                showToast(`點播失敗: ${data.error}`, "error");
            }
        } catch (e) {
            showToast(`點播例外: ${e}`, "error");
        }
    });

    // Control Buttons
    document.getElementById("btn-play-pause").onclick = () => {
        sendPlayerAction(isMusicPlaying ? "pause" : "resume");
    };
    document.getElementById("btn-skip").onclick = () => sendPlayerAction("skip");
    document.getElementById("btn-stop").onclick = () => sendPlayerAction("stop");
    document.getElementById("btn-shuffle").onclick = () => sendPlayerAction("shuffle");
    document.getElementById("btn-loop").onclick = () => {
        // Cycle loop mode: off -> song -> queue -> off
        const currentMode = document.getElementById("btn-loop").getAttribute("data-mode") || "off";
        let nextMode = "song";
        if (currentMode === "song") nextMode = "queue";
        else if (currentMode === "queue") nextMode = "off";
        sendPlayerAction("loop", { mode: nextMode });
    };
    document.getElementById("btn-autoplay").onclick = () => {
        sendPlayerAction("autoplay");
    };

    // Volume Slider
    const volSlider = document.getElementById("volume-slider");
    volSlider.oninput = () => {
        document.getElementById("volume-text").textContent = `${volSlider.value}%`;
        updateVolumeIcon(volSlider.value);
    };
    volSlider.onchange = () => {
        sendPlayerAction("volume", { volume: volSlider.value });
    };
}

async function sendPlayerAction(action, extra = {}) {
    if (!currentGuildId) {
        showToast("請先選擇伺服器！", "warning");
        return;
    }
    try {
        const payload = Object.assign({ action }, extra);
        const res = await fetch(`/api/player/${currentGuildId}/action`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.success) {
            pollMusicPlayer();
        } else {
            showToast(data.error || "操作失敗", "error");
        }
    } catch (e) {
        showToast(`指令傳送失敗: ${e}`, "error");
    }
}

async function pollMusicPlayer() {
    if (!currentGuildId) return;

    try {
        const res = await fetch(`/api/player/${currentGuildId}`);
        if (!res.ok) return;
        const data = await res.json();

        const disc = document.getElementById("vinyl-disc");
        const playBtn = document.getElementById("btn-play-pause");
        const statusBadge = document.getElementById("nowplaying-status");

        isMusicPlaying = data.is_playing;

        if (data.is_playing) {
            disc.classList.add("playing");
            playBtn.innerHTML = '<i class="fa-solid fa-pause"></i>';
            statusBadge.className = "track-state-badge badge-playing";
            statusBadge.innerHTML = '<i class="fa-solid fa-play"></i> 正在播放中';
        } else if (data.is_paused) {
            disc.classList.remove("playing");
            playBtn.innerHTML = '<i class="fa-solid fa-play"></i>';
            statusBadge.className = "track-state-badge badge-paused";
            statusBadge.innerHTML = '<i class="fa-solid fa-pause"></i> 已暫停';
        } else {
            disc.classList.remove("playing");
            playBtn.innerHTML = '<i class="fa-solid fa-play"></i>';
            statusBadge.className = "track-state-badge badge-idle";
            statusBadge.textContent = "閒置中";
        }

        // Loop mode styling
        const loopBtn = document.getElementById("btn-loop");
        loopBtn.setAttribute("data-mode", data.loop_mode);
        if (data.loop_mode === "song") {
            loopBtn.classList.add("active");
            loopBtn.innerHTML = '<i class="fa-solid fa-repeat"></i> <span style="font-size:9px;position:absolute;bottom:2px;">1</span>';
        } else if (data.loop_mode === "queue") {
            loopBtn.classList.add("active");
            loopBtn.innerHTML = '<i class="fa-solid fa-repeat"></i>';
        } else {
            loopBtn.classList.remove("active");
            loopBtn.innerHTML = '<i class="fa-solid fa-repeat"></i>';
        }

        // Autoplay styling
        const autoBtn = document.getElementById("btn-autoplay");
        autoBtn.classList.toggle("active", Boolean(data.autoplay));

        // Volume
        document.getElementById("volume-slider").value = data.volume;
        document.getElementById("volume-text").textContent = `${data.volume}%`;
        updateVolumeIcon(data.volume);

        // Track metadata
        if (data.current) {
            document.getElementById("nowplaying-title").textContent = data.current.title;
            document.getElementById("nowplaying-artist").textContent = data.current.artist;
            document.getElementById("nowplaying-requester").textContent = `點播者: ${data.current.requester}`;
            if (data.current.thumbnail) {
                document.getElementById("nowplaying-thumb").src = data.current.thumbnail;
            }
            document.getElementById("time-current").textContent = data.current.position_str;
            document.getElementById("time-duration").textContent = data.current.duration_str;
            document.getElementById("progress-bar-fill").style.width = `${data.current.progress_percent}%`;
        } else {
            document.getElementById("nowplaying-title").textContent = "目前未在播放音樂";
            document.getElementById("nowplaying-artist").textContent = "選取歌曲或於上方輸入搜尋以開始播放";
            document.getElementById("nowplaying-requester").textContent = "點播者: --";
            document.getElementById("time-current").textContent = "00:00";
            document.getElementById("time-duration").textContent = "00:00";
            document.getElementById("progress-bar-fill").style.width = "0%";
        }

        // Queue list
        renderQueueList(data.queue);

    } catch (e) {
        console.error("pollMusicPlayer error:", e);
    }
}

function updateVolumeIcon(vol) {
    const icon = document.getElementById("volume-icon");
    if (vol == 0) icon.className = "fa-solid fa-volume-xmark volume-icon text-danger";
    else if (vol < 40) icon.className = "fa-solid fa-volume-low volume-icon";
    else icon.className = "fa-solid fa-volume-high volume-icon";
}

function renderQueueList(queue) {
    const container = document.getElementById("queue-items-container");
    document.getElementById("queue-count-badge").textContent = `${queue.length} 首歌曲`;

    if (!queue || queue.length === 0) {
        container.innerHTML = `
            <div class="empty-placeholder">
                <i class="fa-solid fa-music"></i>
                <p>目前佇列中沒有排隊的歌曲</p>
            </div>
        `;
        return;
    }

    let html = "";
    queue.forEach((item, idx) => {
        html += `
            <div class="queue-item">
                <span class="queue-item-idx">#${item.index}</span>
                <img src="${item.thumbnail || 'https://images.unsplash.com/photo-1614613535308-eb5fbd3d2c17?w=100'}" class="queue-item-thumb">
                <div class="queue-item-meta">
                    <h5 class="queue-item-title">${item.title}</h5>
                    <span class="queue-item-artist">${item.artist} &bull; ${item.requester}</span>
                </div>
                <span class="queue-item-duration">${item.duration_str}</span>
                <button class="btn-remove-queue" onclick="removeQueueSong(${idx})" title="從清單移除">
                    <i class="fa-solid fa-trash-can"></i>
                </button>
            </div>
        `;
    });
    container.innerHTML = html;
}

function removeQueueSong(index) {
    sendPlayerAction("remove_queue", { index });
}

/* ==========================================================================
   4. Audio Recording & Instant Replay Clip Generator
   ========================================================================== */
async function pollRecordingStatus() {
    if (!currentGuildId) return;

    try {
        const res = await fetch(`/api/recording/${currentGuildId}/status`);
        if (!res.ok) return;
        const data = await res.json();

        const badge = document.getElementById("rec-live-badge");
        if (data.is_recording) {
            badge.className = "badge badge-danger";
            badge.innerHTML = '<i class="fa-solid fa-circle"></i> 60秒時光機待命中 (錄製中)';
        } else {
            badge.className = "badge badge-secondary";
            badge.textContent = "閒置中";
        }

        // Active Speakers
        const chipsContainer = document.getElementById("speakers-chips-container");
        if (data.speakers_in_60s && data.speakers_in_60s.length > 0) {
            let chipsHtml = "";
            data.speakers_in_60s.forEach(s => {
                const avatar = s.avatar || "https://cdn.discordapp.com/embed/avatars/0.png";
                chipsHtml += `
                    <div class="speaker-chip">
                        <img src="${avatar}">
                        <span>${s.name}</span>
                    </div>
                `;
            });
            chipsContainer.innerHTML = chipsHtml;
        } else {
            chipsContainer.innerHTML = '<span class="chip-empty">近 60 秒無人發言</span>';
        }

    } catch (e) {
        console.error("pollRecordingStatus error:", e);
    }
}

async function generateClip(seconds) {
    if (!currentGuildId) {
        showToast("請先選擇伺服器！", "warning");
        return;
    }

    showToast(`正在擷取前 ${seconds} 秒對話音訊並無損編碼 MP3...`, "info");
    try {
        const res = await fetch(`/api/recording/${currentGuildId}/clip`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ seconds })
        });

        if (!res.ok) {
            const errData = await res.json();
            showToast(errData.error || "剪輯失敗", "warning");
            return;
        }

        const filename = res.headers.get("X-Clip-Filename") || `clip_${seconds}s.mp3`;
        const blob = await res.blob();
        const audioUrl = URL.createObjectURL(blob);

        // Update preview player
        const previewBox = document.getElementById("clip-preview-box");
        const player = document.getElementById("clip-audio-player");
        const downloadLink = document.getElementById("clip-download-link");
        const fileNameSpan = document.getElementById("clip-file-name");

        fileNameSpan.textContent = filename;
        player.src = audioUrl;
        downloadLink.href = audioUrl;
        downloadLink.download = filename;

        previewBox.style.display = "flex";
        player.play();
        showToast(`前 ${seconds} 秒精彩對話剪輯完成！可立即試聽或下載。`, "success");

    } catch (e) {
        showToast(`剪輯例外: ${e}`, "error");
    }
}

/* Recordings History Table */
async function loadRecordingsList() {
    try {
        const res = await fetch("/api/recordings");
        if (!res.ok) return;
        const files = await res.json();

        const tbody = document.getElementById("recordings-tbody");
        if (!files || files.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted">目前本機尚未存檔任何 MP3 錄音檔</td></tr>';
            return;
        }

        let html = "";
        files.forEach(f => {
            html += `
                <tr>
                    <td><i class="fa-solid fa-file-audio text-accent"></i> <strong>${f.filename}</strong></td>
                    <td><span class="badge badge-secondary">${f.size_mb} MB</span></td>
                    <td class="text-muted">${f.created_at}</td>
                    <td>
                        <a href="${f.url}" download="${f.filename}" class="btn btn-secondary btn-xs"><i class="fa-solid fa-download"></i> 下載</a>
                        <button class="btn btn-danger btn-xs" onclick="deleteRecording('${f.filename}')"><i class="fa-solid fa-trash"></i> 刪除</button>
                    </td>
                </tr>
            `;
        });
        tbody.innerHTML = html;
    } catch (e) {
        console.error("loadRecordingsList error:", e);
    }
}

async function deleteRecording(filename) {
    if (!confirm(`確定要刪除錄音檔案 ${filename} 嗎？`)) return;
    try {
        const res = await fetch(`/api/recordings/${filename}`, { method: "DELETE" });
        const data = await res.json();
        if (data.success) {
            showToast(`已成功刪除 ${filename}`, "info");
            loadRecordingsList();
        } else {
            showToast(`刪除失敗: ${data.error}`, "error");
        }
    } catch (e) {
        showToast(`刪除例外: ${e}`, "error");
    }
}

/* ==========================================================================
   5. Live System Logs Terminal (Server-Sent Events)
   ========================================================================== */
function initLogStream() {
    const terminal = document.getElementById("terminal-body");
    
    if (logEventSource) {
        logEventSource.close();
    }

    try {
        logEventSource = new EventSource("/api/logs/stream");

        logEventSource.onmessage = (event) => {
            const rawLine = JSON.parse(event.data);
            appendLogLine(rawLine);
        };

        logEventSource.onerror = () => {
            console.warn("Log SSE Stream disconnected, reconnecting...");
        };
    } catch (e) {
        terminal.innerHTML = `<div class="log-line text-danger">[錯誤] 無法建立日誌串流連線: ${e}</div>`;
    }
}

function appendLogLine(line) {
    const terminal = document.getElementById("terminal-body");
    const div = document.createElement("div");
    div.className = "log-line";

    // Format log styling
    if (line.includes("[ERROR]")) div.classList.add("log-error");
    else if (line.includes("[WARNING]")) div.classList.add("log-warn");
    else if (line.includes("[INFO]")) div.classList.add("log-info");

    div.setAttribute("data-raw", line);

    // Apply Highlight
    div.innerHTML = escapeAndHighlightLog(line);

    // Filter check
    if (!matchesFilter(line)) {
        div.style.display = "none";
    }

    terminal.appendChild(div);

    // Limit buffer to 500 lines
    if (terminal.children.length > 500) {
        terminal.removeChild(terminal.children[0]);
    }

    if (document.getElementById("chk-autoscroll").checked) {
        terminal.scrollTop = terminal.scrollHeight;
    }
}

function escapeAndHighlightLog(text) {
    const escaped = text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
    
    // Format timestamp [YYYY-MM-DD HH:MM:SS]
    return escaped.replace(
        /^\[(\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2})\]\s\[([A-Z]+)\]\s([^:]+):/g,
        '<span class="log-ts">[$1]</span> <span class="log-level">[$2]</span> <span class="log-name">$3:</span>'
    );
}

function matchesFilter(line) {
    if (logFilterLevel !== "ALL" && !line.includes(`[${logFilterLevel}]`)) {
        return false;
    }
    if (logSearchQuery && !line.toLowerCase().includes(logSearchQuery.toLowerCase())) {
        return false;
    }
    return true;
}

function filterLogs(level) {
    logFilterLevel = level;
    document.querySelectorAll(".filter-pill").forEach(p => {
        p.classList.toggle("active", p.getAttribute("data-filter") === level);
    });
    refilterAllLogs();
}

function handleLogSearch(query) {
    logSearchQuery = query.trim();
    refilterAllLogs();
}

function refilterAllLogs() {
    const lines = document.querySelectorAll("#terminal-body .log-line");
    lines.forEach(lineDiv => {
        const raw = lineDiv.getAttribute("data-raw") || "";
        lineDiv.style.display = matchesFilter(raw) ? "block" : "none";
    });
    if (document.getElementById("chk-autoscroll").checked) {
        scrollLogToBottom();
    }
}

function clearLogTerminal() {
    document.getElementById("terminal-body").innerHTML = "";
}

function scrollLogToBottom() {
    const terminal = document.getElementById("terminal-body");
    terminal.scrollTop = terminal.scrollHeight;
}

/* ==========================================================================
   6. Quick Header Actions (Reload / Reboot)
   ========================================================================== */
function initQuickActions() {
    document.getElementById("btn-quick-reload").onclick = async () => {
        showToast("正在動態熱重載所有模組...", "info");
        try {
            const res = await fetch("/api/bot/action", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ action: "reload" })
            });
            const data = await res.json();
            if (data.success) {
                showToast(`所有模組已熱重載完成 (${data.reloaded.length} 個模組)`, "success");
            } else {
                showToast("熱重載失敗", "error");
            }
        } catch (e) {
            showToast(`執行失敗: ${e}`, "error");
        }
    };

    document.getElementById("btn-quick-restart").onclick = async () => {
        if (!confirm("⚠️ 您確定要完全重新啟動機器人主進程嗎？\n重啟將在約 3~5 秒內完成並重新連線。")) return;
        showToast("正在發起進程完全重啟...", "warning");
        try {
            const res = await fetch("/api/bot/action", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ action: "restart" })
            });
            const data = await res.json();
            if (data.success) {
                showToast("機器人進程正在重啟中，請稍候重新整理頁面...", "info");
            }
        } catch (e) {
            showToast(`重啟發起失敗: ${e}`, "error");
        }
    };
}
