import json
import random
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any
import discord
from discord.ext import commands
from discord.commands import slash_command, Option
from config.settings import CONFIG_DIR

logger = logging.getLogger(__name__)

LIFE_STATS_FILE = CONFIG_DIR / "life_stats.json"

# ==============================================================================
# 1. 全球 80 億人口國家資料庫 (基於真實聯合國與世界銀行出生率及人均數據)
# ==============================================================================
COUNTRIES_DB = [
    # --- 亞洲 ---
    {
        "id": "TW", "name": "台灣", "flag": "🇹🇼", "weight": 13, "region": "東亞",
        "prob_text": "0.10%", "life_exp": 81, "gdp_text": "$33,000", "tier": "high",
        "male_names": ["陳柏宇", "林冠宇", "張宏銘", "黃家豪", "李俊傑", "楊子軒", "王志偉"],
        "female_names": ["林映彤", "黃佳蓉", "陳品妤", "張雅婷", "李佳玲", "楊宜臻", "許心怡"]
    },
    {
        "id": "JP", "name": "日本", "flag": "🇯🇵", "weight": 70, "region": "東亞",
        "prob_text": "0.54%", "life_exp": 84, "gdp_text": "$34,000", "tier": "high",
        "male_names": ["佐藤 蓮", "田中 翔太", "高橋 健一", "鈴木 悠真", "渡邊 拓海", "伊藤 大樹"],
        "female_names": ["田中 結衣", "佐藤 葵", "高橋 陽菜", "鈴木 美咲", "渡邊 櫻", "小林 凜"]
    },
    {
        "id": "KR", "name": "韓國", "flag": "🇰🇷", "weight": 25, "region": "東亞",
        "prob_text": "0.19%", "life_exp": 83, "gdp_text": "$32,000", "tier": "high",
        "male_names": ["金敏俊", "李道賢", "朴宇成", "崔俊秀", "鄭載赫", "姜棟元"],
        "female_names": ["李智恩", "金書妍", "朴秀雅", "崔智媛", "鄭恩菲", "韓韶禧"]
    },
    {
        "id": "CN", "name": "中國", "flag": "🇨🇳", "weight": 950, "region": "東亞",
        "prob_text": "7.3%", "life_exp": 78, "gdp_text": "$12,500", "tier": "mid",
        "male_names": ["張偉", "王強", "李磊", "劉洋", "陳浩", "楊帆", "黃勇"],
        "female_names": ["王秀英", "李芳", "張婷", "陳靜", "劉萌", "楊雪", "周潔"]
    },
    {
        "id": "IN", "name": "印度", "flag": "🇮🇳", "weight": 2300, "region": "南亞",
        "prob_text": "17.6%", "life_exp": 70, "gdp_text": "$2,600", "tier": "low",
        "male_names": ["Aarav Patel", "Vihaan Sharma", "Vivaan Gupta", "Aditya Kumar", "Arjun Singh"],
        "female_names": ["Ananya Sharma", "Diya Patel", "Aadhya Singh", "Pari Verma", "Saanvi Joshi"]
    },
    {
        "id": "ID", "name": "印尼", "flag": "🇮🇩", "weight": 440, "region": "東南亞",
        "prob_text": "3.4%", "life_exp": 71, "gdp_text": "$4,900", "tier": "mid",
        "male_names": ["Budi Santoso", "Reza Pratama", "Dimas Setiawan", "Eko Prasetyo"],
        "female_names": ["Siti Nurhaliza", "Dewi Lestari", "Putri Rahayu", "Ayu Wulandari"]
    },
    {
        "id": "PH", "name": "菲律賓", "flag": "🇵🇭", "weight": 210, "region": "東南亞",
        "prob_text": "1.6%", "life_exp": 72, "gdp_text": "$3,900", "tier": "mid",
        "male_names": ["Joshua Santos", "Angelo Cruz", "Daniel Reyes", "Gabriel Ramos"],
        "female_names": ["Maria Clara", "Princess Alcantara", "Bea Nicole", "Chloe Mae"]
    },
    {
        "id": "VN", "name": "越南", "flag": "🇻🇳", "weight": 160, "region": "東南亞",
        "prob_text": "1.2%", "life_exp": 74, "gdp_text": "$4,300", "tier": "mid",
        "male_names": ["阮明智 (Nguyen Minh Tri)", "陳文勇 (Tran Van Dung)", "黎國寶 (Le Quoc Bao)"],
        "female_names": ["阮氏香 (Nguyen Thi Huong)", "陳玉美 (Tran Ngoc My)", "范芳草 (Pham Phuong Thao)"]
    },
    {
        "id": "SG", "name": "新加坡", "flag": "🇸🇬", "weight": 4, "region": "東南亞",
        "prob_text": "0.03%", "life_exp": 84, "gdp_text": "$84,000", "tier": "ultra",
        "male_names": ["Ryan Tan", "Marcus Lim", "Lucas Lee", "Jayden Teo"],
        "female_names": ["Chloe Tan", "Megan Lim", "Hannah Wong", "Rachel Ng"]
    },
    {
        "id": "AE", "name": "阿拉伯聯合大公國", "flag": "🇦🇪", "weight": 10, "region": "中東",
        "prob_text": "0.08%", "life_exp": 79, "gdp_text": "$50,000", "tier": "ultra",
        "male_names": ["Mohammed Al-Mansoor", "Rashid Al-Falasi", "Zayed Al-Nahyan"],
        "female_names": ["Fatima Al-Kaabi", "Maryam Al-Hashimi", "Noura Al-Qasimi"]
    },

    # --- 歐洲 ---
    {
        "id": "CH", "name": "瑞士", "flag": "🇨🇭", "weight": 8, "region": "西歐",
        "prob_text": "0.06%", "life_exp": 84, "gdp_text": "$93,000", "tier": "ultra",
        "male_names": ["Lukas Weber", "Noah Müller", "Julian Keller", "Luca Rossi"],
        "female_names": ["Mia Gerber", "Emma Schneider", "Elena Meier", "Lara Steiner"]
    },
    {
        "id": "NO", "name": "挪威", "flag": "🇳🇴", "weight": 5, "region": "北歐",
        "prob_text": "0.04%", "life_exp": 83, "gdp_text": "$89,000", "tier": "ultra",
        "male_names": ["Jakob Hansen", "Filip Olsen", "Oliver Johansen", "Emil Berg"],
        "female_names": ["Nora Haugen", "Emma Larsen", "Sophie Moen", "Ingrid Dahl"]
    },
    {
        "id": "DE", "name": "德國", "flag": "🇩🇪", "weight": 75, "region": "西歐",
        "prob_text": "0.57%", "life_exp": 81, "gdp_text": "$48,000", "tier": "high",
        "male_names": ["Felix Schmidt", "Maximilian Becker", "Leon Wagner", "Paul Fischer"],
        "female_names": ["Hannah Weber", "Emma Hoffmann", "Marie Schulz", "Sophia Richter"]
    },
    {
        "id": "GB", "name": "英國", "flag": "🇬🇧", "weight": 68, "region": "西歐",
        "prob_text": "0.52%", "life_exp": 81, "gdp_text": "$46,000", "tier": "high",
        "male_names": ["Oliver Smith", "George Taylor", "Arthur Brown", "Harry Wilson"],
        "female_names": ["Olivia Jones", "Amelia Davies", "Isla Evans", "Ava Thomas"]
    },
    {
        "id": "FR", "name": "法國", "flag": "🇫🇷", "weight": 70, "region": "西歐",
        "prob_text": "0.53%", "life_exp": 82, "gdp_text": "$44,000", "tier": "high",
        "male_names": ["Gabriel Martin", "Léo Bernard", "Louis Dubois", "Hugo Robert"],
        "female_names": ["Jade Richard", "Louise Petit", "Ambre Durand", "Alice Moreau"]
    },
    {
        "id": "UA", "name": "烏克蘭", "flag": "🇺🇦", "weight": 28, "region": "東歐",
        "prob_text": "0.21%", "life_exp": 72, "gdp_text": "$4,500", "tier": "mid",
        "male_names": ["Ivan Shevchenko", "Dmytro Bondarenko", "Oleksandr Tkachenko"],
        "female_names": ["Anastasia Boyko", "Olena Melnyk", "Kateryna Moroz"]
    },

    # --- 美洲 ---
    {
        "id": "US", "name": "美國", "flag": "🇺🇸", "weight": 350, "region": "北美",
        "prob_text": "2.7%", "life_exp": 79, "gdp_text": "$76,000", "tier": "high",
        "male_names": ["Liam Miller", "Noah Davis", "James Wilson", "William Anderson"],
        "female_names": ["Olivia Martinez", "Emma Taylor", "Sophia Thomas", "Isabella Moore"]
    },
    {
        "id": "CA", "name": "加拿大", "flag": "🇨🇦", "weight": 36, "region": "北美",
        "prob_text": "0.27%", "life_exp": 82, "gdp_text": "$52,000", "tier": "high",
        "male_names": ["Liam Tremblay", "Noah Roy", "Lucas Gagnon", "Benjamin Bouchard"],
        "female_names": ["Olivia Côté", "Emma Bélanger", "Charlotte Gauthier"]
    },
    {
        "id": "BR", "name": "巴西", "flag": "🇧🇷", "weight": 270, "region": "南美",
        "prob_text": "2.1%", "life_exp": 76, "gdp_text": "$8,900", "tier": "mid",
        "male_names": ["Miguel Silva", "Arthur Santos", "Heitor Oliveira", "Bernardo Souza"],
        "female_names": ["Helena Rodrigues", "Alice Ferreira", "Laura Alves", "Valentina Pereira"]
    },
    {
        "id": "MX", "name": "墨西哥", "flag": "🇲🇽", "weight": 180, "region": "中美",
        "prob_text": "1.4%", "life_exp": 75, "gdp_text": "$10,000", "tier": "mid",
        "male_names": ["Santiago Hernandez", "Mateo Garcia", "Leonardo Martinez"],
        "female_names": ["Sofia Lopez", "Valentina Gonzalez", "Regina Rodriguez"]
    },
    {
        "id": "AR", "name": "阿根廷", "flag": "🇦🇷", "weight": 60, "region": "南美",
        "prob_text": "0.46%", "life_exp": 77, "gdp_text": "$13,000", "tier": "mid",
        "male_names": ["Benjamín Rossi", "Mateo Fernandez", "Bautista Gomez"],
        "female_names": ["Catalina Diaz", "Emma Alvarez", "Martina Romero"]
    },

    # --- 非洲 ---
    {
        "id": "NG", "name": "奈及利亞", "flag": "🇳🇬", "weight": 720, "region": "西非",
        "prob_text": "5.5%", "life_exp": 55, "gdp_text": "$2,100", "tier": "low",
        "male_names": ["Chukwu Emeka", "Oluwaseun Adebayo", "Ibrahim Musa", "Emmanuel Okafor"],
        "female_names": ["Ngozi Eze", "Amina Bello", "Chidinma Okonkwo", "Fatima Abubakar"]
    },
    {
        "id": "ET", "name": "衣索比亞", "flag": "🇪🇹", "weight": 380, "region": "東非",
        "prob_text": "2.9%", "life_exp": 65, "gdp_text": "$1,100", "tier": "low",
        "male_names": ["Yohannes Bekele", "Abebe Tadesse", "Dawit Haile", "Kassahun Desta"],
        "female_names": ["Tirhas Mengistu", "Hirut Alemu", "Sara Tesfaye", "Bethlehem Kebede"]
    },
    {
        "id": "EG", "name": "埃及", "flag": "🇪🇬", "weight": 240, "region": "北非",
        "prob_text": "1.8%", "life_exp": 72, "gdp_text": "$4,300", "tier": "mid",
        "male_names": ["Youssef Hassan", "Omar Ibrahim", "Ahmed Mahmoud", "Ali Mostafa"],
        "female_names": ["Mariam Farouk", "Salma El-Sayed", "Nour Abdel-Rahman"]
    },
    {
        "id": "CD", "name": "剛果民主共和國", "flag": "🇨🇩", "weight": 320, "region": "中非",
        "prob_text": "2.5%", "life_exp": 60, "gdp_text": "$600", "tier": "low",
        "male_names": ["Dieudonné Kabila", "Jean-Luc Tshisekedi", "Patrick Lumumba"],
        "female_names": ["Esperance Mbuyi", "Marie-Claire Kasongo", "Dorcas Mukendi"]
    },
    {
        "id": "ZA", "name": "南非", "flag": "🇿🇦", "weight": 110, "region": "南部非洲",
        "prob_text": "0.85%", "life_exp": 64, "gdp_text": "$6,700", "tier": "mid",
        "male_names": ["Lethabo Mokoena", "Junior Dlamini", "Sipho Ndlovu"],
        "female_names": ["Melokuhle Khumalo", "Amahle Sithole", "Bokamoso Zulu"]
    },

    # --- 大洋洲 ---
    {
        "id": "AU", "name": "澳洲", "flag": "🇦🇺", "weight": 31, "region": "大洋洲",
        "prob_text": "0.24%", "life_exp": 83, "gdp_text": "$65,000", "tier": "high",
        "male_names": ["Oliver Smith", "Noah Jones", "Jack Williams", "William Brown"],
        "female_names": ["Charlotte Wilson", "Amelia Taylor", "Isla Johnson", "Mia Martin"]
    },
    {
        "id": "NZ", "name": "紐西蘭", "flag": "🇳🇿", "weight": 6, "region": "大洋洲",
        "prob_text": "0.05%", "life_exp": 82, "gdp_text": "$48,000", "tier": "high",
        "male_names": ["Oliver Taylor", "Leo Campbell", "Jack Wilson", "Luka Smith"],
        "female_names": ["Isla Davis", "Amelia Brown", "Charlotte Evans", "Harper Bell"]
    }
]

