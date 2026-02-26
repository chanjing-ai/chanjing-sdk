"""
声音克隆服务：上传参考音频 → 克隆声音 → 轮询 → 返回 voice_id。
"""

from __future__ import annotations

import logging
import os
import time
from typing import Callable, Optional

from ..api import BASE_URL, ApiClient, check_billing_error
from ..cache import VoiceCloneCache
from ..utils import (
    file_content_hash,
    format_duration,
    get_audio_duration,
    trim_audio,
)

logger = logging.getLogger("chanjing")


class VoiceCloneService:
    """声音克隆业务逻辑。"""

    def __init__(self, api: ApiClient, cache: VoiceCloneCache) -> None:
        self._api = api
        self._cache = cache

    def clone(
        self,
        audio_path: str,
        access_token: str,
        *,
        model: str = "cicada3.0-turbo",
        use_cache: bool = True,
        on_progress: Optional[Callable[[str, int, str], None]] = None,
    ) -> str:
        """
        克隆声音，返回 voice_id。

        Args:
            audio_path: 参考音频文件路径（15秒-5分钟）
            access_token: 平台 access_token
            model: 模型类型 "cicada3.0-turbo" | "cicada3.0" | "cicada1.0"
            use_cache: 是否使用缓存（同音频+同模型跳过重复克隆）
            on_progress: 可选进度回调 (stage, percent, message)
        """
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"参考音频文件不存在: {audio_path}")

        def _progress(stage: str, pct: int, msg: str) -> None:
            if on_progress:
                on_progress(stage, pct, msg)

        # 检查音频时长
        duration = get_audio_duration(audio_path)
        if duration is not None:
            logger.info("参考音频时长: %s", format_duration(duration))
            if duration < 15:
                raise ValueError(
                    f"参考音频时长过短: {format_duration(duration)}，"
                    f"要求至少 15 秒（当前 {duration:.1f} 秒）"
                )
            if duration > 300:
                logger.info("音频时长超过5分钟，尝试自动裁剪...")
                trimmed = trim_audio(audio_path, max_duration=299)
                if trimmed:
                    audio_path = trimmed
                    logger.info("已自动裁剪到 4:59")
                else:
                    raise ValueError(
                        f"参考音频时长超限: {format_duration(duration)} (最长 5:00)，"
                        f"自动裁剪失败，请安装 ffmpeg 或手动裁剪"
                    )

        audio_hash = file_content_hash(audio_path)

        # 缓存检查
        if use_cache:
            cached_id = self._cache.get(audio_hash, model)
            if cached_id:
                logger.info("命中声音克隆缓存，voice_id=%s", cached_id)
                if self._validate_voice(cached_id, access_token):
                    _progress("声音克隆", 100, "缓存命中")
                    return cached_id
                else:
                    logger.info("缓存的声音已失效，重新克隆")
                    self._cache.remove(audio_hash, model)

        # 上传音频
        _progress("上传音频", 0, "上传参考音频...")

        def _on_upload(pct: int, msg: str) -> None:
            _progress("上传音频", pct, msg)

        upload_result = self._api.upload_file(
            audio_path, "prompt_audio", access_token,
            on_progress=_on_upload,
        )
        audio_public_url = upload_result["url"]
        if not audio_public_url:
            raise RuntimeError("上传接口未返回公网URL，请检查 service 参数")

        # 创建克隆任务
        _progress("声音克隆", 0, "创建克隆任务...")
        result = self._api.json_request(
            "POST",
            f"{BASE_URL}/open/v1/create_customised_audio",
            rate_category="voice_clone",
            json={
                "name": f"clone_{int(time.time())}",
                "url": audio_public_url,
                "model_type": model,
            },
            headers={"access_token": access_token, "Content-Type": "application/json"},
        )
        voice_id = result["data"]
        logger.info("声音克隆任务创建成功，voice_id=%s", voice_id)

        # 轮询克隆结果
        self._poll_clone(voice_id, access_token, on_progress)

        # 写入缓存
        if use_cache:
            self._cache.put(audio_hash, model, voice_id)
            logger.info("声音克隆结果已缓存")

        return voice_id

    def _validate_voice(self, voice_id: str, access_token: str) -> bool:
        """验证缓存的 voice_id 是否仍然有效。"""
        try:
            result = self._api.json_request(
                "GET",
                f"{BASE_URL}/open/v1/customised_audio",
                rate_category="voice_clone",
                params={"id": voice_id},
                headers={"access_token": access_token},
            )
            return result["data"]["status"] == 2
        except Exception:
            return False

    def _poll_clone(
        self,
        voice_id: str,
        access_token: str,
        on_progress: Optional[Callable[[str, int, str], None]] = None,
        max_wait: int = 600,
    ) -> None:
        """轮询声音克隆状态直到完成。"""
        start = time.time()
        last_status = -1
        last_pct = -1
        consecutive_errors = 0

        logger.info("等待声音克隆完成...")
        while True:
            elapsed = time.time() - start
            if elapsed > max_wait:
                raise TimeoutError(f"声音克隆超时（{int(elapsed)}秒），voice_id: {voice_id}")

            try:
                result = self._api.json_request(
                    "GET",
                    f"{BASE_URL}/open/v1/customised_audio",
                    rate_category="voice_clone",
                    silent_rate=True,
                    params={"id": voice_id},
                    headers={"access_token": access_token},
                )
                consecutive_errors = 0
            except Exception as e:
                consecutive_errors += 1
                if consecutive_errors >= 5:
                    raise RuntimeError(f"声音克隆轮询连续失败5次: {e}") from e
                time.sleep(5)
                continue

            data = result["data"]
            status = data["status"]
            api_progress = data.get("progress", 0)

            if status == 2:
                if on_progress:
                    on_progress("声音克隆", 100, "声音克隆完成")
                logger.info("声音克隆完成！")
                return
            elif status == 4:
                err_msg = data.get("err_msg", "未知错误")
                check_billing_error(err_msg)
                raise RuntimeError(f"声音克隆失败: {err_msg}")
            elif status == 3:
                raise RuntimeError("声音克隆任务已过期")
            elif status == 99:
                raise RuntimeError("声音克隆任务已被删除")
            else:
                if status != last_status or api_progress != last_pct:
                    status_text = "等待制作" if status == 0 else "制作中"
                    logger.info("声音克隆: %d%% - %s", api_progress, status_text)
                    if on_progress:
                        on_progress("声音克隆", api_progress, status_text)
                    last_status = status
                    last_pct = api_progress
                time.sleep(5)
