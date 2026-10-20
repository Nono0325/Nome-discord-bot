import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any
import discord
from config.settings import CONFIG_DIR

logger = logging.getLogger(__name__)

SETTINGS_FILE = CONFIG_DIR / "guild_settings.json"

class GuildSettingsManager:
    """
    管理每個 Discord 伺服器的持久化設定（例如專屬音樂文字頻道）
    """

    def __init__(self, file_path: Path = SETTINGS_FILE):
        self.file_path = file_path
        self._data: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self):
        if self.file_path.exists():
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            except Exception as e:
                logger.error(f"讀取伺服器設定檔失敗: {e}")
                self._data = {}
        else:
            self._data = {}

    def _save(self):
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"儲存伺服器設定檔失敗: {e}")

    def get_music_channel_id(self, guild_id: int) -> Optional[int]:
        """取得指定伺服器設定的專屬音樂頻道 ID"""
        guild_key = str(guild_id)
        return self._data.get(guild_key, {}).get("music_channel_id")

    def set_music_channel_id(self, guild_id: int, channel_id: int):
        """設定指定伺服器的專屬音樂頻道 ID"""
        guild_key = str(guild_id)
        if guild_key not in self._data:
            self._data[guild_key] = {}
        self._data[guild_key]["music_channel_id"] = channel_id
        self._save()

    def clear_music_channel_id(self, guild_id: int) -> bool:
        """清除指定伺服器的專屬音樂頻道設定"""
        guild_key = str(guild_id)
        if guild_key in self._data and "music_channel_id" in self._data[guild_key]:
            del self._data[guild_key]["music_channel_id"]
            self._save()
            return True
        return False

    def get_music_channel(self, guild: discord.Guild) -> Optional[discord.TextChannel]:
        """取得指定伺服器的專屬文字頻道物件（若頻道存在且為文字頻道）"""
        cid = self.get_music_channel_id(guild.id)
        if cid:
            ch = guild.get_channel(cid)
            if isinstance(ch, discord.TextChannel):
                return ch
        return None

guild_settings = GuildSettingsManager()