# ==============================================================================
# 2. 家庭背景經濟階級
# ==============================================================================
FAMILY_TIERS = {
    "ultra": [
        ("💎 全球頂尖 1% 豪門望族", 0.05, {"wealth": +40, "happiness": +15, "knowledge": +20}),
        ("🏡 殷實富裕菁英階層", 0.45, {"wealth": +25, "happiness": +15, "knowledge": +15}),
        ("🏢 溫飽健全中產家庭", 0.45, {"wealth": +10, "happiness": +10, "knowledge": +10}),
        ("🏚️ 偶遇波折的工薪家庭", 0.05, {"wealth": -5, "happiness": -5, "knowledge": 0})
    ],
    "high": [
        ("💎 顯赫名門或政商富豪", 0.02, {"wealth": +35, "happiness": +15, "knowledge": +15}),
        ("🏡 體面富足中產階級", 0.38, {"wealth": +20, "happiness": +10, "knowledge": +10}),
        ("🏢 普通平凡受薪家庭", 0.48, {"wealth": +5, "happiness": +5, "knowledge": +5}),
        ("🏚️ 勉強維持底層家庭", 0.12, {"wealth": -15, "happiness": -10, "knowledge": -5})
    ],
    "mid": [
        ("🏡 當地少數富商名流", 0.03, {"wealth": +30, "happiness": +10, "knowledge": +10}),
        ("🏢 勤奮打拼的小康家庭", 0.32, {"wealth": +10, "happiness": +5, "knowledge": +5}),
        ("🏚️ 終日勞碌普通工薪", 0.45, {"wealth": -5, "happiness": -5, "knowledge": 0}),
        ("⛺ 捉襟見肘邊緣家庭", 0.20, {"wealth": -20, "happiness": -15, "knowledge": -10})
    ],
    "low": [
        ("🏢 鎮上少見的富裕商戶", 0.01, {"wealth": +25, "happiness": +10, "knowledge": +10}),
        ("🏚️ 日夜粗工的貧困家庭", 0.34, {"wealth": -10, "happiness": -10, "knowledge": -5}),
        ("⛺ 難以溫飽的窮困農戶", 0.45, {"wealth": -25, "happiness": -20, "knowledge": -15}),
        ("☠️ 遭遇飢饉與戰禍流民", 0.20, {"wealth": -35, "happiness": -25, "knowledge": -20, "health": -20})
    ]
}

