import asyncio
import logging
import os
import re
import shutil
import threading
import time
import queue
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Dict, Any
import discord
import yt_dlp
from config.settings import COOKIES_TXT_PATH, FFMPEG_EXE, BASE_DIR

logger = logging.getLogger(__name__)

# 本地音訊極速快取目錄 (杜絕 YouTube 網路波動與 Connection Reset 10054)
AUDIO_CACHE_DIR = BASE_DIR / "cache" / "audio"
AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# 搜尋系統上的 Node.js 以支援 YouTube JS 簽名解碼
NODE_PATH = Path("C:/Program Files/nodejs/node.exe")
JS_RUNTIMES = {"node": {"path": str(NODE_PATH)}} if NODE_PATH.exists() else {"node": {}}

# yt-dlp 選項設定：強制優先挑選最高音質 Opus/WebM 串流，並配置快取輸出與 ffmpeg 位置
YTDL_OPTIONS: Dict[str, Any] = {
    "format": "bestaudio[acodec=opus]/bestaudio[ext=webm]/bestaudio/best",
    "format_sort": ["abr", "asr", "acodec:opus", "ext:webm"],
    "extractaudio": True,
    "audioformat": "opus",
    "outtmpl": str(AUDIO_CACHE_DIR / "%(id)s.%(ext)s"),
    "restrictfilenames": True,
    "noplaylist": True,
    "nocheckcertificate": True,
    "ignoreerrors": False,
    "logtostderr": False,
    "quiet": True,
    "no_warnings": True,
    "default_search": "auto",
    "source_address": "0.0.0.0",
    "js_runtimes": JS_RUNTIMES,
    "ffmpeg_location": str(FFMPEG_EXE.parent if FFMPEG_EXE.is_file() else FFMPEG_EXE),
}

if COOKIES_TXT_PATH.exists():
    YTDL_OPTIONS["cookiefile"] = str(COOKIES_TXT_PATH)

# FFmpeg 本地極速無損播放參數 (無網路開銷、無抖動、零延遲)
FFMPEG_LOCAL_OPTIONS = {
    "options": "-vn -af aresample=48000:filter_size=32:cutoff=0.99"
}

