"""
HTTP 请求封装：带重试、频率控制、文件上传。
"""

from __future__ import annotations

import logging
import os
import time
from typing import TYPE_CHECKING, Any, Callable, Optional

import requests

from .utils import format_file_size

if TYPE_CHECKING:
    from .auth import AuthManager

logger = logging.getLogger("chanjing")

BASE_URL = "https://open-api.chanjing.cc"


# ────────────────────────── 频率控制 ──────────────────────────

class RateLimiter:
    """
    按接口类别分别控制请求频率。
    实例级别（非全局），每个 ApiClient 拥有独立的 RateLimiter。
    """

    INTERVALS = {
        "lip_sync": 6.0,
        "voice_clone": 6.0,
        "tts": 0.5,
        "default": 1.0,
    }

    def __init__(self) -> None:
        self._timestamps: dict[str, float] = {}

    def wait(self, category: str = "default", silent: bool = False) -> None:
        interval = self.INTERVALS.get(category, self.INTERVALS["default"])
        last_time = self._timestamps.get(category, 0)
        elapsed = time.time() - last_time

        if elapsed < interval:
            wait_time = interval - elapsed
            if not silent:
                logger.debug("频率控制(%s)：等待 %.1fs", category, wait_time)
            time.sleep(wait_time)

        self._timestamps[category] = time.time()


# ────────────────────────── 上传进度包装器 ──────────────────────────

class UploadProgress:
    """将 bytes 包装为可读对象，requests 分块读取时触发进度回调。"""

    def __init__(
        self,
        data: bytes,
        desc: str = "上传",
        on_progress: Optional[Callable[[int, str], None]] = None,
    ) -> None:
        self._data = data
        self._total = len(data)
        self._pos = 0
        self._desc = desc
        self._last_pct = -20
        self._on_progress = on_progress

    def read(self, size: int = -1) -> bytes:
        if self._pos >= self._total:
            return b""
        if size == -1 or size is None:
            chunk = self._data[self._pos:]
            self._pos = self._total
        else:
            end = min(self._pos + size, self._total)
            chunk = self._data[self._pos:end]
            self._pos = end

        if self._total > 0:
            pct = int(self._pos / self._total * 100)
            if pct >= self._last_pct + 20 or pct >= 100:
                msg = f"{self._desc}: {pct}%"
                logger.info(
                    "%s (%s/%s)",
                    msg,
                    format_file_size(self._pos),
                    format_file_size(self._total),
                )
                self._last_pct = pct
                if self._on_progress:
                    self._on_progress(pct, msg)

        return chunk

    def __len__(self) -> int:
        return self._total


# ────────────────────────── API 客户端 ──────────────────────────

