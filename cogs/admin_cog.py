import os
import sys
import time
import json
import subprocess
import importlib
import logging
import threading
import asyncio
import discord
from discord.ext import commands
from discord.commands import slash_command, Option

from config.settings import RESTART_INFO_PATH, BASE_DIR

logger = logging.getLogger(__name__)

# 記錄機器人啟動時間
START_TIME = time.time()

COG_MAPPING = {
    "music": "cogs.music_cog",
    "record": "cogs.record_cog",
    "channel": "cogs.channel_cog",
    "auth": "cogs.auth_cog",
    "admin": "cogs.admin_cog",
    "book": "cogs.book_cog",
    "panel": "cogs.panel_cog",
}

async def execute_bot_restart(bot: discord.Bot):
    """
    執行完全重新啟動：優雅釋放語音連線後生成全新 Python 行程並結束舊行程
    """
    logger.info("⚡ 正在執行機器人完全重新啟動 (Full Reboot)...")

    # 1. 優雅斷開所有伺服器的語音連線並保存錄音
    for guild in list(bot.guilds):
        try:
            if hasattr(bot, "voice_manager"):
                await bot.voice_manager.disconnect_voice(guild.id)
        except Exception as ex:
            logger.debug(f"斷開語音伺服器 {guild.id} 警告: {ex}")

    # 2. 啟動全新 Python 行程
    python_exe = sys.executable
    script_path = str(BASE_DIR / "main.py")

    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    subprocess.Popen([python_exe, script_path], cwd=str(BASE_DIR), **kwargs)

    # 3. 關閉 Discord 連線並終止舊行程
    await bot.close()
    await asyncio.sleep(0.5)
    os._exit(0)


class RestartConfirmView(discord.ui.View):
    """
    重新啟動確認按鈕視圖
    """
    def __init__(self, bot: discord.Bot, author_id: int):
        super().__init__(timeout=60)
        self.bot = bot
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ 只有發起重啟的管理員可以進行確認！", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="確認重新啟動", style=discord.ButtonStyle.danger, emoji="🔄")
    async def confirm_restart(self, button: discord.ui.Button, interaction: discord.Interaction):
        for child in self.children:
            child.disabled = True

        embed = discord.Embed(
            title="🔄 機器人正在重新啟動中...",
            description="正在釋放連線資源並啟動全新進程，預計 3~5 秒內完成，請稍候...",
            color=0xE67E22
        )
        await interaction.response.edit_message(embed=embed, view=self)

        # 儲存重啟訊息資訊
        try:
            with open(RESTART_INFO_PATH, "w", encoding="utf-8") as f:
                json.dump({
                    "channel_id": interaction.channel_id,
                    "message_id": interaction.message.id,
                    "timestamp": time.time()
                }, f)
        except Exception as e:
            logger.error(f"儲存重啟資訊失敗: {e}")

        # 執行重啟
        await execute_bot_restart(self.bot)

    @discord.ui.button(label="取消", style=discord.ButtonStyle.secondary, emoji="✖️")
    async def cancel_restart(self, button: discord.ui.Button, interaction: discord.Interaction):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="❎ 已取消重新啟動。", embed=None, view=None)

