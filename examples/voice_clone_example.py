"""
声音克隆 + 语音合成示例。

用法:
    python voice_clone_example.py

运行前请确保：
1. 已安装 SDK:  pip install -e ../
2. 已配置凭证（见 lip_sync_example.py 说明）
"""

from chanjing import CicadaClient


def progress_callback(stage: str, percent: int, message: str) -> None:
    print(f"  [{stage}] {percent}% - {message}")


def main() -> None:
        # 初始化客户端（凭证也可通过环境变量或配置文件提供）
    client = CicadaClient(
        app_id="your-app-id",
        secret_key="your-secret-key",
    )

    # ── 方式一：一步完成（声音克隆 + 语音合成） ──
    print("=" * 50)
    print("方式一：voice_clone_and_speak（一步到位）")
    print("=" * 50)

    result = client.voice_clone_and_speak(
        reference_audio="./sample_audio.wav",
        text="你好，这是用蝉镜AI克隆的声音合成的语音。",
        model="cicada3.0-turbo",
        speed=1.0,
        pitch=1.0,
        on_progress=progress_callback,
    )

    print(f"\n音频URL: {result.audio_url}")
    print(f"时长:    {result.duration:.1f}秒")
    result.download("./output_clone_speak.mp3")
    print("已保存到 ./output_clone_speak.mp3")

    # ── 方式二：分步调用 ──
    print("\n" + "=" * 50)
    print("方式二：分步调用（先克隆，再合成）")
    print("=" * 50)

    # 第一步：克隆声音（结果会自动缓存）
    voice_id = client.clone_voice(
        reference_audio="./sample_audio.wav",
        model="cicada3.0-turbo",
        on_progress=progress_callback,
    )
    print(f"\n声音ID: {voice_id}")

    # 第二步：用克隆的声音合成多段语音
    for i, text in enumerate(["第一段测试语音。", "第二段测试语音，语速加快。"], 1):
        result = client.tts(
            voice_id=voice_id,
            text=text,
            speed=1.0 + (i - 1) * 0.3,
            on_progress=progress_callback,
        )
        output_path = f"./output_tts_{i}.mp3"
        result.download(output_path)
        print(f"第{i}段已保存到 {output_path}（时长: {result.duration:.1f}秒）")


if __name__ == "__main__":
    main()
