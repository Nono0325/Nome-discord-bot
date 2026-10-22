import time
import random
import asyncio
import logging
from typing import Optional, List
import discord
from music.ytdl_source import Song, YTDLSource
from core.guild_settings import guild_settings

logger = logging.getLogger(__name__)

class GuildPlayer:
    """
    負責單一 Discord 伺服器 (Guild) 的音樂播放佇列與播放控制
    具備多工非同步預載 (Prefetching) 與無盡電台模式 (Autoplay)
    """

    def __init__(self, bot: discord.Bot, guild_id: int):
        self.bot = bot
        self.guild_id = guild_id
        
        self.queue: asyncio.Queue[Song] = asyncio.Queue()
        self.queue_list: List[Song] = []  # 方便展示與查看列表
        self.history: List[Song] = []
        
        self.current: Optional[Song] = None
        self.current_source: Optional[YTDLSource] = None
        
        # 播放進度與暫停時間追蹤 (供動態同步歌詞精準對齊使用)
        self.play_start_time: Optional[float] = None
        self.pause_start_time: Optional[float] = None
        self.total_paused_duration: float = 0.0

        self.next_event = asyncio.Event()
        self.volume: float = 0.5
        self.loop_mode: str = "off"  # "off", "song", "queue"
        self.autoplay: bool = False   # 無盡推薦電台模式
        self.current_bitrate: int = 128  # 當前播放音訊位元率 (kbps)
        
        self.text_channel: Optional[discord.TextChannel] = None
        self.player_task: Optional[asyncio.Task] = None
        self.prefetch_task: Optional[asyncio.Task] = None
        self.is_stopped: bool = False

    @property
    def elapsed_seconds(self) -> float:
        """取得目前曲目已播放的秒數 (扣除暫停時間)"""
        if not self.play_start_time or not self.current:
            return 0.0
        if self.pause_start_time:
            return max(0.0, self.pause_start_time - self.play_start_time - self.total_paused_duration)
        return max(0.0, time.time() - self.play_start_time - self.total_paused_duration)

    @property
    def target_text_channel(self) -> Optional[discord.TextChannel]:
        """優先回傳伺服器設定的專屬音樂頻道，未設定時回傳預設文字頻道"""
        guild = self.bot.get_guild(self.guild_id)
        if guild:
            ch = guild_settings.get_music_channel(guild)
            if ch:
                return ch
        return self.text_channel

    @property
    def voice_client(self) -> Optional[discord.VoiceClient]:
        guild = self.bot.get_guild(self.guild_id)
        return guild.voice_client if guild else None

    def start_loop(self):
        """啟動播放循環監聽任務"""
        if self.player_task is None or self.player_task.done():
            self.is_stopped = False
            self.player_task = self.bot.loop.create_task(self._player_loop())

    async def add_song(self, song: Song, to_front: bool = False):
        """加入歌曲至佇列"""
        if to_front:
            self.queue_list.insert(0, song)
            # 保持相同 Queue 物件，清空並依 queue_list 重新填入，避免正在 await get() 的協程被懸掛遺棄
            while not self.queue.empty():
                try:
                    self.queue.get_nowait()
                except Exception:
                    break
            for s in self.queue_list:
                self.queue.put_nowait(s)
        else:
            self.queue_list.append(song)
            await self.queue.put(song)
            
        self.start_loop()
        self.trigger_prefetch()

    def trigger_prefetch(self):
        """[多工處理] 觸發下一首歌曲的背景提前快取與預載"""
        vc = self.voice_client
        if vc and vc.is_playing() and self.queue_list:
            if self.prefetch_task is None or self.prefetch_task.done():
                next_song = self.queue_list[0]
                if not getattr(next_song, "local_filepath", None):
                    self.prefetch_task = self.bot.loop.create_task(
                        YTDLSource.prefetch_stream(next_song)
                    )

    def shuffle(self) -> int:
        """[隨機播放] 隨機混洗當前佇列"""
        if len(self.queue_list) < 2:
            return len(self.queue_list)

        random.shuffle(self.queue_list)
        # 保持相同 Queue 物件，清空並依打亂後的 queue_list 重新填入
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except Exception:
                break
        for s in self.queue_list:
            self.queue.put_nowait(s)

        self.trigger_prefetch()
        return len(self.queue_list)

    async def _fetch_autoplay_recommendations(self):
        """[無盡電台] 當佇列用盡時，自動向 YouTube Music 推薦相似好歌加入佇列"""
        from music.ytm_client import ytm_client
        seed_id = None
        if self.current:
            seed_id = self.current.id
        elif self.history:
            seed_id = self.history[-1].id

        if not seed_id:
            return

        try:
            logger.info(f"無盡電台模式啟用中，正在為曲目 {seed_id} 探索自動推薦歌曲...")
            radio_songs = await asyncio.to_thread(ytm_client.get_radio_songs, seed_id)
            if radio_songs:
                # 排除已在歷史記錄中的歌曲
                history_ids = {h.id for h in self.history[-20:]}
                added_count = 0
                for r in radio_songs[:5]:
                    if r["id"] in history_ids:
                        continue
                    new_song = Song(
                        id=r["id"],
                        title=r["title"],
                        artist=r["artist"],
                        duration=r["duration"],
                        thumbnail=r["thumbnail"],
                        webpage_url=r["url"],
                        requester="🤖 YouTube Music 無盡推薦"
                    )
                    await self.add_song(new_song)
                    added_count += 1

                if added_count > 0:
                    ch = self.target_text_channel
                    if ch:
                        await ch.send(f"📻 **無盡電台**：已自動無縫載入 **{added_count}** 首推薦音樂！")
        except Exception as e:
            logger.error(f"無盡電台推薦獲取失敗: {e}")

    async def _player_loop(self):
        """核心播放循環"""
        while not self.is_stopped:
            self.next_event.clear()

            # 檢查是否需要自動填充推薦歌曲
            if self.autoplay and self.queue.empty():
                await self._fetch_autoplay_recommendations()

            # 等候下一首歌曲
            try:
                # 5分鐘內無新歌曲則自動退出
                song = await asyncio.wait_for(self.queue.get(), timeout=300.0)
            except asyncio.TimeoutError:
                if self.voice_client and not self.voice_client.is_playing():
                    ch = self.target_text_channel
                    if ch:
                        await ch.send("⏱️ 播放佇列已空閒超過 5 分鐘，機器人已自動離開語音頻道。")
                    await self.voice_client.disconnect()
                break

            # 從 queue_list 移除對應的第一項
            if self.queue_list and self.queue_list[0] == song:
                self.queue_list.pop(0)

            self.current = song

            vc = self.voice_client
            if not vc or not vc.is_connected():
                logger.warning("語音客戶端未連線，停止播放迴圈。")
                break

            # 觸發下一首歌曲的預載
            self.trigger_prefetch()

            try:
                source = await YTDLSource.create_source(song, volume=self.volume)
                self.current_source = source

                def after_playing(error):
                    if error:
                        logger.error(f"播放歌曲 {song.title} 時發生錯誤: {error}")
                    self.bot.loop.call_soon_threadsafe(self.next_event.set)

                self.play_start_time = time.time()
                self.pause_start_time = None
                self.total_paused_duration = 0.0

                # 計算該伺服器與語音頻道支援的最高音訊位元率 (kbps)
                ch_kbps = int(vc.channel.bitrate / 1000) if getattr(vc.channel, "bitrate", None) else 128
                limit_kbps = int(vc.guild.bitrate_limit / 1000) if hasattr(vc.guild, "bitrate_limit") else ch_kbps
                target_bitrate = min(512, max(ch_kbps, limit_kbps, 128))
                self.current_bitrate = target_bitrate

                # 若 VoiceClient 已經建立 Opus 編碼器，即時調整至最高音質參數
                if hasattr(vc, "encoder") and vc.encoder:
                    try:
                        vc.encoder.set_bitrate(target_bitrate)
                        vc.encoder.set_signal_type("music")
                        vc.encoder.set_bandwidth("full")
                        vc.encoder.set_fec(True)
                        vc.encoder.set_expected_packet_loss_percent(0.05)
                    except Exception as e_enc:
                        logger.debug(f"設置 Opus 編碼器參數警告: {e_enc}")

                # 以最高音質標準 (OPUS_SIGNAL_MUSIC, OPUS_APPLICATION_AUDIO, fullband, 最大位元率) 播放音訊
                vc.play(
                    source,
                    after=after_playing,
                    application="audio",
                    bitrate=target_bitrate,
                    fec=True,
                    expected_packet_loss=0.05,
                    bandwidth="full",
                    signal_type="music"
                )

                # 發送正在播放 Embed
                await self.send_now_playing()

            except Exception as e:
                logger.error(f"建立音訊來源失敗: {e}")
                ch = self.target_text_channel
                if ch:
                    await ch.send(f"⚠️ 無法播放 **{song.title}**: {e}")
                self.next_event.set()

            # 等待當前歌曲播放完畢
            await self.next_event.wait()

            # 處理循環模式
            if self.loop_mode == "song" and self.current:
                await self.add_song(self.current, to_front=True)
            elif self.loop_mode == "queue" and self.current:
                await self.add_song(self.current, to_front=False)
            elif self.current:
                self.history.append(self.current)

            self.play_start_time = None
            self.pause_start_time = None
            self.total_paused_duration = 0.0
            self.current = None
            self.current_source = None

    async def send_now_playing(self, channel: Optional[discord.TextChannel] = None):
        """發送目前播放中的美觀 Embed 卡片"""
        target = channel or self.target_text_channel
        if not self.current or not target:
            return

        embed = discord.Embed(
            title="🎶 正在播放 (Now Playing)",
            description=f"[{self.current.title}]({self.current.webpage_url})",
            color=0xFF0033  # YouTube Music 紅
        )
        embed.add_field(name="藝人 / 頻道", value=self.current.artist, inline=True)
        embed.add_field(name="時長", value=self.current.duration, inline=True)
        embed.add_field(name="點播者", value=self.current.requester, inline=True)
        
        loop_str = {"off": "關閉", "song": "單曲循環", "queue": "清單循環"}.get(self.loop_mode, "關閉")
        embed.add_field(name="循環模式", value=loop_str, inline=True)
        embed.add_field(name="無盡電台", value="🟢 開啟" if self.autoplay else "⚪ 關閉", inline=True)
        
        bitrate_display = getattr(self, "current_bitrate", 128)
        embed.add_field(name="音質規格", value=f"✨ 48kHz Hi-Fi ({bitrate_display} kbps)", inline=True)
        embed.add_field(name="音量", value=f"{int(self.volume * 100)}%", inline=True)
        embed.add_field(name="佇列尚餘", value=f"{len(self.queue_list)} 首", inline=True)

        if self.current.thumbnail:
            embed.set_thumbnail(url=self.current.thumbnail)
        embed.set_footer(text=f"✨ Hi-Fi 原音品質 • 48kHz 立體聲 • Opus {bitrate_display} kbps • 點擊按鈕快速控制")

        view = MusicControlView(self)
        await target.send(embed=embed, view=view)

    def pause(self):
        vc = self.voice_client
        if vc and vc.is_playing():
            if not self.pause_start_time:
                self.pause_start_time = time.time()
            vc.pause()

    def resume(self):
        vc = self.voice_client
        if vc and vc.is_paused():
            if self.pause_start_time:
                self.total_paused_duration += time.time() - self.pause_start_time
                self.pause_start_time = None
            vc.resume()

    def skip(self):
        vc = self.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()

    def stop(self):
        self.is_stopped = True
        self.play_start_time = None
        self.pause_start_time = None
        self.total_paused_duration = 0.0
        self.queue_list.clear()
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except Exception:
                break
        vc = self.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()

    def set_volume(self, vol: float):
        self.volume = max(0.0, min(2.0, vol))
        if self.current_source:
            self.current_source.volume = self.volume


