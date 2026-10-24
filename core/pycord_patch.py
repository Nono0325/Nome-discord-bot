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
        # 0. 補丁 JitterBuffer：擴大緩衝區至 60 訊框 (1.2秒)，避免 Windows 線程調度抖動時丟棄語音封包
        from discord.voice.utils.buffer import JitterBuffer
        _orig_jb_init = JitterBuffer.__init__

        def _patched_jb_init(self, max_size: int = 60, *, pref_size: int = 1, prefill: int = 1):
            _orig_jb_init(self, max_size=max(max_size, 60), pref_size=pref_size, prefill=prefill)

        JitterBuffer.__init__ = _patched_jb_init

        # 0.1 補丁 PacketDecoder._get_next_packet：發生序號間隙時取最舊封包，杜絕 flush() 丟棄後續所有封包問題
        def _patched_get_next_packet(self, timeout: float):
            packet = self._buffer.pop(timeout=timeout)
            if packet is None:
                if self._buffer and len(self._buffer) > 0:
                    try:
                        packet = self._buffer._pop()
                        self._buffer._last_tx_seq = packet.sequence
                        self._buffer._update_has_item()
                    except Exception:
                        packet = None
                else:
                    return None
            elif not packet:
                packet = self._make_fakepacket()
            return packet

        PacketDecoder._get_next_packet = _patched_get_next_packet

        # 1. 補丁 PacketRouter._do_run：防止單一損毀封包中斷錄音線程，並確保結束標記觸發時立即釋放線程
        def _patched_do_run(self):
            while not self._end_thread.is_set():
                self.waiter.wait()
                if self._end_thread.is_set():
                    break
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

        # 3. 補丁 PacketDecryptor._decrypt_rtp_aead_xchacha20_poly1305_rtpsize：修復官方裁切 8 bytes 嚴重損毀 Opus 封包問題
        def _safe_decrypt_aead(self, packet):
            packet.adjust_rtpsize()
            nonce = packet.nonce + b"\x00" * 20
            try:
                result = self.box.decrypt(
                    packet.decrypted_data or packet.data,
                    bytes(packet.header),
                    nonce,
                )
            except Exception:
                return OPUS_SILENCE

            if packet.extended:
                offset = packet.update_extended_header(result)
                return result[offset:]

            return result

        PacketDecryptor._decrypt_rtp_aead_xchacha20_poly1305_rtpsize = _safe_decrypt_aead

        # 4. 補丁 PacketDecryptor.decrypt_rtp：支援 DAVE 端到端解密並保證非 DAVE 成員無縫 fallback
        def _patched_decrypt_rtp(self, packet):
            state = self.client._connection
            dave = state.dave_session

            try:
                raw_payload = self._decryptor_rtp(packet)
            except Exception:
                packet.decrypted_data = OPUS_SILENCE
                return OPUS_SILENCE

            if not raw_payload or raw_payload == OPUS_SILENCE:
                packet.decrypted_data = OPUS_SILENCE
                return OPUS_SILENCE

            if dave is not None and dave.ready and davey:
                uid = state.ssrc_user_map.get(packet.ssrc)
                if uid:
                    try:
                        decrypted_audio = dave.decrypt(
                            uid,
                            davey.MediaType.audio,
                            raw_payload,
                        )
                        packet.decrypted_data = decrypted_audio
                    except Exception:
                        packet.decrypted_data = raw_payload
                else:
                    packet.decrypted_data = raw_payload
            else:
                packet.decrypted_data = raw_payload

            if packet.decrypted_data is None:
                packet.decrypted_data = OPUS_SILENCE

            return packet.decrypted_data

        PacketDecryptor.decrypt_rtp = _patched_decrypt_rtp

        # 5. 補丁 PacketRouter.run：防止停止錄音時拋出 RecordingException 導致線程崩潰
        def _patched_run(self):
            try:
                self._do_run()
            except Exception as exc:
                logger.debug("PacketRouter 迴圈異常: %s", exc)
                self.reader.error = exc
            finally:
                try:
                    if self.reader.client.is_recording():
                        self.reader.client.stop_recording()
                except Exception:
                    pass
                self.waiter.clear()

        PacketRouter.run = _patched_run

        # 5.1 補丁 PacketRouter.destroy_all_decoders：使用 list 拷貝鍵值，避免迭代時 pop() 導致 dictionary changed size during iteration
        def _patched_destroy_all_decoders(self) -> None:
            with self._lock:
                for ssrc in list(self.decoders.keys()):
                    self.destroy_decoder(ssrc)

        PacketRouter.destroy_all_decoders = _patched_destroy_all_decoders

        # 6. 補丁 VoiceConnectionState：強制開啟 DAVE Passthrough 穿透模式，防止 Discord 因端到端加密尚未收斂而全頻道靜音
        from discord.voice.state import VoiceConnectionState
        _orig_reinit_dave = VoiceConnectionState.reinit_dave_session

        async def _patched_reinit_dave_session(self):
            await _orig_reinit_dave(self)
            if self.dave_session:
                try:
                    self.dave_session.set_passthrough_mode(True, 10)
                    logger.info("已為 DAVE 語音會話啟用 Passthrough 穿透模式，保證音樂播放清晰無阻")
                except Exception as ex:
                    logger.debug("啟用 DAVE passthrough 例外: %s", ex)

        VoiceConnectionState.reinit_dave_session = _patched_reinit_dave_session

        _orig_execute_dave_transition = VoiceConnectionState.execute_dave_transition

        async def _patched_execute_dave_transition(self, transition: int):
            await _orig_execute_dave_transition(self, transition)
            if self.dave_session:
                try:
                    self.dave_session.set_passthrough_mode(True, 10)
                except Exception:
                    pass

        # 7. 補丁 VoiceClient.disconnect：保證 cleanup() 與 _remove_voice_client 必然執行，並先關閉錄音以釋放 Reader 背景執行緒
        from discord.voice.client import VoiceClient
        _orig_vc_disconnect = VoiceClient.disconnect

        async def _patched_vc_disconnect(self, *, force: bool = False) -> None:
            try:
                if hasattr(self, "is_recording") and self.is_recording():
                    self.stop_recording()
            except Exception:
                pass
            try:
                await _orig_vc_disconnect(self, force=force)
            finally:
                try:
                    self.cleanup()
                except Exception:
                    pass
                try:
                    if hasattr(self, "channel") and self.channel:
                        key, _ = self.channel._get_voice_client_key()
                        self.client._connection._remove_voice_client(key)
                except Exception:
                    pass

        VoiceClient.disconnect = _patched_vc_disconnect

        # 7.1 補丁 VoiceClient.stop：只停止音樂播放 (AudioPlayer)，絕不誤殺語音錄音接收器 (_reader)
        _orig_vc_stop = VoiceClient.stop

        def _patched_vc_stop(self) -> None:
            """
            只停止音訊播放 (AudioPlayer)，絕不誤殺語音錄音接收器 (_reader)
            """
            if self._player:
                self._player.stop()
            if self._player_future:
                self.loop.call_soon_threadsafe(
                    self._set_future_result_if_pending, self._player_future, None
                )
            self._player = None
            self._player_future = None

        VoiceClient.stop = _patched_vc_stop

        # 8. 補丁 Connectable.connect：若目標伺服器已有舊的未連線殘留物件，自動移除並清理，防止拋出 Already connected
        from discord.abc import Connectable
        _orig_connect = Connectable.connect

        async def _patched_connect(self, *, timeout: float = 60.0, reconnect: bool = True, cls=discord.utils.MISSING):
            key_id, _ = self._get_voice_client_key()
            existing = self._state._get_voice_client(key_id)
            if existing is not None:
                if not existing.is_connected():
                    # 舊連線已失效或未連線，強制清理並移除
                    try:
                        await existing.disconnect(force=True)
                    except Exception:
                        pass
                    try:
                        existing.cleanup()
                    except Exception:
                        pass
                    self._state._remove_voice_client(key_id)
            return await _orig_connect(self, timeout=timeout, reconnect=reconnect, cls=cls)

        Connectable.connect = _patched_connect

        logger.info("已成功套用 Pycord 語音接收、DAVE 穿透與語音連線防卡死修復補丁 (Pycord patches applied)")
    except Exception as e:
        logger.warning(f"套用 Pycord 補丁時發生例外: {e}")
