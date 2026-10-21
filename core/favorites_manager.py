import json
import time
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from config.settings import CONFIG_DIR
from music.ytdl_source import Song

logger = logging.getLogger(__name__)

FAVORITES_FILE = CONFIG_DIR / "favorites.json"

class FavoritesManager:
    """
    管理使用者的個人私房收藏歌單 (Personal Favorites)
    支援持久化存儲、隨機播放、一鍵加入與個別刪除管理
    """

    def __init__(self, file_path: Path = FAVORITES_FILE):
        self.file_path = file_path
        self._data: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self):
        if self.file_path.exists():
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            except Exception as e:
                logger.error(f"讀取收藏歌單設定檔失敗: {e}")
                self._data = {}
        else:
            self._data = {}

    def _save(self):
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"儲存收藏歌單設定檔失敗: {e}")

    def get_favorites(self, user_id: int) -> List[Dict[str, Any]]:
        """取得指定使用者的所有收藏歌曲清單"""
        user_key = str(user_id)
        user_info = self._data.get(user_key, {})
        return user_info.get("favorites", [])

    def add_favorite(self, user_id: int, song: Song, username: str = "") -> Tuple[bool, str, int]:
        """
        將歌曲加入使用者的收藏清單
        回傳 (是否成功, 提示訊息, 目前總收藏數)
        """
        user_key = str(user_id)
        if user_key not in self._data:
            self._data[user_key] = {
                "username": username,
                "favorites": []
            }
        else:
            if username:
                self._data[user_key]["username"] = username

        favs = self._data[user_key]["favorites"]

        # 檢查是否已存在 (依 song.id 或 webpage_url 判斷)
        for item in favs:
            if item.get("id") == song.id or (song.webpage_url and item.get("webpage_url") == song.webpage_url):
                return False, f"⚠️ 歌曲 **{song.title}** 已經在您的收藏歌單中囉！", len(favs)

        new_entry = {
            "id": song.id,
            "title": song.title,
            "artist": song.artist,
            "duration": song.duration,
            "thumbnail": song.thumbnail,
            "webpage_url": song.webpage_url,
            "added_at": time.time()
        }
        favs.append(new_entry)
        self._save()
        return True, f"⭐ 已成功將 **{song.title}** 加入您的個人收藏歌單！", len(favs)

    def remove_favorite(self, user_id: int, song_id: str) -> Tuple[bool, Optional[str], int]:
        """從使用者收藏清單中移除指定歌曲"""
        user_key = str(user_id)
        if user_key not in self._data:
            return False, None, 0

        favs = self._data[user_key]["favorites"]
        removed_title = None
        for i, item in enumerate(favs):
            if item.get("id") == song_id:
                removed_title = item.get("title")
                favs.pop(i)
                self._save()
                return True, removed_title, len(favs)

        return False, None, len(favs)

    def clear_favorites(self, user_id: int) -> int:
        """清空使用者的所有收藏歌曲，回傳被清空的數量"""
        user_key = str(user_id)
        if user_key in self._data:
            count = len(self._data[user_key].get("favorites", []))
            self._data[user_key]["favorites"] = []
            self._save()
            return count
        return 0

    @staticmethod
    def to_song(entry: Dict[str, Any], requester: str = "私房收藏歌單") -> Song:
        """將字典項目轉換回 Song 物件"""
        return Song(
            id=entry.get("id", ""),
            title=entry.get("title", "未知歌曲"),
            artist=entry.get("artist", "未知歌手"),
            duration=entry.get("duration", "0:00"),
            thumbnail=entry.get("thumbnail", ""),
            webpage_url=entry.get("webpage_url", f"https://www.youtube.com/watch?v={entry.get('id', '')}"),
            requester=requester
        )

favorites_manager = FavoritesManager()
