import asyncio
import time
import logging
from typing import Optional, List
import discord
from discord.ext import commands
from discord.commands import slash_command, Option
from discord.ui import Modal, InputText, View, Button, Select

from music.ytm_client import ytm_client
from music.ytdl_source import Song, YTDLSource
from core.guild_settings import guild_settings

logger = logging.getLogger(__name__)

# ==============================================================================
# 1. 互動式彈窗 (Modals)
# ==============================================================================

class PlaySongModal(Modal):
    """點歌彈出輸入視窗：讓使用者直接輸入歌曲名稱或貼上網址"""

    def __init__(self, bot: discord.Bot):
        super().__init__(title="🎵 點播 YouTube Music 歌曲")
        self.bot = bot

        self.add_item(InputText(
            label="歌曲名稱、歌手或 YouTube 網址",
            placeholder="例如：周杰倫 晴天、Lo-Fi、告五人、或貼上 YouTube 連結",
            required=True
        ))
        self.add_item(InputText(
            label="指定語音頻道名稱 (選填，留空自動加入您所在頻道)",
            placeholder="例如：一般語音、音樂台 (留空即可)",
            required=False
        ))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        query = self.children[0].value.strip()
        channel_name = self.children[1].value.strip() if len(self.children) > 1 and self.children[1].value else None

        # 尋找目標語音頻道
        target_vc = None
        if channel_name:
            target_vc = discord.utils.find(
                lambda c: c.name.lower() == channel_name.lower(),
                interaction.guild.voice_channels
            )

        if not target_vc:
            if interaction.user.voice and interaction.user.voice.channel:
                target_vc = interaction.user.voice.channel

        if not target_vc:
            return await interaction.followup.send(
                "❌ 請先加入一個語音頻道，或者在第二欄填寫正確的語音頻道名稱！",
                ephemeral=True
            )

        try:
            # 連線語音頻道
            vc = await self.bot.voice_manager.connect_voice(target_vc, text_channel=interaction.channel)
            player = self.bot.voice_manager.get_player(interaction.guild.id)
            player.text_channel = interaction.channel

            # 解析歌曲
            songs = await YTDLSource.create_song_list(
                query,
                requester=interaction.user.display_name
            )
            if not songs:
                return await interaction.followup.send(
                    f"⚠️ 找不到關於 **{query}** 的歌曲或串流音訊。",
                    ephemeral=True
                )

            for song in songs:
                await player.add_song(song)

            if len(songs) == 1:
                s = songs[0]
                embed = discord.Embed(
                    title="✅ 已成功加入播放佇列！",
                    description=f"[{s.title}]({s.webpage_url})",
                    color=0x2ECC71
                )
                embed.add_field(name="歌手 / 頻道", value=s.artist, inline=True)
                embed.add_field(name="時長", value=s.duration, inline=True)
                if s.thumbnail:
                    embed.set_thumbnail(url=s.thumbnail)
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                embed = discord.Embed(
                    title=f"✅ 已成功載入播放清單！(共 {len(songs)} 首)",
                    description=f"第一首：**{songs[0].title}**",
                    color=0x2ECC71
                )
                await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"點歌視窗處理失敗: {e}", exc_info=True)
            await interaction.followup.send(f"❌ 點播失敗: {e}", ephemeral=True)


class AskBookModal(Modal):
    """解答之書彈出輸入視窗：讓使用者在心中默念後輸入疑惑"""

    def __init__(self, bot: discord.Bot):
        super().__init__(title="📖 打開神秘《解答之書》")
        self.bot = bot

        self.add_item(InputText(
            label="請在心中默念三遍，並輸入你心中的疑惑",
            placeholder="例如：我該換工作嗎？我們會有未來嗎？我該不該向他告白？",
            required=True
        ))

    async def callback(self, interaction: discord.Interaction):
        from cogs.book_cog import BOOK_ANSWERS, BookAnswersView
        import random

        question = self.children[0].value.strip()
        entry = random.choice(BOOK_ANSWERS)
        page_no = random.randint(1, 384)

        embed = discord.Embed(
            title="📖《 解 答 之 書 》The Book of Answers",
            description=(
                f"✦ **詢問者**：{interaction.user.mention}\n"
                f"✦ **心中的問題**：*{question}*\n\n"
                f"```fix\n"
                f"  『 {entry['zh']} 』\n"
                f"```\n"
                f"🏛️ **English**: *{entry['en']}*\n\n"
                f"📜 **冥想指引**：\n> {entry['desc']}"
            ),
            color=0xD4AF37  # 燙金古籍色
        )
        embed.set_thumbnail(url="https://images.unsplash.com/photo-1544716278-ca5e3f4abd8c?w=300&auto=format&fit=crop&q=80")
        embed.set_footer(text=f"✦ 第 {page_no} 頁 ✦ 誠心所願，心誠則靈 ✦")

        view = BookAnswersView(interaction.user.id, question=question)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


