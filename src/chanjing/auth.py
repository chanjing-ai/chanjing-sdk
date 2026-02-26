"""
鉴权管理：Token 获取、缓存、自动刷新。

支持三种凭证来源（优先级从高到低）：
1. 构造函数参数
2. 环境变量 CHANJING_APP_ID / CHANJING_SECRET_KEY
3. 配置文件 ~/.chanjing/config.json
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .api import ApiClient

logger = logging.getLogger("chanjing")

_DEFAULT_CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".chanjing")
_DEFAULT_CONFIG_FILE = os.path.join(_DEFAULT_CONFIG_DIR, "config.json")


class AuthManager:
    """
    实例级鉴权管理器。

    - 通过构造参数 / 环境变量 / 配置文件获取凭证
    - Token 缓存到磁盘（~/.chanjing/cache/token.json），24h 有效
    - 凭证变更自动作废旧 Token
    - Token 过期前 5 分钟自动刷新
    """

    def __init__(
        self,
        app_id: Optional[str] = None,
        secret_key: Optional[str] = None,
        cache_dir: Optional[str] = None,
    ) -> None:
        self._app_id, self._secret_key = self._resolve_credentials(app_id, secret_key)
        self._cache_dir = cache_dir or os.path.join(_DEFAULT_CONFIG_DIR, "cache")
        self._token_cache_file = os.path.join(self._cache_dir, "token.json")

        self._config_hash = self._compute_hash(self._app_id, self._secret_key)
        self._token: Optional[str] = None
        self._token_expire: float = 0
        self._token_config_hash: Optional[str] = None

    # ── 凭证解析 ──

    @staticmethod
    def _resolve_credentials(
        app_id: Optional[str],
        secret_key: Optional[str],
    ) -> tuple[str, str]:
        """按优先级解析凭证：参数 > 环境变量 > 配置文件。"""
        # 1. 构造参数
        if app_id and secret_key:
            return app_id.strip(), secret_key.strip()

        # 2. 环境变量
        env_app_id = os.environ.get("CHANJING_APP_ID", "").strip()
        env_secret = os.environ.get("CHANJING_SECRET_KEY", "").strip()
        if env_app_id and env_secret:
            return env_app_id, env_secret

        # 3. 配置文件
        if os.path.exists(_DEFAULT_CONFIG_FILE):
            try:
                with open(_DEFAULT_CONFIG_FILE, "r", encoding="utf-8") as f:
                    config = json.load(f)
                file_app_id = config.get("app_id", "").strip()
                file_secret = config.get("secret_key", "").strip()
                if file_app_id and file_secret:
                    return file_app_id, file_secret
            except Exception:
                pass

        raise ValueError(
            "未找到蝉镜 AI 凭证。请通过以下任一方式配置：\n"
            "  1. CicadaClient(app_id='...', secret_key='...')\n"
            "  2. 设置环境变量 CHANJING_APP_ID 和 CHANJING_SECRET_KEY\n"
            "  3. 创建配置文件 ~/.chanjing/config.json\n"
            "获取凭证: https://www.chanjing.cc/platform/api_keys"
        )

    @staticmethod
    def _compute_hash(app_id: str, secret_key: str) -> str:
        return hashlib.md5(f"{app_id}:{secret_key}".encode()).hexdigest()

    # ── Token 缓存 ──

    def _load_token_cache(self) -> None:
        try:
            if os.path.exists(self._token_cache_file):
                with open(self._token_cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._token = data.get("access_token")
                    self._token_expire = data.get("expire_time", 0)
                    self._token_config_hash = data.get("config_hash")
        except Exception:
            self._token = None
            self._token_expire = 0
            self._token_config_hash = None

    def _save_token_cache(self) -> None:
        try:
            os.makedirs(self._cache_dir, exist_ok=True)
            with open(self._token_cache_file, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "access_token": self._token,
                        "expire_time": self._token_expire,
                        "config_hash": self._config_hash,
                    },
                    f,
                    indent=2,
                )
        except Exception as e:
            logger.warning("保存 token 缓存失败: %s", e)

    # ── 核心方法 ──

    def _config_changed(self) -> bool:
        return self._config_hash != self._token_config_hash

    def _refresh_token(self, api: ApiClient) -> None:
        """向蝉镜 API 请求新 token。"""
        from .api import BASE_URL

        logger.info("正在获取 AccessToken...")
        result = api.json_request(
            "POST",
            f"{BASE_URL}/open/v1/access_token",
            _retried_auth=True,
            json={"app_id": self._app_id, "secret_key": self._secret_key},
        )
        data = result.get("data", {})
        self._token = data.get("access_token")
        self._token_expire = time.time() + 24 * 3600
        self._token_config_hash = self._config_hash

        if not self._token:
            raise RuntimeError("API 返回的 access_token 为空，请检查 app_id / secret_key 是否正确")

        self._save_token_cache()
        logger.info("AccessToken 获取成功并已缓存")

    def get_token(self, api: ApiClient) -> str:
        """
        获取有效的 AccessToken。

        优先使用内存/磁盘缓存，过期前 5 分钟自动刷新。
        """
        now = time.time()

        if self._config_changed():
            self._token = None
            self._token_expire = 0
            self._token_config_hash = None

        if self._token and now < self._token_expire - 300:
            return self._token

        if self._token is None:
            self._load_token_cache()
            if self._token and now < self._token_expire - 300 and not self._config_changed():
                logger.debug("使用缓存的 AccessToken")
                return self._token
            if self._config_changed():
                self._token = None
                self._token_expire = 0
                self._token_config_hash = None

        self._refresh_token(api)
        return self._token  # type: ignore[return-value]

    def reset(self) -> None:
        """重置鉴权状态，强制下次刷新 Token。"""
        self._token = None
        self._token_expire = 0
        self._token_config_hash = None
