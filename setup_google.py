import os
import sys
from pathlib import Path
from config.settings import (
    OAUTH_JSON_PATH,
    BROWSER_JSON_PATH,
    COOKIES_TXT_PATH,
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    CONFIG_DIR
)
import ytmusicapi
from ytmusicapi import YTMusic

def print_banner():
    print("=" * 60)
    print("  🎵 YouTube Music Google 帳號授權綁定小幫手 🎵")
    print("=" * 60)
    print()

def setup_oauth_flow():
    print("\n--- [模式 1] Google OAuth 設備代碼授權 ---")
    print("此模式使用 Google 官方設備代碼流程（最安全、穩定）。")
    print("需要 Google Cloud Console 的 Client ID 與 Client Secret。")
    print("（若尚未建立，可在 Google Cloud 啟用 YouTube Data API v3 並建立 TV/Limited Input Device 憑證）")
    print()

    client_id = GOOGLE_CLIENT_ID or input("請輸入 Google Client ID: ").strip()
    client_secret = GOOGLE_CLIENT_SECRET or input("請輸入 Google Client Secret: ").strip()

    if not client_id or not client_secret:
        print("❌ Client ID 與 Client Secret 不能為空！")
        return

    try:
        print("\n⏳ 正在向 Google 請求設備授權代碼...")
        ytmusicapi.setup_oauth(
            client_id=client_id,
            client_secret=client_secret,
            filepath=str(OAUTH_JSON_PATH),
            open_browser=True
        )
        print(f"\n🎉 恭喜！Google OAuth 授權成功！憑證已存至: {OAUTH_JSON_PATH}")
    except Exception as e:
        print(f"\n❌ OAuth 授權失敗: {e}")

def setup_browser_headers():
    print("\n--- [模式 2] 瀏覽器請求標頭 (Browser Headers) ---")
    print("此模式無需申請 Google Cloud 憑證！")
    print("步驟：")
    print("1. 在瀏覽器打開 https://music.youtube.com 並確保已登入您的 Google 帳號。")
    print("2. 按下鍵盤 F12 開啟開發人員工具，切換至『網路 (Network)』標籤頁。")
    print("3. 在網頁上點擊任一歌曲或歌單，在網路清單中找到發往 music.youtube.com 的請求（例如 browse）。")
    print("4. 右鍵點擊該請求 -> 複製 (Copy) -> 複製請求標頭 (Copy Request Headers)。")
    print("5. 複製後回到此處貼上。")
    print()

    try:
        ytmusicapi.setup(filepath=str(BROWSER_JSON_PATH))
        print(f"\n🎉 瀏覽器標頭設定成功！已儲存至: {BROWSER_JSON_PATH}")
    except Exception as e:
        print(f"\n❌ 設定失敗: {e}")

def check_status():
    print("\n--- [目前登入狀態檢查] ---")
    from music.ytm_client import ytm_client
    ytm_client.reload()
    print(f"認證模式: {ytm_client.auth_mode}")
    print(f"已認證: {'是' if ytm_client.is_authenticated() else '否'}")

    if ytm_client.is_authenticated():
        try:
            liked = ytm_client.get_liked_songs(limit=5)
            print(f"✅ 連線成功！已按讚歌曲取樣數: {len(liked)}")
            for i, s in enumerate(liked, start=1):
                print(f"   {i}. {s['title']} - {s['artist']}")
        except Exception as e:
            print(f"⚠️ 讀取歌曲時發生警訊: {e}")
    else:
        print("未偵測到有效憑證，目前運作於訪客模式（僅能搜尋公開歌曲）。")

def main():
    print_banner()
    while True:
        print("請選擇操作選項:")
        print("1. 使用 Google OAuth 登入 (需 GCP 憑證，推薦)")
        print("2. 使用 瀏覽器請求標頭 登入 (免 GCP 憑證)")
        print("3. 查看 cookies.txt 放置指引")
        print("4. 檢查目前帳號連線狀態")
        print("5. 離開")
        choice = input("\n請輸入選項 (1-5): ").strip()

        if choice == "1":
            setup_oauth_flow()
        elif choice == "2":
            setup_browser_headers()
        elif choice == "3":
            print("\n--- [模式 3] cookies.txt 說明 ---")
            print("您可以使用瀏覽器擴充套件（如 'Get cookies.txt locally'）匯出 cookies.txt。")
            print(f"匯出後請將檔案命名為 `cookies.txt` 並直接放置於：")
            print(f"👉 {COOKIES_TXT_PATH}")
            print("機器人將自動偵測並載入 cookies.txt。\n")
        elif choice == "4":
            check_status()
        elif choice == "5":
            print("再見！")
            break
        else:
            print("無效的選項，請重新輸入。")
        print("\n" + "-" * 60 + "\n")

if __name__ == "__main__":
    main()
