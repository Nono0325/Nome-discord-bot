# 🎵 Discord YouTube Music & 語音對話錄音機器人

這是一個專為 Discord 設計的全功能音樂與錄音機器人，具備以下強大特色：
1. **Google 帳號整合**：登入 Google 帳號後，可直接在語音頻道播放個人的 **YouTube Music** 歌單、已按讚歌曲（Liked Songs）與延伸電台。即使未登入，也能透過訪客模式暢播任何公開歌曲！
2. **前一分鐘語音回放（Instant Replay Clip）**：在語音頻道通話時，機器人會於記憶體中維護滾動式循環緩衝區（Rolling Buffer）。隨時輸入 `/clip`（或點擊播放介面按鈕），機器人將**自動將過去 60 秒所有成員的發言對話依真實時間軸混音成單一立體聲 MP3** 並直接上傳至頻道！
3. **全程自動錄音存檔**：支援 `/autorecord` 設定，機器人進入語音頻道後可自動開始全程錄音，通話結束後自動混音並輸出為 MP3 存檔。
4. **人數達標自動進出語音頻道**：當任一語音頻道聚集 2 位以上成員時，機器人將自動連線加入開始維護對話緩衝區；當成員離開至無人（或未播放音樂且人數少於 2 人）時自動離開以節省伺服器頻寬。

---

## 🚀 快速安裝與環境需求

本專案已為您配置好 Python 虛擬環境 (`.venv`) 與 `FFmpeg 9.0.1` 核心。

### 依賴套件
- **Python**: 3.11+
- **核心套件**: `py-cord[voice]`, `yt-dlp`, `ytmusicapi`, `pydub`, `python-dotenv`

---

## 🔑 步驟一：設定 Discord 機器人 Token

您提供的資訊：
- **Application / Client ID**: `1562031172777938954`
- **Public Key**: `872c8d90e80e0d6c3ee0fc801415ff76ce13551b31cf88fac6233670924ab819`

