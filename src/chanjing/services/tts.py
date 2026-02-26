"""
语音合成（TTS）服务：使用已克隆的声音合成语音。
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Callable, Optional

from ..api import BASE_URL, ApiClient, check_billing_error

logger = logging.getLogger("chanjing")


@dataclass
class TTSResult:
    """语音合成结果。"""

    audio_url: str
    task_id: str
    duration: float = 0.0

    def download(self, path: str) -> str:
        """下载合成的音频到本地文件。"""
        import requests as _requests

        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        response = _requests.get(self.audio_url, stream=True, timeout=300)
        response.raise_for_status()
        with open(path, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
        logger.info("音频已下载到 %s", path)
        return path


class TTSService:
    """TTS 语音合成业务逻辑。"""

    def __init__(self, api: ApiClient) -> None:
        self._api = api

    def synthesize(
        self,
        voice_id: str,
        text: str,
        access_token: str,
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
            access_token: 平台 access_token
            speed: 语速（0.5-2.0）
            pitch: 音调（0.1-3.0）
            on_progress: 可选进度回调 (stage, percent, message)
        """
        if not text or not text.strip():
            raise ValueError("合成文案不能为空")
        if len(text) > 4000:
            raise ValueError(f"文案长度超过限制: {len(text)}/4000字")

        def _progress(stage: str, pct: int, msg: str) -> None:
            if on_progress:
                on_progress(stage, pct, msg)

        _progress("语音合成", 0, "创建合成任务...")
        result = self._api.json_request(
            "POST",
            f"{BASE_URL}/open/v1/create_audio_task",
            rate_category="tts",
            json={
                "audio_man": voice_id,
                "speed": speed,
                "pitch": pitch,
                "text": {"text": text, "plain_text": text},
            },
            headers={"access_token": access_token, "Content-Type": "application/json"},
        )
        task_id = result["data"]["task_id"]
        logger.info("语音合成任务创建成功，task_id=%s", task_id)

        audio_url, duration = self._poll(task_id, access_token, on_progress)

        _progress("语音合成", 100, "语音合成完成")
        return TTSResult(audio_url=audio_url, task_id=task_id, duration=duration)

    def _poll(
        self,
        task_id: str,
        access_token: str,
        on_progress: Optional[Callable[[str, int, str], None]] = None,
        max_wait: int = 600,
    ) -> tuple[str, float]:
        """轮询语音合成状态，返回 (audio_url, duration)。"""
        start = time.time()
        poll_count = 0
        consecutive_errors = 0

        logger.info("等待语音合成完成...")
        while True:
            elapsed = time.time() - start
            if elapsed > max_wait:
                raise TimeoutError(f"语音合成超时（{int(elapsed)}秒），task_id: {task_id}")

            try:
                result = self._api.json_request(
                    "POST",
                    f"{BASE_URL}/open/v1/audio_task_state",
                    rate_category="tts",
                    silent_rate=True,
                    json={"task_id": task_id},
                    headers={"access_token": access_token, "Content-Type": "application/json"},
                )
                consecutive_errors = 0
            except Exception as e:
                consecutive_errors += 1
                if consecutive_errors >= 5:
                    raise RuntimeError(f"语音合成轮询连续失败5次: {e}") from e
                time.sleep(5)
                continue

            data = result["data"]
            status = data["status"]

            if status == 9:
                err_msg = data.get("errMsg", "")
                if err_msg:
                    check_billing_error(err_msg)
                    err_reason = data.get("errReason", "")
                    detail = err_msg
                    if err_reason:
                        detail += f"（原因: {err_reason}）"
                    raise RuntimeError(f"语音合成失败: {detail}")

                full = data.get("full", {})
                audio_url = full.get("url", "")
                duration = full.get("duration", 0)

                if not audio_url:
                    raise RuntimeError(f"语音合成完成但未返回音频URL，task_id: {task_id}")

                logger.info("语音合成完成！时长: %.1f秒", duration)
                return audio_url, duration
            elif status == 1:
                poll_count += 1
                if poll_count <= 6:
                    estimated_pct = min(90, poll_count * 15)
                else:
                    estimated_pct = min(95, 90 + (poll_count - 6))
                if on_progress:
                    on_progress("语音合成", estimated_pct, "语音合成中...")
                sleep_time = 3 if poll_count <= 10 else 5
                time.sleep(sleep_time)
            else:
                poll_count += 1
                logger.warning("语音合成返回未知状态: %d", status)
                time.sleep(5)
