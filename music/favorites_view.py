import random
import asyncio
import logging
from typing import Optional, List, Dict, Any
import discord
from discord.ui import View, Select, Button

from core.favorites_manager import favorites_manager
from music.ytdl_source import Song

logger = logging.getLogger(__name__)

def build_favorites_embed(user: discord.User | discord.Member, favorites: List[Dict[str, Any]]) -> discord.Embed:
    """
    建立個人收藏歌單展示 Embed
    """
    total = len(favorites)
    embed = discord.Embed(
        title=f"⭐ {user.display_name} 的私房收藏歌單",
        color=0xF1C40F  # 耀眼星空金
    )
    if hasattr(user, "display_avatar") and user.display_avatar:
        embed.set_author(name=f"{user.display_name} 的專屬音樂庫", icon_url=user.display_avatar.url)

    if total == 0:
        embed.description = (
            "📭 **您的收藏歌單目前空空如也！**\n\n"
            "✦ **如何加入歌曲？**\n"
            "1. 在播放音樂時，點擊播放卡片下方的 **「⭐ 收藏本曲」** 按鈕。\n"
            "2. 或在文字頻道輸入 `/favorite_add` 將目前或指定歌曲加入。\n\n"
            "隨時打造您的專屬私房電台！"
        )
        embed.set_footer(text="收藏庫容量無上限 • 跨伺服器永久保存")
        return embed

    # 列出最近或前 15 首收藏歌曲
    lines = []
    display_limit = min(12, total)
    for i, s in enumerate(favorites[:display_limit], start=1):
        artist = s.get("artist", "未知歌手")
        duration = s.get("duration", "0:00")
        url = s.get("webpage_url") or f"https://www.youtube.com/watch?v={s.get('id', '')}"
        lines.append(f"`{i:02d}.` [{s.get('title')}]({url}) - `{artist}` (`{duration}`)")

    content = "\n".join(lines)
    if total > display_limit:
        content += f"\n\n*...以及其餘 {total - display_limit} 首收藏歌曲*"

    embed.description = (
        f"📚 **目前共收藏了 `{total}` 首心愛歌曲**\n\n"
        f"{content}\n\n"
        "💡 **操作指南**：\n"
        "• 下拉選單挑選任一首單曲直接點播\n"
        "• 點擊「▶️ 播放全部」依序點播\n"
        "• 點擊「🔀 隨機播放」混洗打亂點播"
    )

    if favorites and favorites[0].get("thumbnail"):
        embed.set_thumbnail(url=favorites[0]["thumbnail"])

    embed.set_footer(text=f"總曲目數: {total} 首 • 點擊下方按鈕即可快速操控")
    return embed


class FavoriteSongSelect(Select):
    """
    從個人收藏清單中挑選單曲進行播放
    """
    def __init__(self, favorites: List[Dict[str, Any]], bot: discord.Bot):
        options = []
        for i, s in enumerate(favorites[:25], start=1):
            title = s.get("title", "未知歌曲")[:85]
            artist = s.get("artist", "未知歌手")[:60]
            options.append(
                discord.SelectOption(
                    label=f"{i}. {title}",
                    value=s.get("id"),
                    description=f"歌手: {artist} ({s.get('duration', '0:00')})",
                    emoji="🎵"
                )
            )
        super().__init__(
            placeholder="🎵 請選擇想點播的私房收藏歌曲...",
            min_values=1,
            max_values=1,
            options=options,
            row=0
        )
        self.bot = bot
        self.favorites = favorites

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        selected_id = self.values[0]
        target_item = next((item for item in self.favorites if item.get("id") == selected_id), None)
        if not target_item:
            return await interaction.followup.send("⚠️ 找不到該首收藏歌曲。", ephemeral=True)

        # 檢查語音連線
        player = self.bot.voice_manager.get_player(interaction.guild.id)
        if not player.voice_client or not player.voice_client.is_connected():
            if not interaction.user.voice or not interaction.user.voice.channel:
                return await interaction.followup.send("❌ 請先加入一個語音頻道！", ephemeral=True)
            await self.bot.voice_manager.connect_voice(interaction.user.voice.channel, text_channel=interaction.channel)

        player.text_channel = interaction.channel
        song_obj = favorites_manager.to_song(target_item, requester=f"{interaction.user.display_name} (私房收藏)")
        await player.add_song(song_obj)

        embed = discord.Embed(
            title="⭐ 已點播私房收藏歌曲！",
            description=f"[{song_obj.title}]({song_obj.webpage_url})",
            color=0xF1C40F
        )
        embed.add_field(name="歌手", value=song_obj.artist, inline=True)
        embed.add_field(name="時長", value=song_obj.duration, inline=True)
        if song_obj.thumbnail:
            embed.set_thumbnail(url=song_obj.thumbnail)

        await interaction.followup.send(embed=embed, ephemeral=True)


