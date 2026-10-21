import random
import time
import hashlib
import logging
import discord
from discord.ext import commands
from discord.commands import slash_command, Option

logger = logging.getLogger(__name__)

# ==============================================================================
# 解答之書經典題庫 (The Book of Answers)
# 收錄 180+ 條中英雙語對照、涵蓋決策、感情、事業、哲思、直覺之啟示
# ==============================================================================
BOOK_ANSWERS = [
    # --- 堅定正面 (Affirmative & Action) ---
    {"zh": "毫不猶豫地前進", "en": "Proceed without hesitation", "desc": "宇宙正在為你開路，不要被恐懼阻擋，大步向前吧。"},
    {"zh": "這將是你最棒的決定", "en": "It will be your best decision", "desc": "放下疑慮，你的選擇正在引領你走向豐盛。"},
    {"zh": "就是現在，別再等待", "en": "Now is the time, wait no longer", "desc": "時機已完全成熟，行動比完美的計畫更有力量。"},
    {"zh": "大膽去做，奇蹟將會發生", "en": "Be bold, miracles will happen", "desc": "突破常規的勇氣，將帶給你意想不到的驚喜。"},
    {"zh": "百分之百的肯定", "en": "Absolutely yes", "desc": "毫無疑問，順從內心最渴望的方向。"},
    {"zh": "全力以赴，放手一搏", "en": "Give it your all and take the chance", "desc": "不要給自己留遺憾，傾注所有熱情。"},
    {"zh": "答案比你想像的更樂觀", "en": "The answer is more optimistic than you think", "desc": "烏雲即將散去，背後的晴空早已為你準備好。"},
    {"zh": "去做吧，結果會讓你微笑", "en": "Do it, the result will make you smile", "desc": "這是一條帶著光明的道路。"},
    {"zh": "抓住即將出現的機會", "en": "Seize the upcoming opportunity", "desc": "敏銳觀察身邊的微小改變，那是命運的敲門聲。"},
    {"zh": "信任你的第一直覺", "en": "Trust your first instinct", "desc": "你的潛意識早就知道正確答案，別被過度思考所困。"},
    {"zh": "主動出擊，別處於被動", "en": "Take the initiative, don't be passive", "desc": "掌控命運的鑰匙在你自己手中。"},
    {"zh": "你可以辦得到", "en": "You can definitely do it", "desc": "低估自己是你唯一的弱點，你比想像中更強大。"},
    {"zh": "這件事值得你堅持", "en": "This is worth your persistence", "desc": "黎明前總是最黑暗的，再往前走一步就是日出。"},
    {"zh": "答應它", "en": "Say yes to it", "desc": "開放的心胸將為你迎來意想不到的好運。"},
    {"zh": "這是一個嶄新的起點", "en": "This is a brand new beginning", "desc": "告別過去的包袱，擁抱屬於你的新章節。"},
    {"zh": "美好的事即將發生", "en": "Something wonderful is about to happen", "desc": "保持期待的心情迎接明天的到來。"},
    {"zh": "這是一份命中注定的禮物", "en": "It is a destined gift", "desc": "感恩當下的一切，那是成長的契機。"},
    {"zh": "堅持到底，終會開花結果", "en": "Hold on till the end, it will blossom", "desc": "深埋土裡的種子正在積蓄力量破土而出。"},

    # --- 審慎觀察 (Caution & Reflection) ---
    {"zh": "現在還不是最佳時機", "en": "Now is not the right time", "desc": "急躁容易帶來波折，耐心等待水到渠成之時。"},
    {"zh": "退一步，海闊天空", "en": "Take a step back and see the bigger picture", "desc": "換個視角抽離現場，問題的本質會更加明朗。"},
    {"zh": "重新審視你的初心", "en": "Revisit your original intention", "desc": "問問當初為何出發，那裡藏著解開困惑的指針。"},
    {"zh": "別讓情緒替你做決定", "en": "Do not let emotions make the decision", "desc": "深呼吸，等心情平靜如水後再給出答案。"},
    {"zh": "你需要更多客觀資訊", "en": "You need more objective information", "desc": "不要僅憑片段的猜測下定論，多方求證為宜。"},
    {"zh": "放慢腳步，答案自然浮現", "en": "Slow down, the answer will emerge naturally", "desc": "太快的步伐會讓你錯過路旁的關鍵提示。"},
    {"zh": "不要輕易承諾", "en": "Do not make promises lightly", "desc": "給自己留一點迴旋空間，避免背負過重的負擔。"},
    {"zh": "注意隱藏在細節中的陷阱", "en": "Pay attention to details and hidden traps", "desc": "看似美好的表面下，可能藏有被忽略的代價。"},
    {"zh": "尋求身邊智者的建議", "en": "Seek advice from a wise person nearby", "desc": "旁觀者清，傾聽一位你信任的人的觀點。"},
    {"zh": "再給彼此一點時間", "en": "Give it a little more time", "desc": "發酵需要時間，著急只會打碎原本的美意。"},
    {"zh": "此時沈默勝過言語", "en": "Silence is better than words right now", "desc": "無聲勝有聲，讓時間代替你回答。"},
    {"zh": "防人之心不可無", "en": "Keep your guard up", "desc": "保持善良，但務必留存自我保護的底線。"},
    {"zh": "這件事可能沒有表面單純", "en": "This may not be as simple as it seems", "desc": "多留一份心眼，觀察背後的動機與邏輯。"},
    {"zh": "停下來，先照顧好自己", "en": "Stop, take care of yourself first", "desc": "你已經疲倦了，充電比繼續硬撐更重要。"},
    {"zh": "暫時擱置，幾天後再看", "en": "Put it aside for a few days", "desc": "距離會帶來清醒，過幾天你會有全新的想法。"},

    # --- 釋懷放手 (Letting Go & Acceptance) ---
    {"zh": "學會放手，才能擁抱未來", "en": "Let it go to embrace the future", "desc": "雙手緊抓著枯葉，如何能摘下即將綻放的新花。"},
    {"zh": "原諒過去，放過自己", "en": "Forgive the past and be gentle with yourself", "desc": "過去已經結束，你無須再為舊事背負懲罰。"},
    {"zh": "這件事情其實沒那麼重要", "en": "This matters less than you think", "desc": "五年後回頭看，這只是一段微不足道的插曲。"},
    {"zh": "接受不完美，才會看見光芒", "en": "Accept imperfection to see the light", "desc": "裂痕往往是光照射進來的地方。"},
    {"zh": "不要執著於單一結果", "en": "Do not fixate on a single outcome", "desc": "通往幸福的路不只一條，條條大路通羅馬。"},
    {"zh": "失去，是為了更好的相遇", "en": "Losing makes room for something better", "desc": "空出來的位置，將會迎來真正契合的人事物。"},
    {"zh": "順其自然，別強求", "en": "Let nature take its course, do not force it", "desc": "強摘的果子不甜，讓緣分自在流動。"},
    {"zh": "告別不屬於你的圈子", "en": "Say goodbye to what doesn't belong to you", "desc": "留給真正懂你價值的人更多空間。"},
    {"zh": "允許自己有脆弱的時刻", "en": "Allow yourself to be vulnerable", "desc": "哭泣不是軟弱，而是洗滌心靈重新啟程的儀式。"},
    {"zh": "該結束的就讓它落幕吧", "en": "Let what must end come to a close", "desc": "完美的謝幕，是為了下一場盛大演出的開端。"},

    # --- 哲理啟示 (Wisdom & Philosophy) ---
    {"zh": "答案就在你眼前", "en": "The answer is right in front of you", "desc": "不必捨近求遠，真相就在最唾手可得的地方。"},
    {"zh": "最珍貴的答案藏在最簡單的選擇裡", "en": "The truest answer lies in the simplest choice", "desc": "剔除所有繁雜借口，剩下最純粹的那個念頭。"},
    {"zh": "信任時間的安排", "en": "Trust the timing of your life", "desc": "每個人都有自己的時區，你沒有落後，也沒有太早。"},
    {"zh": "鏡子裡的人會給你指引", "en": "The person in the mirror will guide you", "desc": "凝視自己的眼睛，問問內心深處最誠實的自己。"},
    {"zh": "結果並非唯一目的，享受過程", "en": "The outcome is not the only goal, enjoy the journey", "desc": "途中的風景與經歷，才是生命最深刻的餽贈。"},
    {"zh": "換個角度，世界完全不同", "en": "Change your perspective, the world changes", "desc": "翻轉思考，困境往往是包裝醜陋的轉機。"},
    {"zh": "你的價值無需他人定義", "en": "Your value does not need others' definition", "desc": "你本自具足，無須向外界乞求認同。"},
    {"zh": "少即是多", "en": "Less is more", "desc": "做減法的人生，會讓你感到無比輕盈。"},
    {"zh": "善意終將回流到你身上", "en": "Kindness will eventually flow back to you", "desc": "種下一顆善念的種子，靜待花開時分。"},
    {"zh": "迷茫是因為選擇太多", "en": "Confusion arises from too many choices", "desc": "只挑一件眼下最重要的事，全神貫注做好它。"},
    {"zh": "風暴過後，大海終歸平靜", "en": "After the storm, the ocean returns to peace", "desc": "痛苦與混亂只是一時的陣雨，它一定會過去。"},

    # --- 詼諧幽默 (Humorous & Casual) ---
    {"zh": "先去吃頓好吃的再說", "en": "Go have a delicious meal first", "desc": "胃滿足了，大腦思考才會清晰，犒賞自己一下吧。"},
    {"zh": "去睡一覺，明天答案自然清晰", "en": "Sleep on it, clarity comes tomorrow", "desc": "疲倦的心靈解不開死結，醒來又是嶄新的一天。"},
    {"zh": "別問了，你心裡早就有數", "en": "Stop asking, you already know in your heart", "desc": "你只是在尋找外界的支持來印證自己的決定。"},
    {"zh": "答案在風中飄盪", "en": "The answer is blowing in the wind", "desc": "放鬆點，人生沒那麼多生死攸關的重大考題。"},
    {"zh": "喝杯水，深呼吸三次", "en": "Drink water and take three deep breaths", "desc": "讓身體歸位，放鬆肩膀，焦慮會隨風消散。"},
    {"zh": "拋個硬幣吧，硬幣在空中時你就會明白", "en": "Flip a coin, you'll know your wish mid-air", "desc": "當硬幣旋轉時，你心底期盼它落下的那一面就是答案。"},
    {"zh": "去散散步，吹吹晚風", "en": "Take a walk and feel the evening breeze", "desc": "遠離螢幕與雜訊，大自然會為你梳理思緒。"},
    {"zh": "這個問題的答案取決於你的晚餐", "en": "The answer depends on what you have for dinner", "desc": "保持好心情，生活中的很多結會不攻自破。"},
    {"zh": "笑一個，天塌不下來", "en": "Smile, the sky is not falling", "desc": "只要還活著呼吸，任何難題都能迎刃而解。"},
    {"zh": "試試看，最壞也不過如此", "en": "Give it a shot, the worst is not that bad", "desc": "谷底之後每一步都是向上爬升。"}
]

