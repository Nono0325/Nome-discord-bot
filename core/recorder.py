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
        
        # 循環緩衝區: {user_id: deque([(timestamp, pcm_bytes), ...])}
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

        # 取得 PCM 數據
        pcm_bytes = b""
        if hasattr(data, "pcm") and data.pcm:
            pcm_bytes = data.pcm
        elif isinstance(data, (bytes, bytearray)):
            pcm_bytes = bytes(data)

        if not pcm_bytes:
            return

        # 1. 存入使用者滾動緩衝區
        if user_id not in self.rolling_buffers:
            self.rolling_buffers[user_id] = deque()

        u_buf = self.rolling_buffers[user_id]
        u_buf.append((now, pcm_bytes))

        # 清除超過緩衝上限（例如 65 秒）的舊封包
        cutoff = now - self.buffer_seconds
        while u_buf and u_buf[0][0] < cutoff:
            u_buf.popleft()

        # 2. 如果正在進行完整會話錄音，同步保存
        if self.is_session_recording:
            self.session_chunks.append((user_id, now, pcm_bytes))

    def get_replay_audio(self, duration_seconds: float = 60.0) -> Tuple[io.BytesIO, List[int]]:
        """
        即時混音並輸出過去指定秒數（預設 60 秒）的對話 MP3
        """
        now = time.time()
        data_snapshot = {
            u_id: list(chunks) for u_id, chunks in self.rolling_buffers.items()
        }
        return AudioMixer.mix_replay_buffer(data_snapshot, duration_seconds, end_time=now)

    async def get_replay_audio_async(self, duration_seconds: float = 60.0) -> Tuple[io.BytesIO, List[int]]:
        """
        [多工處理] 非同步即時混音並輸出過去指定秒數的對話 MP3（不卡 Discord 事件循環）
        """
        now = time.time()
        data_snapshot = {
            u_id: list(chunks) for u_id, chunks in self.rolling_buffers.items()
        }
        return await AudioMixer.mix_replay_buffer_async(data_snapshot, duration_seconds, end_time=now)

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