### 如何取得機器人 Token（Bot Token）：
1. 開啟 [Discord Developer Portal](https://discord.com/developers/applications/1562031172777938954/bot)。
2. 點擊左側選單的 **「Bot」**。
3. 在 **「Build-A-Bot」** 區域點擊 **「Reset Token」**，複製產生出的 Bot Token（格式如：`MTU2...xxx.yyy.zzz`）。
4. 在下方 **「Privileged Gateway Intents」** 區塊，**務必勾選啟用以下選項**：
   - ✅ **PRESENCE INTENT**
   - ✅ **SERVER MEMBERS INTENT**
   - ✅ **MESSAGE CONTENT INTENT**
5. 打開專案根目錄的 `.env` 檔案，將 Token 貼在：
   ```env
   DISCORD_TOKEN=你的_DISCORD_BOT_TOKEN
   ```

### 邀請機器人加入伺服器：
點擊下方專屬授權連結，將機器人邀請至您的 Discord 伺服器：
👉 [點我邀請機器人到伺服器](https://discord.com/oauth2/authorize?client_id=1562031172777938954&permissions=3238912&scope=bot%20applications.commands)

*(具備連線語音、說話、發言、Slash 指令等必備權限)*

---

## 🔐 步驟二：綁定 Google 帳號 (YouTube Music)

登入 Google 帳號後即可存取個人的 YouTube Music 按讚音樂與私人歌單。

我們提供了一鍵式小幫手，請在終端機執行：
```powershell
.\.venv\Scripts\python.exe setup_google.py
```

### 支援的三種登入方式：
1. **模式 1：Google 官方設備碼登入（推薦、最安全）**
   - 終端機會顯示一組代碼，並引導您打開 [google.com/device](https://www.google.com/device)。
   - 輸入代碼並登入 Google 帳號按下「允許」，機器人將自動取得憑證並儲存至 `config/oauth.json`。
2. **模式 2：瀏覽器請求標頭（Browser Headers，免建立 Google Cloud 憑證）**
   - 打開 [music.youtube.com](https://music.youtube.com) 並登入。
   - 按 F12 開啟開發人員工具 -> Network -> 找到任一請求右鍵複製請求標頭（Copy Request Headers）貼至終端機，自動存為 `config/browser.json`。
3. **模式 3：cookies.txt**
   - 使用瀏覽器擴充套件匯出 `cookies.txt`，直接放入 `config/cookies.txt` 即可。

> 💡 **提示**：即使不綁定 Google 帳號，機器人也會自動以**訪客模式**運作，依然可以透過 `/play` 搜尋並播放全世界所有公開的 YouTube Music 歌曲！

---

## 🎮 步驟三：啟動機器人

在專案目錄下執行以下指令：
```powershell
.\.venv\Scripts\python.exe main.py
```
當終端機顯示 `🤖 機器人已成功上線！` 即代表就緒！

---

## 📋 完整指令表 (Slash Commands)

### 🎛️ 視覺化全功能互動控制台 (Dashboard - 免打指令首選！)
> 💡 **告別記憶指令！** 機器人支援完整的圖形化互動面板與視窗彈窗（Modals），所有功能皆可一鍵點擊完成。

| 指令 | 說明 |
| :--- | :--- |
| `/panel` | **首推推薦！** 召喚全功能視覺化控制台，包含 6 大分類切換選單、15 個即時快捷按鈕與點歌/解答彈出式輸入視窗！ |
| `/setup_panel [頻道]` | 在專屬文字頻道建立並**自動置頂釘選**永久控制台，全體成員隨時點擊即用！ |

### 🎵 音樂播放指令群
| 指令 | 說明 |
| :--- | :--- |
| `/join [語音頻道]` | 指定讓機器人加入特定的語音頻道（亦支援彈出互動式下拉選單挑選） |
| `/leave` | 讓機器人退出目前的語音頻道 |
| `/play <歌曲或網址> [語音頻道]` | 在語音頻道播放 YouTube Music 歌曲（可選填指定欲播放之語音頻道） |
| `/ytm_liked [數量]` | 播放您 Google 帳號中的「已按讚的好音樂（Liked Songs）」 |
| `/ytm_playlists` | 彈出下拉選單，瀏覽並點播 Google 帳號內的個人播放清單 |
| `/ytm_radio <歌曲>` | 根據指定歌曲自動產生無限推薦電台並加入佇列 |
| `/autoplay [開/關]` | **新功能！** 切換無盡推薦電台模式（佇列播完自動推薦續播相似歌曲） |
| `/genre <風格>` | **新功能！** 播放指定曲風或情境（動漫、Lo-Fi、搖滾、流行、爵士、電音等 12+ 種風格） |
| `/genres` | **新功能！** 開啟互動式曲風與情境音樂專區選單 |
| `/random_play` | **新功能！** 隨機探索當前熱門流行單曲與精選好歌 |
| `/shuffle` | **新功能！** 隨機混洗當前佇列順序 |
| `/pause` / `/resume` | 暫停 / 繼續播放 |
| `/skip` | 跳至下一首歌曲 |
| `/stop` | 停止播放、清空佇列並讓機器人退出語音頻道 |
| `/queue` | 查看目前的播放佇列清單 |
| `/lyrics [歌曲] [mode]` | **新功能！** 即時顯示目前播放歌曲的動態同步歌詞 (卡拉OK即時滾動) 或查詢特定歌曲完整歌詞 |
| `/nowplaying` | 顯示正在播放歌曲的精緻卡片與即時互動控制按鈕 (含「⭐ 收藏本曲」按鈕) |
| `/volume <0-100>` | 調整播放音量百分比 |
| `/loop <模式>` | 切換循環模式：關閉 / 單曲循環 / 清單循環 |

### ⭐ 個人私房收藏歌單 (Personal Favorites - 新亮點功能！)
> 💡 打造專屬於您的音樂庫！在播放歌曲時隨時點擊卡片上的「⭐ 收藏本曲」即可一鍵存入，支援隨機混洗電台播放！

| 指令 | 說明 |
| :--- | :--- |
| `/favorites` | **新功能！** 召喚個人私房收藏歌單面板（支援單曲挑選、一鍵全部播放、隨機混洗與個別刪除） |
| `/favorite_add [歌曲]` | **新功能！** 將當前正在播放的歌曲，或指定的歌曲直接加入個人收藏庫 |
| `/favorite_play [shuffle]` | **新功能！** 一鍵在語音頻道點播個人全部收藏歌曲（可自選是否隨機混洗） |

### 🎙️ 語音錄音與 1 分鐘對話回放指令群
| 指令 | 說明 |
| :--- | :--- |
| `/clip [秒數]` | **核心功能！** 擷取過去 60 秒（或自訂秒數）所有成員的語音對話，自動對齊時間軸混音成立體聲 MP3 並發送至頻道！ |
| `/autorecord <true/false>` | 開啟或關閉進入語音時的「全程自動錄音存檔」 |
| `/record_start` | 手動開始一場會議／對話錄音 |
| `/record_stop` | 結束手動錄音，混音後存檔至 `recordings/` 目錄並上傳至頻道 |
| `/record_status` | 查看目前語音頻道錄音緩衝區與最近 60 秒有說話的成員 |

### 🔄 不斷線更新與多工管理指令群
| 指令 | 說明 |
| :--- | :--- |
| `/reload [模組]` | **零停機熱重載！** 無需重啟機器人、不中斷語音與音樂，動態重載 Python 模組與指令 |
| `/git_pull` | **雲端熱更新！** 直接從 GitHub 抓取最新程式庫並自動完成零停機熱重載 |
| `/restart [force]` | **新功能！** 完全重新啟動機器人主進程（具備防誤觸確認對話框與重啟就緒自動回報） |
| `/sysinfo` | 查看多工運作狀態（背景 Thread 數量、延遲 Ping、連線伺服器與運行時間） |

### 🔑 帳號管理指令群
| 指令 | 說明 |
| :--- | :--- |
| `/google_status` | 查看目前 Google 帳號認證狀態與已解鎖功能 |
| `/google_login` | 獲取 Google 帳號綁定指南與授權流程說明 |
| `/google_logout` | 登出目前的 Google 憑證並切換回訪客模式 |

### 📖 解答之書 (The Book of Answers) 指令群
| 指令 | 說明 |
| :--- | :--- |
| `/book [問題] [secret]` | **新功能！** 翻開神秘的《解答之書》，為您心中的疑惑指引迷津（支援悄悄話模式與互動按鈕翻閱） |
| `/book_daily` | **新功能！** 抽取今日專屬解答之書頁，獲取一整天的生活靈魂啟示與能量指針 |

### 📌 專屬文字頻道管理指令群
| 指令 | 說明 |
| :--- | :--- |
| `/set_channel [頻道]` | 設定專屬音樂文字頻道（支援直接指定或彈出互動式下拉選單挑選） |
| `/channel_status` | 查看目前伺服器所設定的專屬音樂文字頻道與運作模式 |
| `/clear_channel` | 清除專屬頻道綁定，恢復為隨使用者點歌頻道即時回應 |

---

## 📂 專案結構說明

```
Discord-Boot/
├── .env                  # 設定檔 (包含 Token、設定開關)
├── main.py               # 機器人主入口程式
├── setup_google.py       # Google 帳號登入授權精靈
├── config/
│   ├── settings.py       # 全域設定與路徑載入器
│   ├── oauth.json        # Google OAuth 憑證 (自動產生)
│   └── browser.json      # 瀏覽器標頭憑證 (選用)
├── core/
│   ├── favorites_manager.py # 個人私房收藏歌單持久化管理器
│   ├── audio_mixer.py    # 時間軸多軌多成員對話混音引擎 (支援連續游標對齊與峰值標準化)
│   ├── pycord_patch.py   # Pycord 語音接收與 DAVE / JitterBuffer 熱修復補丁
│   ├── recorder.py       # 60秒循環緩衝區 (RollingBufferSink) 與會話錄音
│   └── voice_manager.py  # 語音連線、播放器與錄音器中央管理器
├── music/
│   ├── ytm_client.py     # YouTube Music API 封裝 (支援 OAuth / 訪客模式)
│   ├── ytdl_source.py    # yt-dlp 串流解析與 FFmpeg 音訊來源
│   ├── lyrics_service.py # LRCLIB 高精度動態時間戳與 YouTube Music 官方歌詞服務
│   ├── lyrics_view.py    # 卡拉OK動態同步滾動視圖與長篇分頁視圖
│   ├── favorites_view.py # 私房收藏歌單下拉選單、播放與移除互動視圖
│   └── player.py         # 伺服器播放佇列、循環與即時按鈕面板
├── cogs/
│   ├── panel_cog.py      # 全功能視覺化互動控制台與點歌/解答彈窗 (免打指令)
│   ├── music_cog.py      # 音樂播放、隨機、曲風、歌詞與佇列 Slash 指令
│   ├── record_cog.py     # 語音剪輯 (/clip) 與全程錄音 Slash 指令
│   ├── book_cog.py       # 神秘《解答之書》心靈指引與每日能量 Slash 指令
│   ├── channel_cog.py    # 專屬音樂文字頻道綁定 Slash 指令
│   ├── admin_cog.py      # 不斷線更新 (/reload, /git_pull) 與多工系統監控
│   └── auth_cog.py       # Google 帳號與 YouTube Music 授權狀態 Slash 指令
└── recordings/           # 自動儲存的完整錄音 MP3 目錄
```
