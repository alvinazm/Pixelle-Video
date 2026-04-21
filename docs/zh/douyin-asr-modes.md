# 抖音视频文案提取 — ASR 模式开发说明

## 三种实现方案概览

| 模式 | 实现方式 | 核心依赖 | 代表模型 |
|------|----------|----------|----------|
| 本地模式 | faster-whisper | 无 | base / small / medium |
| API-Transcription | `dashscope.audio.asr.Transcription` | dashscope SDK | paraformer-v2 |
| API-ChatCompletion | Chat Completions 音频消息 | httpx + ffmpeg | qwen3-asr-flash |

---

## 模式一：本地模式（faster-whisper）

### 实现原理

纯本地推理，无需网络请求。流程：下载视频 → ffmpeg 提取 WAV 音频 → faster-whisper 模型推理 → zhconv 转简体。

### 核心代码

```python
from faster_whisper import WhisperModel

model = WhisperModel("base", device="auto", compute_type="auto")
segments, info = model.transcribe("audio.wav", language="zh", beam_size=5)
text = "".join(seg.text for seg in segments)
text = zhconv.convert(text, "zh-hans")  # 繁体转简体
```

### 优势

- **完全免费**，无 API 调用费用
- **无时长限制**，本地 GPU/CPU 任意跑
- **无网络依赖**，离线可用
- **隐私安全**，视频不上传任何服务器

### 劣势

- **首次加载慢**，base 模型约 1-2GB，需下载模型文件
- **推理速度依赖硬件**，CPU 推理 RTF 通常 0.1x（1分钟音频需10分钟）
- **GPU 效果好**，无显卡机器体验差
- **模型质量有限**，faster-whisper base 对口音/噪音敏感

### 适用场景

- 零成本、隐私敏感、无网络环境
- 视频时长 < 2 分钟（CPU 推理可接受范围）

---

## 模式二：API-Transcription（paraformer-v2）

### 实现原理

调用 DashScope 原生 ASR API，传入视频 URL，服务器端自动下载并转写。异步任务模式，支持轮询等待结果。

### 核心代码

```python
import dashscope
from http import HTTPStatus
from urllib import request

dashscope.api_key = api_key

# 发起异步任务
task = dashscope.audio.asr.Transcription.async_call(
    model="paraformer-v2",
    file_urls=[video_url],
    language_hints=["zh"],
)
task_id = task.output["task_id"]

# 轮询等待完成
for _ in range(60):
    result = dashscope.audio.asr.Transcription.wait(task=task_id)
    if result.output["task_status"] == "SUCCEEDED":
        break
    if result.output["task_status"] == "FAILED":
        raise RuntimeError(result.output["message"])
    time.sleep(2)

# 获取结果
result_url = result.output["results"][0]["transcription_url"]
raw = json.loads(request.urlopen(result_url).read().decode())
text = raw["transcripts"][0]["text"]
```

### 优势

- **无时长限制**，DashScope 官方处理长音频自动分段
- **代码最简洁**，无需本地 ffmpeg、无需 base64、无需分段逻辑
- **服务器端处理**，视频 URL 直传，阿里云下载
- **专项 ASR 模型**，paraformer-v2 针对中文语音优化
- **无本地资源占用**，不消耗 CPU/GPU

### 劣势

- **依赖 DashScope 下载能力**，抖音视频 URL 需能被阿里云服务器访问
- **总耗时略长**（~22s vs ~16s），含服务器下载 + 推理 + 排队
- **有 API 费用**，按音频时长计费
- **视频 URL 有效期**，抖音 CDN 链接可能过期

### 适用场景

- 视频时长 > 4 分钟（超过 qwen3-asr-flash 限制）
- 有 DashScope 账号，API 费用可接受
- 希望代码最简、无本地依赖

---

## 模式三：API-ChatCompletion（qwen3-asr-flash）

### 实现原理

将音频转为 base64，通过 Chat Completions API 的 `input_audio` 消息格式发送给 LLM，由 LLM 做语音识别。需本地下载 + ffmpeg 转码 + base64 编码。

### 核心代码

```python
import base64, subprocess, httpx

# 1. 流式下载 + 转 MP3 32kbps（避免超过6MB限制）
proc = subprocess.Popen([
    "ffmpeg", "-i", video_url, "-vn",
    "-acodec", "libmp3lame", "-b:a", "32k",
    "-ar", "16000", "-ac", "1", "audio.mp3"
], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
proc.wait()

# 2. base64 编码
audio_b64 = base64.b64encode(Path("audio.mp3").read_bytes()).decode()

# 3. 发送 Chat Completions
payload = {
    "model": "qwen3-asr-flash",
    "messages": [{"role": "user", "content": [{
        "type": "input_audio",
        "input_audio": f"data:audio/mpeg;base64,{audio_b64}"
    }]}],
    "stream": False,
}
resp = httpx.post(endpoint, json=payload, headers=headers, timeout=120)
text = resp.json()["choices"][0]["message"]["content"]
```

### 优势

- **速度快**，绕过了专项 ASR，直接用 LLM 做识别，总耗时 ~16s
- **支持更长音频**，通过分段处理可支持 ~30 分钟（270s/段 × 多段）
- **API 费用低**，qwen3-asr-flash 价格远低于 paraformer-v2
- **可本地缓存音频**，下载后可复用

### 劣势

- **本地处理复杂**，需 ffmpeg、流式下载、base64 编码
- **有 6MB 请求体限制**，需压缩音频（MP3 32kbps）
- **有 270s 单次限制**，需手动分段拼接
- **依赖视频 CDN 可访问**，本地下载可能比 DashScope 慢

### 适用场景

- 视频时长 4-30 分钟
- 追求最快速度，愿意本地处理
- DashScope 账号费用敏感

---

## 三模式横向对比

| 维度 | 本地 faster-whisper | API paraformer-v2 | API qwen3-asr-flash |
|------|---------------------|-------------------|---------------------|
| **费用** | 免费 | 按音频时长计费 | 按 token/音频计费 |
| **时长限制** | 无 | 无 | 270s/段（可分段） |
| **总耗时（约2分钟音频）** | ~60s（CPU） | ~22s | ~16s |
| **本地依赖** | ffmpeg + 模型文件 | 无 | ffmpeg |
| **网络依赖** | 仅下载视频 | 需 DashScope 能访问 URL | 仅下载视频 |
| **代码复杂度** | 中 | 低 | 高 |
| **首次加载** | 慢（下载模型） | 无 | 无 |
| **离线可用** | ✅ | ❌ | ❌ |
| **隐私** | 最优（完全本地） | 视频上传阿里云 | 视频上传本地服务器 |
| **长音频（>10分钟）** | CPU 慢，不推荐 | ✅ 推荐 | ✅ 可行 |

---

## 推荐选择

```
视频 < 2 分钟 + 无网络/隐私敏感 → 本地模式（faster-whisper）
视频 > 4 分钟 + 追求简洁 → API-Transcription（paraformer-v2）
视频 2-30 分钟 + 追求速度 → API-ChatCompletion（qwen3-asr-flash）
```

当前实现（`web/pipelines/douyin_parser.py`）同时支持本地模式和 API-Transcription，用户可在页面自由切换。API-ChatCompletion（qwen3-asr-flash）已移除但代码保留，如需恢复可参考上述核心代码。
