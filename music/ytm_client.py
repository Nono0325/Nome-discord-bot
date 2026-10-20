import json
import logging
from typing import List, Dict, Any, Optional
from ytmusicapi import YTMusic, OAuthCredentials
from config.settings import (
    OAUTH_JSON_PATH,
    BROWSER_JSON_PATH,
    COOKIES_TXT_PATH,
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET
)

logger = logging.getLogger(__name__)

class YouTubeMusicClient:
    """
    YouTube Music 客戶端封裝：
    支援 Google OAuth 帳號登入、瀏覽器 Cookie 認證，或未登入的訪客模式。
    """

    def __init__(self):
        self.ytm: Optional[YTMusic] = None
        self.auth_mode: str = "guest"
        self.user_name: Optional[str] = None
        self.reload()

    def reload(self):
        """重新載入認證與初始化 YTMusic"""
        self.auth_mode = "guest"
        self.user_name = None

        # 1. 嘗試 OAuth 認證 (oauth.json)
        if OAUTH_JSON_PATH.exists():
            try:
                if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
                    creds = OAuthCredentials(
                        client_id=GOOGLE_CLIENT_ID,
                        client_secret=GOOGLE_CLIENT_SECRET
                    )
                    self.ytm = YTMusic(str(OAUTH_JSON_PATH), oauth_credentials=creds)
                else:
                    self.ytm = YTMusic(str(OAUTH_JSON_PATH))
                self.auth_mode = "oauth"
                logger.info("YouTube Music 成功使用 Google OAuth 模式登入！")
            except Exception as e:
                logger.warning(f"OAuth 載入失敗: {e}")

        # 2. 嘗試 Browser Headers 認證 (browser.json)
        if self.auth_mode == "guest" and BROWSER_JSON_PATH.exists():
            try:
                self.ytm = YTMusic(str(BROWSER_JSON_PATH))
                self.auth_mode = "browser"
                logger.info("YouTube Music 成功使用 Browser Headers 模式登入！")
            except Exception as e:
                logger.warning(f"Browser JSON 載入失敗: {e}")

        # 3. 嘗試 Cookies 認證 (cookies.txt)
        if self.auth_mode == "guest" and COOKIES_TXT_PATH.exists():
            try:
                self.ytm = YTMusic(str(COOKIES_TXT_PATH))
                self.auth_mode = "cookie"
                logger.info("YouTube Music 成功使用 cookies.txt 模式登入！")
            except Exception as e:
                logger.warning(f"Cookies.txt 載入失敗: {e}")

        # 4. 訪客模式 (未登入 Google 帳號)
        if self.ytm is None or self.auth_mode == "guest":
            try:
                self.ytm = YTMusic()
                self.auth_mode = "guest"
                logger.info("YouTube Music 使用訪客模式（未登入 Google 帳號）。")
            except Exception as e:
                logger.error(f"訪客模式初始化失敗: {e}")

        # 嘗試取得使用者個人資訊 (若有登入)
        if self.is_authenticated():
            try:
                # 測試取得個人歌單來確認是否有效
                playlists = self.ytm.get_library_playlists(limit=1)
                self.user_name = "Google 使用者"
            except Exception:
                pass

    def is_authenticated(self) -> bool:
        """是否已成功登入 Google 帳號"""
        return self.auth_mode in ("oauth", "browser", "cookie")

    def search_songs(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """搜尋 YouTube Music 歌曲"""
        try:
            results = self.ytm.search(query, filter="songs", limit=limit)
            cleaned = []
            for item in results:
                video_id = item.get("videoId")
                if not video_id:
                    continue
                artists = ", ".join([a.get("name", "") for a in item.get("artists", [])])
                thumbnails = item.get("thumbnails", [])
                thumb_url = thumbnails[-1]["url"] if thumbnails else ""
                cleaned.append({
                    "id": video_id,
                    "title": item.get("title", "未知曲名"),
                    "artist": artists or "未知藝人",
                    "duration": item.get("duration", "0:00"),
                    "thumbnail": thumb_url,
                    "url": f"https://music.youtube.com/watch?v={video_id}"
                })
            return cleaned
        except Exception as e:
            logger.error(f"搜尋 YouTube Music 失敗: {e}")
            return []

    def get_liked_songs(self, limit: int = 50) -> List[Dict[str, Any]]:
        """取得已按讚的好音樂 (Liked Songs)"""
        if not self.is_authenticated():
            raise PermissionError("請先登入 Google 帳號才能讀取個人『已按讚的歌曲』！")

        try:
            liked = self.ytm.get_liked_songs(limit=limit)
            tracks = liked.get("tracks", [])
            cleaned = []
            for item in tracks:
                video_id = item.get("videoId")
                if not video_id:
                    continue
                artists = ", ".join([a.get("name", "") for a in item.get("artists", [])])
                thumbnails = item.get("thumbnails", [])
                thumb_url = thumbnails[-1]["url"] if thumbnails else ""
                cleaned.append({
                    "id": video_id,
                    "title": item.get("title", "未知曲名"),
                    "artist": artists or "未知藝人",
                    "duration": item.get("duration", "0:00"),
                    "thumbnail": thumb_url,
                    "url": f"https://music.youtube.com/watch?v={video_id}"
                })
            return cleaned
        except Exception as e:
            logger.error(f"取得已按讚歌曲失敗: {e}")
            raise

    def get_user_playlists(self, limit: int = 25) -> List[Dict[str, Any]]:
        """取得使用者的個人播放清單列表"""
        if not self.is_authenticated():
            raise PermissionError("請先登入 Google 帳號才能讀取個人歌單！")

        try:
            playlists = self.ytm.get_library_playlists(limit=limit)
            cleaned = []
            for pl in playlists:
                pl_id = pl.get("playlistId")
                if not pl_id:
                    continue
                thumbnails = pl.get("thumbnails", [])
                thumb_url = thumbnails[-1]["url"] if thumbnails else ""
                cleaned.append({
                    "id": pl_id,
                    "title": pl.get("title", "未命名歌單"),
                    "count": pl.get("count", 0),
                    "thumbnail": thumb_url
                })
            return cleaned
        except Exception as e:
            logger.error(f"取得個人歌單失敗: {e}")
            raise

    def get_playlist_songs(self, playlist_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """取得指定播放清單內的歌曲"""
        try:
            playlist = self.ytm.get_playlist(playlist_id, limit=limit)
            tracks = playlist.get("tracks", [])
            cleaned = []
            for item in tracks:
                video_id = item.get("videoId")
                if not video_id:
                    continue
                artists = ", ".join([a.get("name", "") for a in item.get("artists", [])])
                thumbnails = item.get("thumbnails", [])
                thumb_url = thumbnails[-1]["url"] if thumbnails else ""
                cleaned.append({
                    "id": video_id,
                    "title": item.get("title", "未知曲名"),
                    "artist": artists or "未知藝人",
                    "duration": item.get("duration", "0:00"),
                    "thumbnail": thumb_url,
                    "url": f"https://music.youtube.com/watch?v={video_id}"
                })
            return cleaned
        except Exception as e:
            logger.error(f"取得歌單歌曲失敗: {e}")
            raise

    def get_radio_songs(self, video_id: str) -> List[Dict[str, Any]]:
        """取得基於某首歌的延伸電台歌曲 (Radio)"""
        try:
            watch = self.ytm.get_watch_playlist(videoId=video_id)
            tracks = watch.get("tracks", [])
            cleaned = []
            for item in tracks:
                v_id = item.get("videoId")
                if not v_id:
                    continue
                artists = ", ".join([a.get("name", "") for a in item.get("artists", [])])
                thumbnails = item.get("thumbnails", [])
                thumb_url = thumbnails[-1]["url"] if thumbnails else ""
                cleaned.append({
                    "id": v_id,
                    "title": item.get("title", "未知曲名"),
                    "artist": artists or "未知藝人",
                    "duration": item.get("length", "0:00"),
                    "thumbnail": thumb_url,
                    "url": f"https://music.youtube.com/watch?v={v_id}"
                })
            return cleaned
        except Exception as e:
            logger.error(f"取得電台歌曲失敗: {e}")
            return []

# 單例全域客戶端
ytm_client = YouTubeMusicClient()