# ==============================================================================
# 3. 五大人生年齡階段事件資料庫
# ==============================================================================
STAGE_EVENTS = {
    # ----------------------------------------------------
    # 階段 1：童年成長 (0 - 12歲)
    # ----------------------------------------------------
    "childhood": [
        {
            "title": "幼時求學與啟蒙",
            "desc": "你到了入學啟蒙的年齡，父母問你對什麼最感興趣？",
            "choices": [
                {
                    "label": "專心背書學知識",
                    "emoji": "📚",
                    "effects": {"knowledge": +15, "happiness": -5},
                    "story": "你童年成績名列前茅，成了親戚眼中會讀書的乖孩子。"
                },
                {
                    "label": "整天在田野街道跑跳",
                    "emoji": "🏃",
                    "effects": {"health": +15, "happiness": +15, "knowledge": -5},
                    "story": "你結交了一群死黨，曬得黝黑健康，度過無憂無慮的童年。"
                },
                {
                    "label": "主動幫家裡分擔家務",
                    "emoji": "🧹",
                    "effects": {"wealth": +10, "happiness": +5, "knowledge": +5},
                    "story": "你早早體會了父母的辛勞，心智比同齡人成熟許多。"
                }
            ]
        },
        {
            "title": "童年的意外與考驗",
            "desc": "家鄉發生了一場流感與極端氣候，身邊不少人生病。",
            "choices": [
                {
                    "label": "好好休養加強鍛鍊",
                    "emoji": "💪",
                    "effects": {"health": +10, "happiness": +5},
                    "story": "你挺過病痛，身體抵抗力變得更加堅強。"
                },
                {
                    "label": "借閱舊書藉以排遣",
                    "emoji": "📖",
                    "effects": {"knowledge": +15, "happiness": +5},
                    "story": "在家避難期間，你閱讀了大量課外書籍，眼界大開。"
                },
                {
                    "label": "與鄰居孩童抱團互助",
                    "emoji": "🤝",
                    "effects": {"happiness": +15, "wealth": -5},
                    "story": "你在困頓中收穫了珍貴的真摯友誼。"
                }
            ]
        }
    ],

    # ----------------------------------------------------
    # 階段 2：青少年與升學 (13 - 18歲)
    # ----------------------------------------------------
    "youth": [
        {
            "title": "命運的大考與升學抉擇",
            "desc": "你即將結束中學階段，擺在面前的是一場關鍵的人生抉擇。",
            "choices": [
                {
                    "label": "挑燈夜戰拚命考大學",
                    "emoji": "🎓",
                    "effects": {"knowledge": +20, "wealth": +10, "health": -10, "happiness": -5},
                    "story": "你熬夜苦讀順利考進頂尖大學，成功改變了起跑線！"
                },
                {
                    "label": "學習一技之長提早工作",
                    "emoji": "🔧",
                    "effects": {"wealth": +25, "knowledge": +5, "happiness": +5},
                    "story": "你學得一手好手藝，早早經濟獨立開始存下第一桶金。"
                },
                {
                    "label": "勇敢追求文藝或體育夢想",
                    "emoji": "🎨",
                    "effects": {"happiness": +25, "wealth": -10, "knowledge": +10},
                    "story": "雖然前路迷茫，但你在熱愛中找到了生命的光彩。"
                }
            ]
        },
        {
            "title": "青澀初戀與人際波折",
            "desc": "你在校園或生活圈裡遇見了讓你怦然心動的對象，同時身邊朋友也各有煩惱。",
            "choices": [
                {
                    "label": "勇敢告白展開熱戀",
                    "emoji": "💌",
                    "effects": {"happiness": +20, "wealth": -10},
                    "story": "你們談了一場難忘的青春戀愛，心中充滿甜甜回憶。"
                },
                {
                    "label": "專注自身成長暫不談情",
                    "emoji": "🧘",
                    "effects": {"knowledge": +15, "wealth": +10},
                    "story": "你把重心放在充實自我上，在各方面展現了出色的專注力。"
                },
                {
                    "label": "仗義執言幫助受欺負的朋友",
                    "emoji": "🛡️",
                    "effects": {"happiness": +15, "health": -5},
                    "story": "你挺身而出贏得了大家的尊重與深厚信任。"
                }
            ]
        }
    ],

    # ----------------------------------------------------
    # 階段 3：青年打拼與成家 (19 - 35歲)
    # ----------------------------------------------------
    "adult": [
        {
            "title": "職涯十字路口與打拼",
            "desc": "初入社會，你迎來了職涯發展的關鍵機遇與巨大挑戰。",
            "choices": [
                {
                    "label": "進入大型機構追求穩定升遷",
                    "emoji": "🏢",
                    "effects": {"wealth": +20, "knowledge": +10, "health": -10},
                    "story": "你成了體面白領，雖然常加班，但收入穩定節節攀升。"
                },
                {
                    "label": "賭上積蓄嘗試創業冒險",
                    "emoji": "🚀",
                    "effects": {"wealth": +35, "happiness": +10, "health": -15},
                    "story": "你歷經風雨成功開拓出自己的事業版圖，身家倍增！"
                },
                {
                    "label": "選擇慢活自由業重視生活平衡",
                    "emoji": "☕",
                    "effects": {"happiness": +25, "health": +15, "wealth": -5},
                    "story": "你生活愜意自在，身心健康，懂得享受人生每一個當下。"
                }
            ]
        },
        {
            "title": "婚姻、家庭與居住考驗",
            "desc": "三十而立，人生邁入結婚、成家或定居的重大關口。",
            "choices": [
                {
                    "label": "咬緊牙關買房定居組建家庭",
                    "emoji": "🏡",
                    "effects": {"happiness": +20, "wealth": -20, "knowledge": +5},
                    "story": "你有了溫暖的避風港和相知相守的伴侶，家庭和樂融融。"
                },
                {
                    "label": "享受獨身自由出國移居探索",
                    "emoji": "✈️",
                    "effects": {"happiness": +20, "knowledge": +15, "wealth": +10},
                    "story": "你足跡遍布多國，拓展了寬廣的國際視野與多元體驗。"
                },
                {
                    "label": "與親友合資置產互助共榮",
                    "emoji": "🤝",
                    "effects": {"wealth": +25, "happiness": +10},
                    "story": "團結力量大，家庭家族資產水漲船高。"
                }
            ]
        }
    ],

    # ----------------------------------------------------
    # 階段 4：壯年中年與風浪 (36 - 60歲)
    # ----------------------------------------------------
    "middle": [
        {
            "title": "中年危機與人生洗禮",
            "desc": "步入不惑之年，身心體力漸感疲憊，事業與家庭責任日益沉重。",
            "choices": [
                {
                    "label": "定期體檢開始注重養生長壽",
                    "emoji": "🥗",
                    "effects": {"health": +25, "happiness": +10, "wealth": -10},
                    "story": "及時發現健康隱患並成功調養，整個人精神煥發。"
                },
                {
                    "label": "全力栽培後代成為家族希望",
                    "emoji": "👨‍👩‍👧",
                    "effects": {"happiness": +20, "knowledge": +10, "wealth": -15},
                    "story": "孩子品學兼優成材，成了你最驕傲的成就與心靈寄託。"
                },
                {
                    "label": "轉向公益慈善回饋鄉里社會",
                    "emoji": "❤️",
                    "effects": {"happiness": +30, "wealth": -15},
                    "story": "你的善行感動了許多人，在地方上備受愛戴與推崇。"
                }
            ]
        }
    ],

    # ----------------------------------------------------
    # 階段 5：晚年歲月與終章 (61 - 85+歲)
    # ----------------------------------------------------
    "senior": [
        {
            "title": "桑榆晚景與生命回眸",
            "desc": "歲月如梭，你已白髮蒼蒼，坐在搖椅前回望這漫長而獨特的一生。",
            "choices": [
                {
                    "label": "蒔花弄草享受兒孫繞膝之樂",
                    "emoji": "🌻",
                    "effects": {"happiness": +25, "health": +10},
                    "story": "子孫滿堂圍繞膝前，晚年溫馨安寧，心中毫無遺憾。"
                },
                {
                    "label": "撰寫生平回憶錄傳承後代",
                    "emoji": "✍️",
                    "effects": {"knowledge": +20, "happiness": +15},
                    "story": "你將一生的智慧與人生歷練記錄成冊，代代相傳。"
                },
                {
                    "label": "放下一切漫遊山川放鬆心靈",
                    "emoji": "🌄",
                    "effects": {"happiness": +20, "health": +5},
                    "story": "在山海大自然間靜靜感受生命的恬淡與壯麗。"
                }
            ]
        }
    ]
}

