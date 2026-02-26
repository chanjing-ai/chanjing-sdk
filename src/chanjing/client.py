"""
CicadaClient —— 蝉镜 AI SDK 统一入口。

用法:
    from chanjing import CicadaClient

    client = CicadaClient(app_id="xxx", secret_key="yyy")

    # 对口型
    result = client.lip_sync(video="video.mp4", audio="audio.wav")
    result.download("output.mp4")

    # 声音克隆 + TTS
    result = client.voice_clone_and_speak(
        reference_audio="ref.mp3",
        text="你好世界",
    )
    result.download("output.mp3")
"""

from __future__ import annotations

import logging
import os
from typing import Callable, Optional

from .api import ApiClient
from .auth import AuthManager
from .cache import VoiceCloneCache
from .services.lip_sync import LipSyncResult, LipSyncService
from .services.tts import TTSResult, TTSService
from .services.voice_clone import VoiceCloneService

logger = logging.getLogger("chanjing")

_DEFAULT_CACHE_DIR = os.path.join(os.path.expanduser("~"), ".chanjing", "cache")


class CicadaClient:
    """
    蝉镜 AI Python SDK 主入口。

    凭证获取优先级：构造参数 > 环境变量 > ~/.chanjing/config.json

    Args:
        app_id: 蝉镜平台 App ID（可选，也可通过环境变量或配置文件提供）
        secret_key: 蝉镜平台 Secret Key（可选）
        cache_dir: 缓存目录，默认 ~/.chanjing/cache/
        log_level: 日志级别，默认 INFO。设为 None 不修改日志配置。
    """

    def __init__(
        self,
        app_id: Optional[str] = None,
        secret_key: Optional[str] = None,
        cache_dir: Optional[str] = None,
        log_level: Optional[int] = logging.INFO,
    ) -> None:
        if log_level is not None:
            logging.basicConfig(
                level=log_level,
                format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
                datefmt="%H:%M:%S",
            )

        self._cache_dir = cache_dir or _DEFAULT_CACHE_DIR
        self._auth = AuthManager(app_id, secret_key, cache_dir=self._cache_dir)
        self._api = ApiClient(self._auth)
        self._voice_cache = VoiceCloneCache(self._cache_dir)

        self._lip_sync_svc = LipSyncService(self._api)
        self._voice_clone_svc = VoiceCloneService(self._api, self._voice_cache)
        self._tts_svc = TTSService(self._api)

    def _get_token(self) -> str:
        return self._auth.get_token(self._api)

    # ────────────────────────── 对口型 ──────────────────────────

    def lip_sync(
        self,
        video: str,
        audio: str,
        *,
        model: str = "pro",
        backway: str = "forward",
        drive_mode: str = "normal",
        on_progress: Optional[Callable[[str, int, str], None]] = None,
    ) -> LipSyncResult:
        """
        音频驱动视频对口型。

        Args:
            video: 本地视频文件路径
            audio: 本地音频文件路径
            model: "standard" 或 "pro"（默认 pro，唇齿更清晰）
            backway: "forward"（正放，默认）或 "reverse"（倒放）
            drive_mode: "normal"（正常驱动，默认）或 "random"（随机帧驱动）
            on_progress: 可选进度回调 fn(stage, percent, message)

        Returns:
            LipSyncResult 对象，包含 video_url、task_id，可调用 .download() 保存到本地
        """
        token = self._get_token()
        return self._lip_sync_svc.create(
            video_path=video,
            audio_path=audio,
            access_token=token,
            model=model,
            backway=backway,
            drive_mode=drive_mode,
            on_progress=on_progress,
        )

    # ────────────────────────── 声音克隆 ──────────────────────────

    def clone_voice(
        self,
        reference_audio: str,
        *,
        model: str = "cicada3.0-turbo",
        use_cache: bool = True,
        on_progress: Optional[Callable[[str, int, str], None]] = None,
    ) -> str:
        """
        克隆声音，返回 voice_id。

        Args:
            reference_audio: 参考音频路径（15秒-5分钟，mp3/wav/m4a）
            model: "cicada3.0-turbo"（默认）| "cicada3.0" | "cicada1.0"
            use_cache: 是否缓存克隆结果（同音频+同模型跳过重复克隆）
            on_progress: 可选进度回调 fn(stage, percent, message)

        Returns:
            voice_id 字符串
        """
        token = self._get_token()
        return self._voice_clone_svc.clone(
            audio_path=reference_audio,
            access_token=token,
            model=model,
            use_cache=use_cache,
            on_progress=on_progress,
        )

    # ────────────────────────── TTS 语音合成 ──────────────────────────

    def tts(
        self,
        voice_id: str,
        text: str,
        *,
        speed: float = 1.0,
        pitch: float = 1.0,
        on_progress: Optional[Callable[[str, int, str], None]] = None,
    ) -> TTSResult:
        """
        使用已克隆的声音合成语音。

        Args:
            voice_id: 声音 ID（由 clone_voice 返回）
            text: 要合成的文案（最多4000字）
            speed: 语速（0.5-2.0，默认 1.0）
            pitch: 音调（0.1-3.0，默认 1.0）
            on_progress: 可选进度回调 fn(stage, percent, message)

        Returns:
            TTSResult 对象，包含 audio_url、task_id、duration，可调用 .download() 保存
        """
        token = self._get_token()
        return self._tts_svc.synthesize(
            voice_id=voice_id,
            text=text,
            access_token=token,
            speed=speed,
            pitch=pitch,
            on_progress=on_progress,
        )

    # ────────────────────────── 声音克隆 + TTS 一步到位 ──────────────────────────

    def voice_clone_and_speak(
        self,
        reference_audio: str,
        text: str,
        *,
        model: str = "cicada3.0-turbo",
        speed: float = 1.0,
        pitch: float = 1.0,
        use_cache: bool = True,
        on_progress: Optional[Callable[[str, int, str], None]] = None,
    ) -> TTSResult:
        """
        声音克隆 + 语音合成一步完成。

        先克隆参考音频的声音，再用克隆的声音合成指定文案。

        Args:
            reference_audio: 参考音频路径（15秒-5分钟）
            text: 要合成的文案（最多4000字）
            model: 声音克隆模型
            speed: 语速（0.5-2.0）
            pitch: 音调（0.1-3.0）
            use_cache: 是否缓存声音克隆结果
            on_progress: 可选进度回调 fn(stage, percent, message)

        Returns:
            TTSResult 对象
        """
        voice_id = self.clone_voice(
            reference_audio=reference_audio,
            model=model,
            use_cache=use_cache,
            on_progress=on_progress,
        )
        return self.tts(
            voice_id=voice_id,
            text=text,
            speed=speed,
            pitch=pitch,
            on_progress=on_progress,
        )
