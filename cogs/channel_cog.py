import logging
import discord
from discord.ext import commands
from discord.commands import slash_command, Option
from core.guild_settings import guild_settings

logger = logging.getLogger(__name__)

class ChannelSelectDropdown(discord.ui.Select):
    """
    互動式文字頻道下拉選單
    """
    def __init__(self):
        super().__init__(
            select_type=discord.ComponentType.channel_select,
            placeholder="請選擇一個文字頻道作為專屬音樂頻道...",
            min_values=1,
            max_values=1,
            channel_types=[discord.ChannelType.text]
        )

    async def callback(self, interaction: discord.Interaction):
        # 檢查操作者權限
        if not (
            interaction.user.guild_permissions.manage_channels
            or interaction.user.guild_permissions.administrator
            or interaction.user.id == interaction.guild.owner_id
        ):
            return await interaction.response.send_message(
                "❌ 您需要具備「管理頻道」或「管理員」權限才能修改專屬頻道！",
                ephemeral=True
            )

        selected_channel = self.values[0]
        guild_settings.set_music_channel_id(interaction.guild_id, selected_channel.id)

        # 嘗試在目標專屬頻道發送一則提示通知
        try:
            target_ch = interaction.guild.get_channel(selected_channel.id)
            if isinstance(target_ch, discord.TextChannel):
                from cogs.panel_cog import build_dashboard_embed, DashboardView
                p_embed = build_dashboard_embed(interaction.guild, interaction.client, category="overview")
                p_view = DashboardView(interaction.client)
                msg = await target_ch.send(embed=p_embed, view=p_view)
                try:
                    await msg.pin()
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"無法在目標頻道發送控制面板: {e}")

        embed = discord.Embed(
            title="✅ 專屬音樂頻道設定成功！",
            description=f"已成功將專屬音樂頻道設定為：<#{selected_channel.id}>\n以後所有音樂控制面板與播報訊息都會集中在此頻道發送。",
            color=0x2ECC71
        )
        await interaction.response.edit_message(embed=embed, view=None)

class ChannelSelectView(discord.ui.View):
    """
    包含下拉選單與清除按鈕的頻道配置視圖
    """
    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(ChannelSelectDropdown())

    @discord.ui.button(label="清除綁定 (恢復預設)", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def clear_binding(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not (
            interaction.user.guild_permissions.manage_channels
            or interaction.user.guild_permissions.administrator
            or interaction.user.id == interaction.guild.owner_id
        ):
            return await interaction.response.send_message(
                "❌ 您需要具備「管理頻道」或「管理員」權限才能修改設定！",
                ephemeral=True
            )

        guild_settings.clear_music_channel_id(interaction.guild_id)
        embed = discord.Embed(
            title="🗑️ 已清除專屬音樂頻道設定",
            description="已恢復為預設模式：機器人將在每次發送點歌指令的頻道即時發送播放卡片與通知。",
            color=0x95A5A6
        )
        await interaction.response.edit_message(embed=embed, view=None)

class ChannelCog(commands.Cog):
    """
    專屬頻道管理指令群
    """

    def __init__(self, bot: discord.Bot):
        self.bot = bot

    def _check_perms(self, ctx: discord.ApplicationContext) -> bool:
        return (
            ctx.author.guild_permissions.manage_channels
            or ctx.author.guild_permissions.administrator
            or ctx.author.id == ctx.guild.owner_id
        )

    @slash_command(name="set_channel", description="設定或選擇機器人的專屬音樂文字頻道")
    async def set_channel(
        self,
        ctx: discord.ApplicationContext,
        channel: Option(discord.TextChannel, "直接指定目標文字頻道 (若不填寫則開啟下拉選單選擇)", required=False) = None
    ):
        if not self._check_perms(ctx):
            return await ctx.respond(
                "❌ 您需要具備「管理頻道」或「管理員」權限才能使用此指令！",
                ephemeral=True
            )

        if channel:
            guild_settings.set_music_channel_id(ctx.guild.id, channel.id)

            # 在目標頻道發送歡迎通知
            try:
                from cogs.panel_cog import build_dashboard_embed, DashboardView
                p_embed = build_dashboard_embed(ctx.guild, self.bot, category="overview")
                p_view = DashboardView(self.bot)
                msg = await channel.send(embed=p_embed, view=p_view)
                try:
                    await msg.pin()
                except Exception:
                    pass
            except Exception as e:
                logger.warning(f"無法在目標頻道發送控制面板: {e}")

            embed = discord.Embed(
                title="✅ 專屬音樂頻道設定成功！",
                description=f"已成功將專屬音樂頻道指定為：{channel.mention}\n以後所有音樂控制面板與播報訊息都會集中在此頻道發送。",
                color=0x2ECC71
            )
            await ctx.respond(embed=embed, ephemeral=True)
        else:
            current_ch = guild_settings.get_music_channel(ctx.guild)
            current_desc = f"目前已設定：{current_ch.mention}" if current_ch else "目前狀態：未設定（隨指令頻道發送）"

            embed = discord.Embed(
                title="📌 選擇專屬音樂文字頻道",
                description=(
                    f"{current_desc}\n\n"
                    "請從下方選單選擇一個文字頻道作為機器人的專屬頻道，或點擊紅色按鈕清除綁定："
                ),
                color=0x3498DB
            )
            view = ChannelSelectView()
            await ctx.respond(embed=embed, view=view, ephemeral=True)

    @slash_command(name="channel_status", description="查看目前伺服器設定的專屬音樂頻道")
    async def channel_status(self, ctx: discord.ApplicationContext):
        current_ch = guild_settings.get_music_channel(ctx.guild)
        embed = discord.Embed(
            title="📌 專屬音樂文字頻道狀態",
            color=0x2ECC71 if current_ch else 0x95A5A6
        )
        if current_ch:
            embed.description = f"目前專屬音樂頻道：{current_ch.mention}"
            embed.add_field(
                name="運作模式",
                value="所有音樂正在播放卡片、控制面板與系統通知將固定在此頻道發布。",
                inline=False
            )
            embed.set_footer(text="若要更改或取消，請使用 /set_channel 或 /clear_channel")
        else:
            embed.description = "目前尚未設定專屬音樂頻道。"
            embed.add_field(
                name="運作模式",
                value="機器人會在成員執行點歌指令的當下頻道即時發送音樂卡片。",
                inline=False
            )
            embed.set_footer(text="您可以使用 /set_channel 設定一個專屬文字頻道！")

        await ctx.respond(embed=embed, ephemeral=True)

    @slash_command(name="clear_channel", description="清除專屬音樂文字頻道設定（恢復為隨指令頻道發送）")
    async def clear_channel(self, ctx: discord.ApplicationContext):
        if not self._check_perms(ctx):
            return await ctx.respond(
                "❌ 您需要具備「管理頻道」或「管理員」權限才能使用此指令！",
                ephemeral=True
            )

        success = guild_settings.clear_music_channel_id(ctx.guild.id)
        if success:
            embed = discord.Embed(
                title="🗑️ 已清除專屬音樂頻道設定",
                description="已成功恢復為預設模式：機器人將在每次點歌的頻道即時發布卡片與通知。",
                color=0x2ECC71
            )
        else:
            embed = discord.Embed(
                title="ℹ️ 尚未設定專屬頻道",
                description="本伺服器本來就未綁定專屬音樂頻道，目前已處於預設模式。",
                color=0x95A5A6
            )
        await ctx.respond(embed=embed, ephemeral=True)

def setup(bot: discord.Bot):
    bot.add_cog(ChannelCog(bot))
