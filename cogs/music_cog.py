import random
import logging
from typing import Optional
import discord
from discord.ext import commands
from discord.commands import slash_command, Option
from music.ytm_client import ytm_client
from music.ytdl_source import Song, YTDLSource
from music.player import GuildPlayer
from core.guild_settings import guild_settings

logger = logging.getLogger(__name__)

class PlaylistSelect(discord.ui.Select):
    """
    YouTube Music 個人播放清單下拉選單
    """

    def __init__(self, playlists: list, player: GuildPlayer):
        options = []
        for pl in playlists[:25]:
            desc = f"共 {pl['count']} 首歌曲" if pl.get("count") else "播放清單"
            options.append(
                discord.SelectOption(
                    label=pl["title"][:95],
                    value=pl["id"],
                    description=desc[:95],
                    emoji="📑"
                )
            )
        super().__init__(placeholder="請選擇要載入的 YouTube Music 歌單...", min_values=1, max_values=1, options=options)
        self.player = player

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        playlist_id = self.values[0]
        try:
            songs = ytm_client.get_playlist_songs(playlist_id, limit=50)
            if not songs:
                return await interaction.followup.send("⚠️ 此播放清單內沒有找到可播放的歌曲。")

            user_name = interaction.user.display_name
            added_count = 0
            for s in songs:
                song_obj = Song(
                    id=s["id"],
                    title=s["title"],
                    artist=s["artist"],
                    duration=s["duration"],
                    thumbnail=s["thumbnail"],
                    webpage_url=s["url"],
                    requester=user_name
                )
                await self.player.add_song(song_obj)
                added_count += 1

            embed = discord.Embed(
                title="📑 成功載入 YouTube Music 歌單！",
                description=f"已將 **{added_count}** 首歌曲加入播放佇列！",
                color=0xFF0033
            )
            await interaction.followup.send(embed=embed)
        except Exception as e:
            await interaction.followup.send(f"❌ 讀取歌單失敗: {e}")

class PlaylistSelectView(discord.ui.View):
    def __init__(self, playlists: list, player: GuildPlayer):
        super().__init__(timeout=120)
        self.add_item(PlaylistSelect(playlists, player))

