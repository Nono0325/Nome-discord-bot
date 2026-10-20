import asyncio
import logging
from dataclasses import dataclass
from typing import Optional, Dict, Any
import discord
import yt_dlp
from config.settings import COOKIES_TXT_PATH

logger = logging.getLogger(__name__)

# yt-dlp 選項設定
YTDL_OPTIONS: Dict[str, Any] = {
    "format": "bestaudio/best",
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
}

if COOKIES_TXT_PATH.exists():
    YTDL_OPTIONS["cookiefile"] = str(COOKIES_TXT_PATH)

# FFmpeg 串流播放參數
FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn"
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

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
        異步解析歌曲的 stream_url 並建立 FFmpeg 音訊來源
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

        audio_source = discord.FFmpegPCMAudio(song.stream_url, **FFMPEG_OPTIONS)
        return cls(audio_source, song=song, volume=volume)

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
