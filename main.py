import os
import sys

# Windows 終端機 UTF-8 編碼支援 (避免 emoji 列印時發生 cp950 編碼錯誤)
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import logging
from pathlib import Path

# 設定基本記錄
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("DiscordBot")

# 匯入環境設定
from config.settings import (
    DISCORD_TOKEN,
    COMMAND_PREFIX,
    AUTO_RECORD,
    REPLAY_BUFFER_SECONDS,
    AUTO_JOIN_ENABLED,
    AUTO_JOIN_MIN_MEMBERS,
    RESTART_INFO_PATH
)
import discord
from core.pycord_patch import apply_pycord_patches
from core.voice_manager import VoiceManager
from music.ytm_client import ytm_client

# 套用 Pycord 錄音相容性修復補丁
apply_pycord_patches()

# 建立 Discord Bot (啟用標準語音與伺服器 intents，無需啟用特權 intents 即可穩定運作)
intents = discord.Intents.default()
intents.voice_states = True
intents.guilds = True

bot = discord.Bot(intents=intents)
bot.voice_manager = VoiceManager(bot)

# 設定音訊接收日誌等級（避免損毀封包資訊刷屏）
logging.getLogger("discord.opus").setLevel(logging.WARNING)
logging.getLogger("discord.voice.receive.reader").setLevel(logging.WARNING)

# 載入 Cogs
COGS = [
    "cogs.music_cog",
    "cogs.record_cog",
    "cogs.auth_cog",
    "cogs.channel_cog",
    "cogs.admin_cog",
    "cogs.book_cog",
    "cogs.panel_cog"
]

for cog in COGS:
    try:
        bot.load_extension(cog)
        logger.info(f"成功載入模組: {cog}")
    except Exception as e:
        logger.error(f"載入模組 {cog} 失敗: {e}", exc_info=True)

@bot.event
async def on_ready():
    logger.info("=" * 60)
    logger.info(f"🤖 機器人已成功上線！")
    logger.info(f"名稱: {bot.user.name}#{bot.user.discriminator} (ID: {bot.user.id})")
    logger.info(f"已連線伺服器數量: {len(bot.guilds)}")
    logger.info(f"YouTube Music 登入狀態: {ytm_client.auth_mode}")
    logger.info(f"全程自動錄音: {'開啟' if AUTO_RECORD else '關閉'}")
    logger.info(f"前一分鐘回放緩衝區長度: {REPLAY_BUFFER_SECONDS} 秒")
    logger.info(f"自動加入語音: {'開啟 (>= ' + str(AUTO_JOIN_MIN_MEMBERS) + ' 人)' if AUTO_JOIN_ENABLED else '關閉'}")
    logger.info("=" * 60)
    sys.stdout.flush()

    # 清理舊的殘留語音連線
    for vc in bot.voice_clients:
        try:
            await vc.disconnect(force=True)
        except Exception:
            pass

    # 若啟動時已有語音頻道達到人數門檻，自動加入
    if AUTO_JOIN_ENABLED:
        for guild in bot.guilds:
            if not guild.voice_client:
                for channel in guild.voice_channels:
                    non_bots = [m for m in channel.members if not m.bot]
                    if len(non_bots) >= AUTO_JOIN_MIN_MEMBERS:
                        logger.info(f"伺服器 {guild.name} 頻道 {channel.name} 成員達 {len(non_bots)} 人，機器人自動加入！")
                        try:
                            await bot.voice_manager.connect_voice(channel, manual=False)
                        except Exception as e:
                            logger.warning(f"自動加入頻道 {channel.name} 失敗: {e}")
                        break

    # 設定機器人狀態
    activity = discord.Activity(
        type=discord.ActivityType.listening,
        name="YouTube Music 🎵 | /play | /clip"
    )
    await bot.change_presence(status=discord.Status.online, activity=activity)

    # 檢查是否有未完成的重啟通知
    if RESTART_INFO_PATH.exists():
        try:
            import json
            import time
            with open(RESTART_INFO_PATH, "r", encoding="utf-8") as f:
                r_info = json.load(f)
            RESTART_INFO_PATH.unlink(missing_ok=True)
            ch_id = r_info.get("channel_id")
            msg_id = r_info.get("message_id")
            start_ts = r_info.get("timestamp", 0)
            elapsed_sec = round(time.time() - start_ts, 2) if start_ts else 0

            channel = bot.get_channel(ch_id)
            if channel:
                msg = await channel.fetch_message(msg_id)
                if msg:
                    embed = discord.Embed(
                        title="✅ 機器人已成功重新啟動！",
                        description=(
                            f"🔄 **重啟耗時**: `{elapsed_sec}` 秒\n"
                            f"⚡ **連線延遲 (Ping)**: `{int(bot.latency * 1000)}` ms\n"
                            f"🌐 **連線伺服器數**: `{len(bot.guilds)}`\n\n"
                            "全功能模組已全新載入完畢，隨時可進行點歌或語音操作！"
                        ),
                        color=0x2ECC71
                    )
                    await msg.edit(embed=embed, view=None)
        except Exception as ex:
            logger.debug(f"更新重啟訊息失敗: {ex}")

