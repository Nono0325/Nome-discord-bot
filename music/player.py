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
    """

    def __init__(self, bot: discord.Bot, guild_id: int):
        self.bot = bot
        self.guild_id = guild_id
        
        self.queue: asyncio.Queue[Song] = asyncio.Queue()
        self.queue_list: List[Song] = []  # 方便展示與查看列表
        self.history: List[Song] = []
        
        self.current: Optional[Song] = None
        self.current_source: Optional[YTDLSource] = None
        
        self.next_event = asyncio.Event()
        self.volume: float = 0.5
        self.loop_mode: str = "off"  # "off", "song", "queue"
        
        self.text_channel: Optional[discord.TextChannel] = None
        self.player_task: Optional[asyncio.Task] = None
        self.is_stopped: bool = False

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
            # 重新建置 asyncio.Queue
            new_q = asyncio.Queue()
            new_q.put_nowait(song)
            while not self.queue.empty():
                new_q.put_nowait(self.queue.get_nowait())
            self.queue = new_q
        else:
            self.queue_list.append(song)
            await self.queue.put(song)
            
        self.start_loop()

    async def _player_loop(self):
        """核心播放循環"""
        while not self.is_stopped:
            self.next_event.clear()

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

            try:
                source = await YTDLSource.create_source(song, volume=self.volume)
                self.current_source = source

                def after_playing(error):
                    if error:
                        logger.error(f"播放歌曲 {song.title} 時發生錯誤: {error}")
                    self.bot.loop.call_soon_threadsafe(self.next_event.set)

                vc.play(source, after=after_playing)

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
        embed.add_field(name="音量", value=f"{int(self.volume * 100)}%", inline=True)
        embed.add_field(name="佇列尚餘", value=f"{len(self.queue_list)} 首", inline=True)

        if self.current.thumbnail:
            embed.set_thumbnail(url=self.current.thumbnail)
        embed.set_footer(text="點擊下方按鈕可進行快速控制，或使用 /clip 擷取前一分鐘語音對話")

        view = MusicControlView(self)
        await target.send(embed=embed, view=view)

    def pause(self):
        vc = self.voice_client
        if vc and vc.is_playing():
            vc.pause()

    def resume(self):
        vc = self.voice_client
        if vc and vc.is_paused():
            vc.resume()

    def skip(self):
        vc = self.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()

    def stop(self):
        self.is_stopped = True
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
    即時控制按鈕視圖 (暫停/播放、下一首、停止、1分鐘回放剪輯)
    """

    def __init__(self, player: GuildPlayer):
        super().__init__(timeout=180)
        self.player = player

    @discord.ui.button(label="暫停 / 繼續", style=discord.ButtonStyle.primary, emoji="⏯️")
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

    @discord.ui.button(label="下一首", style=discord.ButtonStyle.secondary, emoji="⏭️")
    async def skip_track(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.player.skip()
        await interaction.response.send_message("⏭️ 已跳至下一首！", ephemeral=True)

    @discord.ui.button(label="停止播放", style=discord.ButtonStyle.danger, emoji="⏹️")
    async def stop_player(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.player.stop()
        await interaction.response.send_message("⏹️ 已停止播放並清空佇列！", ephemeral=True)

    @discord.ui.button(label="擷取前 1 分鐘對話", style=discord.ButtonStyle.success, emoji="🎬")
    async def clip_replay(self, button: discord.ui.Button, interaction: discord.Interaction):
        # 轉交給錄音 cog 處理
        rec_cog = interaction.client.get_cog("RecordCog")
        if rec_cog:
            await rec_cog.handle_clip(interaction, seconds=60)
        else:
            await interaction.response.send_message("❌ 錄音模組未啟用！", ephemeral=True)
