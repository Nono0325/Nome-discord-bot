import io
import time
import logging
from collections import deque
from typing import Dict, List, Tuple
import discord
from discord.sinks import Sink, Filters, default_filters
from core.audio_mixer import AudioMixer

logger = logging.getLogger(__name__)

class RollingBufferSink(Sink):
    """
    自訂語音接收器：
    1. 維護最近 60 秒的循環緩衝區（Rolling Buffer），供隨時擷取前一分鐘對話。
    2. 支援全場自動錄音並存檔。
    """
    __sink_listeners__ = ()

    def __init__(self, buffer_seconds: float = 65.0, auto_record: bool = False, vc=None, *, filters=None):
        super().__init__(filters=filters)
        self.vc = vc
        self.encoding = "pcm"
        self.buffer_seconds = buffer_seconds
        
        # 循環緩衝區: 存放時間、使用者 ID 與原始 PCM 語音資料
        self.rolling_stream: deque[Tuple[float, int, bytes]] = deque()
        self.rolling_buffers: Dict[int, deque[Tuple[float, bytes]]] = {}
        
        # 完整錄音會話
        self.is_session_recording = auto_record
        self.session_chunks: List[Tuple[int, float, bytes]] = []
        self.session_start_time = time.time()
        self.session_end_time: float | None = None

    def init(self, vc):
        self.vc = vc
        try:
            super().init(vc)
        except Exception:
            pass

    def is_opus(self) -> bool:
        return False

    def walk_children(self):
        return ()

    def format_audio(self, audio):
        pass

    def write(self, data, user):
        """
        接收到語音封包回呼函式
        """
        now = time.time()
        
        # 取得使用者 ID
        user_id = 0
        if user and hasattr(user, "id"):
            user_id = user.id
        elif isinstance(user, int) and user != 0:
            user_id = user
        elif hasattr(data, "source") and data.source and hasattr(data.source, "id"):
            user_id = data.source.id
        elif hasattr(data, "packet") and hasattr(data.packet, "ssrc"):
            ssrc = data.packet.ssrc
            if self.vc and hasattr(self.vc, "_connection") and hasattr(self.vc._connection, "ssrc_user_map"):
                user_id = self.vc._connection.ssrc_user_map.get(ssrc, 0)
            if not user_id and self.vc and hasattr(self.vc, "_ssrc_to_id"):
                user_id = self.vc._ssrc_to_id.get(ssrc, 0)
            if not user_id:
                user_id = ssrc

        if not user_id:
            user_id = 1  # 預設非零標識，避免因未解析成員而丟失語音封包

        # 排除機器人自身的音樂發送封包，確保錄到的是「頻道裡大家的語音對話」
        bot_user_id = self.vc.user.id if (self.vc and hasattr(self.vc, "user") and self.vc.user) else None
        if bot_user_id and user_id == bot_user_id:
            return

        # 取得 PCM 數據
        pcm_bytes = b""
        if hasattr(data, "pcm") and data.pcm:
            pcm_bytes = data.pcm
        elif isinstance(data, (bytes, bytearray)):
            pcm_bytes = bytes(data)

        if not pcm_bytes:
            return

        # 1. 存入統一時間軸直通循環串流 (Direct Chronological Stream)
        self.rolling_stream.append((now, user_id, pcm_bytes))
        cutoff = now - self.buffer_seconds
        while self.rolling_stream and self.rolling_stream[0][0] < cutoff:
            self.rolling_stream.popleft()

        # 2. 如果正在進行完整會話錄音，同步保存
        if self.is_session_recording:
            self.session_chunks.append((user_id, now, pcm_bytes))

    def _extract_recent_stream(self, duration_seconds: float) -> Tuple[List[Tuple[float, int, bytes]], float]:
        """
        從循環串流中擷取最近秒數的有效語音片段，並解析 SSRC 為真實成員 ID
        """
        now = time.time()
        start_time = now - duration_seconds
        bot_id = self.vc.user.id if (self.vc and hasattr(self.vc, "user") and self.vc.user) else None

        valid_chunks: List[Tuple[float, int, bytes]] = []
        for c_time, uid, pcm in list(self.rolling_stream):
            if c_time >= start_time and pcm:
                target_id = uid
                if uid < 1000000000000 and self.vc:
                    resolved_id = None
                    if hasattr(self.vc, "_connection") and hasattr(self.vc._connection, "ssrc_user_map"):
                        resolved_id = self.vc._connection.ssrc_user_map.get(uid)
                    if not resolved_id and hasattr(self.vc, "_ssrc_to_id"):
                        resolved_id = self.vc._ssrc_to_id.get(uid)
                    if resolved_id:
                        target_id = resolved_id

                if bot_id and target_id == bot_id:
                    continue
                valid_chunks.append((c_time, target_id, pcm))

        return valid_chunks, now

    def get_replay_audio(self, duration_seconds: float = 60.0) -> Tuple[io.BytesIO, List[int]]:
        """
        即時直通輸出過去指定秒數（預設 60 秒）的大家對話 MP3（不混音，100% 完整保留所有字詞）
        """
        chunks, now = self._extract_recent_stream(duration_seconds)
        return AudioMixer.mix_replay_buffer(chunks, duration_seconds, end_time=now)

    async def get_replay_audio_async(self, duration_seconds: float = 60.0) -> Tuple[io.BytesIO, List[int]]:
        """
        [多工處理] 非同步即時直通輸出過去指定秒數的對話 MP3（不卡死 Discord 播歌循環）
        """
        chunks, now = self._extract_recent_stream(duration_seconds)
        return await AudioMixer.mix_replay_buffer_async(chunks, duration_seconds, end_time=now)

    def start_session_recording(self):
        """
        開始完整會話錄音
        """
        self.session_chunks.clear()
        self.session_start_time = time.time()
        self.is_session_recording = True
        logger.info("已開始完整錄音會話。")

    def stop_session_recording(self, filename: str | None = None) -> str | None:
        """
        停止會話錄音並輸出為 MP3 檔案
        """
        if not self.is_session_recording or not self.session_chunks:
            self.is_session_recording = False
            return None

        self.session_end_time = time.time()
        self.is_session_recording = False

        if not filename:
            timestr = time.strftime("%Y%m%d_%H%M%S")
            filename = f"record_{timestr}.mp3"

        out_path = AudioMixer.mix_full_session(
            self.session_chunks,
            self.session_start_time,
            self.session_end_time,
            filename
        )
        self.session_chunks.clear()
        logger.info(f"完整錄音會話已儲存至: {out_path}")
        return out_path

    async def stop_session_recording_async(self, filename: str | None = None) -> str | None:
        """
        [多工處理] 非同步停止會話錄音並輸出為 MP3 檔案
        """
        if not self.is_session_recording or not self.session_chunks:
            self.is_session_recording = False
            return None

        self.session_end_time = time.time()
        self.is_session_recording = False

        if not filename:
            timestr = time.strftime("%Y%m%d_%H%M%S")
            filename = f"record_{timestr}.mp3"

        snapshot_chunks = list(self.session_chunks)
        self.session_chunks.clear()

        out_path = await AudioMixer.mix_full_session_async(
            snapshot_chunks,
            self.session_start_time,
            self.session_end_time,
            filename
        )
        logger.info(f"完整錄音會話已非同步儲存至: {out_path}")
        return out_path

    def cleanup(self):
        """
        清理錄音器
        """
        self.finished = True
        if self.is_session_recording:
            try:
                self.stop_session_recording()
            except Exception as e:
                logger.error(f"清理錄音緩衝區時發生錯誤: {e}")