# ==============================================================================
# 4. 人生狀態類別
# ==============================================================================
@dataclass
class LifeSession:
    user_id: int
    country: dict
    gender: str
    name: str
    family_desc: str
    family_tier: str
    rerolls_left: int = 2

    age: int = 0
    health: int = 70
    happiness: int = 65
    knowledge: int = 50
    wealth: int = 50

    alive: bool = True
    death_age: int = 80
    cause_of_death: str = "壽終正寢"
    history: List[str] = field(default_factory=list)
    stage_index: int = 0  # 0: childhood, 1: youth, 2: adult, 3: middle, 4: senior

    def clamp(self):
        self.health = max(0, min(100, self.health))
        self.happiness = max(0, min(100, self.happiness))
        self.knowledge = max(0, min(100, self.knowledge))
        self.wealth = max(0, min(100, self.wealth))

    def evaluate_title(self) -> str:
        score = (self.health + self.happiness + self.knowledge + self.wealth) / 4
        if score >= 85:
            return "👑 80億人中的天選之子 (Legend of the Earth)"
        elif self.wealth >= 85 and self.happiness >= 75:
            return "💎 億萬身家的人生贏家 (Wealthy & Blissful)"
        elif self.knowledge >= 85:
            return "🎓 智慧卓絕的當世智者 (Master of Wisdom)"
        elif self.happiness >= 85:
            return "✨ 樂天知命的幸福智者 (True Happiness)"
        elif self.health >= 85 and self.age >= 80:
            return "🌲 松柏長青的長壽耆宿 (Centenarian)"
        elif self.wealth <= 25 and score >= 60:
            return "🌱 逆境綻放的傲雪梅花 (Triumph Over Adversity)"
        elif score >= 60:
            return "🏡 平凡而圓滿的人生 (A Fulfilling Life)"
        else:
            return "🌪️ 歷經滄桑的風雨行者 (Survivor of the Storm)"