class FavoriteRemoveSelect(Select):
    """
    從個人收藏清單中挑選單曲進行刪除
    """
    def __init__(self, favorites: List[Dict[str, Any]], parent_view):
        options = []
        for i, s in enumerate(favorites[:25], start=1):
            title = s.get("title", "未知歌曲")[:85]
            options.append(
                discord.SelectOption(
                    label=f"移除: {title}",
                    value=s.get("id"),
                    description=f"{s.get('artist', '未知歌手')} ({s.get('duration', '0:00')})",
                    emoji="🗑️"
                )
            )
        super().__init__(
            placeholder="🗑️ 請選擇要從收藏中移除的歌曲...",
            min_values=1,
            max_values=1,
            options=options,
            row=0
        )
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        selected_id = self.values[0]
        ok, title, rem_count = favorites_manager.remove_favorite(interaction.user.id, selected_id)
        if ok:
            embed = build_favorites_embed(interaction.user, favorites_manager.get_favorites(interaction.user.id))
            # 重建 View
            new_view = FavoritesView(interaction.user, self.parent_view.bot)
            await interaction.response.edit_message(embed=embed, view=new_view)
            await interaction.followup.send(f"🗑️ 已成功將 **{title}** 從您的收藏歌單中移除！(尚餘 {rem_count} 首)", ephemeral=True)
        else:
            await interaction.response.send_message("⚠️ 移除失敗或歌曲不存在。", ephemeral=True)


class FavoritesView(View):
    """
    個人私房收藏歌單全功能互動面板
    """
    def __init__(self, user: discord.User | discord.Member, bot: discord.Bot):
        super().__init__(timeout=180)
        self.user = user
        self.bot = bot
        self.favorites = favorites_manager.get_favorites(user.id)

        # Row 0: 若有收藏則顯示選單
        if self.favorites:
            self.add_item(FavoriteSongSelect(self.favorites, bot))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("❌ 這是別人的私房收藏歌單！請使用 `/favorites` 開啟您自己的歌單。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="播放全部", style=discord.ButtonStyle.success, emoji="▶️", row=1)
    async def btn_play_all(self, button: discord.ui.Button, interaction: discord.Interaction):
        favs = favorites_manager.get_favorites(self.user.id)
        if not favs:
            return await interaction.response.send_message("⚠️ 您的收藏歌單目前沒有歌曲！", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        player = self.bot.voice_manager.get_player(interaction.guild.id)
        if not player.voice_client or not player.voice_client.is_connected():
            if not interaction.user.voice or not interaction.user.voice.channel:
                return await interaction.followup.send("❌ 請先加入一個語音頻道！", ephemeral=True)
            await self.bot.voice_manager.connect_voice(interaction.user.voice.channel, text_channel=interaction.channel)

        player.text_channel = interaction.channel
        for item in favs:
            song_obj = favorites_manager.to_song(item, requester=f"{interaction.user.display_name} (私房收藏)")
            await player.add_song(song_obj)

        await interaction.followup.send(
            f"▶️ 已成功將您的 **{len(favs)}** 首收藏歌曲全部依序加入佇列！",
            ephemeral=True
        )

    @discord.ui.button(label="隨機混洗播放", style=discord.ButtonStyle.primary, emoji="🔀", row=1)
    async def btn_shuffle_play(self, button: discord.ui.Button, interaction: discord.Interaction):
        favs = favorites_manager.get_favorites(self.user.id)
        if not favs:
            return await interaction.response.send_message("⚠️ 您的收藏歌單目前沒有歌曲！", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        player = self.bot.voice_manager.get_player(interaction.guild.id)
        if not player.voice_client or not player.voice_client.is_connected():
            if not interaction.user.voice or not interaction.user.voice.channel:
                return await interaction.followup.send("❌ 請先加入一個語音頻道！", ephemeral=True)
            await self.bot.voice_manager.connect_voice(interaction.user.voice.channel, text_channel=interaction.channel)

        player.text_channel = interaction.channel
        shuffled = list(favs)
        random.shuffle(shuffled)
        for item in shuffled:
            song_obj = favorites_manager.to_song(item, requester=f"{interaction.user.display_name} (私房隨機)")
            await player.add_song(song_obj)

        await interaction.followup.send(
            f"🔀 已成功將您的 **{len(favs)}** 首收藏歌曲**隨機混洗**加入佇列！",
            ephemeral=True
        )

    @discord.ui.button(label="移除單曲", style=discord.ButtonStyle.secondary, emoji="🗑️", row=1)
    async def btn_remove_mode(self, button: discord.ui.Button, interaction: discord.Interaction):
        favs = favorites_manager.get_favorites(self.user.id)
        if not favs:
            return await interaction.response.send_message("⚠️ 目前沒有可移除的歌曲。", ephemeral=True)

        # 建立專門移除的 View
        remove_view = View(timeout=60)
        remove_view.add_item(FavoriteRemoveSelect(favs, self))
        await interaction.response.send_message("🗑️ 請在下方選單中選擇要刪除的歌曲：", view=remove_view, ephemeral=True)

    @discord.ui.button(label="清空收藏", style=discord.ButtonStyle.danger, emoji="⚠️", row=1)
    async def btn_clear(self, button: discord.ui.Button, interaction: discord.Interaction):
        favs = favorites_manager.get_favorites(self.user.id)
        if not favs:
            return await interaction.response.send_message("⚠️ 您的收藏歌單已經是空的。", ephemeral=True)

        cleared_count = favorites_manager.clear_favorites(self.user.id)
        new_embed = build_favorites_embed(self.user, [])
        new_view = FavoritesView(self.user, self.bot)
        await interaction.response.edit_message(embed=new_embed, view=new_view)
        await interaction.followup.send(f"⚠️ 已成功清空您的所有收藏歌曲（共清除 {cleared_count} 首）。", ephemeral=True)
