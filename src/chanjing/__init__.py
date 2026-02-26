"""
蝉镜 AI Python SDK

用法:
    from chanjing import CicadaClient

    client = CicadaClient(app_id="xxx", secret_key="yyy")
    result = client.lip_sync(video="video.mp4", audio="audio.wav")
"""

from .client import CicadaClient
from .services.lip_sync import LipSyncResult
from .services.tts import TTSResult

__version__ = "1.0.0"
__all__ = ["CicadaClient", "LipSyncResult", "TTSResult", "__version__"]