class MusicControlView(discord.ui.View):
    """
    即時控制按鈕視圖：
    包含暫停/播放、下一首、隨機混洗、同步歌詞、無盡電台開關、停止播放與 1 分鐘語音剪輯
    """

    def __init__(self, player: GuildPlayer):
        super().__init__(timeout=180)
        self.player = player
        # 更新按鈕樣式以反映目前無盡電台狀態
        self.update_button_styles()

    def update_button_styles(self):
        for child in self.children:
            if hasattr(child, "custom_id") and child.custom_id == "toggle_autoplay":
                if self.player.autoplay:
                    child.style = discord.ButtonStyle.success
                    child.label = "無盡電台: 開"
                else:
                    child.style = discord.ButtonStyle.secondary
                    child.label = "無盡電台: 關"

    @discord.ui.button(label="暫停 / 繼續", style=discord.ButtonStyle.primary, emoji="⏯️", row=0)
    async def toggle_play(self, button: discord.ui.Button, interaction: discord.Interaction):
        vc = self.player.voice_client
        if not vc:
            return await interaction.response.send_message("❌ 機器人目前不在語音頻道中！", ephemeral=True)
        
        if vc.is_paused():
            self.player.resume()
            await interaction.response.send_message("▶️ 已繼續播放！", ephemeral=True)
        elif vc.is_playing():
            self.player.pause()
            await interaction.response.send_message("⏸️ 已暫停播放！", ephemeral=True)
        else:
            await interaction.response.send_message("目前無音訊正在播放。", ephemeral=True)

    @discord.ui.button(label="下一首", style=discord.ButtonStyle.secondary, emoji="⏭️", row=0)
    async def skip_track(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.player.skip()
        await interaction.response.send_message("⏭️ 已跳至下一首！", ephemeral=True)

    @discord.ui.button(label="隨機混洗", style=discord.ButtonStyle.secondary, emoji="🔀", row=0)
    async def shuffle_queue(self, button: discord.ui.Button, interaction: discord.Interaction):
        count = self.player.shuffle()
        if count < 2:
            return await interaction.response.send_message("⚠️ 佇列歌曲少於 2 首，無法隨機排列。", ephemeral=True)
        await interaction.response.send_message(f"🔀 已成功打亂 **{count}** 首歌曲順序！", ephemeral=True)

    @discord.ui.button(label="同步歌詞", style=discord.ButtonStyle.success, emoji="🎙️", row=0)
    async def show_lyrics(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not self.player.current:
            return await interaction.response.send_message("❌ 目前沒有正在播放的歌曲！", ephemeral=True)

        await interaction.response.defer()
        from music.lyrics_service import lyrics_service
        from music.lyrics_view import LiveLyricsView, FullLyricsView, build_synced_embed

        song = self.player.current
        lyrics_data = await lyrics_service.get_lyrics(
            title=song.title,
            artist=song.artist,
            video_id=song.id,
            thumbnail=song.thumbnail
        )

        if not lyrics_data:
            return await interaction.followup.send(
                f"⚠️ 找不到歌曲 **{song.title}** 的歌詞資料。",
                ephemeral=True
            )

        if lyrics_data.synced and lyrics_data.lines:
            view = LiveLyricsView(
                player=self.player,
                song=song,
                lyrics_data=lyrics_data,
                requester_id=interaction.user.id
            )
            embed, _ = build_synced_embed(self.player, song, lyrics_data)
            msg = await interaction.followup.send(embed=embed, view=view)
            view.start_sync(msg)
        else:
            view = FullLyricsView(
                lyrics_data=lyrics_data,
                player=self.player,
                song=song,
                requester_id=interaction.user.id
            )
            msg = await interaction.followup.send(embed=view.get_embed(), view=view)
            view.message = msg

    @discord.ui.button(label="無盡電台: 關", style=discord.ButtonStyle.secondary, emoji="🔁", custom_id="toggle_autoplay", row=1)
    async def toggle_autoplay(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.player.autoplay = not self.player.autoplay
        self.update_button_styles()
        status_str = "🟢 已開啟無盡推薦電台！佇列結束時將自動續播相似歌曲。" if self.player.autoplay else "⚪ 已關閉無盡電台。"
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(status_str, ephemeral=True)

    @discord.ui.button(label="前 1 分鐘對話", style=discord.ButtonStyle.secondary, emoji="🎬", row=1)
    async def clip_replay(self, button: discord.ui.Button, interaction: discord.Interaction):
        rec_cog = interaction.client.get_cog("RecordCog")
        if rec_cog:
            await rec_cog.handle_clip(interaction, seconds=60)
        else:
            await interaction.response.send_message("❌ 錄音模組未啟用！", ephemeral=True)

    @discord.ui.button(label="收藏本曲", style=discord.ButtonStyle.secondary, emoji="⭐", row=1)
    async def favorite_current_song(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not self.player.current:
            return await interaction.response.send_message("❌ 目前沒有正在播放的歌曲！", ephemeral=True)
        from core.favorites_manager import favorites_manager
        ok, msg, count = favorites_manager.add_favorite(
            interaction.user.id,
            self.player.current,
            username=interaction.user.display_name
        )
        await interaction.response.send_message(
            f"{msg}\n📚 您目前共收藏了 **{count}** 首歌曲！隨時可在控制台點擊「⭐ 私房收藏」隨機或全部播放。",
            ephemeral=True
        )

    @discord.ui.button(label="停止播放", style=discord.ButtonStyle.danger, emoji="⏹️", row=1)
    async def stop_player(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.player.stop()
        await interaction.response.send_message("⏹️ 已停止播放並清空佇列！", ephemeral=True)