class AdminCog(commands.Cog):
    """
    [不斷線更新與系統多工管理]
    支援無重啟動態熱更新 (Hot Reload)、Git 自動同步與多工狀態監控
    """

    def __init__(self, bot: discord.Bot):
        self.bot = bot

    @slash_command(name="reload", description="[不斷線更新] 動態熱重載指定或所有模組，保持語音連線與音樂不中斷")
    async def reload_module(
        self,
        ctx: discord.ApplicationContext,
        target: Option(
            str,
            "選擇要熱重載的模組",
            choices=["全部模組 (all)", "控制面板 (panel)", "音樂模組 (music)", "解答之書 (book)", "錄音模組 (record)", "頻道管理 (channel)", "帳號認證 (auth)"],
            required=False,
            default="全部模組 (all)"
        )
    ):
        await ctx.defer(ephemeral=True)

        reloaded = []
        failed = []

        modules_to_reload = []
        if "all" in target:
            modules_to_reload = list(COG_MAPPING.values())
        else:
            for key, path in COG_MAPPING.items():
                if key in target:
                    modules_to_reload.append(path)

        # 優先重載底層核心模組 (若已 import)
        core_mods = ["core.audio_mixer", "core.recorder", "music.ytdl_source", "music.ytm_client", "music.player"]
        for mod_name in core_mods:
            if mod_name in sys.modules:
                try:
                    importlib.reload(sys.modules[mod_name])
                except Exception as ex:
                    logger.debug(f"核心模組 {mod_name} 重載跳過: {ex}")

        for ext in modules_to_reload:
            try:
                self.bot.reload_extension(ext)
                reloaded.append(ext.split(".")[-1])
            except Exception as e:
                logger.error(f"熱重載模組 {ext} 失敗: {e}", exc_info=True)
                failed.append(f"{ext.split('.')[-1]} ({e})")

        embed = discord.Embed(
            title="🔄 不斷線熱更新 (Zero-Downtime Hot-Reload)",
            color=0x2ECC71 if not failed else 0xE67E22
        )
        if reloaded:
            embed.add_field(name="✅ 成功重載模組", value=", ".join(reloaded), inline=False)
        if failed:
            embed.add_field(name="❌ 重載失敗", value="\n".join(failed), inline=False)

        embed.set_footer(text="語音連線、正在播放的音樂與背景錄音均未中斷！")
        await ctx.respond(embed=embed, ephemeral=True)

    @slash_command(name="git_pull", description="[不斷線更新] 從 GitHub 抓取最新程式碼並自動執行無縫熱重載")
    async def git_pull(self, ctx: discord.ApplicationContext):
        await ctx.defer(ephemeral=True)

        try:
            # 非同步執行 git pull
            proc = await asyncio.create_subprocess_exec(
                "git", "pull", "origin", "main",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            out_str = stdout.decode("utf-8", errors="ignore").strip()
            err_str = stderr.decode("utf-8", errors="ignore").strip()

            if proc.returncode != 0:
                return await ctx.respond(f"❌ Git Pull 執行失敗:\n```{err_str or out_str}```", ephemeral=True)

            # 熱重載所有 Cogs
            reloaded = []
            for ext in COG_MAPPING.values():
                try:
                    self.bot.reload_extension(ext)
                    reloaded.append(ext.split(".")[-1])
                except Exception as ex:
                    logger.debug(f"更新後重載 {ext} 警告: {ex}")

            embed = discord.Embed(
                title="🚀 GitHub 程式庫更新與熱重載完成！",
                description=f"```\n{out_str[:800]}\n```",
                color=0x3498DB
            )
            embed.add_field(name="熱重載模組", value=", ".join(reloaded) if reloaded else "無變更", inline=False)
            embed.set_footer(text="零停機時間，連線持續保持中！")
            await ctx.respond(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"執行 Git 更新時發生錯誤: {e}")
            await ctx.respond(f"❌ 更新時發生例外: {e}", ephemeral=True)

    @slash_command(name="sysinfo", description="查看機器人多工運作數據 (Thread 池、記憶體、連線與延遲)")
    async def sysinfo(self, ctx: discord.ApplicationContext):
        uptime_sec = int(time.time() - START_TIME)
        hours, rem = divmod(uptime_sec, 3600)
        minutes, seconds = divmod(rem, 60)
        uptime_str = f"{hours} 小時 {minutes} 分 {seconds} 秒"

        active_threads = threading.active_count()
        ping_ms = round(self.bot.latency * 1000, 1)

        # 統計伺服器與語音狀態
        guilds_count = len(self.bot.guilds)
        voice_clients = len(self.bot.voice_clients)

        embed = discord.Embed(
            title="⚡ 機器人多工運作與效能儀表板",
            color=0x5865F2
        )
        embed.add_field(name="⏱️ 連續運行時間", value=uptime_str, inline=True)
        embed.add_field(name="📶 Gateway 延遲", value=f"{ping_ms} ms", inline=True)
        embed.add_field(name="🧵 多工活動執行緒", value=f"{active_threads} 個執行緒", inline=True)
        embed.add_field(name="🌐 已連線伺服器", value=f"{guilds_count} 個", inline=True)
        embed.add_field(name="🔊 活躍語音連線", value=f"{voice_clients} 個", inline=True)
        embed.add_field(name="🚀 Python 版本", value=sys.version.split()[0], inline=True)

        await ctx.respond(embed=embed)

    def _is_admin(self, ctx: discord.ApplicationContext) -> bool:
        if not ctx.guild:
            return True
        return (
            ctx.author.guild_permissions.administrator
            or ctx.author.guild_permissions.manage_guild
            or ctx.author.id == ctx.guild.owner_id
        )

    @slash_command(name="restart", description="[管理員限定] 完全重新啟動機器人進程 (Reboot Process)")
    async def restart_bot(
        self,
        ctx: discord.ApplicationContext,
        force: Option(bool, "是否跳過確認直接重新啟動", required=False, default=False) = False
    ):
        if not self._is_admin(ctx):
            return await ctx.respond("❌ 只有伺服器管理員或擁有者才能執行重啟！", ephemeral=True)

        if force:
            embed = discord.Embed(
                title="🔄 機器人正在重新啟動中...",
                description="正在釋放連線資源並啟動全新進程，預計 3~5 秒內完成，請稍候...",
                color=0xE67E22
            )
            msg = await ctx.respond(embed=embed)
            actual_msg = await msg.fetch() if hasattr(msg, "fetch") else msg

            try:
                with open(RESTART_INFO_PATH, "w", encoding="utf-8") as f:
                    json.dump({
                        "channel_id": ctx.channel_id,
                        "message_id": actual_msg.id if actual_msg else 0,
                        "timestamp": time.time()
                    }, f)
            except Exception as e:
                logger.error(f"儲存重啟資訊失敗: {e}")

            await execute_bot_restart(self.bot)
        else:
            embed = discord.Embed(
                title="🔄 機器人重新啟動確認",
                description=(
                    "您確定要完全重新啟動機器人進程嗎？\n\n"
                    "⚠️ **注意事項**：\n"
                    "• 重新啟動將暫時中斷目前的語音連線、音樂播放與錄音。\n"
                    "• 全新進程將在約 3~5 秒後自動上線並恢復運作。\n"
                    "• 若只需更新程式或指令，建議優先使用不斷線熱重載 `/reload`。"
                ),
                color=0xE74C3C
            )
            view = RestartConfirmView(self.bot, ctx.author.id)
            await ctx.respond(embed=embed, view=view, ephemeral=True)

def setup(bot: discord.Bot):
    bot.add_cog(AdminCog(bot))
