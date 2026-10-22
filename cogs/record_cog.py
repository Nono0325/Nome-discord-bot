import os
import io
import time
import logging
from typing import Optional
import discord
from discord.ext import commands
from discord.commands import slash_command, Option

logger = logging.getLogger(__name__)

class RecordCog(commands.Cog):
    """
    語音對話錄音與即時前一分鐘回放 (Instant Replay Clip) 指令群
    """

    def __init__(self, bot: discord.Bot):
        self.bot = bot

    @property
    def voice_mgr(self):
        return self.bot.voice_manager

    async def handle_clip(self, interaction_or_ctx, seconds: int = 60):
        """
        核心剪輯邏輯：提取前指定秒數（預設 60 秒）的多人混音對話
        """
        is_interaction = isinstance(interaction_or_ctx, discord.Interaction)
        guild = interaction_or_ctx.guild

        if not guild:
            msg = "❌ 請在伺服器中使用此指令！"
            if is_interaction:
                return await interaction_or_ctx.response.send_message(msg, ephemeral=True)
            return await interaction_or_ctx.respond(msg, ephemeral=True)

        sink = self.voice_mgr.get_sink(guild.id)
        if not sink:
            msg = "❌ 機器人目前未在語音頻道錄製音訊或未加入語音頻道！請先讓機器人加入語音。"
            if is_interaction:
                return await interaction_or_ctx.response.send_message(msg, ephemeral=True)
            return await interaction_or_ctx.respond(msg, ephemeral=True)

        if is_interaction:
            await interaction_or_ctx.response.defer()
        else:
            await interaction_or_ctx.defer()

        try:
            seconds = max(5, min(180, seconds))
            mp3_buf, active_uids = await sink.get_replay_audio_async(duration_seconds=float(seconds))

            # 檢查檔案大小是否有效 (排除完全無語音資料的情況)
            mp3_size = len(mp3_buf.getvalue())
            if not active_uids or mp3_size < 1000:
                embed = discord.Embed(
                    title="⚠️ 未偵測到語音活動",
                    description=f"在過去 **{seconds}** 秒內沒有成員在語音頻道發言。",
                    color=0xE67E22
                )
                if is_interaction:
                    return await interaction_or_ctx.followup.send(embed=embed, ephemeral=True)
                return await interaction_or_ctx.respond(embed=embed, ephemeral=True)

            # 格式化參與說話的成員名稱（不使用 @ 標記成員，避免擾民）
            guild = interaction_or_ctx.guild
            speakers = []
            for uid in active_uids:
                if uid > 1000000000000:
                    member = guild.get_member(uid) if guild else None
                    if not member:
                        member = self.bot.get_user(uid)
                    if member:
                        speakers.append(f"**{member.display_name}**")
                    else:
                        speakers.append(f"成員({uid})")
                else:
                    member_name = None
                    if sink.vc:
                        real_uid = sink.vc._ssrc_to_id.get(uid)
                        if not real_uid and hasattr(sink.vc, "_connection"):
                            real_uid = sink.vc._connection.ssrc_user_map.get(uid)
                        if real_uid:
                            m = guild.get_member(real_uid) if guild else None
                            if not m:
                                m = self.bot.get_user(real_uid)
                            if m:
                                member_name = m.display_name
                    if member_name:
                        speakers.append(f"**{member_name}**")
                    else:
                        speakers.append(f"語音成員(軌道 {uid})")
            speakers_str = ", ".join(speakers) if speakers else "語音成員"

            timestr = time.strftime("%Y%m%d_%H%M%S")
            filename = f"clip_{seconds}s_{timestr}.mp3"
            file = discord.File(mp3_buf, filename=filename)

            embed = discord.Embed(
                title=f"🎬 前 {seconds} 秒語音對話精彩剪輯！",
                description=f"⏱️ **剪輯長度:** {seconds} 秒\n🗣️ **參與對話成員:** {speakers_str}\n📦 **檔案大小:** {mp3_size / (1024*1024):.2f} MB",
                color=0x2ECC71
            )
            embed.set_footer(text="音訊已採用直通無損串流輸出，完整保留對話內容 (320 kbps MP3)")

            allowed_mentions = discord.AllowedMentions.none()
            if is_interaction:
                await interaction_or_ctx.followup.send(embed=embed, file=file, allowed_mentions=allowed_mentions)
            else:
                await interaction_or_ctx.respond(embed=embed, file=file, allowed_mentions=allowed_mentions)

        except Exception as e:
            logger.error(f"擷取前一分鐘對話失敗: {e}")
            err_msg = f"❌ 擷取語音回放時發生錯誤: {e}"
            if is_interaction:
                await interaction_or_ctx.followup.send(err_msg, ephemeral=True)
            else:
                await interaction_or_ctx.respond(err_msg, ephemeral=True)

    @slash_command(name="clip", description="擷取語音頻道中前 1 分鐘（或指定秒數）的完整成員對話並匯出 MP3")
    async def clip(
        self,
        ctx: discord.ApplicationContext,
        seconds: Option(int, "回溯秒數 (預設 60 秒，最長 120 秒)", required=False, default=60, min_value=10, max_value=120)
    ):
        await self.handle_clip(ctx, seconds=seconds)

    @slash_command(name="autorecord", description="設定是否在機器人進入語音時自動全程錄音存檔")
    async def autorecord(
        self,
        ctx: discord.ApplicationContext,
        enabled: Option(bool, "是否啟用自動全程錄音存檔", required=True)
    ):
        self.voice_mgr.auto_record = enabled
        sink = self.voice_mgr.get_sink(ctx.guild.id)
        if sink:
            sink.is_session_recording = enabled
            if enabled:
                sink.start_session_recording()

        status_text = "✅ **已開啟** 全程自動錄音！" if enabled else "⏹️ **已關閉** 全程自動錄音（但仍會保持前一分鐘對話剪輯緩衝區）。"
        embed = discord.Embed(
            title="🎙️ 自動錄音設定變更",
            description=status_text,
            color=0x3498DB
        )
        await ctx.respond(embed=embed, ephemeral=True)

    @slash_command(name="record_start", description="手動開始一場完整的語音對話錄音會話")
    async def record_start(self, ctx: discord.ApplicationContext):
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.respond("❌ 請先加入語音頻道！", ephemeral=True)

        voice_channel = ctx.author.voice.channel
        await self.voice_mgr.connect_voice(voice_channel, text_channel=ctx.channel)

        sink = self.voice_mgr.get_sink(ctx.guild.id)
        if not sink:
            return await ctx.respond("❌ 啟動錄音器失敗。", ephemeral=True)

        sink.start_session_recording()
        embed = discord.Embed(
            title="🔴 完整對話錄音已開始",
            description=f"正在錄製頻道 **{voice_channel.name}** 中的對話...\n完成後請使用 `/record_stop` 結束並儲存檔案。",
            color=0xE74C3C
        )
        await ctx.respond(embed=embed, ephemeral=True)

    @slash_command(name="record_stop", description="結束完整錄音會話，儲存至磁碟並上傳 MP3 錄音檔")
    async def record_stop(self, ctx: discord.ApplicationContext):
        await ctx.defer()
        sink = self.voice_mgr.get_sink(ctx.guild.id)
        if not sink or not sink.is_session_recording:
            return await ctx.respond("⚠️ 目前沒有正在進行的手動或自動錄音會話。", ephemeral=True)

        timestr = time.strftime("%Y%m%d_%H%M%S")
        filename = f"session_{timestr}.mp3"
        out_path = await sink.stop_session_recording_async(filename)

        if not out_path or not os.path.exists(out_path):
            return await ctx.respond("⚠️ 錄音會話中沒有錄到任何成員語音數據。", ephemeral=True)

        file_size = os.path.getsize(out_path)
        embed = discord.Embed(
            title="💾 錄音會話已結束並儲存",
            description=f"📁 **檔案已存至本機目錄:** `{out_path}`\n📦 **檔案大小:** {file_size / (1024*1024):.2f} MB",
            color=0x2ECC71
        )

        # 若檔案小於 Discord 限制 (25MB)，直接上傳至頻道
        if file_size < 24 * 1024 * 1024:
            file = discord.File(out_path, filename=filename)
            await ctx.respond(embed=embed, file=file)
        else:
            embed.set_footer(text="檔案大小超過 Discord 上傳限制，已保存在本機磁碟。")
            await ctx.respond(embed=embed)

    @slash_command(name="record_status", description="查看當前語音頻道的錄音緩衝區與說話狀態")
    async def record_status(self, ctx: discord.ApplicationContext):
        sink = self.voice_mgr.get_sink(ctx.guild.id)
        if not sink:
            return await ctx.respond("機器人目前不在語音頻道中，錄音模組閒置中。", ephemeral=True)

        now = time.time()
        active_in_60s = []
        for uid, chunks in sink.rolling_buffers.items():
            if chunks and now - chunks[-1][0] < 60.0:
                active_in_60s.append(uid)

        guild = ctx.guild
        speakers = []
        for uid in active_in_60s:
            if uid > 1000000000000:
                member = guild.get_member(uid) if guild else None
                if not member:
                    member = self.bot.get_user(uid)
                if member:
                    speakers.append(f"**{member.display_name}**")
                else:
                    speakers.append(f"成員({uid})")
            else:
                speakers.append("語音成員")
        speakers_str = ", ".join(speakers) if speakers else "最近無人說話"

        embed = discord.Embed(
            title="📊 語音錄製與緩衝區狀態",
            color=0x9B59B6
        )
        embed.add_field(name="前一分鐘緩衝狀態", value="🟢 正常監聽中（隨時可用 `/clip` 擷取）", inline=False)
        embed.add_field(name="全程自動錄音存檔", value="🔴 進行中" if sink.is_session_recording else "⚪ 未開啟", inline=True)
        embed.add_field(name="近 60 秒發言成員", value=speakers_str, inline=False)
        await ctx.respond(embed=embed, allowed_mentions=discord.AllowedMentions.none(), ephemeral=True)

def setup(bot: discord.Bot):
    bot.add_cog(RecordCog(bot))
