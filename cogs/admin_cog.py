import os
import sys
import time
import importlib
import logging
import threading
import asyncio
import discord
from discord.ext import commands
from discord.commands import slash_command, Option

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
}

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
            choices=["全部模組 (all)", "音樂模組 (music)", "錄音模組 (record)", "解答之書 (book)", "頻道管理 (channel)", "帳號認證 (auth)"],
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

def setup(bot: discord.Bot):
    bot.add_cog(AdminCog(bot))
