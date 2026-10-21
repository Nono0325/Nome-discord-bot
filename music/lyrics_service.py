import re
import json
import logging
import urllib.request
import urllib.parse
from dataclasses import dataclass
from typing import Optional, List, Tuple, Dict
from music.ytm_client import ytm_client

logger = logging.getLogger(__name__)

@dataclass
class LyricsData:
    title: str
    artist: str
    synced: bool
    lines: List[Tuple[float, str]]  # [(timestamp_in_seconds, line_text), ...]
    plain: str
    source: str  # "LRCLIB (動態同步)" / "YouTube Music (官方歌詞)"
    thumbnail: str = ""

def format_time(sec: float) -> str:
    """將秒數格式化為 mm:ss"""
    sec = max(0, int(sec))
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

def parse_duration_str(d_str: str) -> float:
    """將時間字串 (如 04:29) 解析為浮點數秒數"""
    try:
        parts = [float(p) for p in d_str.strip().split(":")]
        if len(parts) == 1:
            return parts[0]
        elif len(parts) == 2:
            return parts[0] * 60 + parts[1]
        elif len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
    except Exception:
        pass
    return 0.0

def format_progress_bar(current: float, total: float, length: int = 12) -> str:
    """生成文字進度條"""
    if total <= 0:
        return "🔘" + ("▬" * length) + f" `{format_time(current)}`"
    ratio = min(1.0, max(0.0, current / total))
    dot_pos = min(length - 1, int(ratio * length))
    bar = ""
    for i in range(length):
        if i == dot_pos:
            bar += "🔘"
        else:
            bar += "▬"
    return f"{bar} `{format_time(current)} / {format_time(total)}`"

