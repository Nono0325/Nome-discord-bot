import os
import sys
import time
import json
import asyncio
import logging
from pathlib import Path
from typing import Optional, Any

from aiohttp import web
import discord

from config.settings import (
    BASE_DIR,
    LOG_FILE_PATH,
    RECORDINGS_DIR,
    DASHBOARD_HOST,
    DASHBOARD_PORT,
    AUTO_RECORD,
    REPLAY_BUFFER_SECONDS,
)

logger = logging.getLogger("Dashboard")

STATIC_DIR = BASE_DIR / "dashboard" / "static"
START_TIME = time.time()

_RUNNER: Optional[web.AppRunner] = None
_SITE: Optional[web.TCPSite] = None


def parse_duration_to_seconds(val: Any) -> float:
    """將時長 (秒數或 'MM:SS' / 'HH:MM:SS') 轉為浮點數秒數"""
    if not val:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        if val == "直播中":
            return 0.0
        parts = val.strip().split(":")
        try:
            if len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
            elif len(parts) == 2:
                return int(parts[0]) * 60 + float(parts[1])
            return float(val)
        except Exception:
            return 0.0
    return 0.0


def format_seconds(seconds: Any) -> str:
    """將秒數或時間字串格式化為 HH:MM:SS 或 MM:SS"""
    if seconds is None or seconds == "":
        return "00:00"
    if isinstance(seconds, str):
        if ":" in seconds:
            return seconds
        try:
            seconds = float(seconds)
        except ValueError:
            return seconds
    try:
        s = int(seconds)
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"
    except Exception:
        return str(seconds)


def get_system_metrics() -> dict:
    """獲取基本系統與進程指標"""
    import threading
    threads_count = threading.active_count()
    
    # 嘗試讀取進程記憶體
    mem_mb = 0.0
    try:
        import psutil
        process = psutil.Process()
        mem_mb = round(process.memory_info().rss / (1024 * 1024), 1)
    except Exception:
        pass

    # Windows 64-bit ctypes 原生呼叫 Fallback (若 psutil 未安裝或異常)
    if mem_mb <= 0.0 and sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                    ("PrivateUsage", ctypes.c_size_t),
                ]
            kernel32 = ctypes.windll.kernel32
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            kernel32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESS_MEMORY_COUNTERS_EX), wintypes.DWORD]
            kernel32.K32GetProcessMemoryInfo.restype = wintypes.BOOL
            
            counters = PROCESS_MEMORY_COUNTERS_EX()
            counters.cb = ctypes.sizeof(counters)
            if kernel32.K32GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), ctypes.sizeof(counters)):
                mem_mb = round(counters.WorkingSetSize / (1024 * 1024), 1)
        except Exception:
            pass

    if mem_mb <= 0.0:
        mem_mb = 64.0

    uptime_sec = round(time.time() - START_TIME)
    return {
        "threads": threads_count,
        "memory_mb": mem_mb,
        "uptime_seconds": uptime_sec,
        "uptime_str": format_seconds(uptime_sec),
        "python_version": sys.version.split()[0],
        "platform": sys.platform
    }