@bot.event
async def on_voice_state_update(member, before, after):
    """
    1. 當語音頻道中達到 2 人以上時，自動加入
    2. 當語音頻道成員減少（只剩 0 人，或少於 2 人且未手動召喚/未播放音樂）時，自動退出
    """
    if member.id == bot.user.id:
        return

    # 若只是麥克風/耳機靜音切換，不涉及頻道變動，則忽略
    if before.channel == after.channel:
        return


    # ----------------------------------------------------
    # 情境一：成員加入或切換至某個語音頻道 (after.channel)
    # ----------------------------------------------------
    if after.channel is not None and AUTO_JOIN_ENABLED:
        target_ch = after.channel
        guild = target_ch.guild
        
        # 取得頻道非機器人成員（使用 voice_states 確保即時準確，不受快取影響）
        ch_user_ids = set(target_ch.voice_states.keys())
        if not member.bot:
            ch_user_ids.add(member.id)
        if bot.user and bot.user.id in ch_user_ids:
            ch_user_ids.remove(bot.user.id)

        # 計算非機器人人數
        non_bot_count = 0
        for uid in ch_user_ids:
            m = guild.get_member(uid)
            if m:
                if not m.bot:
                    non_bot_count += 1
            else:
                non_bot_count += 1

        logger.info(f"語音頻道動態: 成員 {member.display_name} 進入 {target_ch.name} (頻道現有人數: {non_bot_count}, 門檻: {AUTO_JOIN_MIN_MEMBERS})")

        if non_bot_count >= AUTO_JOIN_MIN_MEMBERS:
            vc = guild.voice_client
            from core.guild_settings import guild_settings
            text_ch = guild_settings.get_music_channel(guild)

            # 機器人尚未連線語音
            if not vc or not vc.is_connected():
                logger.info(f"語音頻道 {target_ch.name} 成員達 {non_bot_count} 人 (>= {AUTO_JOIN_MIN_MEMBERS})，機器人自動加入並啟動語音對話錄製。")
                try:
                    await bot.voice_manager.connect_voice(target_ch, text_channel=text_ch, manual=False)
                    if text_ch:
                        embed = discord.Embed(
                            title="🎙️ 機器人已自動加入語音頻道！",
                            description=f"已連線至 **{target_ch.name}** 並自動啟動語音對話錄製！\n隨時可以使用 `/clip` 擷取前 1 分鐘精彩對話，或使用 `/play` 點歌。",
                            color=0x2ECC71
                        )
                        await text_ch.send(embed=embed)
                except Exception as e:
                    logger.warning(f"自動加入語音頻道 {target_ch.name} 失敗: {e}")
            elif vc.channel and vc.channel.id != target_ch.id:
                # 機器人已在其他頻道，檢查原頻道是否已經無人且未在播歌
                curr_user_ids = set(vc.channel.voice_states.keys())
                if bot.user and bot.user.id in curr_user_ids:
                    curr_user_ids.remove(bot.user.id)
                curr_non_bots = [uid for uid in curr_user_ids if not (guild.get_member(uid) and guild.get_member(uid).bot)]
                if len(curr_non_bots) == 0 and not vc.is_playing():
                    logger.info(f"原頻道 {vc.channel.name} 已無成員，新頻道 {target_ch.name} 達 {non_bot_count} 人，自動移動。")
                    try:
                        await bot.voice_manager.connect_voice(target_ch, manual=False)
                    except Exception as e:
                        logger.warning(f"自動移動語音頻道失敗: {e}")

    # ----------------------------------------------------
    # 情境二：成員離開或切換出原本的語音頻道 (before.channel)
    # ----------------------------------------------------
    if before.channel is not None:
        left_ch = before.channel
        guild = left_ch.guild
        vc = guild.voice_client
        # 確保連線已建立且機器人位於成員剛剛離開的頻道
        if vc and vc.is_connected() and vc.channel and vc.channel.id == left_ch.id:
            left_user_ids = set(left_ch.voice_states.keys())
            left_user_ids.discard(member.id)
            if bot.user:
                left_user_ids.discard(bot.user.id)

            remaining_count = 0
            for uid in left_user_ids:
                m = guild.get_member(uid)
                if m:
                    if not m.bot:
                        remaining_count += 1
                else:
                    remaining_count += 1

            is_manual = bot.voice_manager.manual_joins.get(guild.id, False)

            # 規則 1：完全沒有任何非機器人成員時，必然離開
            if remaining_count == 0:
                logger.info(f"頻道 {vc.channel.name} 已無其他成員，機器人自動退出語音。")
                await bot.voice_manager.disconnect_voice(guild.id)
            # 規則 2：若是自動加入的狀態，且人數降至門檻以下且未在播歌/暫停中時，自動退出
            elif not is_manual and remaining_count < AUTO_JOIN_MIN_MEMBERS:
                player = bot.voice_manager.players.get(guild.id)
                has_active_music = (
                    vc.is_playing()
                    or vc.is_paused()
                    or (player and (player.current is not None or len(player.queue_list) > 0))
                )
                if not has_active_music:
                    logger.info(f"頻道 {vc.channel.name} 成員少於 {AUTO_JOIN_MIN_MEMBERS} 人且無音樂播放，機器人自動退出。")
                    await bot.voice_manager.disconnect_voice(guild.id)

@bot.event
async def on_application_command_error(ctx: discord.ApplicationContext, error: discord.DiscordException):
    logger.error(f"指令執行錯誤: {error}", exc_info=True)
    if not ctx.response.is_done():
        await ctx.respond(f"❌ 執行指令時發生錯誤: {error}", ephemeral=True)
    else:
        await ctx.followup.send(f"❌ 執行指令時發生錯誤: {error}", ephemeral=True)

def run():
    if not DISCORD_TOKEN or DISCORD_TOKEN == "YOUR_DISCORD_BOT_TOKEN_HERE":
        print("\n" + "!" * 60)
        print("❌ 錯誤：尚未填寫 DISCORD_TOKEN！")
        print("請在 .env 檔案中填入您的 Discord Bot Token。")
        print("您可以在 Discord 開發者門戶 -> Bot -> Reset Token 取得。")
        print("!" * 60 + "\n")
        sys.exit(1)

    try:
        bot.run(DISCORD_TOKEN)
    except (KeyboardInterrupt, SystemExit):
        logger.info("機器人程序已優雅關閉。")
    except Exception as e:
        logger.error(f"機器人執行期間發生未預期錯誤: {e}")

if __name__ == "__main__":
    run()