class ApiClient:
    """
    底层 HTTP 客户端，封装重试、频率控制和业务状态码检查。

    通过注入 AuthManager 实现 Token 过期自动刷新。
    """

    def __init__(self, auth: AuthManager) -> None:
        self._auth = auth
        self._rate_limiter = RateLimiter()

    # ── 基础 HTTP 请求 ──

    def request(
        self,
        method: str,
        url: str,
        *,
        max_retries: int = 3,
        retry_delay: int = 3,
        rate_category: str = "default",
        silent_rate: bool = False,
        **kwargs: Any,
    ) -> requests.Response:
        """带重试和频率控制的 HTTP 请求。"""
        self._rate_limiter.wait(rate_category, silent=silent_rate)

        last_exception: Optional[Exception] = None
        for attempt in range(1, max_retries + 1):
            try:
                if "timeout" not in kwargs:
                    kwargs["timeout"] = 30
                response = requests.request(method, url, **kwargs)
                response.raise_for_status()
                return response
            except requests.exceptions.ConnectionError as e:
                last_exception = e
                if attempt < max_retries:
                    logger.warning("网络连接失败，%ds后重试 (%d/%d)", retry_delay, attempt, max_retries)
                    time.sleep(retry_delay)
            except requests.exceptions.Timeout as e:
                last_exception = e
                if attempt < max_retries:
                    logger.warning("请求超时，%ds后重试 (%d/%d)", retry_delay, attempt, max_retries)
                    time.sleep(retry_delay)
            except requests.exceptions.HTTPError:
                raise
            except Exception:
                raise

        raise ConnectionError(f"请求失败（已重试{max_retries}次）: {last_exception}")

    # ── JSON 业务请求 ──

    def json_request(
        self,
        method: str,
        url: str,
        *,
        rate_category: str = "default",
        silent_rate: bool = False,
        _retried_auth: bool = False,
        **kwargs: Any,
    ) -> dict:
        """发送请求并解析 JSON，检查业务状态码，Token 过期时自动刷新。"""
        response = self.request(
            method, url,
            rate_category=rate_category,
            silent_rate=silent_rate,
            **kwargs,
        )
        result = response.json()
        code = result.get("code")

        if code == 0:
            return result

        msg = result.get("msg", "未知错误")

        if code in (10400, 10401) and not _retried_auth:
            logger.warning("AccessToken 已失效 (code=%d)，正在自动刷新...", code)
            self._auth.reset()
            new_token = self._auth.get_token(self)
            headers = kwargs.get("headers", {})
            if isinstance(headers, dict) and "access_token" in headers:
                headers = dict(headers)
                headers["access_token"] = new_token
                kwargs["headers"] = headers
            return self.json_request(
                method, url,
                rate_category=rate_category,
                silent_rate=silent_rate,
                _retried_auth=True,
                **kwargs,
            )

        if code in (10400, 10401):
            raise PermissionError(
                f"AccessToken 验证失败 (code={code}): {msg}\n"
                f"请检查 app_id / secret_key 是否正确。\n"
                f"获取凭证: https://www.chanjing.cc/platform/api_keys"
            )

        raise RuntimeError(f"API 请求失败 (code={code}): {msg}")

    # ── 文件上传 ──

    def upload_file(
        self,
        file_path: str,
        service: str,
        access_token: str,
        on_progress: Optional[Callable[[int, str], None]] = None,
    ) -> dict[str, str]:
        """
        两步上传文件到蝉镜平台 + 轮询文件同步状态。

        返回 {"file_id": "...", "url": "..."}
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")

        file_name = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        file_label = "视频" if "video" in service else "音频"

        logger.info("开始上传%s: %s (%s)", file_label, file_name, format_file_size(file_size))

        # 步骤1：获取上传地址
        result = self.json_request(
            "GET",
            f"{BASE_URL}/open/v1/common/create_upload_url",
            rate_category="default",
            params={"service": service, "name": file_name},
            headers={"access_token": access_token},
        )

        upload_data = result.get("data", {})
        sign_url = upload_data.get("sign_url")
        file_id = upload_data.get("file_id")
        file_url = upload_data.get("full_path", "")
        mime_type = upload_data.get("mime_type", "application/octet-stream")

        # 步骤2：PUT 上传
        with open(file_path, "rb") as f:
            file_data = f.read()
        data_size = len(file_data)

        upload_body = UploadProgress(file_data, f"上传{file_label}", on_progress=on_progress)

        response = self.request(
            "PUT", sign_url,
            max_retries=2,
            rate_category="default",
            headers={
                "Content-Type": mime_type,
                "Content-Length": str(data_size),
            },
            data=upload_body,
            timeout=(15, 120),
        )

        if response.status_code != 200:
            raise RuntimeError(f"文件上传失败: HTTP {response.status_code}")

        logger.info("%s上传成功，file_id=%s", file_label, file_id)

        # 轮询文件同步状态
        self._poll_file_status(file_id, access_token)

        return {"file_id": file_id, "url": file_url}

    def _poll_file_status(
        self,
        file_id: str,
        access_token: str,
        poll_interval: int = 3,
        max_wait: int = 90,
    ) -> None:
        """轮询文件状态，等待服务器同步完成（status=1）。"""
        start = time.time()
        while True:
            elapsed = time.time() - start
            if elapsed > max_wait:
                raise TimeoutError(f"文件同步超时（已等待 {int(elapsed)}s），file_id: {file_id}")
            time.sleep(poll_interval)
            try:
                detail = self.json_request(
                    "GET",
                    f"{BASE_URL}/open/v1/common/file_detail",
                    rate_category="default",
                    silent_rate=True,
                    params={"id": file_id},
                    headers={"access_token": access_token},
                )
                status = detail.get("data", {}).get("status", 0)
                if status == 1:
                    logger.info("文件同步完成（耗时 %ds）", int(time.time() - start))
                    return
                if status in (98, 99, 100):
                    status_msg = {98: "内容安全检测失败", 99: "文件已删除", 100: "文件已清理"}
                    raise RuntimeError(f"文件不可用 (status={status}): {status_msg.get(status, '未知')}")
            except TimeoutError:
                raise
            except RuntimeError:
                raise
            except Exception as e:
                logger.warning("查询文件状态失败: %s，继续等待...", e)


# ────────────────────────── 业务工具 ──────────────────────────

BILLING_KEYWORDS = ("扣费失败", "余额不足", "蝉豆不足", "蝉豆余额", "欠费")


def check_billing_error(msg: str) -> None:
    """检测扣费失败相关错误，抛出包含充值引导的异常。"""
    if not msg:
        return
    if any(kw in msg for kw in BILLING_KEYWORDS):
        raise RuntimeError(
            f"蝉豆余额不足，扣费失败\n"
            f"请前往蝉镜平台充值: https://www.chanjing.cc\n"
            f"API 返回: {msg}"
        )