# FFmpeg 直播串流備用參數 (僅在無盡直播或快取失敗時啟用)
FFMPEG_STREAM_OPTIONS = {
    "before_options": (
        '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 '
        '-http_persistent 0 '
        '-reconnect_on_network_error 1 -reconnect_on_http_error 4xx,5xx '
        '-user_agent "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"'
    ),
    "options": "-vn -bufsize 16384k -af aresample=48000:filter_size=32:cutoff=0.99"
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

def sanitize_song_id(song_id: str) -> str:
    """清理檔名中的特殊字元"""
    return re.sub(r'[\\/*?:"<>|]', "", song_id)

def find_cached_file(song_id: str) -> Optional[Path]:
    """尋找本地是否已存在該歌曲的完整音訊快取"""
    clean_id = sanitize_song_id(song_id)
    if not clean_id:
        return None
    for p in AUDIO_CACHE_DIR.glob(f"{clean_id}.*"):
        if p.is_file() and p.stat().st_size > 50000:  # 大於 50KB 代表已完整下載
            return p
    return None

def download_song_to_cache(song_url: str, song_id: str) -> Optional[Path]:
    """[極速下載] 透過 yt-dlp 將整首歌曲預載至本地快取 (只需 1~2 秒，徹底杜絕播歌卡頓)"""
    cached = find_cached_file(song_id)
    if cached:
        return cached

    clean_id = sanitize_song_id(song_id)
    outtmpl = str(AUDIO_CACHE_DIR / f"{clean_id}.%(ext)s")
    dl_opts = dict(YTDL_OPTIONS)
    dl_opts["outtmpl"] = outtmpl

    try:
        with yt_dlp.YoutubeDL(dl_opts) as ydl:
            ydl.download([song_url])
        return find_cached_file(song_id)
    except Exception as e:
        logger.warning(f"本地快取下載失敗 ({song_id}): {e}")
        return None

def cleanup_cache(max_size_mb: int = 1000):
    """自動清理快取目錄，保留最近使用的歌曲，防止磁碟空間超標"""
    try:
        files = [p for p in AUDIO_CACHE_DIR.glob("*.*") if p.is_file()]
        total_size = sum(f.stat().st_size for f in files)
        max_bytes = max_size_mb * 1024 * 1024
        if total_size > max_bytes:
            files.sort(key=lambda f: f.stat().st_mtime)
            for f in files:
                try:
                    f_size = f.stat().st_size
                    f.unlink(missing_ok=True)
                    total_size -= f_size
                    if total_size <= max_bytes * 0.7:
                        break
                except Exception:
                    pass
    except Exception as e:
        logger.debug(f"快取清理失敗: {e}")

class BufferedAudioSource(discord.AudioSource):
    """
    雙向平滑記憶體音訊來源：
    在背景獨立執行緒預先讀取音訊訊框至記憶體 Queue (約 300 個訊框，6 秒緩衝)。
    Discord AudioPlayer 每次呼叫 read() 時直接從 RAM 0 微秒極速取出，完全杜絕任何 I/O 抖動！
    """
    FRAME_SIZE = 3840  # 48000Hz * 2 channels * 2 bytes * 0.02s

    def __init__(self, original: discord.AudioSource, buffer_size: int = 300, prefill: int = 25):
        self.original = original
        self.buffer_size = buffer_size
        self.prefill = prefill
        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=buffer_size)
        self._stop_event = threading.Event()
        self._eof = False
        self._prefilled = False

        self._worker = threading.Thread(
            target=self._reader_loop,
            daemon=True,
            name="AudioBufferReader"
        )
        self._worker.start()

    def _reader_loop(self):
        while not self._stop_event.is_set():
            try:
                data = self.original.read()
                if not data:
                    self._eof = True
                    break
                while not self._stop_event.is_set():
                    try:
                        self._queue.put(data, timeout=0.1)
                        break
                    except queue.Full:
                        continue
            except Exception as e:
                logger.debug(f"音訊緩衝讀取緒例外: {e}")
                self._eof = True
                break

    def read(self) -> bytes:
        if not self._prefilled and not self._eof:
            start_wait = time.perf_counter()
            while self._queue.qsize() < self.prefill and not self._eof and not self._stop_event.is_set():
                if time.perf_counter() - start_wait > 1.5:
                    break
                time.sleep(0.01)
            self._prefilled = True

        try:
            return self._queue.get(timeout=0.02)
        except queue.Empty:
            if self._eof:
                return b""
            return b"\x00" * self.FRAME_SIZE

    def is_opus(self) -> bool:
        return self.original.is_opus()

    def cleanup(self) -> None:
        self._stop_event.set()
        try:
            self.original.cleanup()
        except Exception:
            pass
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

@dataclass
class Song:
    """代表播放清單中的一首曲目"""
    id: str
    title: str
    artist: str
    duration: str
    thumbnail: str
    webpage_url: str
    requester: str = "未知使用者"
    stream_url: Optional[str] = None
    local_filepath: Optional[str] = None
    is_live: bool = False

