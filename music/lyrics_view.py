import time
import asyncio
import logging
from typing import Optional, List, Tuple
import discord
from music.ytdl_source import Song
from music.lyrics_service import (
    LyricsData,
    format_time,
    parse_duration_str,
    format_progress_bar
)

logger = logging.getLogger(__name__)

def paginate_lyrics(text: str, max_chars: int = 1500) -> List[str]:
    """將過長的歌詞安全切分為多頁 (避開 Discord 單個欄位/Embed 長度限制)"""
    if not text:
        return ["(暫無純文字歌詞內容)"]
    pages = []
    current_page = []
    current_len = 0
    for line in text.splitlines():
        line_len = len(line) + 1
        if current_len + line_len > max_chars and current_page:
            pages.append("\n".join(current_page))
            current_page = [line]
            current_len = line_len
        else:
            current_page.append(line)
            current_len += line_len
    if current_page:
        pages.append("\n".join(current_page))
    return pages if pages else ["(暫無純文字歌詞內容)"]

def build_synced_embed(player, song: Song, lyrics_data: LyricsData) -> Tuple[discord.Embed, int]:
    """建立動態同步歌詞 Embed，並回傳當前歌詞行的索引 (以便偵測是否有跳行)"""
    elapsed = player.elapsed_seconds
    total_sec = parse_duration_str(song.duration)
    lines = lyrics_data.lines

    current_idx = 0
    if lines:
        for i, (t, _) in enumerate(lines):
            if t <= elapsed:
                current_idx = i
            else:
                break

    # 取目前歌詞前後的視窗 (前 2 行、當前行、後 3 行)
    start_idx = max(0, current_idx - 2)
    end_idx = min(len(lines), current_idx + 4)

    body_lines = []
    for i in range(start_idx, end_idx):
        t, text = lines[i]
        t_str = format_time(t)
        if i == current_idx:
            body_lines.append(f"👉 **__🎙️ [{t_str}] {text}__**")
        elif i < current_idx:
            body_lines.append(f"   *[{t_str}] {text}*")
        else:
            body_lines.append(f"   [{t_str}] {text}")

    body_text = "\n".join(body_lines) if body_lines else "🎶 *(伴奏中 / 音樂播放中)*"
    progress = format_progress_bar(elapsed, total_sec)

    embed = discord.Embed(
        title="🎙️ 動態同步歌詞 (Live Lyrics)",
        description=f"### [{song.title}]({song.webpage_url})\n**藝人 / 歌手:** {lyrics_data.artist or song.artist}\n\n{body_text}\n\n{progress}",
        color=0x1DB954  # Spotify 綠
    )
    if song.thumbnail:
        embed.set_thumbnail(url=song.thumbnail)
    embed.set_footer(text=f"來源: {lyrics_data.source} • 動態實時滾動 • 點擊下方按鈕可切換完整歌詞")
    return embed, current_idx