# ==============================================================================
# 2. 輔助視圖 (音量調整按鈕群)
# ==============================================================================

class VolumeControlView(View):
    """音量快捷調整按鈕視圖"""

    def __init__(self, player):
        super().__init__(timeout=60)
        self.player = player

    @discord.ui.button(label="🔇 靜音 (0%)", style=discord.ButtonStyle.secondary, row=0)
    async def vol_0(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.player.set_volume(0.0)
        await interaction.response.send_message("🔇 已將音量調整為 **0% (靜音)**", ephemeral=True)

    @discord.ui.button(label="🔉 25%", style=discord.ButtonStyle.secondary, row=0)
    async def vol_25(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.player.set_volume(0.25)
        await interaction.response.send_message("🔉 已將音量調整為 **25%**", ephemeral=True)

    @discord.ui.button(label="🔊 50% (預設)", style=discord.ButtonStyle.primary, row=0)
    async def vol_50(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.player.set_volume(0.50)
        await interaction.response.send_message("🔊 已將音量調整為 **50%**", ephemeral=True)

    @discord.ui.button(label="🔊 80%", style=discord.ButtonStyle.secondary, row=0)
    async def vol_80(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.player.set_volume(0.80)
        await interaction.response.send_message("🔊 已將音量調整為 **80%**", ephemeral=True)

    @discord.ui.button(label="📢 100%", style=discord.ButtonStyle.success, row=0)
    async def vol_100(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.player.set_volume(1.00)
        await interaction.response.send_message("📢 已將音量調整為 **100% (滿音量)**", ephemeral=True)


def build_quality_embed(guild: discord.Guild, current_bitrate: int) -> discord.Embed:
    """生成音質位元率設定說明 Embed"""
    vc = guild.voice_client
    ch_name = vc.channel.name if (vc and vc.channel) else "未加入語音"
    ch_kbps = int(vc.channel.bitrate / 1000) if (vc and getattr(vc.channel, "bitrate", None)) else 128

    desc = (
        f"🎧 **目前音訊輸出位元率**：`{current_bitrate} kbps`\n"
        f"📡 **語音頻道**：`{ch_name}` (頻道上限: `{ch_kbps} kbps`)\n\n"
        "✦ **音質切換指南（遇到卡頓斷斷續續時建議降低）**：\n"
        "• 🌟 **320 kbps (極致發燒)**：頂級無損高頻細節，需要優質高速網路。\n"
        "• 🎵 **128 kbps (高品質)**：CD 級清晰度，音質與流暢的官方推薦平衡。\n"
        "• ⚖️ **96 kbps (標準平衡)**：Discord 預設，穩定性高，絕不卡頓。\n"
        "• 🛡️ **64 kbps (弱網防卡)**：啟用強效 20% 封包遺失容錯補償，網路不穩救星！\n"
        "• ⚡ **48 kbps (極速省流)**：超低流量佔用，極限弱網環境專用。"
    )
    embed = discord.Embed(
        title="🎧 音樂播放音質切換 (Bitrate Control)",
        description=desc,
        color=0x3498DB
    )
    embed.set_footer(text="點選下方按鈕即可即時動態生效，無需重啟歌曲！")
    return embed


class QualityControlView(View):
    """音質位元率快捷切換按鈕視圖"""

    def __init__(self, player):
        super().__init__(timeout=60)
        self.player = player

    @discord.ui.button(label="🌟 320k 極致", style=discord.ButtonStyle.secondary, row=0)
    async def q_320(self, button: discord.ui.Button, interaction: discord.Interaction):
        real_bitrate = self.player.set_bitrate(320)
        await interaction.response.send_message(
            f"🌟 已將音質切換為 **{real_bitrate} kbps**！(極致發燒高保真)",
            ephemeral=True
        )

    @discord.ui.button(label="🎵 128k 高品質", style=discord.ButtonStyle.secondary, row=0)
    async def q_128(self, button: discord.ui.Button, interaction: discord.Interaction):
        real_bitrate = self.player.set_bitrate(128)
        await interaction.response.send_message(
            f"🎵 已將音質切換為 **{real_bitrate} kbps**！(官方平衡推薦)",
            ephemeral=True
        )

    @discord.ui.button(label="⚖️ 96k 標準 (推薦)", style=discord.ButtonStyle.primary, row=0)
    async def q_96(self, button: discord.ui.Button, interaction: discord.Interaction):
        real_bitrate = self.player.set_bitrate(96)
        await interaction.response.send_message(
            f"⚖️ 已將音質切換為 **{real_bitrate} kbps**！(最穩定抗抖動，絕不卡頓)",
            ephemeral=True
        )

    @discord.ui.button(label="🛡️ 64k 弱網防卡", style=discord.ButtonStyle.success, row=0)
    async def q_64(self, button: discord.ui.Button, interaction: discord.Interaction):
        real_bitrate = self.player.set_bitrate(64)
        await interaction.response.send_message(
            f"🛡️ 已將音質切換為 **{real_bitrate} kbps**！(已啟用 20% 封包遺失抗卡頓補償)",
            ephemeral=True
        )

    @discord.ui.button(label="⚡ 48k 極速", style=discord.ButtonStyle.secondary, row=0)
    async def q_48(self, button: discord.ui.Button, interaction: discord.Interaction):
        real_bitrate = self.player.set_bitrate(48)
        await interaction.response.send_message(
            f"⚡ 已將音質切換為 **{real_bitrate} kbps**！(極致抗延遲省流)",
            ephemeral=True
        )


# ==============================================================================
# 3. 控制面板主視圖 (DashboardView)
# ==============================================================================

def build_dashboard_embed(guild: discord.Guild, bot: discord.Bot, category: str = "overview") -> discord.Embed:
    """生成控制面板的美觀 Embed"""
    voice_mgr = bot.voice_manager
    player = voice_mgr.get_player(guild.id)
    sink = voice_mgr.get_sink(guild.id)
    vc = guild.voice_client

    # 語音連線狀態
    if vc and vc.is_connected() and vc.channel:
        voice_status = f"🟢 已連線至 **{vc.channel.name}**"
    else:
        voice_status = "⚪ 未連線 (點擊下方按鈕將自動加入)"

    # 音樂播放狀態
    if player.current:
        music_status = f"🎶 **正在播放**: [{player.current.title}]({player.current.webpage_url}) (`{player.current.duration}`)"
    else:
        music_status = "💤 目前無音樂正在播放"

    # 錄音緩衝狀態
    buf_status = "🟢 正常監聽中（隨時可點擊「🎬 前1分對話」剪輯）" if (vc and vc.is_recording()) else "⚪ 語音未就緒"
    rec_status = "🔴 全程錄音中" if (sink and sink.is_session_recording) else "⚪ 未開啟"

    if category == "overview":
        embed = discord.Embed(
            title="🎛️ Nome 智能控制中心 (Interactive Control Center)",
            description=(
                "歡迎使用全功能互動面板！**所有功能均可透過下方按鈕與選單操作，完全不需要記憶或輸入指令！**\n\n"
                f"📡 **語音狀態**: {voice_status}\n"
                f"{music_status}\n"
                f"🎙️ **對話緩衝**: {buf_status}\n"
                f"💾 **自動錄音**: {rec_status}\n"
                f"🔁 **無盡電台**: {'🟢 開啟' if player.autoplay else '⚪ 關閉'} | 🔊 **音量**: {int(player.volume * 100)}% | 🎧 **音質**: {getattr(player, 'current_bitrate', 96)}k"
            ),
            color=0x3498DB
        )
        embed.add_field(
            name="💡 快捷操作指南",
            value=(
                "• **🔍 點歌**: 點擊彈出小視窗輸入歌名/網址，自動連線播放\n"
                "• **⭐ 私房收藏**: 瀏覽個人專屬音樂庫、一鍵全部或隨機點播\n"
                "• **🎬 前1分對話**: 一鍵混音導出過去 60 秒立體聲通話 MP3\n"
                "• **🎙️ 動態歌詞**: 開啟即時卡拉OK滾動歌詞面板\n"
                "• **📖 問解答之書**: 默念心中疑惑，揭示命運解答"
            ),
            inline=False
        )
        embed.set_footer(text="提示：可透過上方「功能分頁」切換專屬功能選單 • 24/7 全天候在線")

    elif category == "music":
        embed = discord.Embed(
            title="🎵 音樂點播與電台專區",
            description=(
                f"{music_status}\n"
                f"📋 **佇列尚餘**: {len(player.queue_list)} 首歌曲\n"
                f"🔊 **目前音量**: {int(player.volume * 100)}% | 🔁 **循環模式**: {player.loop_mode}\n\n"
                "點擊下方按鈕可進行點歌、隨機探索、曲風挑選、音量調整或即時查看歌詞。"
            ),
            color=0x9B59B6
        )

    elif category == "record":
        embed = discord.Embed(
            title="🎙️ 語音通話錄音與對話回放專區",
            description=(
                f"📡 **錄音器狀態**: {buf_status}\n"
                f"💾 **全程自動錄音存檔**: {rec_status}\n\n"
                "• **🎬 前 1 分鐘對話**：隨時擷取過去 60 秒內所有成員的對話，精準混音為立體聲 MP3。\n"
                "• **全程自動錄音**：通話結束後自動混音並上傳錄音檔案至頻道。"
            ),
            color=0x2ECC71
        )

    elif category == "book":
        embed = discord.Embed(
            title="📖 神秘《解答之書》(The Book of Answers)",
            description=(
                "人生總是充滿了抉擇與迷惘，而答案早已隱藏在宇宙之中。\n\n"
                "✦ **如何尋求指引？**\n"
                "1. 在心中清晰默念你的問題三遍。\n"
                "2. 點擊下方 **「📖 問解答之書」** 彈出輸入視窗。\n"
                "3. 按下送出，解答之書將為你翻開命運的扉頁！"
            ),
            color=0xD4AF37
        )

    elif category == "favorites":
        embed = discord.Embed(
            title="⭐ 個人私房收藏歌單專區",
            description=(
                "每位成員都擁有獨立的私房音樂庫，跨伺服器永久儲存！\n\n"
                "✦ **功能亮點**：\n"
                "• **一鍵收藏**：播歌時隨時點擊「⭐ 收藏本曲」存入私人歌單。\n"
                "• **隨機混洗播放**：點擊「🔀 隨機播收藏」立即享受專屬私房電台。\n"
                "• **單曲管理**：點擊「⭐ 私房收藏」可透過下拉選單點播或移除指定歌曲。\n\n"
                "👇 請點擊下方 **「⭐ 私房收藏」** 或 **「🔀 隨機播收藏」** 即可開啟專屬面板！"
            ),
            color=0xF1C40F
        )

    elif category == "settings":
        ch = guild_settings.get_music_channel(guild)
        ch_str = ch.mention if ch else "未綁定 (隨使用者所在文字頻道即時發送)"
        embed = discord.Embed(
            title="⚙️ 伺服器與頻道管理專區",
            description=(
                f"📌 **專屬音樂文字頻道**: {ch_str}\n"
                f"🔑 **YouTube Music 認證模式**: `{ytm_client.auth_mode}`\n"
                f"⚡ **機器人延遲 (Ping)**: `{int(bot.latency * 1000)} ms`\n\n"
                "點擊下方按鈕可快速綁定當前頻道為專屬音樂房或查看系統診斷資訊。"
            ),
            color=0x7F8C8D
        )

    return embed


class CategorySelect(Select):
    """功能分頁下拉選單"""

    def __init__(self):
        options = [
            discord.SelectOption(
                label="🎛️ 綜合控制中心 (總覽首頁)",
                value="overview",
                description="查看目前語音連線、音樂播放與全系統概況",
                default=True
            ),
            discord.SelectOption(
                label="⭐ 個人私房收藏歌單",
                value="favorites",
                description="檢視個人收藏、一鍵全部播放或隨機混洗私房歌曲",
                emoji="⭐"
            ),
            discord.SelectOption(
                label="🎵 音樂與電台專區",
                value="music",
                description="點歌、隨機探索、曲風挑選與播放清單",
                emoji="🎵"
            ),
            discord.SelectOption(
                label="🎙️ 語音通話錄音與剪輯",
                value="record",
                description="前一分鐘對話回放與全程錄音存檔",
                emoji="🎙️"
            ),
            discord.SelectOption(
                label="📖 神秘《解答之書》",
                value="book",
                description="為心中的困惑揭開命運啟示與每日指引",
                emoji="📖"
            ),
            discord.SelectOption(
                label="⚙️ 頻道與系統管理",
                value="settings",
                description="專屬音樂頻道設定與系統診斷",
                emoji="⚙️"
            )
        ]
        super().__init__(
            placeholder="📌 請選擇功能分類專區...",
            min_values=1,
            max_values=1,
            options=options,
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        selected = self.values[0]
        for opt in self.options:
            opt.default = (opt.value == selected)

        embed = build_dashboard_embed(interaction.guild, interaction.client, category=selected)
        await interaction.response.edit_message(embed=embed, view=self.view)


class DashboardView(View):
    """
    全功能互動控制面板視圖：
    整合所有核心功能，提供零打字的全圖形化介面！
    """

    def __init__(self, bot: discord.Bot):
        super().__init__(timeout=None)  # 永久常駐 View
        self.bot = bot

        # Row 0: 分類導航選單
        self.add_item(CategorySelect())

    # ----------------------------------------------------
    # Row 1: 常用高頻核心操作按鈕
    # ----------------------------------------------------
    @discord.ui.button(label="點歌 (輸入歌名)", style=discord.ButtonStyle.primary, emoji="🔍", row=1)
    async def btn_play(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.send_modal(PlaySongModal(self.bot))

    @discord.ui.button(label="前 1 分鐘對話", style=discord.ButtonStyle.success, emoji="🎬", row=1)
    async def btn_clip(self, button: discord.ui.Button, interaction: discord.Interaction):
        rec_cog = interaction.client.get_cog("RecordCog")
        if rec_cog:
            await rec_cog.handle_clip(interaction, seconds=60)
        else:
            await interaction.response.send_message("❌ 錄音模組未啟用！", ephemeral=True)

    @discord.ui.button(label="同步歌詞", style=discord.ButtonStyle.success, emoji="🎙️", row=1)
    async def btn_lyrics(self, button: discord.ui.Button, interaction: discord.Interaction):
        player = self.bot.voice_manager.get_player(interaction.guild.id)
        if not player or not player.current:
            return await interaction.response.send_message("❌ 目前沒有正在播放的歌曲！請先點歌。", ephemeral=True)

        await interaction.response.defer(ephemeral=False)
        from music.lyrics_service import lyrics_service
        from music.lyrics_view import LiveLyricsView, FullLyricsView, build_synced_embed

        song = player.current
        lyrics_data = await lyrics_service.get_lyrics(
            title=song.title,
            artist=song.artist,
            video_id=song.id,
            thumbnail=song.thumbnail
        )

        if not lyrics_data:
            return await interaction.followup.send(f"⚠️ 找不到歌曲 **{song.title}** 的歌詞資料。", ephemeral=True)

        if lyrics_data.synced and lyrics_data.lines:
            view = LiveLyricsView(player=player, song=song, lyrics_data=lyrics_data, requester_id=interaction.user.id)
            embed, _ = build_synced_embed(player, song, lyrics_data)
            msg = await interaction.followup.send(embed=embed, view=view)
            actual_msg = await msg.fetch() if hasattr(msg, "fetch") else msg
            view.start_sync(actual_msg)
        else:
            view = FullLyricsView(lyrics_data=lyrics_data, player=player, song=song, requester_id=interaction.user.id)
            msg = await interaction.followup.send(embed=view.get_embed(), view=view)
            actual_msg = await msg.fetch() if hasattr(msg, "fetch") else msg
            view.message = actual_msg

    @discord.ui.button(label="問解答之書", style=discord.ButtonStyle.secondary, emoji="📖", row=1)
    async def btn_book(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.send_modal(AskBookModal(self.bot))

    @discord.ui.button(label="私房收藏", style=discord.ButtonStyle.primary, emoji="⭐", row=1)
    async def btn_favorites(self, button: discord.ui.Button, interaction: discord.Interaction):
        from core.favorites_manager import favorites_manager
        from music.favorites_view import FavoritesView, build_favorites_embed
        favs = favorites_manager.get_favorites(interaction.user.id)
        embed = build_favorites_embed(interaction.user, favs)
        view = FavoritesView(interaction.user, self.bot)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    # ----------------------------------------------------
    # Row 2: 音樂即時控制器按鈕
    # ----------------------------------------------------
    @discord.ui.button(label="暫停 / 繼續", style=discord.ButtonStyle.primary, emoji="⏯️", row=2)
    async def btn_toggle_play(self, button: discord.ui.Button, interaction: discord.Interaction):
        player = self.bot.voice_manager.get_player(interaction.guild.id)
        vc = player.voice_client
        if not vc:
            return await interaction.response.send_message("❌ 機器人目前不在語音頻道中！", ephemeral=True)

        if vc.is_paused():
            player.resume()
            await interaction.response.send_message("▶️ 已繼續播放！", ephemeral=True)
        elif vc.is_playing():
            player.pause()
            await interaction.response.send_message("⏸️ 已暫停播放！", ephemeral=True)
        else:
            await interaction.response.send_message("目前無音訊正在播放。", ephemeral=True)

    @discord.ui.button(label="下一首", style=discord.ButtonStyle.secondary, emoji="⏭️", row=2)
    async def btn_skip(self, button: discord.ui.Button, interaction: discord.Interaction):
        player = self.bot.voice_manager.get_player(interaction.guild.id)
        vc = player.voice_client
        if not vc or not (vc.is_playing() or vc.is_paused()):
            return await interaction.response.send_message("目前無音訊正在播放。", ephemeral=True)
        player.skip()
        await interaction.response.send_message("⏭️ 已跳至下一首！", ephemeral=True)

    @discord.ui.button(label="隨機混洗", style=discord.ButtonStyle.secondary, emoji="🔀", row=2)
    async def btn_shuffle(self, button: discord.ui.Button, interaction: discord.Interaction):
        player = self.bot.voice_manager.get_player(interaction.guild.id)
        count = player.shuffle()
        if count < 2:
            return await interaction.response.send_message("⚠️ 佇列歌曲少於 2 首，無法隨機打亂。", ephemeral=True)
        await interaction.response.send_message(f"🔀 已成功隨機打亂 **{count}** 首歌曲順序！", ephemeral=True)

    @discord.ui.button(label="播放佇列", style=discord.ButtonStyle.secondary, emoji="📜", row=2)
    async def btn_queue(self, button: discord.ui.Button, interaction: discord.Interaction):
        player = self.bot.voice_manager.get_player(interaction.guild.id)
        if not player.current and not player.queue_list:
            return await interaction.response.send_message("目前播放佇列是空的！請點擊「🔍 點歌」加入歌曲。", ephemeral=True)

        embed = discord.Embed(title="📜 目前播放佇列清單", color=0x3498DB)
        if player.current:
            embed.add_field(
                name="🎶 正在播放",
                value=f"[{player.current.title}]({player.current.webpage_url}) (`{player.current.duration}`)",
                inline=False
            )
        q_items = []
        for i, s in enumerate(player.queue_list[:10], start=1):
            q_items.append(f"`{i}.` [{s.title}]({s.webpage_url}) (`{s.duration}`)")
        if q_items:
            rem = len(player.queue_list) - 10
            extra = f"\n*...以及其餘 {rem} 首歌曲*" if rem > 0 else ""
            embed.add_field(name="📋 即將播放 (前 10 首)", value="\n".join(q_items) + extra, inline=False)

        embed.set_footer(text=f"佇列總曲目: {len(player.queue_list)} 首")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="停止退出", style=discord.ButtonStyle.danger, emoji="⏹️", row=2)
    async def btn_stop(self, button: discord.ui.Button, interaction: discord.Interaction):
        player = self.bot.voice_manager.get_player(interaction.guild.id)
        player.stop()
        vc = player.voice_client
        if vc and vc.is_connected():
            await vc.disconnect()
        await interaction.response.send_message("⏹️ 已停止播放並退出語音頻道。", ephemeral=True)

    # ----------------------------------------------------
    # Row 3: 擴充探索按鈕
    # ----------------------------------------------------
    @discord.ui.button(label="曲風選單", style=discord.ButtonStyle.secondary, emoji="📻", row=3)
    async def btn_genres(self, button: discord.ui.Button, interaction: discord.Interaction):
        from cogs.music_cog import GenreSelectView
        player = self.bot.voice_manager.get_player(interaction.guild.id)
        view = GenreSelectView(player)
        embed = discord.Embed(
            title="🎧 YouTube Music 曲風與情境音樂專區",
            description="請從下方選單挑選想聆聽的曲風（動漫、Lo-Fi、流行、搖滾、爵士、電音等）：",
            color=0x9B59B6
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="流行大探索", style=discord.ButtonStyle.secondary, emoji="🎲", row=3)
    async def btn_popular(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        player = self.bot.voice_manager.get_player(interaction.guild.id)

        # 確保加入語音頻道
        if not player.voice_client or not player.voice_client.is_connected():
            if not interaction.user.voice or not interaction.user.voice.channel:
                return await interaction.followup.send("❌ 請先加入語音頻道！", ephemeral=True)
            await self.bot.voice_manager.connect_voice(interaction.user.voice.channel, text_channel=interaction.channel)

        songs = await asyncio.to_thread(ytm_client.get_random_popular_songs, 15)
        if not songs:
            return await interaction.followup.send("⚠️ 取得熱門探索歌曲失敗。", ephemeral=True)

        for s in songs:
            song_obj = Song(
                id=s["id"], title=s["title"], artist=s["artist"], duration=s["duration"],
                thumbnail=s["thumbnail"], webpage_url=s["url"], requester=f"{interaction.user.display_name} (隨機探索)"
            )
            await player.add_song(song_obj)

        await interaction.followup.send(f"🎲 已成功隨機加入 **{len(songs)}** 首熱門流行歌曲至佇列！", ephemeral=True)

    @discord.ui.button(label="無盡電台", style=discord.ButtonStyle.secondary, emoji="🔁", row=3)
    async def btn_autoplay(self, button: discord.ui.Button, interaction: discord.Interaction):
        player = self.bot.voice_manager.get_player(interaction.guild.id)
        player.autoplay = not player.autoplay
        status_str = "🟢 已開啟無盡電台！佇列播完自動推薦相似好歌。" if player.autoplay else "⚪ 已關閉無盡電台。"
        await interaction.response.send_message(status_str, ephemeral=True)

    @discord.ui.button(label="音量調整", style=discord.ButtonStyle.secondary, emoji="🔊", row=3)
    async def btn_vol(self, button: discord.ui.Button, interaction: discord.Interaction):
        player = self.bot.voice_manager.get_player(interaction.guild.id)
        view = VolumeControlView(player)
        await interaction.response.send_message("🔊 請點選您欲設定的音量大小：", view=view, ephemeral=True)

    @discord.ui.button(label="音質切換", style=discord.ButtonStyle.secondary, emoji="🎧", row=3)
    async def btn_quality(self, button: discord.ui.Button, interaction: discord.Interaction):
        player = self.bot.voice_manager.get_player(interaction.guild.id)
        view = QualityControlView(player)
        current_kbps = getattr(player, "current_bitrate", None) or guild_settings.get_audio_bitrate(interaction.guild.id)
        embed = build_quality_embed(interaction.guild, current_kbps)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    # ----------------------------------------------------
    # Row 4: 個人私房收藏與進階工具按鈕
    # ----------------------------------------------------
    @discord.ui.button(label="隨機播收藏", style=discord.ButtonStyle.success, emoji="🔀", row=4)
    async def btn_fav_shuffle(self, button: discord.ui.Button, interaction: discord.Interaction):
        from core.favorites_manager import favorites_manager
        favs = favorites_manager.get_favorites(interaction.user.id)
        if not favs:
            return await interaction.response.send_message(
                "⚠️ 您的收藏歌單目前是空的！請在播放音樂時點擊「⭐ 收藏本曲」加入最愛歌曲。",
                ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)
        player = self.bot.voice_manager.get_player(interaction.guild.id)
        if not player.voice_client or not player.voice_client.is_connected():
            if not interaction.user.voice or not interaction.user.voice.channel:
                return await interaction.followup.send("❌ 請先加入一個語音頻道！", ephemeral=True)
            await self.bot.voice_manager.connect_voice(interaction.user.voice.channel, text_channel=interaction.channel)

        player.text_channel = interaction.channel
        shuffled = list(favs)
        import random
        random.shuffle(shuffled)
        for item in shuffled:
            song_obj = favorites_manager.to_song(item, requester=f"{interaction.user.display_name} (私房隨機)")
            await player.add_song(song_obj)

        await interaction.followup.send(
            f"🔀 已成功將您的 **{len(favs)}** 首收藏歌曲**隨機混洗**加入佇列！",
            ephemeral=True
        )

    @discord.ui.button(label="每日能量", style=discord.ButtonStyle.secondary, emoji="✨", row=4)
    async def btn_daily_book(self, button: discord.ui.Button, interaction: discord.Interaction):
        from cogs.book_cog import BOOK_ANSWERS
        import time, hashlib, random
        today_str = time.strftime("%Y-%m-%d")
        seed_bytes = f"{today_str}_{interaction.user.id}".encode("utf-8")
        seed_val = int(hashlib.md5(seed_bytes).hexdigest()[:8], 16)
        rng = random.Random(seed_val)
        entry = rng.choice(BOOK_ANSWERS)
        page_no = rng.randint(1, 384)

        embed = discord.Embed(
            title=f"🌅 今日專屬啟示・{today_str}",
            description=(
                f"✦ **守護對象**：{interaction.user.mention}\n\n"
                f"```yaml\n「{entry['zh']}」\n  {entry['en']}\n```\n"
                f"💫 **今日能量指針**：\n> {entry['desc']}\n\n"
                "🕯️ *靜下心來，將這句話融入今日的生活步調中。*"
            ),
            color=0xE67E22
        )
        embed.set_footer(text=f"✦ 今日專屬書頁 第 {page_no} 頁 ✦ 每日凌晨更新 ✦")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="錄音開關", style=discord.ButtonStyle.secondary, emoji="🎙️", row=4)
    async def btn_toggle_record(self, button: discord.ui.Button, interaction: discord.Interaction):
        vm = self.bot.voice_manager
        vm.auto_record = not vm.auto_record
        status = "🔴 全程自動錄音已開啟 (進出語音自動存檔)" if vm.auto_record else "⚪ 全程自動錄音已關閉"
        await interaction.response.send_message(status, ephemeral=True)

    @discord.ui.button(label="系統狀態", style=discord.ButtonStyle.secondary, emoji="⚙️", row=4)
    async def btn_sysinfo(self, button: discord.ui.Button, interaction: discord.Interaction):
        import time, threading
        from cogs.admin_cog import START_TIME
        uptime_sec = int(time.time() - START_TIME)
        hrs, rem = divmod(uptime_sec, 3600)
        mins, secs = divmod(rem, 60)
        uptime_str = f"{hrs}小時 {mins}分 {secs}秒"

        embed = discord.Embed(
            title="⚙️ 機器人系統運作狀態",
            color=0x3498DB
        )
        embed.add_field(name="📶 延遲 (Ping)", value=f"`{int(self.bot.latency * 1000)} ms`", inline=True)
        embed.add_field(name="⏱️ 運行時間", value=f"`{uptime_str}`", inline=True)
        embed.add_field(name="🧵 運作執行緒", value=f"`{threading.active_count()} 個背景線程`", inline=True)
        embed.add_field(name="🌐 連線伺服器數", value=f"`{len(self.bot.guilds)}`", inline=True)
        embed.add_field(name="🎙️ 語音連線中", value=f"`{len(self.bot.voice_clients)}` 個頻道", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="重啟機器人", style=discord.ButtonStyle.danger, emoji="🔄", row=4)
    async def btn_restart(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not (
            interaction.user.guild_permissions.administrator
            or interaction.user.guild_permissions.manage_guild
            or (interaction.guild and interaction.user.id == interaction.guild.owner_id)
        ):
            return await interaction.response.send_message("❌ 只有伺服器管理員或擁有者才能執行重啟！", ephemeral=True)

        from cogs.admin_cog import RestartConfirmView
        embed = discord.Embed(
            title="🔄 機器人重新啟動確認",
            description=(
                "您確定要完全重新啟動機器人進程嗎？\n\n"
                "⚠️ **注意事項**：\n"
                "• 重新啟動將暫時中斷語音連線、音樂播放與錄音。\n"
                "• 全新進程將在約 3~5 秒後自動啟動上線並發送就緒通知。\n"
                "• 若只需更新設定，亦可點選分類選單中的熱重載模組。"
            ),
            color=0xE74C3C
        )
        view = RestartConfirmView(self.bot, interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


# ==============================================================================
# 4. Cog 指令
# ==============================================================================
class PanelCog(commands.Cog):
    """
    全功能圖形化控制面板 (Dashboard) Cog
    """

    def __init__(self, bot: discord.Bot):
        self.bot = bot

    @slash_command(name="panel", description="🎛️ 開啟全功能圖形化控制中心面板 (零打字！全按鈕與彈窗操作)")
    async def panel(
        self,
        ctx: discord.ApplicationContext,
        pin: Option(bool, "是否常駐於此頻道 (公開顯示)", required=False, default=True)
    ):
        embed = build_dashboard_embed(ctx.guild, self.bot, category="overview")
        view = DashboardView(self.bot)
        await ctx.respond(embed=embed, view=view, ephemeral=not pin)

    @slash_command(name="setup_panel", description="📌 在專屬音樂頻道中建立並置頂全功能圖形化控制面板")
    async def setup_panel(self, ctx: discord.ApplicationContext):
        if not (
            ctx.author.guild_permissions.manage_channels
            or ctx.author.guild_permissions.manage_messages
            or ctx.author.guild_permissions.administrator
            or (ctx.guild and ctx.author.id == ctx.guild.owner_id)
        ):
            return await ctx.respond("❌ 只有具備「管理頻道」或「管理訊息」之管理員才能部署置頂控制面板！", ephemeral=True)

        ch = guild_settings.get_music_channel(ctx.guild)
        target_ch = ch or ctx.channel

        embed = build_dashboard_embed(ctx.guild, self.bot, category="overview")
        view = DashboardView(self.bot)
        msg = await target_ch.send(embed=embed, view=view)
        try:
            await msg.pin()
        except Exception:
            pass

        if target_ch.id != ctx.channel.id:
            await ctx.respond(f"✅ 已在專屬音樂頻道 {target_ch.mention} 成功部署並置頂圖形控制面板！", ephemeral=True)
        else:
            await ctx.respond("✅ 已成功部署全功能圖形化控制面板！", ephemeral=True)

def setup(bot: discord.Bot):
    bot.add_cog(PanelCog(bot))
