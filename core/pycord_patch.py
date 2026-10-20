"""
Pycord 2.8+ 語音錄音與 DAVE 協定相容性自動補丁 (Monkey Patch)
解決官方函式庫在音訊接收解碼時的重大問題：
1. 封包損毀時拋出 OpusError 導致錄音線程中斷
2. decrypt_rtp 在非 DAVE 或未就緒時回傳 None 導致音訊全空
3. PacketRouter 缺乏例外保護導致 stop_recording 觸發
"""

import logging
import discord
from discord.opus import PacketDecoder
from discord.voice.receive.router import PacketRouter
from discord.voice.receive.reader import PacketDecryptor
from discord.voice.packets.core import OPUS_SILENCE

try:
    import davey
except ImportError:
    davey = None

logger = logging.getLogger(__name__)

def apply_pycord_patches():
    """套用 Pycord 語音接收補丁"""
    try:
        # 1. 補丁 PacketRouter._do_run：防止單一損毀封包中斷錄音線程
        def _patched_do_run(self):
            while not self._end_thread.is_set():
                self.waiter.wait()
                with self._lock:
                    for decoder in list(self.waiter.items):
                        try:
                            data = decoder.pop_data()
                            if data is not None:
                                self.sink.write(data, data.source)
                        except Exception as e:
                            logger.debug("解碼封包時發生例外（已忽略以保持錄音持續）: %s", e)

        PacketRouter._do_run = _patched_do_run

        # 2. 補丁 PacketDecoder._decode_packet：為 decode 增加安全 fallback
        def _patched_decode_packet(self, packet):
            assert self._decoder is not None
            assert self.sink.client

            other_code = True
            pcm = None

            if packet:
                other_code = False
                try:
                    if packet.decrypted_data:
                        pcm = self._decoder.decode(packet.decrypted_data, fec=False)
                    else:
                        pcm = self._decoder.decode(None, fec=False)
                except Exception as e:
                    try:
                        pcm = self._decoder.decode(None, fec=False)
                    except Exception:
                        pcm = b"\x00" * 3840

            if other_code:
                next_packet = self._buffer.peek_next()
                if next_packet is not None:
                    nextdata = next_packet.decrypted_data
                    try:
                        pcm = self._decoder.decode(nextdata, fec=True)
                    except Exception:
                        pcm = b"\x00" * 3840
                else:
                    try:
                        pcm = self._decoder.decode(None, fec=False)
                    except Exception:
                        pcm = b"\x00" * 3840

            return packet, pcm

        PacketDecoder._decode_packet = _patched_decode_packet

        # 3. 補丁 PacketDecryptor.decrypt_rtp：確保非 DAVE 或未就緒時音訊不為 None
        def _patched_decrypt_rtp(self, packet):
            state = self.client._connection
            dave = state.dave_session

            raw_payload = self._decryptor_rtp(packet)

            if dave is not None and dave.ready and davey:
                uid = state.ssrc_user_map.get(packet.ssrc)
                if uid:
                    try:
                        decrypted_audio = dave.decrypt(
                            uid,
                            davey.MediaType.audio,
                            raw_payload,
                        )
                        if packet.extended:
                            offset = packet.update_extended_header(decrypted_audio)
                            packet.decrypted_data = decrypted_audio[offset:]
                        else:
                            packet.decrypted_data = decrypted_audio
                    except Exception as exc:
                        packet.decrypted_data = OPUS_SILENCE
                else:
                    packet.decrypted_data = OPUS_SILENCE
            else:
                data = raw_payload
                if packet.extended:
                    offset = packet.update_extended_header(data)
                    data = data[offset:]
                packet.decrypted_data = data

            if packet.decrypted_data is None:
                packet.decrypted_data = OPUS_SILENCE

            return packet.decrypted_data

        PacketDecryptor.decrypt_rtp = _patched_decrypt_rtp
        logger.info("已成功套用 Pycord 語音接收熱修復補丁 (Pycord voice-recv patch applied)")
    except Exception as e:
        logger.warning(f"套用 Pycord 補丁時發生例外: {e}")