class LiveLyricsView(discord.ui.View):
    """
    動態即時同步歌詞視圖：
    背景非同步循環即時追蹤歌曲進度，高亮當前歌詞行並更新進度條。
    """

    def __init__(self, player, song: Song, lyrics_data: LyricsData, requester_id: int):
        super().__init__(timeout=600)  # 最長同步 10 分鐘
        self.player = player
        self.song = song
        self.lyrics_data = lyrics_data
        self.requester_id = requester_id
        self.message: Optional[discord.Message] = None
        self.update_task: Optional[asyncio.Task] = None
        self.last_rendered_idx = -1
        self.last_edit_time: float = 0.0
        self.is_active = True

    def start_sync(self, message: discord.Message):
        """啟動動態更新背景任務"""
        self.message = message
        if self.lyrics_data.synced and self.lyrics_data.lines:
            self.update_task = asyncio.create_task(self._live_update_loop())

    async def _live_update_loop(self):
        """背景非同步滾動更新迴圈"""
        consecutive_errors = 0
        while self.is_active and not self.is_finished():
            try:
                # 檢查歌曲是否已更換或停止
                vc = self.player.voice_client
                if (
                    not vc
                    or not vc.is_connected()
                    or self.player.is_stopped
                    or self.player.current != self.song
                ):
                    if self.message:
                        try:
                            end_embed = discord.Embed(
                                title="⏹️ 歌曲已結束或切換",
                                description=f"**[{self.song.title}]({self.song.webpage_url})** 播放已結束，同步歌詞已停止。",
                                color=0x95A5A6
                            )
                            # 停用所有按鈕
                            for child in self.children:
                                child.disabled = True
                            await self.message.edit(embed=end_embed, view=self)
                        except Exception:
                            pass
                    break

                # 若暫停播放中，不需頻繁更新，等待稍候再檢查
                if vc.is_paused():
                    await asyncio.sleep(2.0)
                    continue

                now = time.time()
                embed, cur_idx = build_synced_embed(self.player, self.song, self.lyrics_data)
                
                # 智慧節流策略：歌詞跳行時即時更新；同一行時每 4.5 秒平滑更新進度條，杜絕觸發 Discord 429 限速
                should_edit = (cur_idx != self.last_rendered_idx) or (now - self.last_edit_time >= 4.5)
                if should_edit and self.message:
                    await self.message.edit(embed=embed, view=self)
                    self.last_rendered_idx = cur_idx
                    self.last_edit_time = now
                    consecutive_errors = 0

                await asyncio.sleep(2.0)

            except asyncio.CancelledError:
                break
            except discord.HTTPException as e:
                # 若遭 Discord 限速 (Rate Limit)，短暫等待後繼續
                consecutive_errors += 1
                if consecutive_errors > 4:
                    logger.debug("動態歌詞更新遭多次限速，結束同步迴圈。")
                    break
                await asyncio.sleep(4.0)
            except Exception as e:
                logger.debug(f"動態歌詞更新迴圈例外: {e}")
                consecutive_errors += 1
                if consecutive_errors > 4:
                    break
                await asyncio.sleep(3.0)

    def stop_sync(self):
        """停止背景同步"""
        self.is_active = False
        if self.update_task and not self.update_task.done():
            self.update_task.cancel()

    async def on_timeout(self):
        self.stop_sync()
        if self.message:
            try:
                for child in self.children:
                    child.disabled = True
                await self.message.edit(view=self)
            except Exception:
                pass

    @discord.ui.button(label="📜 完整歌詞", style=discord.ButtonStyle.primary, emoji="📖", row=0)
    async def show_full_lyrics(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.stop_sync()
        full_view = FullLyricsView(
            lyrics_data=self.lyrics_data,
            player=self.player,
            song=self.song,
            requester_id=self.requester_id
        )
        embed = full_view.get_embed()
        await interaction.response.edit_message(embed=embed, view=full_view)
        full_view.message = self.message

    @discord.ui.button(label="🔄 立即刷新", style=discord.ButtonStyle.secondary, emoji="🔄", row=0)
    async def refresh_lyrics(self, button: discord.ui.Button, interaction: discord.Interaction):
        embed, cur_idx = build_synced_embed(self.player, self.song, self.lyrics_data)
        self.last_rendered_idx = cur_idx
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="⏹️ 停止同步", style=discord.ButtonStyle.danger, emoji="⏹️", row=0)
    async def stop_lyrics_sync(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.stop_sync()
        for child in self.children:
            child.disabled = True
        embed = discord.Embed(
            title="⏹️ 動態同步歌詞已停止",
            description=f"**[{self.song.title}]({self.song.webpage_url})** 的即時歌詞同步已手動停止。",
            color=0x7F8C8D
        )
        await interaction.response.edit_message(embed=embed, view=self)

class FullLyricsView(discord.ui.View):
    """
    完整純文字歌詞分頁視圖：
    支援長篇歌詞自動分頁 (⬅️ 上一頁 / ➡️ 下一頁)，並可一鍵切回動態同步模式。
    """

    def __init__(
        self,
        lyrics_data: LyricsData,
        player=None,
        song: Optional[Song] = None,
        requester_id: int = 0
    ):
        super().__init__(timeout=300)
        self.lyrics_data = lyrics_data
        self.player = player
        self.song = song
        self.requester_id = requester_id
        self.message: Optional[discord.Message] = None
        self.current_page = 0
        self.pages = paginate_lyrics(lyrics_data.plain)
        self.update_buttons()

    def update_buttons(self):
        """根據目前頁數更新按鈕啟用狀態"""
        # 尋找上一頁與下一頁按鈕
        for child in self.children:
            if hasattr(child, "custom_id"):
                if child.custom_id == "prev_page":
                    child.disabled = (self.current_page == 0)
                elif child.custom_id == "next_page":
                    child.disabled = (self.current_page >= len(self.pages) - 1)
                elif child.custom_id == "back_to_sync":
                    # 若本曲沒有同步資料，或歌曲已經不在播放中，停用切回同步
                    can_sync = (
                        self.lyrics_data.synced
                        and self.player
                        and self.song
                        and self.player.current == self.song
                    )
                    child.disabled = not can_sync

    def get_embed(self) -> discord.Embed:
        page_content = self.pages[self.current_page]
        title_text = f"📖 完整歌詞：{self.lyrics_data.title}"
        if self.lyrics_data.artist:
            title_text += f" - {self.lyrics_data.artist}"

        embed = discord.Embed(
            title=title_text[:256],
            description=page_content,
            color=0x3498DB
        )
        if self.lyrics_data.thumbnail:
            embed.set_thumbnail(url=self.lyrics_data.thumbnail)

        total_pages = len(self.pages)
        embed.set_footer(
            text=f"頁數: {self.current_page + 1} / {total_pages} • 來源: {self.lyrics_data.source}"
        )
        return embed

    @discord.ui.button(label="上一頁", style=discord.ButtonStyle.secondary, emoji="⬅️", custom_id="prev_page", row=0)
    async def prev_page(self, button: discord.ui.Button, interaction: discord.Interaction):
        if self.current_page > 0:
            self.current_page -= 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="下一頁", style=discord.ButtonStyle.secondary, emoji="➡️", custom_id="next_page", row=0)
    async def next_page(self, button: discord.ui.Button, interaction: discord.Interaction):
        if self.current_page < len(self.pages) - 1:
            self.current_page += 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="🎤 同步歌詞", style=discord.ButtonStyle.success, emoji="🎙️", custom_id="back_to_sync", row=0)
    async def back_to_sync(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not self.player or not self.song or self.player.current != self.song:
            return await interaction.response.send_message("⚠️ 該歌曲已結束或更換，無法重新啟動動態同步。", ephemeral=True)

        live_view = LiveLyricsView(
            player=self.player,
            song=self.song,
            lyrics_data=self.lyrics_data,
            requester_id=self.requester_id
        )
        embed, _ = build_synced_embed(self.player, self.song, self.lyrics_data)
        await interaction.response.edit_message(embed=embed, view=live_view)
        live_view.start_sync(self.message or interaction.message)
