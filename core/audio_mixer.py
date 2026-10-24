import io
import time
import asyncio
import logging
import subprocess
import atexit
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Tuple, Optional
from config.settings import RECORDINGS_DIR, FFMPEG_EXE

logger = logging.getLogger(__name__)

# 專屬音訊非同步工作線程池（避免阻塞 Discord asyncio 事件循環與播歌流程）
_AUDIO_EXECUTOR: Optional[ThreadPoolExecutor] = None

def get_audio_executor() -> ThreadPoolExecutor:
    """獲取全域音訊處理執行緒池，若尚未初始化或已關閉則自動建立"""
    global _AUDIO_EXECUTOR
    if _AUDIO_EXECUTOR is None or getattr(_AUDIO_EXECUTOR, "_shutdown", False):
        _AUDIO_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="AudioMixerWorker")
    return _AUDIO_EXECUTOR

def shutdown_audio_executor(wait: bool = False):
    """主動釋放音訊工作執行緒池，徹底杜絕線程洩漏 (Thread Leak)"""
    global _AUDIO_EXECUTOR
    if _AUDIO_EXECUTOR is not None:
        try:
            _AUDIO_EXECUTOR.shutdown(wait=wait, cancel_futures=True)
            logger.info("AudioMixerWorker 執行緒池已安全釋放完畢。")
        except Exception as e:
            logger.debug(f"關閉 AudioMixer 執行緒池例外: {e}")
        finally:
            _AUDIO_EXECUTOR = None

# 註冊處理程序退出時自動釋放執行緒
atexit.register(shutdown_audio_executor)

