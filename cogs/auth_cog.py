import os
import logging
import discord
from discord.ext import commands
from discord.commands import slash_command
from music.ytm_client import ytm_client
from config.settings import OAUTH_JSON_PATH, BROWSER_JSON_PATH, COOKIES_TXT_PATH

logger = logging.getLogger(__name__)

class AuthCog(commands.Cog):
    """
    Google 帳號登入與 YouTube Music 帳號狀態管理
    """

    def __init__(self, bot: discord.Bot):
        self.bot = bot

    @slash_command(name="google_status", description="查看 Google 帳號與 YouTube Music 登入狀態")
    async def google_status(self, ctx: discord.ApplicationContext):
        is_auth = ytm_client.is_authenticated()
        mode_names = {
            "oauth": "🔑 Google OAuth 官方認證",
            "browser": "🌐 瀏覽器請求標頭 (Browser Headers)",
            "cookie": "🍪 瀏覽器 Cookie (cookies.txt)",
            "guest": "👤 訪客模式 (未登入 Google 帳號)"
        }

        embed = discord.Embed(
            title="Google 帳號登入狀態",
            color=0x2ECC71 if is_auth else 0xF39C12
        )
        embed.add_field(name="目前認證模式", value=mode_names.get(ytm_client.auth_mode, "未知"), inline=False)

        if is_auth:
            features = (
                "✅ 播放個人已按讚的音樂 (`/ytm_liked`)\n"
                "✅ 存取個人 YouTube Music 歌單 (`/ytm_playlists`)\n"
                "✅ 享有個人化演算法與電台推薦 (`/ytm_radio`)\n"
                "✅ 解除年齡限制與地區歌曲限制"
            )
            embed.add_field(name="已解鎖功能", value=features, inline=False)
            embed.set_footer(text="若要登出或切換帳號，請使用 /google_logout")
        else:
            features = (
                "⚠️ 目前為訪客模式，支援公開歌曲搜尋與播放。\n"
                "❌ 無法讀取個人歌單與按讚歌曲。\n\n"
                "💡 **如何登入？** 請在伺服器目錄執行 `python setup_google.py` 或查看 `/google_login` 指南！"
            )
            embed.add_field(name="功能狀態", value=features, inline=False)

        await ctx.respond(embed=embed)

    @slash_command(name="google_login", description="查看如何登入 Google 帳號以播放個人 YouTube Music 歌單")
    async def google_login(self, ctx: discord.ApplicationContext):
        embed = discord.Embed(
            title="🔐 如何綁定 Google 帳號至 YouTube Music 機器人",
            description="本機器人支援三種便利的 Google 帳號登入方式：",
            color=0x4285F4
        )

        oauth_guide = (
            "1. 打開終端機（Terminal）並切換至機器人目錄\n"
            "2. 執行：`python setup_google.py`\n"
            "3. 選擇 **模式 1 (Google TV / 設備授權碼流程)**\n"
            "4. 終端機將提供一組代碼並指引您至 [google.com/device](https://www.google.com/device)\n"
            "5. 輸入代碼並按下允許，機器人即自動完成 Google 登入！"
        )
        embed.add_field(name="方式一：Google 官方設備碼登入（最推薦、最安全）", value=oauth_guide, inline=False)

        cookie_guide = (
            "1. 在瀏覽器打開 [music.youtube.com](https://music.youtube.com) 並登入您的帳號\n"
            "2. 執行 `python setup_google.py` 選擇模式 2 貼上請求標頭\n"
            "3. 或使用擴充套件匯出 `cookies.txt` 放入 `config/cookies.txt`"
        )
        embed.add_field(name="方式二：瀏覽器 Cookie / 請求標頭（免建 GCP 憑證）", value=cookie_guide, inline=False)

        embed.set_footer(text="完成登入後，機器人將立即同步您的 YouTube Music 帳號！")
        await ctx.respond(embed=embed)

    @slash_command(name="google_logout", description="登出目前儲存的 Google 帳號憑證並切換回訪客模式")
    async def google_logout(self, ctx: discord.ApplicationContext):
        if not ytm_client.is_authenticated():
            return await ctx.respond("目前未登入任何 Google 帳號。")

        removed = []
        if OAUTH_JSON_PATH.exists():
            try:
                os.remove(OAUTH_JSON_PATH)
                removed.append("oauth.json")
            except Exception:
                pass

        if BROWSER_JSON_PATH.exists():
            try:
                os.remove(BROWSER_JSON_PATH)
                removed.append("browser.json")
            except Exception:
                pass

        if COOKIES_TXT_PATH.exists():
            try:
                os.remove(COOKIES_TXT_PATH)
                removed.append("cookies.txt")
            except Exception:
                pass

        ytm_client.reload()
        await ctx.respond(f"✅ 已成功清除憑證 ({', '.join(removed)})，已切換回訪客模式！")

def setup(bot: discord.Bot):
    bot.add_cog(AuthCog(bot))