class YTDLSource(discord.PCMVolumeTransformer):
    """
    Discord 音訊串流來源，結合本地極速快取、雙向平滑緩衝與最高音質轉碼
    """

    def __init__(self, source: discord.AudioSource, *, song: Song, volume: float = 0.5):
        super().__init__(source, volume)
        self.song = song

    @classmethod
    async def create_source(cls, song: Song, volume: float = 0.5) -> "YTDLSource":
        """
        建立高穩定音訊來源：
        1. 優先採用本地無損音訊快取 (Local Cache)，徹底擺脫 YouTube 網路中斷與 10054 連線重置！
        2. 若為直播電台或未下載完成，則在背景極速預載或透過平滑串流播放。
        """
        loop = asyncio.get_running_loop()

        local_path = None
        if not song.is_live:
            # 1. 檢查本地快取是否已存在
            cached = find_cached_file(song.id)
            if cached:
                local_path = str(cached)
                logger.info(f"⚡ [本地快取] 歌曲《{song.title}》已存在快取，啟動零延遲本地播放！")
            else:
                # 2. 本地不存在，快速預載 (通常僅需 1~2 秒)
                logger.info(f"📥 [極速下載] 正在將歌曲《{song.title}》快取至本機...")
                cached = await loop.run_in_executor(None, download_song_to_cache, song.webpage_url, song.id)
                if cached:
                    local_path = str(cached)
                    logger.info(f"✅ [快取完成] 歌曲《{song.title}》已就緒，啟動本地極速播放！")

        # 3. 建立音訊來源
        if local_path and os.path.exists(local_path):
            song.local_filepath = local_path
            raw_source = discord.FFmpegPCMAudio(
                local_path,
                executable=str(FFMPEG_EXE),
                **FFMPEG_LOCAL_OPTIONS
            )
        else:
            # 備用串流方案 (例如直播或極端下載例外)
            if not song.stream_url:
                def extract():
                    info = ytdl.extract_info(song.webpage_url, download=False)
                    if "entries" in info:
                        info = info["entries"][0]
                    return info.get("url")

                stream_url = await loop.run_in_executor(None, extract)
                song.stream_url = stream_url

            if not song.stream_url:
                raise RuntimeError(f"無法取得曲目串流網址: {song.title}")

            logger.info(f"🌐 [串流備援] 以網路平滑串流模式播放: 《{song.title}》")
            raw_source = discord.FFmpegPCMAudio(
                song.stream_url,
                executable=str(FFMPEG_EXE),
                **FFMPEG_STREAM_OPTIONS
            )

        # 4. 包裹平滑緩衝區，給予 20ms 音訊時鐘最高優先級 RAM 讀取
        buffered_source = BufferedAudioSource(raw_source, buffer_size=300, prefill=25)
        return cls(buffered_source, song=song, volume=volume)

    @classmethod
    async def prefetch_stream(cls, song: Song):
        """
        [多工處理] 在播放當前歌曲時，於背景提前下載下一首歌曲至本地快取，
        實現歌曲之間切換 0.00 秒零延遲、絕不卡頓！
        """
        if song.is_live:
            return
        loop = asyncio.get_running_loop()

        cached = find_cached_file(song.id)
        if cached:
            song.local_filepath = str(cached)
            return

        def _do_prefetch():
            try:
                p = download_song_to_cache(song.webpage_url, song.id)
                cleanup_cache(max_size_mb=1000)
                return str(p) if p else None
            except Exception as e:
                logger.debug(f"背景提前下載失敗 ({song.title}): {e}")
                return None

        local = await loop.run_in_executor(None, _do_prefetch)
        if local:
            song.local_filepath = local
            logger.info(f"🚀 [提前預載] 下一首歌曲《{song.title}》已在背景完成快取！")

    @classmethod
    async def from_query(cls, query: str, requester: str = "未知使用者") -> Song:
        """
        直接從搜尋詞或一般 YouTube 網址建立 Song 物件
        """
        loop = asyncio.get_running_loop()

        def extract():
            info = ytdl.extract_info(query, download=False)
            if "entries" in info:
                info = info["entries"][0]

            duration_sec = info.get("duration", 0)
            is_live = bool(info.get("is_live", False) or (duration_sec == 0 and info.get("is_live") is not False))
            mins, secs = divmod(duration_sec or 0, 60)
            duration_str = "直播中" if is_live else f"{mins}:{secs:02d}"

            return Song(
                id=str(info.get("id", "")),
                title=info.get("title", "未知曲名"),
                artist=info.get("uploader", "未知藝人"),
                duration=duration_str,
                thumbnail=info.get("thumbnail", ""),
                webpage_url=info.get("webpage_url") or f"https://www.youtube.com/watch?v={info.get('id', '')}",
                requester=requester,
                stream_url=info.get("url"),
                is_live=is_live
            )

        return await loop.run_in_executor(None, extract)
