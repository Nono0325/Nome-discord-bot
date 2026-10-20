import os
import sys
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
from config.settings import DISCORD_TOKEN, COMMAND_PREFIX, AUTO_RECORD, REPLAY_BUFFER_SECONDS
import discord
from core.voice_manager import VoiceManager
from music.ytm_client import ytm_client

# 建立 Discord Bot
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True

bot = discord.Bot(intents=intents)
bot.voice_manager = VoiceManager(bot)

# 載入 Cogs
COGS = [
    "cogs.music_cog",
    "cogs.record_cog",
    "cogs.auth_cog"
]

for cog in COGS:
    try:
        bot.load_extension(cog)
        logger.info(f"成功載入模組: {cog}")
    except Exception as e:
        logger.error(f"載入模組 {cog} 失敗: {e}", exc_info=True)

@bot.event
async def on_ready():
    print("=" * 60)
    print(f"  🤖 機器人已成功上線！")
    print(f"  名稱: {bot.user.name}#{bot.user.discriminator} (ID: {bot.user.id})")
    print(f"  已連線伺服器數量: {len(bot.guilds)}")
    print(f"  YouTube Music 登入狀態: {ytm_client.auth_mode}")
    print(f"  全程自動錄音: {'開啟' if AUTO_RECORD else '關閉'}")
    print(f"  前一分鐘回放緩衝區長度: {REPLAY_BUFFER_SECONDS} 秒")
    print("=" * 60)

    # 設定機器人狀態
    activity = discord.Activity(
        type=discord.ActivityType.listening,
        name="YouTube Music 🎵 | /play | /clip"
    )
    await bot.change_presence(status=discord.Status.online, activity=activity)

@bot.event
async def on_voice_state_update(member, before, after):
    """
    當語音頻道中只剩機器人一人時，自動退出以節省伺服器頻寬與資源
    """
    if member.id == bot.user.id:
        return

    # 檢查是否有機器人所在的頻道成員異動
    for guild in bot.guilds:
        vc = guild.voice_client
        if vc and vc.channel:
            # 取得該頻道非機器人的成員數
            non_bots = [m for m in vc.channel.members if not m.bot]
            if len(non_bots) == 0:
                logger.info(f"頻道 {vc.channel.name} 已無其他成員，機器人自動中斷語音。")
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

    bot.run(DISCORD_TOKEN)

if __name__ == "__main__":
    run()
