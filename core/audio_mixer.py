import io
import time
import asyncio
import logging
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
    具備多工非同步 (Async Worker) 支援，混音不卡死主執行緒。
    """

    SAMPLE_RATE = 48000
    SAMPLE_WIDTH = 2  # 16-bit
    CHANNELS = 2      # Stereo

    @classmethod
    def mix_replay_buffer(
        cls,
        user_buffers: Dict[int, List[Tuple[float, bytes]]],
        duration_seconds: float = 60.0,
        end_time: float | None = None
    ) -> Tuple[io.BytesIO, List[int]]:
        """
        將過去指定秒數（預設 60 秒）內所有成員的語音對話依時間戳混音為單一 MP3（同步底層）。
        """
        if end_time is None:
            end_time = time.time()
        start_time = end_time - duration_seconds
        duration_ms = int(duration_seconds * 1000)

        canvas = AudioSegment.silent(duration=duration_ms, frame_rate=cls.SAMPLE_RATE)
        active_users: List[int] = []

        for user_id, chunks in user_buffers.items():
            user_has_speech = False
            for chunk_time, pcm_data in chunks:
                if chunk_time + 1.0 < start_time or chunk_time > end_time:
                    continue

                if not pcm_data:
                    continue

                try:
                    seg = AudioSegment(
                        data=pcm_data,
                        sample_width=cls.SAMPLE_WIDTH,
                        frame_rate=cls.SAMPLE_RATE,
                        channels=cls.CHANNELS
                    )
                    offset_ms = int((chunk_time - start_time) * 1000)
                    offset_ms = max(0, min(offset_ms, duration_ms - len(seg)))
                    canvas = canvas.overlay(seg, position=offset_ms)
                    user_has_speech = True
                except Exception as e:
                    logger.debug(f"處理使用者 {user_id} 音訊片段時發生錯誤: {e}")

            if user_has_speech:
                active_users.append(user_id)

        output = io.BytesIO()
        canvas.export(output, format="mp3", bitrate="192k")
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
        total_ms = int(total_seconds * 1000)

        canvas = AudioSegment.silent(duration=total_ms, frame_rate=cls.SAMPLE_RATE)

        for user_id, chunk_time, pcm_data in session_chunks:
            if not pcm_data:
                continue
            try:
                seg = AudioSegment(
                    data=pcm_data,
                    sample_width=cls.SAMPLE_WIDTH,
                    frame_rate=cls.SAMPLE_RATE,
                    channels=cls.CHANNELS
                )
                offset_ms = int((chunk_time - session_start) * 1000)
                offset_ms = max(0, min(offset_ms, total_ms - len(seg)))
                canvas = canvas.overlay(seg, position=offset_ms)
            except Exception as e:
                logger.debug(f"混音完整會話時發生錯誤: {e}")

        output_path = RECORDINGS_DIR / output_filename
        canvas.export(str(output_path), format="mp3", bitrate="192k")
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
