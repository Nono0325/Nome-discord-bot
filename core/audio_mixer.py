import io
import time
import logging
from typing import Dict, List, Tuple
from pydub import AudioSegment
from config.settings import RECORDINGS_DIR

logger = logging.getLogger(__name__)

class AudioMixer:
    """
    負責將多位成員的時間軸 PCM 語音片段對齊並混音成完整的 MP3 語音檔案。
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
        將過去指定秒數（預設 60 秒）內所有成員的語音對話依時間戳混音為單一 MP3。
        
        :param user_buffers: 各使用者的語音片段列表，格式為 {user_id: [(timestamp, pcm_bytes), ...]}
        :param duration_seconds: 回溯時間長度（秒）
        :param end_time: 結束時間點，預設為當前時間
        :return: (mp3_io_buffer, active_user_ids)
        """
        if end_time is None:
            end_time = time.time()
        start_time = end_time - duration_seconds
        duration_ms = int(duration_seconds * 1000)

        # 建立指定長度的靜音畫布（48000Hz 立體聲）
        canvas = AudioSegment.silent(duration=duration_ms, frame_rate=cls.SAMPLE_RATE)
        active_users: List[int] = []

        for user_id, chunks in user_buffers.items():
            user_has_speech = False
            for chunk_time, pcm_data in chunks:
                if chunk_time + 1.0 < start_time or chunk_time > end_time:
                    continue  # 不在欲截取的時間範圍內

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

        # 匯出為 MP3
        output = io.BytesIO()
        canvas.export(output, format="mp3", bitrate="192k")
        output.seek(0)
        return output, active_users

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