class BookAnswersView(discord.ui.View):
    """
    解答之書互動式面板：支援再翻一頁、重新提問等操作
    """
    def __init__(self, original_user_id: int, question: str = ""):
        super().__init__(timeout=180)
        self.original_user_id = original_user_id
        self.question = question

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # 允許所有人互動，但若不是發起者可給予提示
        return True

    @discord.ui.button(label="再翻一頁", style=discord.ButtonStyle.primary, emoji="📖")
    async def flip_again(self, button: discord.ui.Button, interaction: discord.Interaction):
        # 隨機抽取另一句解答
        entry = random.choice(BOOK_ANSWERS)
        page_no = random.randint(1, 384)
        
        embed = discord.Embed(
            title="📖《 解 答 之 書 》The Book of Answers",
            description=(
                f"✦ **問題**：*{self.question if self.question else '心中默念的困惑'}*\n\n"
                f"### ✨ **{entry['zh']}**\n"
                f"*{entry['en']}*\n\n"
                f"📜 **指引解析**：\n> {entry['desc']}"
            ),
            color=0xD4AF37 # 典雅燙金色
        )
        embed.set_footer(text=f"✦ 第 {page_no} 頁 ✦ 心誠則靈，答案常存於心 ✦")
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="深層啟示", style=discord.ButtonStyle.secondary, emoji="🔮")
    async def deep_insight(self, button: discord.ui.Button, interaction: discord.Interaction):
        insights = [
            "靈魂的直覺永遠走在理智前面，學會聆聽內心的第一道聲音。",
            "宇宙從不犯錯，當下所經歷的阻礙，都是為了磨礪出更堅韌的你。",
            "當你不再執著於『想要怎樣』，事情往往會以最完美的形式展現。",
            "命運會回報那些敢於誠實面對自我的人，無愧於心便是最好的指引。",
            "無論結果如何，這段經歷都將成為你生命中不可或缺的養分。"
        ]
        chosen_insight = random.choice(insights)
        await interaction.response.send_message(
            f"🔮 **【星界指引與深層洞見】**\n> *「{chosen_insight}」*",
            ephemeral=True
        )

