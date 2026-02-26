"""
对口型示例：音频驱动视频对口型。

用法:
    python lip_sync_example.py

运行前请确保：
1. 已安装 SDK:  pip install -e ../
2. 已配置凭证（任选其一）:

   - 设置环境变量: export CHANJING_APP_ID=xxx CHANJING_SECRET_KEY=yyy
   - 或创建 ~/.chanjing/config.json: {"app_id": "xxx", "secret_key": "yyy"}
   - 或直接在代码中传入 app_id 和 secret_key
"""

from chanjing import CicadaClient


def progress_callback(stage: str, percent: int, message: str) -> None:
    """进度回调示例：打印进度信息。"""
    print(f"  [{stage}] {percent}% - {message}")


def main() -> None:
    # 初始化客户端（凭证也可通过环境变量或配置文件提供）
    client = CicadaClient(
        app_id="your-app-id",
        secret_key="your-secret-key",
    )

    # 创建对口型任务
    result = client.lip_sync(
        video="./sample_video.mp4",
        audio="./sample_audio.wav",
        model="pro",            # "standard" 或 "pro"
        backway="forward",      # "forward"（正放）或 "reverse"（倒放）
        drive_mode="normal",    # "normal" 或 "random"
        on_progress=progress_callback,
    )

    print(f"\n视频URL: {result.video_url}")
    print(f"任务ID:  {result.task_id}")
    print(f"时长:    {result.duration_ms / 1000:.1f}秒")

    # 下载到本地
    result.download("./output_lip_sync.mp4")
    print("已保存到 ./output_lip_sync.mp4")


if __name__ == "__main__":
    main()