class MusicCog(commands.Cog):
    """
    YouTube Music 音樂播放指令群
    """

    def __init__(self, bot: discord.Bot):
        self.bot = bot

    @property
    def voice_mgr(self):
        return self.bot.voice_manager

    async def _ensure_voice(self, ctx: discord.ApplicationContext) -> Optional[discord.VoiceClient]:
        """確保使用者在語音頻道，並連線機器人"""
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.respond("❌ 請先加入一個語音頻道！", ephemeral=True)
            return None

        voice_channel = ctx.author.voice.channel
        vc = await self.voice_mgr.connect_voice(voice_channel, text_channel=ctx.channel)
        return vc

    @slash_command(name="play", description="在語音頻道播放 YouTube Music 歌曲或網址")
    async def play(
        self,
        ctx: discord.ApplicationContext,
        query: Option(str, "歌曲名稱、關鍵字或 YouTube / YouTube Music 網址", required=True)
    ):
        await ctx.defer()
        vc = await self._ensure_voice(ctx)
        if not vc:
            return

        player = self.voice_mgr.get_player(ctx.guild.id)
        player.text_channel = ctx.channel

        user_name = ctx.author.display_name

        try:
            # 判斷是否為直接網址
            if query.startswith("http://") or query.startswith("https://"):
                song = await YTDLSource.from_query(query, requester=user_name)
            else:
                # 優先使用 YouTube Music 搜尋最佳曲目
                results = ytm_client.search_songs(query, limit=5)
                if results:
                    top = results[0]
                    song = Song(
                        id=top["id"],
                        title=top["title"],
                        artist=top["artist"],
                        duration=top["duration"],
                        thumbnail=top["thumbnail"],
                        webpage_url=top["url"],
                        requester=user_name
                    )
                else:
                    song = await YTDLSource.from_query(query, requester=user_name)

            await player.add_song(song)

            embed = discord.Embed(
                title="🎵 已加入播放佇列",
                description=f"[{song.title}]({song.webpage_url})",
                color=0xFF0033
            )
            embed.add_field(name="藝人", value=song.artist, inline=True)
            embed.add_field(name="時長", value=song.duration, inline=True)
            embed.add_field(name="點播者", value=user_name, inline=True)
            embed.add_field(name="目前佇列位置", value=f"第 {len(player.queue_list)} 位", inline=True)
            
            dedicated_ch = guild_settings.get_music_channel(ctx.guild)
            if dedicated_ch and dedicated_ch.id != ctx.channel.id:
                embed.add_field(name="📌 專屬音樂頻道", value=f"控制卡片與通知已同步至 {dedicated_ch.mention}", inline=False)

            if song.thumbnail:
                embed.set_thumbnail(url=song.thumbnail)

            await ctx.respond(embed=embed)

        except Exception as e:
            logger.error(f"播放歌曲失敗: {e}")
            await ctx.respond(f"❌ 搜尋或解析歌曲失敗: {e}")

    @slash_command(name="ytm_liked", description="播放 Google 帳號 YouTube Music 中已按讚的好音樂")
    async def ytm_liked(
        self,
        ctx: discord.ApplicationContext,
        limit: Option(int, "要加入的歌曲數量 (預設 25)", required=False, default=25)
    ):
        await ctx.defer()
        if not ytm_client.is_authenticated():
            return await ctx.respond(
                "❌ 尚未登入 Google 帳號！\n請先使用 `/google_login` 指令或執行 `python setup_google.py` 綁定 Google 帳號。",
                ephemeral=True
            )

        vc = await self._ensure_voice(ctx)
        if not vc:
            return

        player = self.voice_mgr.get_player(ctx.guild.id)
        player.text_channel = ctx.channel

        try:
            songs = ytm_client.get_liked_songs(limit=limit)
            if not songs:
                return await ctx.respond("⚠️ 您的 Google 帳號中沒有找到已按讚的歌曲！")

            user_name = ctx.author.display_name
            for s in songs:
                song_obj = Song(
                    id=s["id"],
                    title=s["title"],
                    artist=s["artist"],
                    duration=s["duration"],
                    thumbnail=s["thumbnail"],
                    webpage_url=s["url"],
                    requester=user_name
                )
                await player.add_song(song_obj)

            embed = discord.Embed(
                title="💖 YouTube Music 已按讚歌曲",
                description=f"已成功載入 **{len(songs)}** 首最愛歌曲至播放佇列！",
                color=0xFF0033
            )
            await ctx.respond(embed=embed)
        except Exception as e:
            await ctx.respond(f"❌ 讀取已按讚歌曲失敗: {e}")

    @slash_command(name="ytm_playlists", description="列出並選擇登入之 Google 帳號的個人播放清單")
    async def ytm_playlists(self, ctx: discord.ApplicationContext):
        await ctx.defer()
        if not ytm_client.is_authenticated():
            return await ctx.respond(
                "❌ 尚未登入 Google 帳號！\n請先使用 `/google_login` 指令或執行 `python setup_google.py` 綁定 Google 帳號。",
                ephemeral=True
            )

        vc = await self._ensure_voice(ctx)
        if not vc:
            return

        player = self.voice_mgr.get_player(ctx.guild.id)
        player.text_channel = ctx.channel

        try:
            playlists = ytm_client.get_user_playlists(limit=25)
            if not playlists:
                return await ctx.respond("⚠️ 在您的 Google 帳號中未找到任何播放清單。")

            embed = discord.Embed(
                title="📑 您的 YouTube Music 個人播放清單",
                description="請點擊下方選單選擇欲載入並播放的歌單：",
                color=0xFF0033
            )
            view = PlaylistSelectView(playlists, player)
            await ctx.respond(embed=embed, view=view)
        except Exception as e:
            await ctx.respond(f"❌ 取得個人清單失敗: {e}")

    @slash_command(name="ytm_radio", description="根據指定歌曲開啟 YouTube Music 無限電台")
    async def ytm_radio(
        self,
        ctx: discord.ApplicationContext,
        query: Option(str, "種子歌曲名稱或藝人", required=True)
    ):
        await ctx.defer()
        vc = await self._ensure_voice(ctx)
        if not vc:
            return

        player = self.voice_mgr.get_player(ctx.guild.id)
        player.text_channel = ctx.channel

        results = ytm_client.search_songs(query, limit=1)
        if not results:
            return await ctx.respond(f"❌ 找不到與 `{query}` 相符的歌曲以產生電台。")

        seed_song = results[0]
        radio_tracks = ytm_client.get_radio_songs(seed_song["id"])
        if not radio_tracks:
            return await ctx.respond("⚠️ 無法為此歌曲生成電台推薦。")

        user_name = ctx.author.display_name
        # 先加入種子曲
        seed_obj = Song(
            id=seed_song["id"],
            title=seed_song["title"],
            artist=seed_song["artist"],
            duration=seed_song["duration"],
            thumbnail=seed_song["thumbnail"],
            webpage_url=seed_song["url"],
            requester=user_name
        )
        await player.add_song(seed_obj)

        for track in radio_tracks[:15]:
            track_obj = Song(
                id=track["id"],
                title=track["title"],
                artist=track["artist"],
                duration=track["duration"],
                thumbnail=track["thumbnail"],
                webpage_url=track["url"],
                requester="YouTube Music 電台推薦"
            )
            await player.add_song(track_obj)

        embed = discord.Embed(
            title="📻 YouTube Music 延伸電台已啟動",
            description=f"種子曲目：[{seed_song['title']}]({seed_song['url']})\n已自動載入 **{len(radio_tracks[:15]) + 1}** 首相似好歌至佇列！",
            color=0xFF0033
        )
        await ctx.respond(embed=embed)

    @slash_command(name="pause", description="暫停目前播放的音樂")
    async def pause(self, ctx: discord.ApplicationContext):
        player = self.voice_mgr.get_player(ctx.guild.id)
        player.pause()
        await ctx.respond("⏸️ 音樂已暫停。")

    @slash_command(name="resume", description="繼續播放已暫停的音樂")
    async def resume(self, ctx: discord.ApplicationContext):
        player = self.voice_mgr.get_player(ctx.guild.id)
        player.resume()
        await ctx.respond("▶️ 已繼續播放音樂。")

    @slash_command(name="skip", description="跳過當前歌曲")
    async def skip(self, ctx: discord.ApplicationContext):
        player = self.voice_mgr.get_player(ctx.guild.id)
        player.skip()
        await ctx.respond("⏭️ 已跳至下一首曲目。")

    @slash_command(name="stop", description="停止播放、清空佇列並離開語音頻道")
    async def stop(self, ctx: discord.ApplicationContext):
        await self.voice_mgr.disconnect_voice(ctx.guild.id)
        await ctx.respond("⏹️ 已停止播放並退出語音頻道。")

    @slash_command(name="queue", description="查看當前的播放佇列")
    async def queue(self, ctx: discord.ApplicationContext):
        player = self.voice_mgr.get_player(ctx.guild.id)
        if not player.current and not player.queue_list:
            return await ctx.respond("📭 目前播放清單是空的！使用 `/play` 來點歌吧！")

        embed = discord.Embed(
            title="📋 目前播放佇列",
            color=0x5865F2
        )
        if player.current:
            embed.add_field(
                name="🎶 正在播放",
                value=f"**[{player.current.title}]({player.current.webpage_url})** ({player.current.duration}) - 點播者: {player.current.requester}",
                inline=False
            )

        if player.queue_list:
            tracks_str = ""
            for idx, s in enumerate(player.queue_list[:10], start=1):
                tracks_str += f"`{idx}.` **[{s.title}]({s.webpage_url})** ({s.duration}) - {s.requester}\n"
            if len(player.queue_list) > 10:
                tracks_str += f"\n*...以及後續還有 {len(player.queue_list) - 10} 首歌曲*"
            embed.add_field(name="⏳ 佇列中的歌曲", value=tracks_str, inline=False)

        await ctx.respond(embed=embed)

    @slash_command(name="nowplaying", description="查看目前正在播放的曲目詳細資訊")
    async def nowplaying(self, ctx: discord.ApplicationContext):
        player = self.voice_mgr.get_player(ctx.guild.id)
        if not player.current:
            return await ctx.respond("目前沒有正在播放的音樂。")
        await player.send_now_playing()
        await ctx.respond("已發送當前曲目卡片！", ephemeral=True)

    @slash_command(name="volume", description="調整播放音量 (0 - 100)")
    async def volume(
        self,
        ctx: discord.ApplicationContext,
        percent: Option(int, "音量百分比 (0 到 100)", required=True, min_value=0, max_value=100)
    ):
        player = self.voice_mgr.get_player(ctx.guild.id)
        vol_float = percent / 100.0
        player.set_volume(vol_float)
        await ctx.respond(f"🔊 音量已調整為 **{percent}%**。")

    @slash_command(name="loop", description="切換循環播放模式")
    async def loop(
        self,
        ctx: discord.ApplicationContext,
        mode: Option(str, "選擇循環模式", choices=["關閉 (off)", "單曲循環 (song)", "清單循環 (queue)"], required=True)
    ):
        player = self.voice_mgr.get_player(ctx.guild.id)
        mode_key = "off"
        if "song" in mode:
            mode_key = "song"
        elif "queue" in mode:
            mode_key = "queue"

        player.loop_mode = mode_key
        names = {"off": "關閉循環", "song": "🔂 單曲循環", "queue": "🔁 清單循環"}
        await ctx.respond(f"已設定為: **{names[mode_key]}**！")

    @slash_command(name="shuffle", description="隨機打亂當前播放清單")
    async def shuffle(self, ctx: discord.ApplicationContext):
        player = self.voice_mgr.get_player(ctx.guild.id)
        if len(player.queue_list) < 2:
            return await ctx.respond("佇列中的歌曲少於 2 首，無法隨機排列。")

        random.shuffle(player.queue_list)
        # 重新建置 asyncio.Queue
        new_q = asyncio.Queue()
        for s in player.queue_list:
            new_q.put_nowait(s)
        player.queue = new_q
        await ctx.respond("🔀 已成功打亂播放佇列順序！")

def setup(bot: discord.Bot):
    bot.add_cog(MusicCog(bot))
