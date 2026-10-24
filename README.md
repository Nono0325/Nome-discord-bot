# 🎵 Discord YouTube Music & 語音對話錄音旗艦機器人

<div align="center">

![Python Version](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Pycord](https://img.shields.io/badge/Py--Cord-2.8.1-5865F2?style=for-the-badge&logo=discord&logoColor=white)
![YouTube Music](https://img.shields.io/badge/YouTube%20Music-Hi--Fi%20Audio-FF0000?style=for-the-badge&logo=youtubemusic&logoColor=white)
![FFmpeg](https://img.shields.io/badge/FFmpeg-9.0.1%20Ready-007808?style=for-the-badge&logo=ffmpeg&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux-0078D6?style=for-the-badge&logo=windows&logoColor=white)
![Thread Safe](https://img.shields.io/badge/Thread%20Safety-Zero--Leak%20Lifecycle-2ECC71?style=for-the-badge&logo=shield&logoColor=white)

**專為高品質社群語音量身打造！融合 Google 官方 YouTube Music 個人歌單、60 秒語音時光機、多工執行緒安全釋放與全視覺化互動控制台的次世代 Discord 機器人。**

[✨ 核心特色](#-核心特色與黑科技架構) • [🚀 快速啟動](#-快速安裝與啟動指南) • [📋 指令大全](#-完整指令指南-slash-commands) • [🎛️ 互動控制台](#-全功能互動控制台-dashboard) • [📂 專案架構](#-專案架構說明) • [❓ 常見問題](#-常見問題與疑難排解-faq)

</div>

---

## 🌟 核心特色與黑科技架構

### 1. 🎵 頂級音質 YouTube Music 旗艦串流
- **Google 帳號私人歌單支援**：登入 Google 帳號後，直接在語音頻道點播個人 **YouTube Music 喜愛的歌曲（Liked Songs）**、私人播放清單與專屬電台。
- **免登入訪客模式（Guest Mode）**：未綁定帳號亦能以訪客身分秒速搜尋並播放全球所有公開音樂。
- **極速本地無損快取 (Local Audio Cache)**：自動快取熱門歌曲至本機並進行 LRU 磁碟空間智慧管理，切歌 **0.00 秒零延遲**，徹底告別 YouTube 網路抖動與 `WinError 10054` 連線重置！
- **20ms 雙向平滑記憶體緩衝區 (`BufferedAudioSource`)**：在背景預讀取音訊訊框至 RAM 隊列，杜絕 I/O 停頓與跳針。
- **48kHz Hi-Fi 原音品質 & Opus FEC**：動態匹配伺服器最高上限頻寬（最高 384 kbps），啟用 Opus 抗丟包前向補償（FEC）。
- **無盡推薦電台 (`/autoplay`) & 12+ 情境曲風 (`/genre`)**：佇列播放完畢自動演算法探勘推薦曲目；內建動漫、Lo-Fi、抒情、電音、爵士等豐富主題專區。

### 2. 🎙️ 60 秒語音對話時光機 (Instant Replay Clip)
- **記憶體滾動循環緩衝區 (Rolling Buffer)**：機器人於語音頻道時，自動在 RAM 維護過去 60 秒成員發言封包。
- **直通無損音訊編碼 (Direct Unmixed Stream Encoding)**：依發言時間軸無損銜接原始 PCM 訊框，完全不經過耗損性的多軌過濾，**100% 完整保留說話字句與細節**！
- **一鍵擷取與自動存檔**：輸入 `/clip`（或點擊面板按鈕），立即將剛才發生的精彩爆笑對話轉碼為 320k 立體聲 MP3 並上傳至頻道。
- **全場自動錄音 (`/autorecord`)**：支援通話全程自動背景錄製，全員退房時自動封裝 MP3 上傳存檔。
- **Pycord 官方 DAVE E2EE 穿透熱補丁**：內建獨家 Monkey Patch，解決 Discord 全新端到端加密協定導致的靜音與解碼報錯問題。

### 3. 🧵 工業級執行緒生命週期安全釋放 (Zero-Leak Thread Safety)
- **多工執行緒池生命週期接管 (`AudioMixerWorker`)**：提供全域非同步音訊工作線程池安全釋放機制，徹底根除 Windows 執行緒洩漏（Thread Leaks）。
- **進程與管線保護 (Process & Pipe Safety)**：FFmpeg 子行程與 I/O 管道實裝 `try...finally` 主動關閉，根除殭屍行程與通訊管道中斷例外 (`0x800700e8`)。
- **全域中斷與關閉保險絲 (`atexit` & Signal Handlers)**：無論是正常退出、`/restart` 重啟或接收到 `Ctrl+C` 終斷，皆能 100% 安全回收所有語音連線、播放緒與監聽器。

### 4. 🎛️ 全功能視覺化控制台 (Dashboard UI)
- **免打指令圖形化介面 (`/panel` & `/setup_panel`)**：包含 6 大分類分頁選單、15 個即時狀態快捷按鈕、點歌/解答之書彈出式視窗（Modal）。
- **即時正在播放卡片 (`/nowplaying`)**：高質感 Embed 卡片，支援即時暫停、切歌、音量調整、單曲循環、隨機播放與「⭐ 收藏本曲」。

### 5. 🎤 動態即時同步滾動歌詞 (Real-Time Synced Lyrics)
- **高精度卡拉OK同步模式**：整合 LRCLIB 與 YouTube Music 雙重歌詞來源，依播放秒數即時動態滾動高亮當前歌詞行。

### 6. ⚡ 零停機動態熱更新 (Zero-Downtime Hot-Reload)
- **不斷音熱重載 (`/reload`)**：無需重新啟動程式，語音通話與音樂播放不中斷，即時重載 Python 模組與指令。
- **雲端同步 (`/git_pull`)**：一鍵由 GitHub 遠端拉取最新更新並完成無縫熱切換。

### 7. 📖 神秘心靈啟示《解答之書》 (The Book of Answers)
- 收錄 180+ 條中英雙語對照之啟示庫，涵蓋決策、感情、哲思與趣味詼諧，支援每日抽取能量籤與悄悄話模式。

---

## 🚀 快速安裝與啟動指南

本專案已為您配置好專屬 Python 虛擬環境 (`.venv`) 與 `FFmpeg 9.0.1` 核心，開箱即用！

### 步驟一：填入 Discord Bot Token
1. 前往 [Discord Developer Portal](https://discord.com/developers/applications) 建立或選擇您的應用程式。
2. 進入左側 **「Bot」** 分頁，點擊 **「Reset Token」** 複製產生的 Bot Token。
3. 往下滑至 **「Privileged Gateway Intents」** 區塊，**務必啟用以下特權意圖**：
   - ✅ **PRESENCE INTENT**
   - ✅ **SERVER MEMBERS INTENT**
   - ✅ **MESSAGE CONTENT INTENT**
4. 開啟專案根目錄下的 `.env` 檔案，將 Token 填入：
   ```env
   DISCORD_TOKEN=你的_DISCORD_BOT_TOKEN
   ```

> 🔗 **邀請機器人進入伺服器**：  
> [點我透過專屬授權連結邀請機器人](https://discord.com/oauth2/authorize?client_id=1562031172777938954&permissions=3238912&scope=bot%20applications.commands)

---

### 步驟二：綁定 Google 帳號 (YouTube Music)

> 💡 **選用功能**：若不登入 Google，機器人將預設以**訪客模式**運作，依然能暢播全球所有公開歌曲！

若欲串接個人的「已按讚歌曲」與私人歌單，請在專案目錄下啟動授權精靈：
```powershell
.\.venv\Scripts\python.exe setup_google.py
```
**精靈提供三種認證模式**：
1. **模式 1：Google 設備碼配對（最推薦、最安全）**：
   - 終端機顯示一組 8 碼配對碼，打開 [google.com/device](https://www.google.com/device) 輸入並確認授權，自動生成 `config/oauth.json`。
2. **模式 2：瀏覽器請求標頭 (Browser Headers)**：
   - 開啟 [music.youtube.com](https://music.youtube.com) 登入後按 F12，複製任一 Request Headers 貼入即可。
3. **模式 3：cookies.txt 匯入**：
   - 將瀏覽器擴充套件匯出的 Netscape 格式 cookie 放置於 `config/cookies.txt`。

---

### 步驟三：啟動機器人

您可透過以下任一方式極速啟動：

#### 方式 A：雙擊一鍵啟動腳本（最推薦，防錯且支援自動重連）
直接雙擊專案目錄下的：
```batch
start.bat
```

#### 方式 B：透過終端機指令啟動
```powershell
.\.venv\Scripts\python.exe main.py
```

#### 方式 C：VS Code 內建環境
專案已內建 [`.vscode/settings.json`](file:///c:/NonoCode/Discord-Boot/.vscode/settings.json)，在 VS Code 中開啟專案後，直接於 `main.py` 右鍵點選「**在終端機中執行 Python 檔案**」，將自動載入虛擬環境直譯器執行。

當終端機印出 `🤖 機器人已成功上線！` 時，即代表所有功能模組已全新就緒！

---

## 📋 完整指令指南 (Slash Commands)

### 🎛️ 全功能互動控制台 (Dashboard)
> 💡 告別繁瑣記憶指令！推薦在伺服器專屬音樂頻道釘選面板，全體成員點擊按鈕即可進行所有操作。

| 斜線指令 | 說明 |
| :--- | :--- |
| `/panel` | **【推薦首選】** 召喚全功能視覺化互動控制台，內建 6 大選單、15 個即時快捷按鈕與彈出式輸入框 |
| `/setup_panel [頻道]` | 在指定的文字頻道建立**自動置頂釘選**的永久控制台面板（管理員限定） |

---

### 🎵 音樂播放與佇列控制
| 斜線指令 | 參數 | 說明 |
| :--- | :--- | :--- |
| `/play` | `<歌曲名稱或網址> [語音頻道]` | 播放指定歌曲或網址（支援 YouTube / YouTube Music，支援搜尋與自選頻道） |
| `/join` | `[語音頻道]` | 讓機器人連線至指定的語音頻道（亦可由互動下拉選單挑選） |
| `/leave` | 無 | 讓機器人中斷連線並退出語音頻道 |
| `/nowplaying` | 無 | 顯示當前播放中的精緻 Embed 卡片與即時互動控制按鈕 |
| `/pause` | 無 | 暫停當前音樂播放 |
| `/resume` | 無 | 繼續播放暫停中的音樂 |
| `/skip` | 無 | 立即跳過當前歌曲並播放下一首（安全釋放前首音訊背景線程） |
| `/stop` | 無 | 停止播放、清空佇列並釋放所有播放器工作資源 |
| `/queue` | 無 | 查看目前伺服器的播放清單與排隊歌曲 |
| `/shuffle` | 無 | 隨機打亂當前播放佇列順序 |
| `/loop` | `<off / song / queue>` | 切換循環模式：關閉循環 / 單曲循環 / 清單循環 |
| `/volume` | `<0-100>` | 調整音樂播放音量百分比 |
| `/autoplay` | `[開啟/關閉]` | 切換無盡電台模式（佇列播畢自動推薦相似音樂續播） |
| `/genre` | `<風格名稱>` | 探索指定主題曲風（動漫、Lo-Fi、抒情、流行、搖滾、爵士、電音等 12+ 種風格） |
| `/genres` | 無 | 開啟視覺化曲風專區下拉選單 |
| `/random_play`| 無 | 隨機探索播放當前 YouTube Music 發燒流行榜好歌 |
| `/lyrics` | `[歌曲名稱] [mode: dynamic/full]` | 開啟即時動態滾動卡拉OK歌詞，或查詢指定歌曲完整歌詞 |

---

### ⭐ 個人私房收藏庫 (Personal Favorites)
> 💡 打造專屬於個人的 Discord 音樂庫！播放音樂時隨時點擊卡片上的「⭐ 收藏本曲」即可一鍵存入個人清單。

| 斜線指令 | 說明 |
| :--- | :--- |
| `/favorites` | 開啟個人私房收藏歌單面板（支援單曲點播、一鍵全部播放、隨機混洗電台與歌曲移除） |
| `/favorite_add [歌曲]` | 將當前正在播放的歌曲，或指定的歌曲新增至個人私房清單 |
| `/favorite_play [shuffle]` | 一鍵在語音頻道播放個人所有的私房收藏歌曲（可自選是否隨機混洗） |

---

### 🎙️ 語音錄音與 60 秒回放剪輯
| 斜線指令 | 參數 | 說明 |
| :--- | :--- | :--- |
| `/clip` | `[秒數: 預設 60]` | **【核心黑科技】** 立即擷取剛才所有成員的語音對話，自動對齊時間軸無損混音成立體聲 MP3 上傳 |
| `/autorecord` | `<true/false>` | 設定進入語音頻道時是否自動全程錄音並於退房時自動存檔上傳 |
| `/record_start`| 無 | 手動開啟一場會議錄音 |
| `/record_stop` | 無 | 手動結束錄音，立即輸出完整 MP3 檔案至頻道 |
| `/record_status`| 無 | 查看當前錄音緩衝區運作狀態與最近發言活躍之成員清單 |

---

### 📖 解答之書 (The Book of Answers)
| 斜線指令 | 參數 | 說明 |
| :--- | :--- | :--- |
| `/book` | `[心中疑惑] [secret: 是/否]` | 翻開神秘的《解答之書》指引迷津（支援互動按鈕翻閱下一頁與悄悄話私密模式） |
| `/book_daily` | 無 | 抽取今日專屬解答之書頁，獲取一整天的生活靈魂啟示與正能量指針 |

---

### 🔄 零停機熱維護與系統監控 (Admin Only)
| 斜線指令 | 參數 | 說明 |
| :--- | :--- | :--- |
| `/reload` | `[指定模組]` | **零停機熱重載！** 不中斷語音與播歌流程，動態熱更新 Python 邏輯並自動釋放舊線程池（管理員限定） |
| `/git_pull` | 無 | **雲端熱更新！** 從 GitHub 遠端同步最新代碼並自動完成所有模組動態重載（管理員限定） |
| `/restart` | `[force: 是/否]` | 安全重新啟動機器人主進程（具備防誤觸二次確認對話框與重啟就緒自動通知，管理員限定） |
| `/logs` | `[lines] [as_file]` | **即時日誌檢視！** 在 Discord 內直接查看最新日誌紀錄或下載完整 `bot.log`（管理員限定） |
| `/sysinfo` | 無 | 查看系統多工健康儀表板（活動背景執行緒數、Gateway Ping 延遲、連線數與連續運行時間） |

---

### 📌 頻道與認證設定
| 斜線指令 | 說明 |
| :--- | :--- |
| `/set_channel [頻道]` | 設定專屬音樂文字頻道（所有點歌卡片與通知將自動集中發送） |
| `/channel_status` | 查看目前伺服器設定之專屬頻道與運作模式 |
| `/clear_channel` | 清除專屬頻道設定，恢復為隨使用者操作文字頻道即時回應 |
| `/google_status` | 查看目前 Google 帳號授權狀態與已解鎖功能 |
| `/google_login` | 檢視 Google 帳號綁定流程指引 |
| `/google_logout` | 登出目前 Google 帳號憑證並無縫切換為訪客模式 |

---

## 📂 專案架構說明

```
Discord-Boot/
├── .env.example             # 環境變數範例檔
├── .gitignore               # Git 忽略配置清單
├── requirements.txt         # Python 依賴套件清單
├── main.py                  # 機器人主入口程式 (含 atexit 全域安全釋放保險絲與雙通道日誌)
├── setup_google.py          # Google 帳號互動式授權精靈 (支援設備碼/標頭/Cookie)
├── start.bat                # Windows 一鍵啟動腳本
├── logs/                    # 系統輪轉日誌目錄 (自動生成 bot.log，最高 10MB 輪轉備份)
├── .vscode/
│   └── settings.json        # VS Code 預設虛擬環境與終端機配置
├── config/
│   ├── settings.py          # 全域環境設定、目錄與 FFmpeg 路徑解析器
│   ├── guild_settings.py    # 伺服器專屬頻道與個性化設定持久化
│   ├── oauth.json           # Google OAuth 憑證檔 (自動生成)
│   └── favorites.json       # 使用者私房收藏庫持久化存檔
├── core/
│   ├── audio_mixer.py       # 音訊轉碼引擎與執行緒池生命週期管理器 (支援直通編碼與安全釋放)
│   ├── favorites_manager.py # 個人收藏庫資料儲存與查詢服務
│   ├── guild_settings.py    # 伺服器自訂位元率與專屬音樂頻道邏輯
│   ├── pycord_patch.py      # Pycord 官方 DAVE E2EE 穿透熱補丁與執行緒防洩漏增強
│   ├── recorder.py          # 60 秒滾動緩衝區 (RollingBufferSink) 與會話錄音器
│   └── voice_manager.py     # 全域語音連線、播放器與錄音器中央生命週期管理器
├── music/
│   ├── ytm_client.py        # YouTube Music API 封裝 (支援 OAuth / 訪客模式 / 電台探勘)
│   ├── ytdl_source.py       # 本地無損音訊快取 (Local Cache) 與雙向平滑緩衝讀取緒
│   ├── player.py            # 單一伺服器播放佇列、無盡電台、跳曲與資源回收核心
│   ├── lyrics_service.py    # LRCLIB 高精度時間戳動態歌詞與 YTM 歌詞服務
│   ├── lyrics_view.py       # 卡拉OK動態同步滾動歌詞 UI 視圖
│   └── favorites_view.py    # 私房收藏庫下拉選單、混洗播放與移除互動視圖
├── cogs/
│   ├── panel_cog.py         # 全功能視覺化互動控制台與點歌/解答彈窗 (免打指令)
│   ├── music_cog.py         # 音樂播放、隨機、曲風、歌詞與佇列 Slash 指令集
│   ├── record_cog.py        # 語音剪輯 (/clip) 與會議錄音 Slash 指令集
│   ├── book_cog.py          # 神秘《解答之書》心靈指引與每日能量 Slash 指令集
│   ├── channel_cog.py       # 專屬音樂文字頻道綁定 Slash 指令集
│   ├── admin_cog.py         # 零停機熱更新 (/reload, /git_pull) 與多工系統監控
│   └── auth_cog.py          # Google 帳號與 YouTube Music 授權狀態 Slash 指令集
├── cache/                   # 本地高音質音樂快取目錄 (自動維護 LRU 清理)
└── recordings/              # 自動儲存之會議與通話錄音 MP3 目錄
```

---

## ❓ 常見問題與疑難排解 (FAQ)

### Q1：啟動時遭遇錯誤 `2147942632 (0x800700e8)` 或終端機立即閃退？
- **原因**：這是 Windows 系統錯誤代碼 `ERROR_NO_DATA`（管道正在被關閉），通常是因為系統選取了全域 Python，或是前次執行的進程/管道尚未釋放。
- **解法**：
  1. 請確保使用虛擬環境中的 Python：`.\.venv\Scripts\python.exe main.py`。
  2. 或直接雙擊執行目錄下的 [`start.bat`](file:///c:/NonoCode/Discord-Boot/start.bat)。
  3. 專案已實裝完善的執行緒池與管道自動清理機制，確保各模組在關閉時皆能 100% 釋放資源。

### Q2：播歌時完全沒有聲音，但機器人顯示正在播放？
- **原因**：Discord 於近期升級了全新端到端加密協定（DAVE），舊版本或未打補丁的機器人會因加密未收斂而處於靜音狀態。
- **解法**：
  - 本專案已在 [`core/pycord_patch.py`](file:///c:/NonoCode/Discord-Boot/core/pycord_patch.py) 實裝自動 Monkey Patch，啟動時即自動開啟 DAVE Passthrough 穿透模式，保證音樂清晰流暢播放！

### Q3：如何開啟或關閉人數達標自動進出語音？
- 請開啟 `.env` 檔案調整以下參數：
  ```env
  AUTO_JOIN_ENABLED=true      # 是否開啟自動加入語音
  AUTO_JOIN_MIN_MEMBERS=2     # 語音頻道達到多少人以上時自動連線
  ```

### Q4：想要更新機器人功能，但語音頻道大家正在聽歌，不想中斷怎麼辦？
- 直接在伺服器輸入 `/reload`（或使用 `/git_pull` 自 GitHub 拉取），機器人將在不中斷音樂與語音連線的前提下完成全模組動態熱重載！

---

<div align="center">

**✨ 享受極致純淨的 YouTube Music 音樂與歡樂的語音回放時光！**  
如果喜歡這個專案，歡迎給予專案一個 ⭐️ Star 支持！

</div>
