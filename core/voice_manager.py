import asyncio
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
        self.manual_joins: Dict[int, bool] = {}

    def get_player(self, guild_id: int) -> GuildPlayer:
        if guild_id not in self.players:
            self.players[guild_id] = GuildPlayer(self.bot, guild_id)
        return self.players[guild_id]

    def get_sink(self, guild_id: int) -> Optional[RollingBufferSink]:
        return self.sinks.get(guild_id)

    async def connect_voice(
        self,
        voice_channel: discord.VoiceChannel,
        text_channel: Optional[discord.TextChannel] = None,
        manual: bool = False
    ) -> discord.VoiceClient:
        """
        連線至語音頻道，並自動啟動語音對話滾動錄音緩衝區
        """
        guild = voice_channel.guild
        self.manual_joins[guild.id] = manual
        vc = guild.voice_client

        if vc and vc.is_connected():
            if vc.channel.id != voice_channel.id:
                if vc.is_recording():
                    try:
                        vc.stop_recording()
                    except Exception:
                        pass
                await vc.move_to(voice_channel)
                await asyncio.sleep(0.5)
        else:
            vc = await voice_channel.connect(timeout=60.0, reconnect=True)

        # 自動檢查並將語音頻道音質升級為該伺服器所支援之最高位元率 (若具備管理頻道權限)
        try:
            if guild.me and voice_channel.permissions_for(guild.me).manage_channels:
                max_limit = int(guild.bitrate_limit)
                if voice_channel.bitrate < max_limit:
                    await voice_channel.edit(bitrate=max_limit, reason="自動升級語音頻道音質至伺服器最高上限")
                    logger.info(f"已自動將語音頻道 {voice_channel.name} 音質升級至 {max_limit // 1000} kbps")
        except Exception as ex:
            logger.debug(f"升級語音頻道音質跳過: {ex}")

        # 設定音樂播放器的預設文字頻道
        player = self.get_player(guild.id)
        if text_channel:
            player.text_channel = text_channel

        # 啟動語音接收器（維護前一分鐘緩衝區與自動錄音）
        if not vc.is_recording():
            sink = RollingBufferSink(
                buffer_seconds=float(REPLAY_BUFFER_SECONDS + 10),
                auto_record=self.auto_record,
                vc=vc
            )
            sink.init(vc)
            self.sinks[guild.id] = sink

            def record_finished_callback(error=None, *args, **kwargs):
                if error:
                    logger.error(f"伺服器 {guild.id} 的語音錄音發生錯誤終止: {error}", exc_info=isinstance(error, Exception))
                else:
                    logger.info(f"伺服器 {guild.id} 的語音錄音已正常結束。")

            try:
                vc.start_recording(sink, record_finished_callback)
                logger.info(f"已在語音頻道 {voice_channel.name} 啟動循環對話緩衝區 (自動錄音={self.auto_record})")
            except Exception as e:
                logger.error(f"啟動語音接收器時發生例外: {e}", exc_info=True)

        return vc

    async def disconnect_voice(self, guild_id: int):
        """
        斷開語音連線，若正在自動錄音則自動匯出並上傳錄音檔，隨後清理資源
        """
        guild = self.bot.get_guild(guild_id)
        player = self.players.get(guild_id)
        target_ch = player.target_text_channel if player else None

        if guild and guild.voice_client:
            vc = guild.voice_client
            if vc.is_recording():
                try:
                    vc.stop_recording()
                except Exception:
                    pass
            await vc.disconnect()

        # 若有正在錄音的會話，自動混音輸出 MP3 並上傳至文字頻道
        if guild_id in self.sinks:
            sink = self.sinks[guild_id]
            if sink.is_session_recording and sink.session_chunks:
                try:
                    import os, time
                    timestr = time.strftime("%Y%m%d_%H%M%S")
                    filename = f"session_{timestr}.mp3"
                    out_path = await sink.stop_session_recording_async(filename)
                    if out_path and os.path.exists(out_path):
                        file_size = os.path.getsize(out_path)
                        if target_ch:
                            embed = discord.Embed(
                                title="💾 語音頻道自動錄音已存檔！",
                                description=f"通話已結束，語音頻道所有成員之對話已自動對齊混音！\n📦 **檔案大小:** {file_size / (1024*1024):.2f} MB",
                                color=0x2ECC71
                            )
                            if file_size < 24 * 1024 * 1024:
                                file = discord.File(out_path, filename=filename)
                                await target_ch.send(embed=embed, file=file)
                            else:
                                embed.set_footer(text=f"檔案已儲存於本機: {out_path}")
                                await target_ch.send(embed=embed)
                except Exception as ex:
                    logger.error(f"自動錄音輸出上傳失敗: {ex}")

            sink.cleanup()
            del self.sinks[guild_id]

        if guild_id in self.players:
            self.players[guild_id].stop()
            del self.players[guild_id]

        self.manual_joins.pop(guild_id, None)

