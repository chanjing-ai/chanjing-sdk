# 蝉镜 AI Python SDK

基于[蝉镜 AI 开放平台](https://www.chanjing.cc/)的 Python SDK，支持数字人对口型、声音克隆和语音合成能力，便于快速应用于虚拟口播、课程讲解以及多种配音等场景。

## 安装

```bash
pip install chanjingsdk
```

安装可选依赖（音频时长检测、视频尺寸检测）：

```bash
pip install chanjingsdk[all]
```

从源码安装（开发模式）：

```bash
cd chanjing-sdk
pip install -e ".[all]"
```

## 配置凭证

前往 https://www.chanjing.cc/platform/api_keys 获取 App ID 和 Secret Key。

支持三种配置方式（优先级从高到低）：

**1. 构造函数参数**

```python
from chanjing import CicadaClient
client = CicadaClient(app_id="your_app_id", secret_key="your_secret_key")
```

**2. 环境变量**

```bash
export CHANJING_APP_ID=your_app_id
export CHANJING_SECRET_KEY=your_secret_key
```

```python
client = CicadaClient()  # 自动读取环境变量
```

**3. 配置文件 `~/.chanjing/config.json`**

```json
{
  "app_id": "your_app_id",
  "secret_key": "your_secret_key"
}
```

```python
client = CicadaClient()  # 自动读取配置文件
```

## 快速开始

### 对口型（音频驱动视频）

```python
from chanjing import CicadaClient

client = CicadaClient(app_id="xxx", secret_key="yyy")

result = client.lip_sync(
    video="./my_video.mp4",
    audio="./my_audio.wav",
    model="pro",           # "standard" | "pro"
    backway="forward",     # "forward" | "reverse"
)

print(result.video_url)
result.download("./output.mp4")
```

### 声音克隆 + 语音合成（一步完成）

```python
result = client.voice_clone_and_speak(
    reference_audio="./reference.mp3",   # 参考音频（15秒-5分钟）
    text="你好，这是克隆的声音。",
    model="cicada3.0-turbo",
    speed=1.0,
    pitch=1.0,
)

print(result.audio_url)
result.download("./output.mp3")
```

### 分步调用（先克隆，再合成）

```python
# 第一步：克隆声音（结果自动缓存）
voice_id = client.clone_voice(
    reference_audio="./reference.mp3",
    model="cicada3.0-turbo",
)

# 第二步：用克隆的声音合成语音（可多次调用）
result = client.tts(voice_id=voice_id, text="你好世界")
result.download("./hello.mp3")

result2 = client.tts(voice_id=voice_id, text="再见世界", speed=1.2)
result2.download("./goodbye.mp3")
```

## 进度回调

所有方法都支持 `on_progress` 回调：

```python
def my_progress(stage: str, percent: int, message: str):
    print(f"[{stage}] {percent}% - {message}")

result = client.lip_sync(
    video="video.mp4",
    audio="audio.wav",
    on_progress=my_progress,
)
```

## API 参考

### `CicadaClient(app_id, secret_key, cache_dir, log_level)`

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `app_id` | str | None | 蝉镜平台 App ID |
| `secret_key` | str | None | 蝉镜平台 Secret Key |
| `cache_dir` | str | `~/.chanjing/cache/` | 缓存目录 |
| `log_level` | int | `logging.INFO` | 日志级别，设 None 不修改 |

### `client.lip_sync(video, audio, model, backway, drive_mode, on_progress)`

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `video` | str | 必填 | 本地视频文件路径 |
| `audio` | str | 必填 | 本地音频文件路径 |
| `model` | str | `"pro"` | `"standard"` 或 `"pro"` |
| `backway` | str | `"forward"` | `"forward"` 或 `"reverse"` |
| `drive_mode` | str | `"normal"` | `"normal"` 或 `"random"` |

返回 `LipSyncResult`：`.video_url` `.task_id` `.duration_ms` `.download(path)`

### `client.clone_voice(reference_audio, model, use_cache, on_progress)`

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `reference_audio` | str | 必填 | 参考音频路径（15秒-5分钟） |
| `model` | str | `"cicada3.0-turbo"` | 模型类型 |
| `use_cache` | bool | `True` | 是否缓存克隆结果 |

返回 `voice_id: str`

### `client.tts(voice_id, text, speed, pitch, on_progress)`

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `voice_id` | str | 必填 | 声音 ID |
| `text` | str | 必填 | 合成文案（最多4000字） |
| `speed` | float | `1.0` | 语速（0.5-2.0） |
| `pitch` | float | `1.0` | 音调（0.1-3.0） |

返回 `TTSResult`：`.audio_url` `.task_id` `.duration` `.download(path)`

### `client.voice_clone_and_speak(reference_audio, text, model, speed, pitch, use_cache, on_progress)`

声音克隆 + 语音合成一步完成，参数同上。返回 `TTSResult`。

## 依赖

| 包 | 必需 | 说明 |
|----|------|------|
| `requests` | 是 | HTTP 请求 |
| `mutagen` | 否 | 音频时长检测（`pip install chanjing[audio]`） |
| `opencv-python` | 否 | 视频尺寸检测（`pip install chanjing[video]`） |

## 支持

- [蝉镜 AI 官网](https://www.chanjing.cc/)
- [API 文档](https://doc.chanjing.cc/)
- [凭证管理](https://www.chanjing.cc/platform/api_keys)
