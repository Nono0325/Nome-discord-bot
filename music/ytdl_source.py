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
from typing import Optional, Dict, Any, List
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
    "noprogress": True,
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
        '-reconnect_on_network_error 1 -reconnect_on_http_error 4xx,5xx '
        '-user_agent "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"'
    ),
    "options": "-vn -bufsize 16384k -af aresample=48000:filter_size=32:cutoff=0.99"
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

_DOWNLOAD_LOCKS: Dict[str, asyncio.Lock] = {}
_LOCK_MUTEX = threading.Lock()

def _get_song_lock(song_id: str) -> asyncio.Lock:
    with _LOCK_MUTEX:
        if song_id not in _DOWNLOAD_LOCKS:
            _DOWNLOAD_LOCKS[song_id] = asyncio.Lock()
        return _DOWNLOAD_LOCKS[song_id]

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

async def ensure_song_cached(song_url: str, song_id: str) -> Optional[Path]:
    """
    非同步安全鎖機制：同一首歌曲在同時間只有單一任務執行下載，杜絕 Windows WinError 32 衝突
    """
    clean_id = sanitize_song_id(song_id)
    lock = _get_song_lock(clean_id)
    async with lock:
        cached = find_cached_file(clean_id)
        if cached:
            return cached

        loop = asyncio.get_running_loop()
        cached = await loop.run_in_executor(None, download_song_to_cache, song_url, clean_id)
        cleanup_cache(max_size_mb=1000)
        return cached

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
        if hasattr(self, "_worker") and self._worker and self._worker.is_alive():
            try:
                self._worker.join(timeout=0.5)
            except Exception:
                pass

    def __del__(self):
        try:
            self.cleanup()
        except Exception:
            pass

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
                # 2. 本地不存在，安全獲取或下載 (同歌曲單一任務，絕不衝突)
                logger.info(f"📥 [極速下載] 正在將歌曲《{song.title}》快取至本機...")
                cached = await ensure_song_cached(song.webpage_url, song.id)
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
                    if info and "entries" in info:
                        entries = [e for e in info.get("entries") or [] if e is not None]
                        info = entries[0] if entries else None
                    return info.get("url") if info else None

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

        cached = find_cached_file(song.id)
        if cached:
            song.local_filepath = str(cached)
            return

        p = await ensure_song_cached(song.webpage_url, song.id)
        if p:
            song.local_filepath = str(p)
            logger.info(f"🚀 [提前預載] 下一首歌曲《{song.title}》已在背景完成快取！")

    @classmethod
    async def from_query(cls, query: str, requester: str = "未知使用者") -> Song:
        """
        直接從搜尋詞或一般 YouTube 網址建立 Song 物件
        """
        loop = asyncio.get_running_loop()

        def extract():
            info = ytdl.extract_info(query, download=False)
            if not info:
                raise RuntimeError("無法獲取歌曲資訊，請確認關鍵字或網址是否有效")

            if "entries" in info:
                entries = [e for e in info.get("entries") or [] if e is not None]
                if not entries:
                    raise RuntimeError("找不到任何相關影片或曲目，請嘗試更換關鍵字或確認網址")
                info = entries[0]

            if not info:
                raise RuntimeError("曲目解析失敗，找不到有效內容")

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

    @classmethod
    async def create_song_list(cls, query: str, requester: str = "未知使用者") -> List[Song]:
        """
        全功能通用歌曲與播放清單解析器：
        1. 支援 YouTube 播放清單網址解析
        2. 支援單一音訊網址解析
        3. 支援關鍵字檢索（優先走 YouTube Music 官方引擎）
        """
        query = query.strip()
        if not query:
            return []

        # 1. 判斷是否為直接網址
        if query.startswith("http://") or query.startswith("https://"):
            if "list=" in query and "playlist" in query:
                loop = asyncio.get_running_loop()
                def extract_pl():
                    pl_opts = dict(YTDL_OPTIONS)
                    pl_opts["noplaylist"] = False
                    pl_opts["extract_flat"] = True
                    with yt_dlp.YoutubeDL(pl_opts) as ydl:
                        return ydl.extract_info(query, download=False)

                try:
                    info = await loop.run_in_executor(None, extract_pl)
                    if info and "entries" in info:
                        songs = []
                        for entry in info["entries"]:
                            if not entry:
                                continue
                            v_id = entry.get("id") or ""
                            d_sec = entry.get("duration", 0) or 0
                            m, s = divmod(int(d_sec), 60)
                            songs.append(Song(
                                id=v_id,
                                title=entry.get("title", "未知曲名"),
                                artist=entry.get("uploader", "未知藝人"),
                                duration=f"{m}:{s:02d}",
                                thumbnail=entry.get("thumbnail", f"https://i.ytimg.com/vi/{v_id}/hqdefault.jpg" if v_id else ""),
                                webpage_url=entry.get("url") or f"https://www.youtube.com/watch?v={v_id}",
                                requester=requester,
                            ))
                        if songs:
                            return songs
                except Exception as e:
                    logger.warning(f"播放清單解析失敗，轉為單曲模式: {e}")

            # 單曲網址解析
            try:
                single = await cls.from_query(query, requester=requester)
                return [single]
            except Exception as e:
                logger.error(f"單曲網址解析失敗 ({query}): {e}")
                return []

        # 2. 關鍵字搜尋：優先使用 YouTube Music
        try:
            from music.ytm_client import ytm_client
            results = await asyncio.to_thread(ytm_client.search_songs, query, 5)
            if results:
                top = results[0]
                return [Song(
                    id=top["id"],
                    title=top["title"],
                    artist=top["artist"],
                    duration=top["duration"],
                    thumbnail=top["thumbnail"],
                    webpage_url=top["url"],
                    requester=requester
                )]
        except Exception as e:
            logger.debug(f"YouTube Music 檢索降級: {e}")

        # 備援：yt-dlp 搜尋
        try:
            single = await cls.from_query(query, requester=requester)
            return [single]
        except Exception as e:
            logger.error(f"備援關鍵字搜尋失敗 ({query}): {e}")
            return []