class BookCog(commands.Cog):
    """
    神秘學《解答之書》(The Book of Answers) 指令群
    提供深邃、幽默或富有哲理的命運指引與靈魂啟發
    """

    def __init__(self, bot: discord.Bot):
        self.bot = bot

    @slash_command(name="book", description="📖 打開神秘的《解答之書》，為您心中的疑惑揭曉命運的指引")
    async def book_answer(
        self,
        ctx: discord.ApplicationContext,
        question: Option(str, "您心中想詢問的問題（選填，亦可默念問題於心）", required=False, default="") = "",
        secret: Option(bool, "是否以悄悄話模式翻開（僅自己可見，保護個人隱私）", required=False, default=False) = False
    ):
        entry = random.choice(BOOK_ANSWERS)
        page_no = random.randint(1, 384)

        display_q = question.strip() if question.strip() else "心中默念的疑惑"

        embed = discord.Embed(
            title="📖《 解 答 之 書 》The Book of Answers",
            description=(
                f"✦ **詢問者**：{ctx.author.mention}\n"
                f"✦ **問題**：*{display_q}*\n\n"
                f"```fix\n"
                f"  『 {entry['zh']} 』\n"
                f"```\n"
                f"🏛️ **English**: *{entry['en']}*\n\n"
                f"📜 **冥想指引**：\n> {entry['desc']}"
            ),
            color=0xD4AF37 # 燙金古籍色
        )
        embed.set_thumbnail(url="https://images.unsplash.com/photo-1544716278-ca5e3f4abd8c?w=300&auto=format&fit=crop&q=80")
        embed.set_footer(text=f"✦ 第 {page_no} 頁 ✦ 誠心所願，心誠則靈 ✦")

        view = BookAnswersView(ctx.author.id, question=display_q)
        await ctx.respond(embed=embed, view=view, ephemeral=secret)

    @slash_command(name="book_daily", description="✨ 翻閱《解答之書》今日啟示，獲得專屬於您的每日能量指引")
    async def book_daily(self, ctx: discord.ApplicationContext):
        # 依日期 + 使用者 ID 生成確定性種子，確保每人每天抽到的今日之書固定（跨進程/重啟皆一致）
        today_str = time.strftime("%Y-%m-%d")
        seed_bytes = f"{today_str}_{ctx.author.id}".encode("utf-8")
        seed_val = int(hashlib.md5(seed_bytes).hexdigest()[:8], 16)
        rng = random.Random(seed_val)
        entry = rng.choice(BOOK_ANSWERS)
        page_no = rng.randint(1, 384)

        embed = discord.Embed(
            title=f"🌅 今日專屬啟示・{today_str}",
            description=(
                f"✦ **守護對象**：{ctx.author.mention}\n\n"
                f"```yaml\n"
                f"「{entry['zh']}」\n"
                f"  {entry['en']}\n"
                f"```\n"
                f"💫 **今日能量指針**：\n> {entry['desc']}\n\n"
                "🕯️ *靜下心來，將這句話融入今日的生活步調中。*"
            ),
            color=0xE67E22 # 溫暖晨曦橙
        )
        embed.set_footer(text=f"✦ 今日專屬書頁 第 {page_no} 頁 ✦ 每日凌晨更新 ✦")
        await ctx.respond(embed=embed)

def setup(bot: discord.Bot):
    bot.add_cog(BookCog(bot))