# ==============================================================================
# 5. 生成隨機新生兒
# ==============================================================================
def generate_baby(user_id: int, rerolls: int = 2) -> LifeSession:
    weights = [c["weight"] for c in COUNTRIES_DB]
    country = random.choices(COUNTRIES_DB, weights=weights, k=1)[0]

    gender = random.choices(["男", "女"], weights=[105, 100], k=1)[0]
    names = country["male_names"] if gender == "男" else country["female_names"]
    name = random.choice(names)

    # 家庭背景
    tier_key = country["tier"]
    tier_pool = FAMILY_TIERS.get(tier_key, FAMILY_TIERS["mid"])
    fam_desc, _, base_effects = random.choices(
        tier_pool,
        weights=[p[1] for p in tier_pool],
        k=1
    )[0]

    # 基礎屬性微調
    health = 70 + base_effects.get("health", 0) + random.randint(-5, 5)
    happiness = 65 + base_effects.get("happiness", 0) + random.randint(-5, 5)
    knowledge = 50 + base_effects.get("knowledge", 0) + random.randint(-5, 5)
    wealth = 50 + base_effects.get("wealth", 0) + random.randint(-5, 5)

    # 預期死亡年齡 (以該國預期壽命為基準，加上浮動)
    life_expectancy = country["life_exp"]
    death_age = max(35, int(random.gauss(life_expectancy, 6)))

    session = LifeSession(
        user_id=user_id,
        country=country,
        gender=gender,
        name=name,
        family_desc=fam_desc,
        family_tier=tier_key,
        rerolls_left=rerolls,
        health=health,
        happiness=happiness,
        knowledge=knowledge,
        wealth=wealth,
        death_age=death_age
    )
    session.clamp()
    return session