class AudioMixer:
    """
    音訊錄製輸出處理器：
    採用直通原始音訊編碼 (Direct Unmixed Stream Encoding)，完全不經過損耗性的多軌加法混音
    與空時間軸零字節填充，徹底杜絕封包丟棄、字詞吞沒與空白間距，保證 100% 完整還原成員語音！
    """

    SAMPLE_RATE = 48000
    SAMPLE_WIDTH = 2  # 16-bit
    CHANNELS = 2      # Stereo
    BYTES_PER_SAMPLE = 4  # 16-bit * 2 channels = 4 bytes

    @classmethod
    def direct_pcm_to_mp3(cls, pcm_bytes: bytes, bitrate: str = "192k") -> io.BytesIO:
        """
        將原始 PCM 語音資料直接快速編碼為高品質 MP3 (預設 192k，兼顧速度與音質)
        """
        if not pcm_bytes:
            return io.BytesIO()

        args = [
            str(FFMPEG_EXE),
            "-f", "s16le",
            "-ar", "48000",
            "-ac", "2",
            "-i", "pipe:0",
            "-b:a", bitrate,
            "-f", "mp3",
            "pipe:1"
        ]
        proc = None
        try:
            proc = subprocess.Popen(
                args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL
            )
            out, _ = proc.communicate(input=pcm_bytes)
            buf = io.BytesIO(out)
            buf.seek(0)
            return buf
        except Exception as e:
            logger.error(f"FFmpeg PCM 直接轉碼 MP3 失敗: {e}")
            if proc:
                try:
                    proc.kill()
                    proc.wait()
                except Exception:
                    pass
            return io.BytesIO()
        finally:
            if proc:
                if proc.stdin:
                    try:
                        proc.stdin.close()
                    except Exception:
                        pass
                if proc.stdout:
                    try:
                        proc.stdout.close()
                    except Exception:
                        pass

    @classmethod
    def mix_replay_buffer(
        cls,
        user_buffers: Dict[int, List[Tuple]] | List[Tuple],
        duration_seconds: float = 60.0,
        end_time: float | None = None
    ) -> Tuple[io.BytesIO, List[int]]:
        """
        直通原始對話剪輯（不混音）：
        依照各成員發言先後時間順序，直接無損拼接原始 PCM 封包並快速輸出為 MP3。
        絕不刪除字句、絕不留大量空白、絕不音量過濾，100% 完整保留所有說話內容！
        """
        if end_time is None:
            end_time = time.time()
        start_time = end_time - duration_seconds

        all_chunks: List[Tuple[float, int, bytes]] = []
        if isinstance(user_buffers, dict):
            for user_id, chunks in user_buffers.items():
                for c in chunks:
                    if not c or len(c) < 2:
                        continue
                    c_time = c[0]
                    c_pcm = c[1]
                    if c_time >= start_time and c_pcm:
                        all_chunks.append((c_time, user_id, c_pcm))
        elif isinstance(user_buffers, list):
            for item in user_buffers:
                if len(item) >= 3:
                    c_time, user_id, c_pcm = item[0], item[1], item[2]
                    if c_time >= start_time and c_pcm:
                        all_chunks.append((c_time, user_id, c_pcm))
                elif len(item) == 2:
                    c_time, c_pcm = item[0], item[1]
                    if c_time >= start_time and c_pcm:
                        all_chunks.append((c_time, 1, c_pcm))

        if not all_chunks:
            return io.BytesIO(), []

        # 依照語音封包到達時間順序排序，形成自然流暢的連貫對話錄音
        all_chunks.sort(key=lambda x: x[0])

        raw_pcm = b"".join(c[2] for c in all_chunks)
        active_users = list({c[1] for c in all_chunks if c[1] != 0})

        mp3_buf = cls.direct_pcm_to_mp3(raw_pcm, bitrate="192k")
        return mp3_buf, active_users

    @classmethod
    async def mix_replay_buffer_async(
        cls,
        user_buffers: Dict[int, List[Tuple]],
        duration_seconds: float = 60.0,
        end_time: float | None = None
    ) -> Tuple[io.BytesIO, List[int]]:
        """
        [多工處理] 在背景線程池中執行直通音訊輸出，100% 不卡頓 Discord 主線程。
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            get_audio_executor(),
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
        output_filename: str,
        bitrate: str = "128k"
    ) -> str:
        """
        直通完整會話錄音（高效能串流寫入）：
        將會議中所有收到的語音片段依到達順序串接，以分段串流方式直接寫入 FFmpeg 輸出至磁碟。
        免除記憶體巨大暴增 (RAM Explosion)，並過濾過短雜訊 (< 3 秒)。
        """
        if not session_chunks:
            return ""

        # 按照時間戳順序排序
        sorted_chunks = sorted(session_chunks, key=lambda x: x[1] if len(x) > 1 else 0)
        pcm_parts = []
        total_pcm_len = 0
        for item in sorted_chunks:
            pcm = None
            if len(item) >= 3 and isinstance(item[2], (bytes, bytearray)):
                pcm = item[2]
            elif len(item) >= 2 and isinstance(item[1], (bytes, bytearray)):
                pcm = item[1]
            if pcm:
                pcm_parts.append(pcm)
                total_pcm_len += len(pcm)

        if not pcm_parts:
            return ""

        # 門檻過濾：少於 3 秒 (3 * 48000 * 4 = 576,000 bytes) 之零碎雜訊檔不予存檔
        if total_pcm_len < 576000:
            logger.info(f"錄音時間過短 ({total_pcm_len} bytes < 3 秒)，自動略過存檔，避免產生垃圾碎片檔案。")
            return ""

        output_path = RECORDINGS_DIR / output_filename
        args = [
            str(FFMPEG_EXE),
            "-y",
            "-f", "s16le",
            "-ar", "48000",
            "-ac", "2",
            "-i", "pipe:0",
            "-b:a", bitrate,
            "-f", "mp3",
            str(output_path)
        ]
        proc = None
        try:
            proc = subprocess.Popen(
                args,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            # 串流直接分段寫入 FFmpeg stdin，徹底免除巨大記憶體緩衝
            for part in pcm_parts:
                proc.stdin.write(part)
            proc.stdin.close()
            proc.wait()
            logger.info(f"直通完整錄音檔案已成功儲存至: {output_path} (PCM 總量: {total_pcm_len} bytes, 位元率: {bitrate})")
            return str(output_path)
        except Exception as e:
            logger.error(f"FFmpeg 串流直接轉碼 MP3 失敗: {e}")
            if proc:
                try:
                    proc.kill()
                    proc.wait()
                except Exception:
                    pass
            return ""
        finally:
            if proc and proc.stdin and not proc.stdin.closed:
                try:
                    proc.stdin.close()
                except Exception:
                    pass

    @classmethod
    async def mix_full_session_async(
        cls,
        session_chunks: List[Tuple],
        session_start: float,
        session_end: float,
        output_filename: str,
        bitrate: str = "128k"
    ) -> str:
        """
        [多工處理] 在背景線程池中非同步輸出完整錄音檔案。
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            get_audio_executor(),
            cls.mix_full_session,
            session_chunks,
            session_start,
            session_end,
            output_filename,
            bitrate
        )