def create_dashboard_app(bot: discord.Bot) -> web.Application:
    """建立 aiohttp Web 控制台應用程序"""
    app = web.Application()

    # -------------------------------------------------------------
    # 靜態首頁與靜態資源
    # -------------------------------------------------------------
    async def index(request: web.Request):
        index_file = STATIC_DIR / "index.html"
        if index_file.exists():
            return web.FileResponse(index_file)
        return web.Response(text="Dashboard index.html not found", status=404)

    async def static_file(request: web.Request):
        filename = request.match_info.get("filename", "")
        file_path = STATIC_DIR / filename
        if file_path.exists() and file_path.is_file():
            return web.FileResponse(file_path)
        return web.Response(text="File not found", status=404)

    # -------------------------------------------------------------
    # API 1: 全域狀態與儀表板總覽
    # -------------------------------------------------------------
    async def api_status(request: web.Request):
        latency_ms = round(bot.latency * 1000, 1) if bot.latency is not None and not (bot.latency != bot.latency) else 0.0
        active_voice = len([vc for vc in bot.voice_clients if vc.is_connected()])
        
        bot_user = {
            "name": bot.user.name if bot.user else "Discord Bot",
            "discriminator": bot.user.discriminator if bot.user else "0000",
            "id": bot.user.id if bot.user else 0,
            "avatar": bot.user.display_avatar.url if bot.user and hasattr(bot.user, "display_avatar") else None,
        }

        # 彙整當前正在播歌之伺服器摘要
        playing_guilds = []
        if hasattr(bot, "voice_manager"):
            for gid, player in bot.voice_manager.players.items():
                if player.is_playing or player.is_paused:
                    guild = bot.get_guild(gid)
                    playing_guilds.append({
                        "guild_id": str(gid),
                        "guild_name": guild.name if guild else str(gid),
                        "title": player.current.title if player.current else "",
                        "is_paused": player.is_paused,
                        "duration": str(player.current.duration) if player.current else "00:00"
                    })

        data = {
            "online": bot.is_ready(),
            "bot": bot_user,
            "latency_ms": latency_ms,
            "guilds_count": len(bot.guilds),
            "voice_clients_count": active_voice,
            "playing_count": len(playing_guilds),
            "playing_guilds": playing_guilds,
            "system": get_system_metrics(),
            "config": {
                "auto_record": getattr(bot.voice_manager, "auto_record", AUTO_RECORD) if hasattr(bot, "voice_manager") else AUTO_RECORD,
                "replay_buffer_seconds": REPLAY_BUFFER_SECONDS
            }
        }
        return web.json_response(data)

    # -------------------------------------------------------------
    # API 2: 伺服器清單與頻道列表
    # -------------------------------------------------------------
    async def api_guilds(request: web.Request):
        guilds_data = []
        for g in bot.guilds:
            vc = g.voice_client
            voice_connected = vc is not None and vc.is_connected()
            voice_ch = vc.channel.name if (voice_connected and vc.channel) else None
            voice_ch_id = str(vc.channel.id) if (voice_connected and vc.channel) else None

            # 語音頻道清單
            v_channels = [
                {"id": str(ch.id), "name": ch.name, "members": len(ch.members)}
                for ch in g.voice_channels
            ]
            # 文字頻道清單
            t_channels = [
                {"id": str(ch.id), "name": ch.name}
                for ch in g.text_channels
            ]

            guilds_data.append({
                "id": str(g.id),
                "name": g.name,
                "icon": g.icon.url if g.icon else None,
                "member_count": g.member_count,
                "voice_connected": voice_connected,
                "current_voice_channel": voice_ch,
                "current_voice_channel_id": voice_ch_id,
                "voice_channels": v_channels,
                "text_channels": t_channels,
            })
        return web.json_response(guilds_data)

    # -------------------------------------------------------------
    # API 3: 音樂播放器狀態
    # -------------------------------------------------------------
    async def api_get_player(request: web.Request):
        gid_str = request.match_info.get("guild_id", "")
        if not gid_str.isdigit():
            return web.json_response({"error": "Invalid guild ID"}, status=400)
        gid = int(gid_str)

        if not hasattr(bot, "voice_manager"):
            return web.json_response({"error": "VoiceManager unavailable"}, status=500)

        guild = bot.get_guild(gid)
        vc = guild.voice_client if guild else None
        player = bot.voice_manager.players.get(gid)

        if not player or not vc:
            return web.json_response({
                "connected": False,
                "is_playing": False,
                "is_paused": False,
                "current": None,
                "queue": [],
                "volume": 100,
                "loop_mode": "off",
                "autoplay": False,
                "bitrate": 128
            })

        current_data = None
        if player.current:
            raw_duration = player.current.duration or "00:00"
            duration_sec = parse_duration_to_seconds(raw_duration)
            position = getattr(player, "elapsed_seconds", getattr(player, "current_position", 0.0)) or 0.0
            progress = round((position / duration_sec * 100) if duration_sec > 0 else 0, 1)
            current_data = {
                "title": player.current.title,
                "artist": player.current.artist,
                "duration": duration_sec,
                "duration_str": str(raw_duration),
                "position": round(position, 1),
                "position_str": format_seconds(position),
                "progress_percent": min(100.0, max(0.0, progress)),
                "thumbnail": player.current.thumbnail,
                "url": player.current.webpage_url,
                "requester": player.current.requester,
            }

        queue_data = [
            {
                "index": i + 1,
                "title": s.title,
                "artist": s.artist,
                "duration": parse_duration_to_seconds(s.duration),
                "duration_str": str(s.duration or "00:00"),
                "thumbnail": s.thumbnail,
                "url": s.webpage_url,
                "requester": s.requester,
            }
            for i, s in enumerate(player.queue_list)
        ]

        return web.json_response({
            "connected": vc.is_connected(),
            "channel_name": vc.channel.name if vc.channel else None,
            "channel_id": str(vc.channel.id) if vc.channel else None,
            "is_playing": player.is_playing,
            "is_paused": player.is_paused,
            "volume": int(player.volume * 100),
            "loop_mode": player.loop_mode,
            "autoplay": player.autoplay,
            "bitrate": getattr(player, "current_bitrate", 128),
            "current": current_data,
            "queue": queue_data,
            "queue_count": len(queue_data),
        })

    # -------------------------------------------------------------
    # API 4: 音樂播控指令
    # -------------------------------------------------------------
    async def api_player_action(request: web.Request):
        gid_str = request.match_info.get("guild_id", "")
        if not gid_str.isdigit():
            return web.json_response({"error": "Invalid guild ID"}, status=400)
        gid = int(gid_str)

        try:
            body = await request.json()
        except Exception:
            body = {}

        action = body.get("action", "")
        player = bot.voice_manager.get_player(gid) if hasattr(bot, "voice_manager") else None
        guild = bot.get_guild(gid)
        vc = guild.voice_client if guild else None

        if not player or not vc:
            return web.json_response({"error": "機器人目前未在該伺服器的語音頻道連線中"}, status=400)

        res = {"success": True, "action": action}

        if action == "play":
            query = body.get("query", "").strip()
            if not query:
                return web.json_response({"error": "請提供歌曲名稱或網址"}, status=400)
            from music.ytdl_source import YTDLSource, Song
            from music.ytm_client import ytm_client
            try:
                # 判斷是否為直接網址
                if query.startswith("http://") or query.startswith("https://"):
                    song_item = await YTDLSource.from_query(query, requester="控制台網頁操作")
                    songs = [song_item] if song_item else []
                else:
                    # 優先使用 YouTube Music 搜尋最佳曲目
                    results = await asyncio.to_thread(ytm_client.search_songs, query, 5)
                    if results:
                        top = results[0]
                        song_item = Song(
                            id=top["id"],
                            title=top["title"],
                            artist=top["artist"],
                            duration=top["duration"],
                            thumbnail=top["thumbnail"],
                            webpage_url=top["url"],
                            requester="控制台網頁操作"
                        )
                        songs = [song_item]
                    else:
                        song_item = await YTDLSource.from_query(query, requester="控制台網頁操作")
                        songs = [song_item] if song_item else []

                if not songs:
                    return web.json_response({"error": "找不到任何符合的歌曲或影片，請更換關鍵字"}, status=404)

                for s in songs:
                    await player.add_song(s)
                res["added_count"] = len(songs)
                res["first_song"] = songs[0].title if songs else None
            except Exception as e:
                logger.exception("Dashboard play error")
                return web.json_response({"error": f"載入歌曲失敗: {e}"}, status=500)

        elif action == "pause":
            player.pause()
        elif action == "resume":
            player.resume()
        elif action == "skip":
            player.skip()
        elif action == "stop":
            player.stop()
        elif action == "shuffle":
            shuffled_count = player.shuffle()
            res["count"] = shuffled_count
        elif action == "volume":
            vol = int(body.get("volume", 100))
            player.set_volume(max(0, min(100, vol)) / 100.0)
            res["volume"] = int(player.volume * 100)
        elif action == "loop":
            mode = body.get("mode", "off")
            if mode in ("off", "song", "queue"):
                player.loop_mode = mode
            res["loop_mode"] = player.loop_mode
        elif action == "autoplay":
            enabled = bool(body.get("enabled", not player.autoplay))
            player.autoplay = enabled
            res["autoplay"] = player.autoplay
        elif action == "seek":
            pos = float(body.get("position", 0))
            success = player.seek(pos)
            res["seek_success"] = success
        elif action == "remove_queue":
            idx = int(body.get("index", -1))
            if 0 <= idx < len(player.queue_list):
                removed = player.queue_list.pop(idx)
                # 重新填充 asyncio.Queue
                while not player.queue.empty():
                    try:
                        player.queue.get_nowait()
                    except Exception:
                        break
                for s in player.queue_list:
                    player.queue.put_nowait(s)
                res["removed"] = removed.title
            else:
                return web.json_response({"error": "無效的隊列索引"}, status=400)
        else:
            return web.json_response({"error": f"Unknown action: {action}"}, status=400)

        return web.json_response(res)

    # -------------------------------------------------------------
    # API 5: 語音連線控制 (加入/離開)
    # -------------------------------------------------------------
    async def api_voice_action(request: web.Request):
        gid_str = request.match_info.get("guild_id", "")
        if not gid_str.isdigit():
            return web.json_response({"error": "Invalid guild ID"}, status=400)
        gid = int(gid_str)

        try:
            body = await request.json()
        except Exception:
            body = {}

        action = body.get("action", "")
        guild = bot.get_guild(gid)
        if not guild:
            return web.json_response({"error": "Guild not found"}, status=404)

        if action == "join":
            channel_id_str = body.get("channel_id", "")
            if not channel_id_str.isdigit():
                return web.json_response({"error": "請選擇語音頻道"}, status=400)
            ch = guild.get_channel(int(channel_id_str))
            if not ch or not isinstance(ch, discord.VoiceChannel):
                return web.json_response({"error": "語音頻道不存在"}, status=404)
            try:
                await bot.voice_manager.connect_voice(ch, manual=True)
                return web.json_response({"success": True, "channel_name": ch.name})
            except Exception as e:
                return web.json_response({"error": f"連線失敗: {e}"}, status=500)

        elif action == "leave":
            try:
                await bot.voice_manager.disconnect_voice(gid)
                return web.json_response({"success": True})
            except Exception as e:
                return web.json_response({"error": f"中斷連線失敗: {e}"}, status=500)

        return web.json_response({"error": f"Unknown action: {action}"}, status=400)

    # -------------------------------------------------------------
    # API 6: 語音錄音與發言狀態
    # -------------------------------------------------------------
    async def api_recording_status(request: web.Request):
        gid_str = request.match_info.get("guild_id", "")
        if not gid_str.isdigit():
            return web.json_response({"error": "Invalid guild ID"}, status=400)
        gid = int(gid_str)

        guild = bot.get_guild(gid)
        vc = guild.voice_client if guild else None
        sink = bot.voice_manager.get_sink(gid) if hasattr(bot, "voice_manager") else None

        if not sink or not vc or not vc.is_connected():
            return web.json_response({
                "active": False,
                "is_recording": False,
                "is_session_recording": False,
                "buffer_seconds": REPLAY_BUFFER_SECONDS,
                "speakers_in_60s": [],
                "rolling_chunks_count": 0,
            })

        # 檢查過去 60 秒發言人員
        now = time.time()
        active_uids = set()
        for c_time, uid, _ in list(sink.rolling_stream):
            if now - c_time < 60.0 and uid:
                active_uids.add(uid)

        speakers = []
        for uid in active_uids:
            name = f"成員 ({uid})"
            avatar = None
            if uid > 1000000000000:
                m = guild.get_member(uid) if guild else None
                if not m:
                    m = bot.get_user(uid)
                if m:
                    name = m.display_name
                    avatar = m.display_avatar.url if hasattr(m, "display_avatar") else None
            speakers.append({"id": str(uid), "name": name, "avatar": avatar})

        return web.json_response({
            "active": True,
            "is_recording": vc.is_recording(),
            "is_session_recording": sink.is_session_recording,
            "buffer_seconds": sink.buffer_seconds,
            "rolling_chunks_count": len(sink.rolling_stream),
            "session_chunks_count": len(sink.session_chunks),
            "speakers_in_60s": speakers,
        })

    # -------------------------------------------------------------
    # API 7: 一鍵剪輯回放並直接輸出 MP3 二進位資料
    # -------------------------------------------------------------
    async def api_make_clip(request: web.Request):
        gid_str = request.match_info.get("guild_id", "")
        if not gid_str.isdigit():
            return web.json_response({"error": "Invalid guild ID"}, status=400)
        gid = int(gid_str)

        sink = bot.voice_manager.get_sink(gid) if hasattr(bot, "voice_manager") else None
        if not sink:
            return web.json_response({"error": "目前該伺服器未在錄音狀態"}, status=400)

        try:
            body = await request.json()
        except Exception:
            body = {}

        seconds = max(5, min(180, int(body.get("seconds", 60))))
        try:
            mp3_buf, active_uids = await sink.get_replay_audio_async(duration_seconds=float(seconds))
            data = mp3_buf.getvalue()
            if not data or len(data) < 1000:
                return web.json_response({"error": f"過去 {seconds} 秒內未偵測到有效發言語音"}, status=404)

            timestr = time.strftime("%Y%m%d_%H%M%S")
            filename = f"clip_{seconds}s_{timestr}.mp3"
            return web.Response(
                body=data,
                content_type="audio/mpeg",
                headers={
                    "Content-Disposition": f'inline; filename="{filename}"',
                    "X-Clip-Filename": filename,
                    "X-Clip-Size": str(len(data))
                }
            )
        except Exception as e:
            logger.error(f"網頁控制台剪輯例外: {e}")
            return web.json_response({"error": f"剪輯失敗: {e}"}, status=500)

    # -------------------------------------------------------------
    # API 8: 歷史錄音檔清單與管理
    # -------------------------------------------------------------
    async def api_recordings_list(request: web.Request):
        files = []
        if RECORDINGS_DIR.exists():
            for p in sorted(RECORDINGS_DIR.glob("*.mp3"), key=lambda x: x.stat().st_mtime, reverse=True):
                stat = p.stat()
                files.append({
                    "filename": p.name,
                    "size_bytes": stat.st_size,
                    "size_mb": round(stat.st_size / (1024 * 1024), 2),
                    "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
                    "url": f"/api/recordings/{p.name}"
                })
        return web.json_response(files)

    async def api_recordings_file(request: web.Request):
        filename = request.match_info.get("filename", "")
        # 防路徑穿越攻擊 (Path Traversal Protection)
        safe_name = os.path.basename(filename)
        file_path = RECORDINGS_DIR / safe_name
        if file_path.exists() and file_path.is_file():
            return web.FileResponse(
                file_path,
                headers={"Content-Disposition": f'inline; filename="{safe_name}"'}
            )
        return web.Response(text="Recording file not found", status=404)

    async def api_recordings_delete(request: web.Request):
        filename = request.match_info.get("filename", "")
        safe_name = os.path.basename(filename)
        file_path = RECORDINGS_DIR / safe_name
        if file_path.exists() and file_path.is_file():
            try:
                os.remove(file_path)
                return web.json_response({"success": True, "deleted": safe_name})
            except Exception as e:
                return web.json_response({"error": f"刪除失敗: {e}"}, status=500)
        return web.Response(text="Recording file not found", status=404)

    # -------------------------------------------------------------
    # API 9: 即時日誌讀取與 SSE 串流
    # -------------------------------------------------------------
    async def api_logs_tail(request: web.Request):
        lines_count = int(request.query.get("lines", 100))
        lines_count = max(10, min(500, lines_count))

        if not LOG_FILE_PATH.exists():
            return web.json_response({"lines": ["(日誌檔案尚未產生)"]})

        try:
            with open(LOG_FILE_PATH, "r", encoding="utf-8", errors="replace") as f:
                all_lines = f.readlines()
            tail_lines = all_lines[-lines_count:] if len(all_lines) > lines_count else all_lines
            return web.json_response({"lines": [line.rstrip("\r\n") for line in tail_lines]})
        except Exception as e:
            return web.json_response({"error": f"讀取日誌失敗: {e}"}, status=500)

    async def api_logs_stream(request: web.Request):
        """Server-Sent Events (SSE) 即時日誌串流"""
        response = web.StreamResponse(
            status=200,
            reason="OK",
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
            }
        )
        await response.prepare(request)

        # 1. 先發送最後 40 行
        if LOG_FILE_PATH.exists():
            try:
                with open(LOG_FILE_PATH, "r", encoding="utf-8", errors="replace") as f:
                    initial_lines = f.readlines()[-40:]
                for line in initial_lines:
                    msg = f"data: {json.dumps(line.rstrip())}\n\n"
                    await response.write(msg.encode("utf-8"))
            except Exception:
                pass

        # 2. 定期檢查檔案尾端追加的全新行
        last_pos = LOG_FILE_PATH.stat().st_size if LOG_FILE_PATH.exists() else 0
        try:
            while True:
                await asyncio.sleep(1.0)
                if LOG_FILE_PATH.exists():
                    curr_size = LOG_FILE_PATH.stat().st_size
                    if curr_size > last_pos:
                        with open(LOG_FILE_PATH, "r", encoding="utf-8", errors="replace") as f:
                            f.seek(last_pos)
                            new_text = f.read()
                            last_pos = f.tell()
                        for line in new_text.splitlines():
                            if line.strip():
                                msg = f"data: {json.dumps(line)}\n\n"
                                await response.write(msg.encode("utf-8"))
                    elif curr_size < last_pos:
                        # 日誌檔案輪轉清空
                        last_pos = 0
        except (asyncio.CancelledError, ConnectionResetError):
            pass

        return response

    # -------------------------------------------------------------
    # API 10: 機器人維護動作 (熱重載/重啟)
    # -------------------------------------------------------------
    async def api_bot_action(request: web.Request):
        try:
            body = await request.json()
        except Exception:
            body = {}

        action = body.get("action", "")
        if action == "reload":
            # 觸發熱重載所有模組
            reloaded = []
            cogs = [
                "cogs.music_cog",
                "cogs.record_cog",
                "cogs.channel_cog",
                "cogs.auth_cog",
                "cogs.admin_cog",
                "cogs.book_cog",
                "cogs.panel_cog",
            ]
            for c in cogs:
                try:
                    bot.reload_extension(c)
                    reloaded.append(c)
                except Exception as e:
                    logger.warning(f"熱重載模組 {c} 失敗: {e}")
            return web.json_response({"success": True, "reloaded": reloaded})

        elif action == "restart":
            # 啟動完全重啟
            try:
                from cogs.admin_cog import execute_bot_restart
                bot.loop.create_task(execute_bot_restart(bot))
                return web.json_response({"success": True, "message": "機器人進程正在重新啟動中..."})
            except Exception as e:
                return web.json_response({"error": f"觸發重啟失敗: {e}"}, status=500)

        return web.json_response({"error": f"Unknown action: {action}"}, status=400)

    # 註冊所有路由
    app.router.add_get("/", index)
    app.router.add_get("/api/status", api_status)
    app.router.add_get("/api/guilds", api_guilds)
    app.router.add_get("/api/player/{guild_id}", api_get_player)
    app.router.add_post("/api/player/{guild_id}/action", api_player_action)
    app.router.add_post("/api/voice/{guild_id}/action", api_voice_action)
    app.router.add_get("/api/recording/{guild_id}/status", api_recording_status)
    app.router.add_post("/api/recording/{guild_id}/clip", api_make_clip)
    app.router.add_get("/api/recordings", api_recordings_list)
    app.router.add_get("/api/recordings/{filename}", api_recordings_file)
    app.router.add_delete("/api/recordings/{filename}", api_recordings_delete)
    app.router.add_get("/api/logs", api_logs_tail)
    app.router.add_get("/api/logs/stream", api_logs_stream)
    app.router.add_post("/api/bot/action", api_bot_action)

    # 靜態資源路由
    app.router.add_get("/{filename:.*}", static_file)

    return app


