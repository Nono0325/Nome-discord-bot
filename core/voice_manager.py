import logging
from typing import Dict, Optional
import discord
from core.recorder import RollingBufferSink
from music.player import GuildPlayer
from config.settings import AUTO_RECORD, REPLAY_BUFFER_SECONDS

logger = logging.getLogger(__name__)

class VoiceManager:
    """
    全域語音管理器：
    管理每個伺服器的 VoiceClient 連線、音樂播放器 (GuildPlayer) 與語音緩衝錄音器 (RollingBufferSink)
    """

    def __init__(self, bot: discord.Bot):
        self.bot = bot
        self.players: Dict[int, GuildPlayer] = {}
        self.sinks: Dict[int, RollingBufferSink] = {}
        self.auto_record: bool = AUTO_RECORD

    def get_player(self, guild_id: int) -> GuildPlayer:
        if guild_id not in self.players:
            self.players[guild_id] = GuildPlayer(self.bot, guild_id)
        return self.players[guild_id]

    def get_sink(self, guild_id: int) -> Optional[RollingBufferSink]:
        return self.sinks.get(guild_id)

    async def connect_voice(
        self,
        voice_channel: discord.VoiceChannel,
        text_channel: Optional[discord.TextChannel] = None
    ) -> discord.VoiceClient:
        """
        連線至語音頻道，並自動啟動語音對話滾動錄音緩衝區
        """
        guild = voice_channel.guild
        vc = guild.voice_client

        if vc and vc.is_connected():
            if vc.channel.id != voice_channel.id:
                await vc.move_to(voice_channel)
        else:
            vc = await voice_channel.connect(timeout=60.0, reconnect=True)

        # 設定音樂播放器的預設文字頻道
        player = self.get_player(guild.id)
        if text_channel:
            player.text_channel = text_channel

        # 啟動語音接收器（維護前一分鐘緩衝區與自動錄音）
        if not vc.is_recording():
            sink = RollingBufferSink(
                buffer_seconds=float(REPLAY_BUFFER_SECONDS + 10),
                auto_record=self.auto_record
            )
            self.sinks[guild.id] = sink

            def record_finished_callback(*args, **kwargs):
                logger.info(f"伺服器 {guild.id} 的語音錄音已結束。")

            try:
                vc.start_recording(sink, record_finished_callback)
                logger.info(f"已在語音頻道 {voice_channel.name} 啟動循環對話緩衝區 (自動錄音={self.auto_record})")
            except Exception as e:
                logger.error(f"啟動語音接收器時發生例外: {e}", exc_info=True)

        return vc

    async def disconnect_voice(self, guild_id: int):
        """
        斷開語音連線並清理資源
        """
        guild = self.bot.get_guild(guild_id)
        if guild and guild.voice_client:
            vc = guild.voice_client
            if vc.is_recording():
                try:
                    vc.stop_recording()
                except Exception:
                    pass
            await vc.disconnect()

        if guild_id in self.players:
            self.players[guild_id].stop()
            del self.players[guild_id]

        if guild_id in self.sinks:
            self.sinks[guild_id].cleanup()
            del self.sinks[guild_id]
