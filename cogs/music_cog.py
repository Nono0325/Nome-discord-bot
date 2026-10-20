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

class GenreSelect(discord.ui.Select):
    """
    YouTube Music 曲風與情境音樂下拉選單
    """
    def __init__(self, player: GuildPlayer):
        from music.ytm_client import GENRES_MAP
        options = []
        for key, g in GENRES_MAP.items():
            options.append(
                discord.SelectOption(
                    label=g["name"][:95],
                    value=key,
                    description=g["description"][:95],
                    emoji=g["emoji"]
                )
            )
        super().__init__(placeholder="🎵 請選擇想聆聽的音樂曲風或情境...", min_values=1, max_values=1, options=options)
        self.player = player

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        from music.ytm_client import ytm_client, GENRES_MAP
        import asyncio
        genre_key = self.values[0]
        g_info = GENRES_MAP.get(genre_key, {"name": genre_key, "emoji": "🎵"})

        try:
            songs = await asyncio.to_thread(ytm_client.get_genre_songs, genre_key, 20)
            if not songs:
                return await interaction.followup.send(f"⚠️ 找不到與 {g_info['name']} 相關的曲目。")

            user_name = interaction.user.display_name
            for s in songs:
                song_obj = Song(
                    id=s["id"],
                    title=s["title"],
                    artist=s["artist"],
                    duration=s["duration"],
                    thumbnail=s["thumbnail"],
                    webpage_url=s["url"],
                    requester=f"{user_name} ({g_info['name']})"
                )
                await self.player.add_song(song_obj)

            embed = discord.Embed(
                title=f"{g_info['emoji']} 已載入 {g_info['name']} 精選曲目！",
                description=f"已成功為您隨機混音並加入 **{len(songs)}** 首好歌至播放佇列！",
                color=0x9B59B6
            )
            await interaction.followup.send(embed=embed)
        except Exception as e:
            await interaction.followup.send(f"❌ 載入曲風失敗: {e}")

class GenreSelectView(discord.ui.View):
    def __init__(self, player: GuildPlayer):
        super().__init__(timeout=120)
        self.add_item(GenreSelect(player))


class VoiceChannelSelectDropdown(discord.ui.Select):
    """
    互動式語音頻道下拉選單
    """
    def __init__(self, voice_mgr, text_channel):
        super().__init__(
            select_type=discord.ComponentType.channel_select,
            placeholder="請選擇要讓機器人加入的語音頻道...",
            min_values=1,
            max_values=1,
            channel_types=[discord.ChannelType.voice, discord.ChannelType.stage_voice]
        )
        self.voice_mgr = voice_mgr
        self.text_channel = text_channel

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        selected_channel = self.values[0]
        vc_target = interaction.guild.get_channel(selected_channel.id)
        if not vc_target or not isinstance(vc_target, (discord.VoiceChannel, discord.StageChannel)):
            return await interaction.followup.send("❌ 找不到選取的語音頻道或無效的頻道類型！", ephemeral=True)

        try:
            await self.voice_mgr.connect_voice(vc_target, text_channel=self.text_channel, manual=True)
            embed = discord.Embed(
                title="🔊 已成功加入語音頻道！",
                description=f"機器人已連線至 {vc_target.mention}，現在可以使用 `/play` 開始點歌！",
                color=0x2ECC71
            )
            await interaction.followup.send(embed=embed)
        except Exception as e:
            await interaction.followup.send(f"❌ 連線至語音頻道失敗: {e}", ephemeral=True)

class VoiceChannelSelectView(discord.ui.View):
    def __init__(self, voice_mgr, text_channel):
        super().__init__(timeout=60)
        self.add_item(VoiceChannelSelectDropdown(voice_mgr, text_channel))