async def start_dashboard(bot: discord.Bot) -> Optional[web.AppRunner]:
    """啟動非同步 Web 控制台伺服器"""
    global _RUNNER, _SITE
    try:
        app = create_dashboard_app(bot)
        _RUNNER = web.AppRunner(app)
        await _RUNNER.setup()
        _SITE = web.TCPSite(_RUNNER, DASHBOARD_HOST, DASHBOARD_PORT)
        await _SITE.start()
        
        display_host = "localhost" if DASHBOARD_HOST in ("0.0.0.0", "127.0.0.1") else DASHBOARD_HOST
        logger.info(f"✨ 機器人控制與監控台 (Web Dashboard) 已啟動！")
        logger.info(f"🌐 本機訪問網址: http://{display_host}:{DASHBOARD_PORT}")
        return _RUNNER
    except Exception as e:
        logger.error(f"啟動 Web 控制台伺服器失敗: {e}", exc_info=True)
        return None


async def stop_dashboard():
    """優雅關閉 Web 控制台伺服器"""
    global _RUNNER, _SITE
    if _SITE:
        try:
            await _SITE.stop()
        except Exception:
            pass
        _SITE = None
    if _RUNNER:
        try:
            await _RUNNER.cleanup()
        except Exception:
            pass
        _RUNNER = None
    logger.info("Web 控制台伺服器已安全停止。")
