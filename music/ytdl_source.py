import asyncio
import logging
from dataclasses import dataclass
from typing import Optional, Dict, Any
import discord
import yt_dlp
import queue
import threading
import time
from config.settings import COOKIES_TXT_PATH, FFMPEG_EXE

logger = logging.getLogger(__name__)

# yt-dlp 選項設定：強制優先挑選最高音質 Opus 串流 (48kHz/最高位元率)，並指定 ffmpeg 位置
YTDL_OPTIONS: Dict[str, Any] = {
    "format": "bestaudio[acodec=opus]/bestaudio[ext=webm]/bestaudio/best",
    "format_sort": ["abr", "asr", "acodec:opus", "ext:webm"],
    "extractaudio": True,
    "audioformat": "opus",
    "outtmpl": "%(extractor)s-%(id)s-%(title)s.%(ext)s",
    "restrictfilenames": True,
    "noplaylist": True,
    "nocheckcertificate": True,
    "ignoreerrors": False,
    "logtostderr": False,
    "quiet": True,
    "no_warnings": True,
    "default_search": "auto",
    "source_address": "0.0.0.0",
    "js_runtimes": {"node": {}},
    "ffmpeg_location": str(FFMPEG_EXE),
}

if COOKIES_TXT_PATH.exists():
    YTDL_OPTIONS["cookiefile"] = str(COOKIES_TXT_PATH)

# FFmpeg 串流播放參數：
# 1. 移除 -reconnect_at_eof 1 避免歌曲結束時重複重連導致 I/O Error
# 2. 保留連線中斷自動重連，杜絕 YouTube -10054 斷線
# 3. 擴增緩衝區至 16384k，並啟用 Sinc 抗混疊重採樣
FFMPEG_OPTIONS = {
    "before_options": (
        '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 '
        '-reconnect_on_network_error 1 -reconnect_on_http_error 4xx,5xx '
        '-user_agent "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"'
    ),
    "options": "-vn -bufsize 16384k -af aresample=48000:filter_size=32:cutoff=0.99"
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

class BufferedAudioSource(discord.AudioSource):
    """
    音訊前置雙向平滑緩衝區 (Pre-buffering Audio Stream)
    在背景獨立執行緒預先讀取底層 FFmpeg 音訊串流至記憶體 Queue 中 (預設 5 秒，約 250 個 20ms 訊框)。
    播放啟動時先預載 1 秒緩衝 (約 50 個訊框)，隨後 Discord 音訊發送執行緒呼叫 read() 時，
    保證從本地記憶體 0 微秒極速取出，徹底阻斷 YouTube 網路波動、延遲抖動造成的音樂忽快忽慢、斷斷續續！
    """
    FRAME_SIZE = 3840  # 48000Hz * 2 channels * 2 bytes * 0.02s

    def __init__(self, original: discord.AudioSource, buffer_size: int = 250, prefill: int = 50):
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
                if time.perf_counter() - start_wait > 2.0:
                    break
                time.sleep(0.01)
            self._prefilled = True

        try:
            return self._queue.get(timeout=0.02)
        except queue.Empty:
            if self._eof:
                return b""
            # 若網路極端嚴重斷線導致緩衝區暫時見底 (underrun)，送出 20ms 靜音封包保持連線，絕不中斷播放
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

class YTDLSource(discord.PCMVolumeTransformer):
    """
    Discord 音訊串流來源，利用 yt-dlp 即時解析 YouTube / YouTube Music 音訊流
    """

    def __init__(self, source: discord.AudioSource, *, song: Song, volume: float = 0.5):
        super().__init__(source, volume)
        self.song = song

    @classmethod
    async def create_source(cls, song: Song, volume: float = 0.5) -> "YTDLSource":
        """
        異步解析歌曲的 stream_url 並建立 FFmpeg 音訊來源 (結合平滑緩衝區)
        """
        loop = asyncio.get_event_loop()
        
        # 若尚未取得直接串流網址，則透過 yt-dlp 異步提取
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

        audio_source = discord.FFmpegPCMAudio(
            song.stream_url,
            executable=str(FFMPEG_EXE),
            **FFMPEG_OPTIONS
        )
        buffered_source = BufferedAudioSource(audio_source, buffer_size=250, prefill=50)
        return cls(buffered_source, song=song, volume=volume)

    @classmethod
    async def prefetch_stream(cls, song: Song):
        """
        [多工處理] 在背景提前解析下一首歌曲的串流網址，實現零延遲秒切換歌曲
        """
        if song.stream_url:
            return
        loop = asyncio.get_running_loop()

        def extract():
            try:
                info = ytdl.extract_info(song.webpage_url, download=False)
                if "entries" in info:
                    info = info["entries"][0]
                return info.get("url")
            except Exception as e:
                logger.debug(f"背景預先解析串流網址失敗 ({song.title}): {e}")
                return None

        url = await loop.run_in_executor(None, extract)
        if url:
            song.stream_url = url

    @classmethod
    async def from_query(cls, query: str, requester: str = "未知使用者") -> Song:
        """
        直接從搜尋詞或一般 YouTube 網址建立 Song 物件
        """
        loop = asyncio.get_event_loop()

        def extract():
            info = ytdl.extract_info(query, download=False)
            if "entries" in info:
                info = info["entries"][0]
            
            # 格式化秒數為 mm:ss
            duration_sec = info.get("duration", 0)
            mins, secs = divmod(duration_sec, 60)
            duration_str = f"{mins}:{secs:02d}"

            return Song(
                id=info.get("id", ""),
                title=info.get("title", "未知曲名"),
                artist=info.get("uploader", "未知藝人"),
                duration=duration_str,
                thumbnail=info.get("thumbnail", ""),
                webpage_url=info.get("webpage_url") or f"https://www.youtube.com/watch?v={info.get('id', '')}",
                requester=requester,
                stream_url=info.get("url")
            )

        return await loop.run_in_executor(None, extract)
