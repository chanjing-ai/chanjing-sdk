"""
声音克隆结果缓存。

缓存 key = md5(音频文件内容) + model_type
缓存 value = voice_id（蝉镜平台返回的克隆声音 ID）

同一个音频文件 + 同一个模型，克隆结果相同，无需重复克隆。
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Optional

logger = logging.getLogger("chanjing")


class VoiceCloneCache:
    """实例级声音克隆缓存，持久化到磁盘。"""

    def __init__(self, cache_dir: str) -> None:
        self._cache_file = os.path.join(cache_dir, "voice_clone.json")
        self._cache: Optional[dict] = None

    def _load(self) -> None:
        if self._cache is not None:
            return
        try:
            if os.path.exists(self._cache_file):
                with open(self._cache_file, "r", encoding="utf-8") as f:
                    self._cache = json.load(f)
            else:
                self._cache = {}
        except Exception:
            self._cache = {}

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._cache_file), exist_ok=True)
            with open(self._cache_file, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning("保存声音克隆缓存失败: %s", e)

    @staticmethod
    def _make_key(file_hash: str, model_type: str) -> str:
        return f"{file_hash}_{model_type}"

    def get(self, file_hash: str, model_type: str) -> Optional[str]:
        """查询缓存，返回 voice_id 或 None。"""
        self._load()
        assert self._cache is not None
        key = self._make_key(file_hash, model_type)
        entry = self._cache.get(key)
        if entry:
            return entry.get("voice_id")
        return None

    def put(self, file_hash: str, model_type: str, voice_id: str) -> None:
        """写入缓存。"""
        self._load()
        assert self._cache is not None
        key = self._make_key(file_hash, model_type)
        self._cache[key] = {
            "voice_id": voice_id,
            "model_type": model_type,
            "created_at": time.time(),
        }
        self._save()

    def remove(self, file_hash: str, model_type: str) -> None:
        """删除某条缓存。"""
        self._load()
        assert self._cache is not None
        key = self._make_key(file_hash, model_type)
        if key in self._cache:
            del self._cache[key]
            self._save()