class LyricsService:
    """
    全方位歌詞服務：
    1. 支援 LRCLIB 高精度動態時間軸同步歌詞 (Synced Lyrics with Timestamps)
    2. 支援 YouTube Music 官方完整歌詞 fallback
    3. 內建記憶體快取，杜絕重複網路請求
    """

    def __init__(self):
        self._cache: Dict[str, LyricsData] = {}

    @staticmethod
    def clean_title(title: str) -> str:
        """清理 YouTube 標題雜訊 (如 MV, Official, 4K, 完整版等標籤)"""
        if not title:
            return ""
        # 移除括號及其內容，如 【Official MV】、[HD]、(官方完整版)
        cleaned = re.sub(r'[\(\[\{【].*?[\)\]\}】]', '', title)
        # 移除常見單詞
        cleaned = re.sub(
            r'(official\s*music\s*video|official\s*mv|official\s*video|official\s*audio|\bmv\b|\baudio\b|\bhd\b|\b4k\b|歌詞版|字幕版)',
            '',
            cleaned,
            flags=re.IGNORECASE
        )
        return cleaned.strip()

    @staticmethod
    def parse_lrc(lrc_text: str) -> List[Tuple[float, str]]:
        """解析 LRC 格式時間戳歌詞"""
        lines: List[Tuple[float, str]] = []
        pattern = re.compile(r'\[(\d+):(\d+(?:\.\d+)?)\](.*)')
        for raw in lrc_text.splitlines():
            raw = raw.strip()
            if not raw:
                continue
            m = pattern.match(raw)
            if m:
                minutes = int(m.group(1))
                seconds = float(m.group(2))
                t = minutes * 60.0 + seconds
                text = m.group(3).strip()
                if text:  # 排除純時間標籤的空行
                    lines.append((t, text))
        lines.sort(key=lambda x: x[0])
        return lines

    async def get_lyrics(
        self,
        title: str,
        artist: str = "",
        video_id: str = "",
        thumbnail: str = ""
    ) -> Optional[LyricsData]:
        """非同步取得歌曲歌詞（優先 LRCLIB 動態同步，次選 YouTube Music）"""
        cache_key = f"{title}_{artist}_{video_id}".lower()
        if cache_key in self._cache:
            return self._cache[cache_key]

        import asyncio
        loop = asyncio.get_running_loop()
        lyrics_data = await loop.run_in_executor(
            None,
            self._fetch_lyrics_sync,
            title,
            artist,
            video_id,
            thumbnail
        )
        if lyrics_data:
            self._cache[cache_key] = lyrics_data
            if len(self._cache) > 100:
                self._cache.pop(next(iter(self._cache)))
        return lyrics_data

    def _fetch_lyrics_sync(
        self,
        title: str,
        artist: str,
        video_id: str,
        thumbnail: str
    ) -> Optional[LyricsData]:
        cleaned_t = self.clean_title(title)

        # 1. 優先嘗試 LRCLIB 精確比對
        lrclib_res = self._query_lrclib_exact(cleaned_t, artist)
        if not lrclib_res:
            # 2. 嘗試 LRCLIB 模糊搜尋
            lrclib_res = self._query_lrclib_search(cleaned_t, artist)

        if lrclib_res:
            synced_lrc = lrclib_res.get("syncedLyrics")
            plain_lrc = lrclib_res.get("plainLyrics", "")
            if synced_lrc:
                parsed_lines = self.parse_lrc(synced_lrc)
                if parsed_lines:
                    return LyricsData(
                        title=lrclib_res.get("trackName") or title,
                        artist=lrclib_res.get("artistName") or artist,
                        synced=True,
                        lines=parsed_lines,
                        plain=plain_lrc or "\n".join(t for _, t in parsed_lines),
                        source="LRCLIB (動態同步)",
                        thumbnail=thumbnail
                    )
            elif plain_lrc:
                return LyricsData(
                    title=lrclib_res.get("trackName") or title,
                    artist=lrclib_res.get("artistName") or artist,
                    synced=False,
                    lines=[],
                    plain=plain_lrc,
                    source="LRCLIB (純文字歌詞)",
                    thumbnail=thumbnail
                )

        # 3. 備援方案：從 YouTube Music 獲取官方歌詞
        if video_id and ytm_client.ytm:
            try:
                watch = ytm_client.ytm.get_watch_playlist(videoId=video_id)
                lyrics_browse_id = watch.get("lyrics")
                if lyrics_browse_id:
                    ytm_lyrics = ytm_client.ytm.get_lyrics(browseId=lyrics_browse_id)
                    if ytm_lyrics and ytm_lyrics.get("lyrics"):
                        return LyricsData(
                            title=title,
                            artist=artist,
                            synced=False,
                            lines=[],
                            plain=ytm_lyrics.get("lyrics"),
                            source="YouTube Music (官方歌詞)",
                            thumbnail=thumbnail
                        )
            except Exception as e:
                logger.debug(f"從 YouTube Music 提取歌詞失敗: {e}")

        return None

    def _query_lrclib_exact(self, track_name: str, artist_name: str) -> Optional[dict]:
        params = {"track_name": track_name}
        if artist_name:
            params["artist_name"] = artist_name
        url = "https://lrclib.net/api/get?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": "DiscordBot-Music/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("syncedLyrics") or data.get("plainLyrics"):
                    return data
        except Exception:
            pass
        return None

    def _query_lrclib_search(self, track_name: str, artist_name: str) -> Optional[dict]:
        query_str = f"{artist_name} {track_name}".strip()
        url = "https://lrclib.net/api/search?" + urllib.parse.urlencode({"q": query_str})
        req = urllib.request.Request(url, headers={"User-Agent": "DiscordBot-Music/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=4) as resp:
                results = json.loads(resp.read().decode("utf-8"))
                if results and isinstance(results, list):
                    # 優先挑選具有 syncedLyrics 的項目
                    for r in results:
                        if r.get("syncedLyrics"):
                            return r
                    return results[0]
        except Exception:
            pass
        return None

lyrics_service = LyricsService()