class MusicCog(commands.Cog):
    """
    YouTube Music 音樂播放指令群
    """

    def __init__(self, bot: discord.Bot):
        self.bot = bot

    @property
    def voice_mgr(self):
        return self.bot.voice_manager

    async def _ensure_voice(
        self,
        ctx: discord.ApplicationContext,
        target_channel: Optional[discord.VoiceChannel] = None
    ) -> Optional[discord.VoiceClient]:
        """確保使用者在語音頻道，並連線機器人 (優先使用 target_channel)"""
        voice_channel = target_channel or (ctx.author.voice.channel if ctx.author.voice else None)
        if not voice_channel:
            await ctx.respond("❌ 請先加入一個語音頻道，或在指令中指定要加入的語音頻道！", ephemeral=True)
            return None

        vc = await self.voice_mgr.connect_voice(voice_channel, text_channel=ctx.channel, manual=True)
        return vc

    @slash_command(name="join", description="指定讓機器人加入特定的語音頻道，或自動加入您所在的頻道")
    async def join(
        self,
        ctx: discord.ApplicationContext,
        channel: Option(discord.VoiceChannel, "選擇要加入的語音頻道 (若未填寫則自動加入您所在的頻道)", required=False) = None
    ):
        # 情況 1：直接在指令中指定了語音頻道
        if channel:
            await ctx.defer()
            try:
                await self.voice_mgr.connect_voice(channel, text_channel=ctx.channel, manual=True)
                embed = discord.Embed(
                    title="🔊 已成功加入語音頻道！",
                    description=f"機器人已連線至 {channel.mention}，現在可以使用 `/play` 開始點歌！",
                    color=0x2ECC71
                )
                await ctx.respond(embed=embed)
            except Exception as e:
                await ctx.respond(f"❌ 連線至語音頻道失敗: {e}", ephemeral=True)
            return

        # 情況 2：使用者已在某個語音頻道中
        if ctx.author.voice and ctx.author.voice.channel:
            target = ctx.author.voice.channel
            await ctx.defer()
            try:
                await self.voice_mgr.connect_voice(target, text_channel=ctx.channel, manual=True)
                embed = discord.Embed(
                    title="🔊 已成功加入語音頻道！",
                    description=f"機器人已加入您所在的頻道 {target.mention}！",
                    color=0x2ECC71
                )
                await ctx.respond(embed=embed)
            except Exception as e:
                await ctx.respond(f"❌ 連線至語音頻道失敗: {e}", ephemeral=True)
            return

        # 情況 3：未指定頻道且使用者也不在任何語音頻道中 -> 彈出語音頻道下拉選單
        embed = discord.Embed(
            title="🔊 選擇要讓機器人加入的語音頻道",
            description="您目前不在任何語音頻道中，請從下方選單挑選機器人要進入的語音頻道：",
            color=0x3498DB
        )
        view = VoiceChannelSelectView(self.voice_mgr, ctx.channel)
        await ctx.respond(embed=embed, view=view, ephemeral=True)

    @slash_command(name="play", description="在語音頻道播放 YouTube Music 歌曲或網址")
    async def play(
        self,
        ctx: discord.ApplicationContext,
        query: Option(str, "歌曲名稱、關鍵字或 YouTube / YouTube Music 網址", required=True),
        channel: Option(discord.VoiceChannel, "指定要連線播放的語音頻道 (若未填寫則自動加入您所在的頻道)", required=False) = None
    ):
        await ctx.defer()
        vc = await self._ensure_voice(ctx, target_channel=channel)
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

    @slash_command(name="leave", description="讓機器人退出目前的語音頻道")
    async def leave(self, ctx: discord.ApplicationContext):
        guild = ctx.guild
        vc = guild.voice_client if guild else None
        if not vc or not vc.is_connected():
            return await ctx.respond("❌ 機器人目前並未在任何語音頻道中。", ephemeral=True)
        await self.voice_mgr.disconnect_voice(guild.id)
        await ctx.respond("👋 機器人已離開語音頻道。")

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
                tracks_str += f"`{idx}.` **[{s.title[:45]}]({s.webpage_url})** ({s.duration}) - {s.requester}\n"
            if len(player.queue_list) > 10:
                tracks_str += f"\n*...以及後續還有 {len(player.queue_list) - 10} 首歌曲*"
            if len(tracks_str) > 1000:
                tracks_str = tracks_str[:980] + "...\n*(過多歌曲已折疊)*"
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
        count = player.shuffle()
        if count < 2:
            return await ctx.respond("佇列中的歌曲少於 2 首，無法隨機排列。")
        await ctx.respond(f"🔀 已成功打亂 **{count}** 首歌曲順序！")

    @slash_command(name="autoplay", description="切換無盡推薦電台模式（佇列結束時自動推薦並續播相似歌曲）")
    async def autoplay(
        self,
        ctx: discord.ApplicationContext,
        enabled: Option(bool, "是否開啟無盡電台模式 (留空則切換)", required=False, default=None)
    ):
        player = self.voice_mgr.get_player(ctx.guild.id)
        if enabled is None:
            player.autoplay = not player.autoplay
        else:
            player.autoplay = enabled

        status_text = "🟢 **已開啟** 無盡推薦電台模式！\n當播放佇列播放完畢時，機器人將自動推薦相似好歌無縫續播，音樂不中斷！" if player.autoplay else "⚪ **已關閉** 無盡電台模式。"
        embed = discord.Embed(
            title="📻 無盡電台設定變更",
            description=status_text,
            color=0x2ECC71 if player.autoplay else 0x95A5A6
        )
        await ctx.respond(embed=embed)

    @slash_command(name="genre", description="播放指定風格或情境的音樂 (動漫, Lo-Fi, 搖滾, 流行, 爵士, 嘻哈, 電音, 助眠...)")
    async def genre(
        self,
        ctx: discord.ApplicationContext,
        style: Option(
            str,
            "選擇預設曲風或自由輸入關鍵字",
            choices=[
                "🌸 anime - J-Pop / 動漫精選",
                "🎧 lofi - Lo-Fi 放鬆 / 專注讀書",
                "🎤 pop - 全球熱門流行 (Pop Hits)",
                "🎸 rock - 搖滾魂 (Rock & Metal)",
                "☕ jazz - 爵士咖啡廳 (Jazz & Cafe)",
                "⚡ hiphop - 嘻哈饒舌 (Hip-Hop & Rap)",
                "💃 edm - 電音舞曲 (EDM & Dance)",
                "🌙 sleep - 深夜抒情 / 助眠放鬆",
                "🏋️ workout - 熱血健身 (Workout & Gym)",
                "🎮 gaming - 遊戲原聲帶 (Gaming OST)",
                "🏮 mandopop - 經典華語流行 (Mandopop)",
                "🇰🇷 kpop - K-Pop 韓流大勢"
            ],
            required=True
        )
    ):
        await ctx.defer()
        vc = await self._ensure_voice(ctx)
        if not vc:
            return

        import asyncio
        from music.ytm_client import GENRES_MAP
        # 擷取代碼 (例如 "🌸 anime - J-Pop" -> "anime")
        key = style.split(" - ")[0].split()[-1].lower() if " - " in style else style.lower()
        g_info = GENRES_MAP.get(key, {"name": style, "emoji": "🎵"})

        player = self.voice_mgr.get_player(ctx.guild.id)
        player.text_channel = ctx.channel

        try:
            songs = await asyncio.to_thread(ytm_client.get_genre_songs, key, 25)
            if not songs:
                return await ctx.respond(f"⚠️ 找不到與 {g_info['name']} 相關的曲目。")

            user_name = ctx.author.display_name
            for s in songs:
                song_obj = Song(
                    id=s["id"],
                    title=s["title"],
                    artist=s["artist"],
                    duration=s["duration"],
                    thumbnail=s["thumbnail"],
                    webpage_url=s["url"],
                    requester=f"{user_name} ({g_info['name']})"
                )
                await player.add_song(song_obj)

            embed = discord.Embed(
                title=f"{g_info['emoji']} 已載入 {g_info['name']} 曲風！",
                description=f"已成功為您隨機混音並加入 **{len(songs)}** 首精選好歌至播放佇列！\n點擊下方按鈕或輸入 `/queue` 查看清單。",
                color=0x9B59B6
            )
            await ctx.respond(embed=embed)
        except Exception as e:
            await ctx.respond(f"❌ 載入曲風失敗: {e}")

    @slash_command(name="genres", description="開啟 YouTube Music 曲風與情境音樂選擇選單")
    async def genres(self, ctx: discord.ApplicationContext):
        vc = await self._ensure_voice(ctx)
        if not vc:
            return

        player = self.voice_mgr.get_player(ctx.guild.id)
        player.text_channel = ctx.channel

        embed = discord.Embed(
            title="🎧 YouTube Music 曲風與情境音樂專區",
            description="請從下方選單挑選您想聆聽的音樂風格或氛圍，機器人將自動為您載入精選歌單並隨機播放：",
            color=0x9B59B6
        )
        view = GenreSelectView(player)
        await ctx.respond(embed=embed, view=view)

    @slash_command(name="random_play", description="隨機播放當前熱門流行歌曲或隨機精選合輯")
    async def random_play(self, ctx: discord.ApplicationContext):
        await ctx.defer()
        vc = await self._ensure_voice(ctx)
        if not vc:
            return

        import asyncio
        player = self.voice_mgr.get_player(ctx.guild.id)
        player.text_channel = ctx.channel

        try:
            songs = await asyncio.to_thread(ytm_client.get_random_popular_songs, 15)
            if not songs:
                return await ctx.respond("⚠️ 取得熱門推薦歌曲失敗。")

            user_name = ctx.author.display_name
            for s in songs:
                song_obj = Song(
                    id=s["id"],
                    title=s["title"],
                    artist=s["artist"],
                    duration=s["duration"],
                    thumbnail=s["thumbnail"],
                    webpage_url=s["url"],
                    requester=f"{user_name} (隨機探索)"
                )
                await player.add_song(song_obj)

            embed = discord.Embed(
                title="🎲 隨機流行音樂大探索！",
                description=f"已隨機挑選 **{len(songs)}** 首熱門單曲加入播放佇列！",
                color=0x3498DB
            )
            await ctx.respond(embed=embed)
        except Exception as e:
            await ctx.respond(f"❌ 隨機探索失敗: {e}")

def setup(bot: discord.Bot):
    bot.add_cog(MusicCog(bot))

