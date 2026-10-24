import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# 載入 .env 檔案
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# 確保虛擬環境的 Scripts (包含 ffmpeg) 加入 PATH
VENV_SCRIPTS = BASE_DIR / ".venv" / "Scripts"
if VENV_SCRIPTS.exists():
    os.environ["PATH"] = str(VENV_SCRIPTS) + os.pathsep + os.environ.get("PATH", "")

# 設定 ffmpeg 執行檔路徑
FFMPEG_EXE = VENV_SCRIPTS / "ffmpeg.exe" if (VENV_SCRIPTS / "ffmpeg.exe").exists() else Path("ffmpeg")

# 設定 pydub ffmpeg 路徑
try:
    import pydub
    from pydub import AudioSegment
    if FFMPEG_EXE.exists():
        AudioSegment.converter = str(FFMPEG_EXE)
        AudioSegment.ffmpeg = str(FFMPEG_EXE)
except ImportError:
    pass

# Discord 設定
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
COMMAND_PREFIX = os.getenv("COMMAND_PREFIX", "!").strip()

# 錄音與回放緩衝區設定
AUTO_RECORD = os.getenv("AUTO_RECORD", "false").lower() in ("true", "1", "yes")
REPLAY_BUFFER_SECONDS = int(os.getenv("REPLAY_BUFFER_SECONDS", "60"))

# 自動加入語音頻道設定 (當頻道達到指定人數時自動加入)
AUTO_JOIN_ENABLED = os.getenv("AUTO_JOIN_ENABLED", "true").lower() in ("true", "1", "yes")
AUTO_JOIN_MIN_MEMBERS = int(os.getenv("AUTO_JOIN_MIN_MEMBERS", "1"))

# Google YouTube Music 認證設定
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()

CONFIG_DIR = BASE_DIR / "config"
CONFIG_DIR.mkdir(exist_ok=True)
RECORDINGS_DIR = BASE_DIR / "recordings"
RECORDINGS_DIR.mkdir(exist_ok=True)
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

OAUTH_JSON_PATH = CONFIG_DIR / "oauth.json"
BROWSER_JSON_PATH = CONFIG_DIR / "browser.json"
COOKIES_TXT_PATH = CONFIG_DIR / "cookies.txt"
RESTART_INFO_PATH = CONFIG_DIR / "restart_info.json"
LOG_FILE_PATH = LOGS_DIR / "bot.log"

# 控制與監控台 (Web Dashboard) 設定
DASHBOARD_ENABLED = os.getenv("DASHBOARD_ENABLED", "true").lower() in ("true", "1", "yes")
DASHBOARD_HOST = os.getenv("DASHBOARD_HOST", "0.0.0.0").strip()
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "5000"))
