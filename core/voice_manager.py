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
        self._disconnect_locks: Dict[int, asyncio.Lock] = {}
        self._connect_locks: Dict[int, asyncio.Lock] = {}

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

        if guild.id not in self._connect_locks:
            self._connect_locks[guild.id] = asyncio.Lock()

        async with self._connect_locks[guild.id]:
            vc = guild.voice_client

            if vc and vc.is_connected():
                if vc.channel and vc.channel.id != voice_channel.id:
                    if vc.is_recording():
                        try:
                            vc.stop_recording()
                        except Exception:
                            pass
                    await vc.move_to(voice_channel)
                    await asyncio.sleep(0.5)
                elif vc.channel and vc.channel.id == voice_channel.id:
                    self.ensure_recording(guild.id)
                    if text_channel:
                        self.get_player(guild.id).text_channel = text_channel
                    return vc
            else:
                # 處理斷線中、半中斷或殘留之殭屍連線，先進行強制清理
                if vc is not None:
                    try:
                        if vc.is_recording():
                            vc.stop_recording()
                    except Exception:
                        pass
                    try:
                        await vc.disconnect(force=True)
                    except Exception:
                        pass
                    try:
                        vc.cleanup()
                    except Exception:
                        pass
                    if hasattr(voice_channel, "_state"):
                        voice_channel._state._remove_voice_client(guild.id)
                    await asyncio.sleep(0.5)

                if hasattr(voice_channel, "_state"):
                    voice_channel._state._remove_voice_client(guild.id)

                try:
                    vc = await voice_channel.connect(timeout=45.0, reconnect=True)
                except (discord.ClientException, discord.errors.ConnectionClosed, asyncio.TimeoutError) as e:
                    # 若 Pycord 內部殘留已連線標記或連線重置 (如 4006)，強制清理並重試
                    logger.warning(f"語音初次連線遭遇標記或連線衝突 ({e})，正在執行深度重置並重試...")
                    if hasattr(voice_channel, "_state"):
                        voice_channel._state._remove_voice_client(guild.id)
                    if guild.voice_client:
                        try:
                            await guild.voice_client.disconnect(force=True)
                        except Exception:
                            pass
                        try:
                            guild.voice_client.cleanup()
                        except Exception:
                            pass
                    if hasattr(voice_channel, "_state"):
                        voice_channel._state._remove_voice_client(guild.id)
                    await asyncio.sleep(1.0)
                    vc = await voice_channel.connect(timeout=45.0, reconnect=True)

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
            # 關鍵保護：必須確認 vc 已成功建立連線且非錄音中，杜絕 RecordingException: not connected to a voice channel
            if vc and vc.is_connected():
                self.ensure_recording(guild.id)

            return vc

    def _create_record_callback(self, guild_id: int, vc: discord.VoiceClient, sink: RollingBufferSink):
        def record_finished_callback(error=None, *args, **kwargs):
            if error:
                logger.error(f"伺服器 {guild_id} 的語音錄音發生錯誤終止: {error}", exc_info=isinstance(error, Exception))
            else:
                logger.info(f"伺服器 {guild_id} 的語音錄音已結束。")

            # 自癒機制：若語音頻道依然連線中且該伺服器錄音 sink 仍未被顯式釋放，自動重新掛載錄音接收器
            if vc and vc.is_connected() and guild_id in self.sinks and not getattr(sink, "finished", False):
                logger.info(f"偵測到伺服器 {guild_id} 語音連線仍處於活躍狀態，正在自動重新掛載錄音接收器 (Auto-Reattach Sink)...")
                try:
                    self.bot.loop.call_later(1.0, lambda: self.ensure_recording(guild_id))
                except Exception as ex:
                    logger.debug(f"排程自動重啟錄音例外: {ex}")
        return record_finished_callback

    def ensure_recording(self, guild_id: int) -> bool:
        """
        確保該伺服器的錄音器處於活躍錄音狀態。
        若語音連線存在但錄音接收器因故中斷，自動重啟並無縫掛載。
        """
        guild = self.bot.get_guild(guild_id)
        if not guild or not guild.voice_client:
            return False
        vc = guild.voice_client
        if not vc.is_connected():
            return False

        sink = self.sinks.get(guild_id)
        if not sink or getattr(sink, "finished", False):
            sink = RollingBufferSink(
                buffer_seconds=float(REPLAY_BUFFER_SECONDS + 10),
                auto_record=self.auto_record,
                vc=vc
            )
            sink.init(vc)
            self.sinks[guild_id] = sink

        if not vc.is_recording():
            try:
                cb = self._create_record_callback(guild_id, vc, sink)
                vc.start_recording(sink, cb)
                logger.info(f"伺服器 {guild_id} 語音錄音接收器已自動掛載並啟動 (自動錄音={self.auto_record})")
                return True
            except Exception as e:
                logger.warning(f"啟動錄音接收器失敗: {e}")
                return False
        return True

    async def disconnect_voice(self, guild_id: int):
        """
        斷開語音連線，若正在自動錄音則自動匯出並上傳錄音檔，隨後清理資源。
        具備異步互斥鎖保護機制，徹底防止並行重入觸發重複匯出與空檔問題。
        """
        if guild_id not in self._disconnect_locks:
            self._disconnect_locks[guild_id] = asyncio.Lock()

        async with self._disconnect_locks[guild_id]:
            guild = self.bot.get_guild(guild_id)
            player = self.players.get(guild_id)
            target_ch = player.target_text_channel if player else None

            # 1. 斷開語音連線
            if guild and guild.voice_client:
                vc = guild.voice_client
                if vc.is_recording():
                    try:
                        vc.stop_recording()
                    except Exception:
                        pass
                try:
                    await vc.disconnect(force=True)
                except Exception as ex:
                    logger.debug(f"斷開語音連線跳過: {ex}")

            # 2. 若有正在錄音的會話，原子性移出 sink 並輸出 MP3
            sink = self.sinks.pop(guild_id, None)
            if sink:
                if sink.is_session_recording and sink.session_chunks:
                    try:
                        import os, time
                        timestr = time.strftime("%Y%m%d_%H%M%S")
                        filename = f"session_{timestr}.mp3"
                        out_path = await sink.stop_session_recording_async(filename)
                        if out_path and os.path.exists(out_path):
                            file_size = os.path.getsize(out_path)
                            # 只有檔案大小大於 50KB (有效錄音，過濾極短雜訊碎片) 時才發送通知
                            if file_size > 50000 and target_ch:
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
                            elif file_size <= 50000:
                                try:
                                    os.remove(out_path)
                                except Exception:
                                    pass
                    except Exception as ex:
                        logger.error(f"自動錄音輸出上傳失敗: {ex}")

                sink.cleanup()

            # 3. 清理音樂播放器
            if guild_id in self.players:
                self.players[guild_id].stop()
                del self.players[guild_id]

            self.manual_joins.pop(guild_id, None)

    async def cleanup_all(self):
        """
        [安全釋放] 徹底釋放所有伺服器的語音連線、錄音器背景執行緒與音樂播放器工作資源
        """
        # 1. 停止並釋放所有播放器執行緒與快取串流
        for guild_id, player in list(self.players.items()):
            try:
                player.stop()
            except Exception as ex:
                logger.debug(f"停止播放器例外 ({guild_id}): {ex}")
        self.players.clear()

        # 2. 清理所有錄音 Sink
        for guild_id, sink in list(self.sinks.items()):
            try:
                sink.cleanup()
            except Exception as ex:
                logger.debug(f"清理 Sink 例外 ({guild_id}): {ex}")
        self.sinks.clear()

        # 3. 斷開所有活躍語音客戶端
        for vc in list(self.bot.voice_clients):
            try:
                if vc.is_recording():
                    vc.stop_recording()
            except Exception:
                pass
            try:
                await vc.disconnect(force=True)
            except Exception:
                pass
            try:
                vc.cleanup()
            except Exception:
                pass

        self.manual_joins.clear()
        logger.info("已完全釋放所有語音連線與相關背景執行緒資源。")

