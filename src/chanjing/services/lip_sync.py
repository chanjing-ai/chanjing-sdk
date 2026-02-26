"""
对口型服务：上传视频+音频 → 创建任务 → 轮询 → 返回结果视频 URL。
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Callable, Optional

from ..api import BASE_URL, ApiClient, check_billing_error
from ..utils import get_video_dimensions

logger = logging.getLogger("chanjing")


@dataclass
class LipSyncResult:
    """对口型任务结果。"""

    video_url: str
    task_id: str
    duration_ms: int = 0

    def download(self, path: str) -> str:
        """下载结果视频到本地文件。"""
        import requests as _requests

        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        response = _requests.get(self.video_url, stream=True, timeout=300)
        response.raise_for_status()
        with open(path, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
        logger.info("视频已下载到 %s", path)
        return path


class LipSyncService:
    """对口型业务逻辑。"""

    def __init__(self, api: ApiClient) -> None:
        self._api = api

    def create(
        self,
        video_path: str,
        audio_path: str,
        access_token: str,
        *,
        model: str = "pro",
        backway: str = "forward",
        drive_mode: str = "normal",
        on_progress: Optional[Callable[[str, int, str], None]] = None,
    ) -> LipSyncResult:
        """
        创建对口型任务并等待完成。

        Args:
            video_path: 本地视频文件路径
            audio_path: 本地音频文件路径
            access_token: 平台 access_token
            model: "standard" 或 "pro"
            backway: "forward"（正放）或 "reverse"（倒放）
            drive_mode: "normal"（正常驱动）或 "random"（随机帧驱动）
            on_progress: 可选进度回调 (stage, percent, message)
        """
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"视频文件不存在: {video_path}")
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"音频文件不存在: {audio_path}")

        def _progress(stage: str, pct: int, msg: str) -> None:
            if on_progress:
                on_progress(stage, pct, msg)

        _progress("准备", 0, "检测视频参数...")

        w, h = get_video_dimensions(video_path)
        if not w or not h:
            w, h = 1080, 1920
            logger.info("无法检测视频尺寸，使用默认值 %dx%d", w, h)
        else:
            logger.info("视频尺寸: %dx%d", w, h)

        backway_value = 2 if backway == "reverse" else 1
        drive_mode_value = "random" if drive_mode == "random" else ""
        model_value = 1 if model == "pro" else 0

        # 上传视频
        _progress("上传视频", 0, "上传视频中...")

        def _on_video_upload(pct: int, msg: str) -> None:
            _progress("上传视频", pct, msg)

        video_result = self._api.upload_file(
            video_path, "lip_sync_video", access_token,
            on_progress=_on_video_upload,
        )

        # 上传音频
        _progress("上传音频", 0, "上传音频中...")

        def _on_audio_upload(pct: int, msg: str) -> None:
            _progress("上传音频", pct, msg)

        audio_result = self._api.upload_file(
            audio_path, "lip_sync_audio", access_token,
            on_progress=_on_audio_upload,
        )

        # 创建任务
        _progress("视频合成", 0, "创建任务...")
        result = self._api.json_request(
            "POST",
            f"{BASE_URL}/open/v1/video_lip_sync/create",
            rate_category="lip_sync",
            silent_rate=True,
            json={
                "video_file_id": video_result["file_id"],
                "audio_type": "audio",
                "audio_file_id": audio_result["file_id"],
                "model": model_value,
                "screen_width": w,
                "screen_height": h,
                "backway": backway_value,
                "drive_mode": drive_mode_value,
            },
            headers={"access_token": access_token, "Content-Type": "application/json"},
        )
        task_id = result.get("data")
        logger.info("对口型任务创建成功，task_id=%s", task_id)

        # 轮询结果
        video_url, duration_ms = self._poll(task_id, access_token, on_progress)

        _progress("完成", 100, "对口型任务完成")
        return LipSyncResult(video_url=video_url, task_id=task_id, duration_ms=duration_ms)

    def _poll(
        self,
        task_id: str,
        access_token: str,
        on_progress: Optional[Callable[[str, int, str], None]] = None,
        max_wait: int = 1800,
    ) -> tuple[str, int]:
        """轮询对口型任务状态，返回 (video_url, duration_ms)。"""
        start = time.time()
        last_progress = -1
        last_status = -1

        logger.info("等待视频合成...")
        while True:
            if time.time() - start > max_wait:
                raise TimeoutError(f"对口型任务超时（{max_wait}秒），task_id: {task_id}")

            result = self._api.json_request(
                "GET",
                f"{BASE_URL}/open/v1/video_lip_sync/detail",
                rate_category="default",
                silent_rate=True,
                params={"id": task_id},
                headers={"access_token": access_token},
            )
            data = result.get("data", {})
            status = data.get("status")
            api_progress = data.get("progress", 0)
            msg = data.get("msg", "")

            if status != last_status or api_progress != last_progress:
                status_text = {0: "排队中", 10: "生成中", 20: "成功", 30: "失败"}.get(status, f"未知({status})")
                logger.info("视频合成: %d%% - %s", api_progress, status_text)
                if on_progress:
                    on_progress("视频合成", api_progress, status_text)
                last_status = status
                last_progress = api_progress

            if status == 20:
                video_url = data.get("video_url", "")
                if not video_url:
                    raise RuntimeError("视频合成完成但未返回视频URL")
                duration_ms = data.get("duration", 0)
                logger.info("视频合成完成！时长: %.1f秒", duration_ms / 1000 if duration_ms else 0)
                return video_url, duration_ms
            elif status == 30:
                check_billing_error(msg)
                raise RuntimeError(f"视频合成失败: {msg}")

            time.sleep(5)