# ==============================================================================
# 6. 檔案持久化統計
# ==============================================================================
def load_all_stats() -> dict:
    if LIFE_STATS_FILE.exists():
        try:
            with open(LIFE_STATS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_user_life(user_id: int, session: LifeSession):
    data = load_all_stats()
    uid_str = str(user_id)
    if uid_str not in data:
        data[uid_str] = {
            "total_lives": 0,
            "max_age": 0,
            "best_happiness": 0,
            "best_wealth": 0,
            "countries_visited": {},
            "titles": []
        }
    u = data[uid_str]
    u["total_lives"] += 1
    u["max_age"] = max(u["max_age"], session.age)
    u["best_happiness"] = max(u["best_happiness"], session.happiness)
    u["best_wealth"] = max(u["best_wealth"], session.wealth)

    cname = session.country["name"]
    u["countries_visited"][cname] = u["countries_visited"].get(cname, 0) + 1

    t = session.evaluate_title()
    if t not in u["titles"]:
        u["titles"].append(t)

    try:
        with open(LIFE_STATS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"儲存人生統計失敗: {e}")

# ==============================================================================
# 7. UI View 實作
# ==============================================================================

def make_progress_bar(val: int) -> str:
    filled = max(0, min(10, val // 10))
    return "🟩" * filled + "⬜" * (10 - filled)

class BirthCertificateView(discord.ui.View):
    """
    出生證明卡 UI：包含「開啟這段人生」與「重新投胎 (Reroll)」
    """
    def __init__(self, session: LifeSession, bot: discord.Bot):
        super().__init__(timeout=180)
        self.session = session
        self.bot = bot
        self.update_buttons()

    def update_buttons(self):
        for child in self.children:
            if hasattr(child, "custom_id") and child.custom_id == "reroll_btn":
                child.label = f"🔄 重新投胎 (剩餘 {self.session.rerolls_left} 次)"
                child.disabled = (self.session.rerolls_left <= 0)

    def get_embed(self) -> discord.Embed:
        c = self.session.country
        embed = discord.Embed(
            title=f"📜 80億分之1 · 隨機轉世出生證明書",
            description=f"歡迎降生到這顆藍色星球！你誕生於 **{c['flag']} {c['name']}**。\n全世界每秒約誕生 4.3 名嬰兒，而你正是其中獨一無二的 **80億分之1**。",
            color=0xF1C40F
        )
        embed.add_field(name="👶 姓名與性別", value=f"**{self.session.name}** ({self.session.gender})", inline=True)
        embed.add_field(name="🌍 出生國家/地區", value=f"{c['flag']} {c['name']} ({c['region']})", inline=True)
        embed.add_field(name="🎲 全球降生機率", value=f"**{c['prob_text']}**", inline=True)

        embed.add_field(name="🏛️ 當地平均壽命", value=f"約 **{c['life_exp']}** 歲", inline=True)
        embed.add_field(name="💵 當地人均所得", value=f"約 **{c['gdp_text']}** USD", inline=True)
        embed.add_field(name="👨‍👩‍👦 家庭出身背景", value=f"{self.session.family_desc}", inline=False)

        stats_str = (
            f"❤️ **健康值:** {self.session.health}  {make_progress_bar(self.session.health)}\n"
            f"😊 **幸福度:** {self.session.happiness}  {make_progress_bar(self.session.happiness)}\n"
            f"📚 **智識度:** {self.session.knowledge}  {make_progress_bar(self.session.knowledge)}\n"
            f"💰 **家境財富:** {self.session.wealth}  {make_progress_bar(self.session.wealth)}"
        )
        embed.add_field(name="📊 先天初始四維屬性", value=stats_str, inline=False)
        embed.set_footer(text="數據參考聯合國 WPP 及世界銀行統計 • 點擊下方按鈕開始模擬這段人生")
        return embed

    @discord.ui.button(label="🚀 開啟這段人生", style=discord.ButtonStyle.success, emoji="🌱", row=0)
    async def start_life(self, button: discord.ui.Button, interaction: discord.Interaction):
        if interaction.user.id != self.session.user_id:
            return await interaction.response.send_message("❌ 這是別人的輪迴人生！請輸入 `/life` 開啟專屬於你的投胎。", ephemeral=True)

        stage_view = LifeStageView(self.session, self.bot)
        embed = stage_view.get_embed()
        await interaction.response.edit_message(embed=embed, view=stage_view)

    @discord.ui.button(label="🔄 重新投胎", style=discord.ButtonStyle.secondary, emoji="🎲", custom_id="reroll_btn", row=0)
    async def reroll(self, button: discord.ui.Button, interaction: discord.Interaction):
        if interaction.user.id != self.session.user_id:
            return await interaction.response.send_message("❌ 這是別人的輪迴人生！", ephemeral=True)

        if self.session.rerolls_left <= 0:
            return await interaction.response.send_message("⚠️ 投胎轉世次數已用盡！請勇敢踏上這段人生旅程。", ephemeral=True)

        self.session = generate_baby(self.session.user_id, rerolls=self.session.rerolls_left - 1)
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)


class LifeStageView(discord.ui.View):
    """
    人生階段事件推進視圖
    """
    STAGE_KEYS = ["childhood", "youth", "adult", "middle", "senior"]
    STAGE_NAMES = [
        ("🌱 童年成長期 (0 - 12歲)", 12),
        ("🎒 少年求學期 (13 - 18歲)", 18),
        ("💼 青年奮鬥期 (19 - 35歲)", 35),
        ("🏡 壯年中年期 (36 - 60歲)", 60),
        ("🌅 晚年終章期 (61 - 85+歲)", 85)
    ]

    def __init__(self, session: LifeSession, bot: discord.Bot):
        super().__init__(timeout=300)
        self.session = session
        self.bot = bot
        self.current_event = self._pick_event()
        self._build_buttons()

    def _pick_event(self) -> dict:
        key = self.STAGE_KEYS[self.session.stage_index]
        pool = STAGE_EVENTS[key]
        return random.choice(pool)

    def _build_buttons(self):
        self.clear_items()
        choices = self.current_event["choices"]
        for idx, c in enumerate(choices):
            btn = discord.ui.Button(
                label=c["label"][:80],
                emoji=c["emoji"],
                style=discord.ButtonStyle.primary if idx == 0 else discord.ButtonStyle.secondary,
                custom_id=f"choice_{idx}",
                row=idx // 2
            )
            btn.callback = self._make_callback(c)
            self.add_item(btn)

        # 加入快速略過/順其自然按鈕
        skip_btn = discord.ui.Button(
            label="⏩ 順其自然，安穩度過",
            style=discord.ButtonStyle.success,
            custom_id="skip_btn",
            row=2
        )
        skip_btn.callback = self._skip_callback
        self.add_item(skip_btn)

    def _make_callback(self, choice: dict):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.session.user_id:
                return await interaction.response.send_message("❌ 這是別人的命運選擇！", ephemeral=True)

            effects = choice.get("effects", {})
            for attr, delta in effects.items():
                cur = getattr(self.session, attr, 50)
                setattr(self.session, attr, cur + delta)

            self.session.clamp()
            story = choice.get("story", "時光飛逝，人生邁入下一個新階段。")
            self.session.history.append(f"• **{self.session.age}歲**: {story}")

            await self._advance_stage(interaction, custom_msg=story)

        return callback

    async def _skip_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.session.user_id:
            return await interaction.response.send_message("❌ 這是別人的命運選擇！", ephemeral=True)

        self.session.happiness += random.randint(2, 8)
        self.session.clamp()
        story = "歲月靜好，你在平淡安穩中度過了這個人生階段。"
        self.session.history.append(f"• **{self.session.age}歲**: {story}")
        await self._advance_stage(interaction, custom_msg=story)

    async def _advance_stage(self, interaction: discord.Interaction, custom_msg: str):
        # 推進年齡
        target_age = self.STAGE_NAMES[self.session.stage_index][1]
        self.session.age = target_age
        self.session.stage_index += 1

        # 檢查是否因健康見底或超過天壽離世
        if self.session.health <= 10:
            self.session.alive = False
            self.session.cause_of_death = "因長期積勞成疾與健康惡化不幸早逝"
        elif self.session.age >= self.session.death_age:
            self.session.alive = False
            self.session.cause_of_death = "平安度過圓滿歲月，壽終正寢"
        elif self.session.stage_index >= len(self.STAGE_KEYS):
            self.session.alive = False
            self.session.cause_of_death = "兒孫繞膝，安詳走完人生最後一程"

        if not self.session.alive:
            # 結束人生，結算
            save_user_life(self.session.user_id, self.session)
            death_view = DeathReportView(self.session, self.bot)
            await interaction.response.edit_message(embed=death_view.get_embed(), view=death_view)
        else:
            # 下一個階段
            self.current_event = self._pick_event()
            self._build_buttons()
            embed = self.get_embed(last_story=custom_msg)
            await interaction.response.edit_message(embed=embed, view=self)

    def get_embed(self, last_story: str = "") -> discord.Embed:
        c = self.session.country
        stage_name = self.STAGE_NAMES[min(self.session.stage_index, len(self.STAGE_NAMES)-1)][0]

        embed = discord.Embed(
            title=f"{c['flag']} {self.session.name} 的人生旅程 · {stage_name}",
            color=0x3498DB
        )

        if last_story:
            embed.add_field(name="📝 近況回顧", value=last_story, inline=False)

        ev = self.current_event
        embed.add_field(name=f"⚡ 關鍵人生事件：{ev['title']}", value=ev['desc'], inline=False)

        stats_str = (
            f"❤️ 健康: **{self.session.health}** | "
            f"😊 幸福: **{self.session.happiness}** | "
            f"📚 智識: **{self.session.knowledge}** | "
            f"💰 財富: **{self.session.wealth}**"
        )
        embed.add_field(name="📊 當前四維屬性", value=stats_str, inline=False)
        embed.set_footer(text=f"國家: {c['name']} • 年齡: {self.session.age} 歲 • 請點擊下方按鈕做出你的選擇")
        return embed


class DeathReportView(discord.ui.View):
    """
    人生終章結算報告書 UI
    """
    def __init__(self, session: LifeSession, bot: discord.Bot):
        super().__init__(timeout=180)
        self.session = session
        self.bot = bot

    def get_embed(self) -> discord.Embed:
        c = self.session.country
        title_rank = self.session.evaluate_title()
        score = int((self.session.health + self.session.happiness + self.session.knowledge + self.session.wealth) / 4)

        # 計算超越全球百分比
        global_rank_pct = min(99, max(5, int(score * 0.95 + random.randint(-3, 3))))

        embed = discord.Embed(
            title="🌍 80億分之1 · 終章命運結算報告書",
            description=(
                f"在浩瀚宇宙與八十億人口的大千世界中，你已完成了屬於 **{c['flag']} {self.session.name}** 的人生。\n"
                f"享年 **{self.session.age}** 歲，死因：**{self.session.cause_of_death}**。"
            ),
            color=0x9B59B6
        )

        embed.add_field(name="🎖️ 獲得人生稱號", value=f"### {title_rank}", inline=False)
        embed.add_field(
            name="🌐 全球對比定位",
            value=f"與全地球 80 億人相較，你一生的綜合幸福與成就指數超越了全球約 **{global_rank_pct}%** 的人口！",
            inline=False
        )

        final_stats = (
            f"❤️ 最終健康: **{self.session.health}**  {make_progress_bar(self.session.health)}\n"
            f"😊 最終幸福: **{self.session.happiness}**  {make_progress_bar(self.session.happiness)}\n"
            f"📚 最終智識: **{self.session.knowledge}**  {make_progress_bar(self.session.knowledge)}\n"
            f"💰 最終財富: **{self.session.wealth}**  {make_progress_bar(self.session.wealth)}"
        )
        embed.add_field(name="📊 最終人生四維維度", value=final_stats, inline=False)

        history_text = "\n".join(self.session.history[-5:]) if self.session.history else "一生平淡安穩，無疾而終。"
        embed.add_field(name="📖 生平關鍵印記回顧", value=history_text, inline=False)

        embed.set_footer(text="人生如同 80 億分之 1 的抽卡，無論生於何處，每一段努力活過的生命都值得銘記。")
        return embed

    @discord.ui.button(label="🔄 再次轉世投胎", style=discord.ButtonStyle.primary, emoji="🌌", row=0)
    async def play_again(self, button: discord.ui.Button, interaction: discord.Interaction):
        if interaction.user.id != self.session.user_id:
            return await interaction.response.send_message("❌ 請使用 `/life` 開啟您自己的輪迴人生！", ephemeral=True)

        new_session = generate_baby(self.session.user_id, rerolls=2)
        birth_view = BirthCertificateView(new_session, self.bot)
        await interaction.response.edit_message(embed=birth_view.get_embed(), view=birth_view)


# ==============================================================================
# 8. Cog 指令定義
# ==============================================================================
class LifeCog(commands.Cog):
    """
    《80億分之1》人生模擬遊戲 (1 in 8 Billion Life Simulator) 指令群
    """

    def __init__(self, bot: discord.Bot):
        self.bot = bot

    @slash_command(name="life", description="🎲 開啟一場《80億分之1》的隨機人生模擬 (出生在世界 172 個國家之一)")
    async def life(self, ctx: discord.ApplicationContext):
        session = generate_baby(ctx.author.id, rerolls=2)
        view = BirthCertificateView(session, self.bot)
        await ctx.respond(embed=view.get_embed(), view=view)

    @slash_command(name="life_stats", description="📊 查看您在《80億分之1》歷次轉世投胎的累計生涯紀錄與圖鑑")
    async def life_stats(self, ctx: discord.ApplicationContext):
        data = load_all_stats()
        uid_str = str(ctx.author.id)
        if uid_str not in data or data[uid_str]["total_lives"] == 0:
            embed = discord.Embed(
                title="📊 80億分之1 · 輪迴檔案庫",
                description="您尚未開啟過任何人生模擬！立即輸入 `/life` 投胎體驗屬於你的 80 億分之 1 命運吧！",
                color=0xE67E22
            )
            return await ctx.respond(embed=embed)

        u = data[uid_str]
        countries = u.get("countries_visited", {})
        top_countries = sorted(countries.items(), key=lambda x: x[1], reverse=True)[:5]
        top_str = ", ".join([f"{c} ({cnt}次)" for c, cnt in top_countries]) if top_countries else "暫無記錄"

        titles_str = "、".join(u.get("titles", [])[-4:]) if u.get("titles") else "暫無稱號"

        embed = discord.Embed(
            title=f"📊 {ctx.author.display_name} 的 80億分之1 輪迴檔案",
            color=0x9B59B6
        )
        embed.add_field(name="🔄 累計轉世次數", value=f"共 **{u['total_lives']}** 世人生", inline=True)
        embed.add_field(name="👴 活過最高壽命", value=f"**{u['max_age']}** 歲", inline=True)
        embed.add_field(name="😊 歷史最高幸福", value=f"**{u['best_happiness']}** 分", inline=True)
        embed.add_field(name="💰 歷史最高財富", value=f"**{u['best_wealth']}** 分", inline=True)
        embed.add_field(name="🗺️ 最常投胎國家", value=top_str, inline=False)
        embed.add_field(name="🎖️ 曾獲得稱號", value=titles_str, inline=False)
        embed.set_footer(text="每一段人生都是一段奇蹟 • 使用 /life 開啟全新轉世")
        await ctx.respond(embed=embed)

def setup(bot: discord.Bot):
    bot.add_cog(LifeCog(bot))
