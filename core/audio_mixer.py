import io
import time
import asyncio
import logging
import audioop
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Tuple
from pydub import AudioSegment
from config.settings import RECORDINGS_DIR

logger = logging.getLogger(__name__)

# 專屬音訊非同步工作線程池（避免阻塞 Discord asyncio 事件循環）
_AUDIO_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="AudioMixerWorker")

class AudioMixer:
    """
    負責將多位成員的時間軸 PCM 語音片段對齊並混音成完整的 MP3 語音檔案。
    使用極速底層 C 語言音訊混音 (audioop / bytearray)，耗時僅數十毫秒，100% 不卡頓播歌主線程。
    """

    SAMPLE_RATE = 48000
    SAMPLE_WIDTH = 2  # 16-bit
    CHANNELS = 2      # Stereo
    BYTES_PER_SAMPLE = 4  # 16-bit * 2 channels = 4 bytes

    @classmethod
    def mix_replay_buffer(
        cls,
        user_buffers: Dict[int, List[Tuple[float, bytes]]],
        duration_seconds: float = 60.0,
        end_time: float | None = None
    ) -> Tuple[io.BytesIO, List[int]]:
        """
        將過去指定秒數（預設 60 秒）內所有成員的語音對話依時間戳混音為單一 MP3。
        以 C 語言快速疊加音軌，徹底杜絕 Python GIL 阻塞造成音樂卡頓問題。
        """
        if end_time is None:
            end_time = time.time()
        start_time = end_time - duration_seconds
        total_samples = int(duration_seconds * cls.SAMPLE_RATE)
        total_bytes = total_samples * cls.BYTES_PER_SAMPLE

        user_tracks: Dict[int, bytearray] = {}
        active_users: List[int] = []

        for user_id, chunks in user_buffers.items():
            user_buf = bytearray(total_bytes)
            user_has_speech = False

            for chunk_time, pcm_data in chunks:
                if not pcm_data:
                    continue
                # 超出 60 秒時間範圍則略過
                if chunk_time + 0.5 < start_time or chunk_time > end_time:
                    continue

                sample_idx = int((chunk_time - start_time) * cls.SAMPLE_RATE)
                byte_offset = sample_idx * cls.BYTES_PER_SAMPLE

                if byte_offset < 0:
                    pcm_data = pcm_data[-byte_offset:]
                    byte_offset = 0

                if byte_offset >= total_bytes:
                    continue

                write_len = min(len(pcm_data), total_bytes - byte_offset)
                if write_len > 0:
                    user_buf[byte_offset : byte_offset + write_len] = pcm_data[:write_len]
                    if not user_has_speech:
                        try:
                            # 檢查音量是否大於背景靜音 (RMS > 25)
                            if audioop.rms(pcm_data[:write_len], 2) > 25:
                                user_has_speech = True
                        except Exception:
                            user_has_speech = True

            if user_has_speech:
                user_tracks[user_id] = user_buf
                active_users.append(user_id)

        output = io.BytesIO()
        if not user_tracks:
            return output, []

        # 以底層音訊混音函式疊加所有人軌道
        mixed_bytes: bytearray | None = None
        for u_id, u_buf in user_tracks.items():
            if mixed_bytes is None:
                mixed_bytes = bytearray(u_buf)
            else:
                mixed_bytes = audioop.add(mixed_bytes, u_buf, 2)

        seg = AudioSegment(
            data=bytes(mixed_bytes),
            sample_width=cls.SAMPLE_WIDTH,
            frame_rate=cls.SAMPLE_RATE,
            channels=cls.CHANNELS
        )
        seg.export(output, format="mp3", bitrate="192k")
        output.seek(0)
        return output, active_users

    @classmethod
    async def mix_replay_buffer_async(
        cls,
        user_buffers: Dict[int, List[Tuple[float, bytes]]],
        duration_seconds: float = 60.0,
        end_time: float | None = None
    ) -> Tuple[io.BytesIO, List[int]]:
        """
        [多工處理] 在背景線程池中執行混音，保證語音與音樂播放 100% 順暢不卡頓。
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            _AUDIO_EXECUTOR,
            cls.mix_replay_buffer,
            user_buffers,
            duration_seconds,
            end_time
        )

    @classmethod
    def mix_full_session(
        cls,
        session_chunks: List[Tuple[int, float, bytes]],
        session_start: float,
        session_end: float,
        output_filename: str
    ) -> str:
        """
        將完整錄音會議的所有成員片段對齊時間戳並輸出至磁碟 MP3 檔案。
        """
        total_seconds = max(1.0, session_end - session_start)
        total_samples = int(total_seconds * cls.SAMPLE_RATE)
        total_bytes = total_samples * cls.BYTES_PER_SAMPLE

        # 依使用者群組
        user_data: Dict[int, bytearray] = {}
        for user_id, chunk_time, pcm_data in session_chunks:
            if not pcm_data:
                continue
            if user_id not in user_data:
                user_data[user_id] = bytearray(total_bytes)

            sample_idx = int((chunk_time - session_start) * cls.SAMPLE_RATE)
            byte_offset = sample_idx * cls.BYTES_PER_SAMPLE

            if byte_offset < 0:
                pcm_data = pcm_data[-byte_offset:]
                byte_offset = 0

            if byte_offset >= total_bytes:
                continue

            write_len = min(len(pcm_data), total_bytes - byte_offset)
            if write_len > 0:
                user_data[user_id][byte_offset : byte_offset + write_len] = pcm_data[:write_len]

        if not user_data:
            return ""

        mixed_bytes: bytearray | None = None
        for u_id, u_buf in user_data.items():
            if mixed_bytes is None:
                mixed_bytes = bytearray(u_buf)
            else:
                mixed_bytes = audioop.add(mixed_bytes, u_buf, 2)

        output_path = RECORDINGS_DIR / output_filename
        seg = AudioSegment(
            data=bytes(mixed_bytes),
            sample_width=cls.SAMPLE_WIDTH,
            frame_rate=cls.SAMPLE_RATE,
            channels=cls.CHANNELS
        )
        seg.export(str(output_path), format="mp3", bitrate="192k")
        return str(output_path)

    @classmethod
    async def mix_full_session_async(
        cls,
        session_chunks: List[Tuple[int, float, bytes]],
        session_start: float,
        session_end: float,
        output_filename: str
    ) -> str:
        """
        [多工處理] 在背景線程池中輸出完整錄音檔案。
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            _AUDIO_EXECUTOR,
            cls.mix_full_session,
            session_chunks,
            session_start,
            session_end,
            output_filename
        )
