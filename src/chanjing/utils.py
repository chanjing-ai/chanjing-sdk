"""
工具函数：文件哈希、音频时长检测、音频裁剪、格式化等。
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from typing import Optional

try:
    from mutagen import File as MutagenFile
    _MUTAGEN_AVAILABLE = True
except ImportError:
    _MUTAGEN_AVAILABLE = False

try:
    import cv2
    _CV2_AVAILABLE = True
except ImportError:
    _CV2_AVAILABLE = False


def file_content_hash(file_path: str) -> str:
    """计算文件内容的 MD5 哈希值。"""
    h = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def format_file_size(size_bytes: float) -> str:
    """格式化文件大小为人类可读字符串。"""
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"


def format_duration(seconds: Optional[float]) -> str:
    """格式化时长（秒 -> 分:秒）。"""
    if seconds is None:
        return "未知"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}:{secs:02d}"


def get_audio_duration(file_path: str) -> Optional[float]:
    """
    获取音频文件时长（秒）。
    优先使用 mutagen，否则回退到 scipy（仅 wav）。
    """
    if not os.path.exists(file_path):
        return None

    if _MUTAGEN_AVAILABLE:
        try:
            audio = MutagenFile(file_path)
            if audio is not None and hasattr(audio.info, "length"):
                return audio.info.length
        except Exception:
            pass

    try:
        from scipy.io import wavfile
        sample_rate, data = wavfile.read(file_path)
        return len(data) / float(sample_rate)
    except Exception:
        pass

    return None


def trim_audio(file_path: str, max_duration: int = 299) -> Optional[str]:
    """
    使用系统 ffmpeg 裁剪音频到指定时长。
    返回裁剪后的临时文件路径，失败返回 None。
    """
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        return None

    ext = os.path.splitext(file_path)[1] or ".wav"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
    tmp.close()

    try:
        result = subprocess.run(
            [ffmpeg_path, "-i", file_path, "-t", str(max_duration), "-y", tmp.name],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0 and os.path.exists(tmp.name) and os.path.getsize(tmp.name) > 0:
            return tmp.name
        return None
    except Exception:
        return None


def get_video_dimensions(video_path: str) -> tuple[Optional[int], Optional[int]]:
    """
    使用 opencv 获取视频宽高。需要安装 opencv-python（可选依赖）。
    返回 (width, height)，不可用时返回 (None, None)。
    """
    if not _CV2_AVAILABLE:
        return None, None
    cap = None
    try:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return None, None
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        return (w, h) if w > 0 and h > 0 else (None, None)
    except Exception:
        return None, None
    finally:
        if cap is not None:
            cap.release()


def infer_extension_from_url(url: str, default: str = ".mp3") -> str:
    """从 URL 路径推断文件扩展名。"""
    url_path = url.split("?")[0]
    for ext in (".mp3", ".wav", ".m4a", ".ogg", ".flac", ".mp4"):
        if url_path.lower().endswith(ext):
            return ext
    return default
