import io
import time
import asyncio
import logging
import audioop
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Tuple
from pydub import AudioSegment
from pydub.effects import normalize
from config.settings import RECORDINGS_DIR

logger = logging.getLogger(__name__)

# 專屬音訊非同步工作線程池（避免阻塞 Discord asyncio 事件循環與播歌流程）
_AUDIO_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="AudioMixerWorker")

class AudioMixer:
    """
    負責將多位成員的時間軸 PCM 語音片段對齊並混音成完整的 MP3 語音檔案。
    採用訊框無縫連續銜接 (Seamless Sequential Frame Alignment) 與動態音量標準化 (Audio Peak Normalization)，
    徹底消除封包覆蓋導致的口齒不清、吞字與聲音模糊問題，達到廣播級清晰人聲。
    混音使用極速底層 C 語言音訊函式 (audioop / bytearray)，100% 不卡頓播歌主線程。
    """

    SAMPLE_RATE = 48000
    SAMPLE_WIDTH = 2  # 16-bit
    CHANNELS = 2      # Stereo
    BYTES_PER_SAMPLE = 4  # 16-bit * 2 channels = 4 bytes

    @classmethod
    def _render_user_track(
        cls,
        chunks: List[Tuple],
        timeline_start: float,
        total_bytes: int,
    ) -> Tuple[bytearray, bool]:
        """
        將單一使用者的音訊訊框依據連續性與時間戳寫入使用者音軌緩衝區。
        關鍵修復：在同一次發言中，訊框緊接著前一訊框末端寫入 (Continuous Cursor)，絕不向前覆蓋！
        只有在成員真正停頓不說話時，才按時間軸空出靜音間隔，徹底解決聲音模糊、機械音與字詞破碎問題。
        """
        user_buf = bytearray(total_bytes)
        user_has_speech = False
        write_cursor = 0
        last_chunk_time: float | None = None
        last_rtp_ts: int | None = None

        for chunk in chunks:
            if not chunk or len(chunk) < 2:
                continue
            chunk_time = chunk[0]
            pcm_data = chunk[1]
            rtp_seq = chunk[2] if len(chunk) > 2 else None
            rtp_ts = chunk[3] if len(chunk) > 3 else None

            if not pcm_data:
                continue

            # 計算當前封包在時間軸上的名義位元組偏移
            nominal_byte_pos = int((chunk_time - timeline_start) * cls.SAMPLE_RATE) * cls.BYTES_PER_SAMPLE

            # 判斷是否屬於同一次講話的連續訊框
            is_continuous = False
            if last_rtp_ts is not None and rtp_ts is not None:
                # RTP 採樣率 48kHz，每 20ms 一幀為 960 採樣點
                d_samples = (rtp_ts - last_rtp_ts) & 0xFFFFFFFF
                # 若間隔在 0 到 3 幀以內 (約 0~60ms)，視為連續語音
                if 0 < d_samples <= 960 * 3:
                    is_continuous = True
            elif last_chunk_time is not None:
                # 若無 RTP 時間戳，到達時間差小於 65ms 視為連續語音訊框
                if (chunk_time - last_chunk_time) < 0.065:
                    is_continuous = True

            if is_continuous:
                # 連續語音：自游標處緊接著寫入，絕不覆蓋先前語音訊框！
                byte_offset = write_cursor
            else:
                # 語音停頓或新句子：依實際時間軸定位；若網路或排程延遲造成名義時間在游標前，則保護性對齊至游標
                byte_offset = max(write_cursor, nominal_byte_pos)

            if byte_offset < 0:
                pcm_data = pcm_data[-byte_offset:]
                byte_offset = 0

            if byte_offset >= total_bytes:
                continue

            write_len = min(len(pcm_data), total_bytes - byte_offset)
            if write_len > 0:
                user_buf[byte_offset : byte_offset + write_len] = pcm_data[:write_len]
                write_cursor = byte_offset + write_len
                last_chunk_time = chunk_time
                last_rtp_ts = rtp_ts

                if not user_has_speech:
                    try:
                        # 檢查音量是否大於微弱環境噪聲 (RMS > 25)
                        if audioop.rms(pcm_data[:write_len], 2) > 25:
                            user_has_speech = True
                    except Exception:
                        user_has_speech = True

        return user_buf, user_has_speech

    @classmethod
    def mix_replay_buffer(
        cls,
        user_buffers: Dict[int, List[Tuple]],
        duration_seconds: float = 60.0,
        end_time: float | None = None
    ) -> Tuple[io.BytesIO, List[int]]:
        """
        將過去指定秒數（預設 60 秒）內所有成員的語音對話依時間戳混音為單一清晰立體聲 MP3。
        使用 C 語言底層 audioop 疊加音軌，並執行自動動態響度標準化。
        """
        if end_time is None:
            end_time = time.time()
        start_time = end_time - duration_seconds
        total_samples = int(duration_seconds * cls.SAMPLE_RATE)
        total_bytes = total_samples * cls.BYTES_PER_SAMPLE

        user_tracks: Dict[int, bytearray] = {}
        active_users: List[int] = []

        for user_id, chunks in user_buffers.items():
            # 過濾僅保留目標時間範圍內的訊框（多寬限 1 秒避免邊界語音被削波）
            filtered_chunks = [
                c for c in chunks
                if c and len(c) >= 2 and (c[0] + 1.0 >= start_time) and (c[0] <= end_time + 1.0)
            ]
            if not filtered_chunks:
                continue

            user_buf, user_has_speech = cls._render_user_track(
                filtered_chunks,
                start_time,
                total_bytes
            )

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

        try:
            # 標準化音量，保留 0.5dB headroom，消除人聲微弱發悶、爆音失真
            seg = normalize(seg, headroom=0.5)
        except Exception as e:
            logger.debug("音訊標準化跳過: %s", e)

        seg.export(output, format="mp3", bitrate="320k")
        output.seek(0)
        return output, active_users

    @classmethod
    async def mix_replay_buffer_async(
        cls,
        user_buffers: Dict[int, List[Tuple]],
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
        session_chunks: List[Tuple],
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

        # 依使用者 ID 分組
        user_grouped: Dict[int, List[Tuple]] = {}
        for item in session_chunks:
            if not item or len(item) < 3:
                continue
            u_id = item[0]
            chunk_data = item[1:]  # (chunk_time, pcm_data, rtp_seq, rtp_ts)
            if u_id not in user_grouped:
                user_grouped[u_id] = []
            user_grouped[u_id].append(chunk_data)

        user_tracks: Dict[int, bytearray] = {}
        for u_id, chunks in user_grouped.items():
            u_buf, has_speech = cls._render_user_track(
                chunks,
                session_start,
                total_bytes
            )
            if has_speech:
                user_tracks[u_id] = u_buf

        if not user_tracks:
            return ""

        mixed_bytes: bytearray | None = None
        for u_id, u_buf in user_tracks.items():
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

        try:
            seg = normalize(seg, headroom=0.5)
        except Exception as e:
            logger.debug("音訊標準化跳過: %s", e)

        seg.export(str(output_path), format="mp3", bitrate="320k")
        return str(output_path)

    @classmethod
    async def mix_full_session_async(
        cls,
        session_chunks: List[Tuple],
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
