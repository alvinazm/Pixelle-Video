# 抖音/快手/小红书视频文案提取 — 技术方案文档

## 整体架构

视频文案提取功能支持三大平台：**抖音**、**快手**、**小红书**，采用统一入口、差异化解析、多模式 ASR 的架构设计。

```
┌─────────────────────────────────────────────────────────────┐
│                    统一入口 (Douyin_Parser)                   │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────────┐ │
│  │   抖音解析   │  │   快手解析   │  │     小红书解析      │ │
│  │  网页抓取   │  │  网页抓取   │  │   xhs-dl API调用    │ │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬──────────┘ │
│         │                 │                      │             │
│         └─────────────────┼──────────────────────┘             │
│                           ▼                                    │
│              ┌─────────────────────────┐                     │
│              │    视频下载直链获取      │                     │
│              └───────────┬─────────────┘                     │
│                          ▼                                   │
│              ┌─────────────────────────┐                     │
│              │      ASR 语音转文字      │                     │
│              │  本地/API-Transcription │                     │
│              │     /API-ChatCompletion │                     │
│              └───────────┬─────────────┘                     │
│                          ▼                                   │
│              ┌─────────────────────────┐                     │
│              │      文案提取/改写       │                     │
│              └─────────────────────────┘                     │
└─────────────────────────────────────────────────────────────┘
```

---

## 第一部分：视频解析方案

### 1. 抖音解析

#### 核心原理
通过访问抖音分享页面，提取嵌入在 HTML 中的 `_ROUTER_DATA` JSON 数据，解析出视频元信息。

#### 技术流程
1. **短链接处理**：如果是 `v.douyin.com` 短链，先 302 跳转获取真实链接
2. **构造请求 URL**：`https://www.iesdouyin.com/share/video/{video_id}`
3. **页面抓取**：使用移动版 User-Agent 访问
4. **数据提取**：正则匹配 `window._ROUTER_DATA = {...}`
5. **视频地址获取**：从 `videoInfoRes.item_list[0].video.play_addr.url_list[0]` 提取，替换 `playwm` 为 `play` 获取无水印版本
6. **标题提取**：从 `desc` 字段获取视频描述

#### 关键代码
```python
def _get_douyin_info(url: str, t_all: float) -> dict:
    # 短链接处理
    if "v.douyin.com" in url:
        resp = client.get(url, follow_redirects=True)
        url = str(resp.url)
    
    # 构造分享页 URL
    video_id = url.split("?")[0].strip("/").split("/")[-1]
    url = f"https://www.iesdouyin.com/share/video/{video_id}"
    
    # 提取 _ROUTER_DATA
    pattern = re.compile(r"window\._ROUTER_DATA\s*=\s*(.*?)</script>", re.DOTALL)
    data = json.loads(match.group(1))
    
    # 获取视频信息
    item = data["loaderData"][info_key]["videoInfoRes"]["item_list"][0]
    video_url = item["video"]["play_addr"]["url_list"][0].replace("playwm", "play")
    title = item.get("desc", "").strip()
```

#### 技术要点
- **反爬策略**：使用移动端 UA，模拟真实设备访问
- **短链跳转**：必须跟随 302 重定向
- **水印处理**：URL 中的 `playwm` 替换为 `play` 可去除水印

---

### 2. 快手解析

#### 核心原理
通过访问快手短视频页面，提取嵌入在 HTML 中的 `__APOLLO_STATE__` GraphQL 状态数据。

#### 技术流程
1. **页面访问**：`https://www.kuaishou.com/short-video/{video_id}`
2. **数据提取**：正则匹配 `window.__APOLLO_STATE__ = {...}`
3. **视频信息定位**：在 GraphQL 缓存中查找 `__typename == "VisionVideoDetailPhoto"` 的对象
4. **多格式视频地址**：
   - 优先 `photoH265Url` (HEVC/H.265)
   - 次选 `photoUrl` (标准 URL)
   - 兜底 `videoResource.json` (嵌套 JSON 解析)
5. **标题提取**：从 `caption` 字段获取

#### 关键代码
```python
def _get_kuaishou_info(url: str, t_all: float) -> dict:
    # 提取 __APOLLO_STATE__
    pattern = re.compile(r"window\.__APOLLO_STATE__\s*=\s*(\{[\s\S]*?\})\s*;")
    data = json.loads(match.group(1))
    
    # 查找视频对象
    photo_key = next(
        k for k, v in client_data.items()
        if isinstance(v, dict) and v.get("__typename") == "VisionVideoDetailPhoto"
    )
    photo = client_data[photo_key]
    
    # 多级视频地址获取
    video_url = photo.get("photoH265Url") or photo.get("photoUrl")
    if not video_url and photo.get("videoResource"):
        # 解析嵌套的 videoResource JSON
        vr_json = photo["videoResource"].get("json", {})
        for codec in ("hevc", "h264"):
            for adaptation in vr_json.get(codec, {}).get("adaptationSet", []):
                for rep in adaptation.get("representation", []):
                    if rep.get("url"):
                        video_url = rep["url"]
                        break
```

#### 技术要点
- **GraphQL 状态**：快手使用 Apollo Client，页面状态存储在 `__APOLLO_STATE__`
- **多编码支持**：同时支持 H.265 和 H.264 编码格式
- **嵌套 JSON**：`videoResource` 字段可能包含嵌套 JSON 字符串需二次解析

---

### 3. 小红书解析

#### 核心原理
与抖音/快手不同，小红书无法直接通过网页抓取获取视频下载地址，需借助第三方 API 服务（xhs-dl）。

#### 技术流程
1. **API 调用**：`POST {xhs_api_url}` 
   - 默认地址：`http://127.0.0.1:5556/xhs/detail`
   - 可配置远程地址
2. **请求体**：`{"url": "小红书分享链接"}`
3. **返回数据结构**：
   ```json
   {
     "data": {
       "作品类型": "视频",
       "作品标题": "...",
       "作品描述": "...",
       "下载地址": "http://sns-bak-v1.xhscdn.com/stream/...",
       "作者昵称": "...",
       "点赞数量": 100,
       "收藏数量": 50,
       "评论数量": 20
     }
   }
   ```
4. **视频/图文区分**：
   - `作品类型 == "视频"`：返回视频下载地址
   - `作品类型 == "图文"`：使用 `作品描述` 作为文案，跳过语音提取
   -  https://sns-bak-v1.xhscdn.com/stream/110/258/01e59e8ac530a69c010377038cf3503826_2 小红书视频cdn地址
   
#### 关键代码
```python
def _get_xiaohongshu_info(url: str, t_all: float) -> dict:
    cfg = config_manager.get_douyin_parser_config()
    xhs_api_url = cfg.get("xhs_api_url", "http://127.0.0.1:5556/xhs/detail")
    
    resp = httpx.post(xhs_api_url, json={"url": url})
    data = resp.json()["data"]
    
    note_type = data.get("作品类型", "未知")
    video_url = data.get("下载地址", "")
    desc = data.get("作品描述", "")
    is_video = note_type == "视频"
    
    return {
        "url": video_url,
        "desc": desc,
        "is_video": is_video,
        "note_type": note_type,
        "note_author": data.get("作者昵称", ""),
        "note_likes": data.get("点赞数量", 0),
        # ... 其他元数据
    }
```

#### 技术要点
- **依赖外部服务**：必须运行 xhs-dl API 服务（本地或远程）
- **图文笔记支持**：与抖音/快手不同，小红书图文笔记可以直接提取文案，无需 ASR
- **API 可配置**：支持配置远程 API 地址，便于多人共享服务

---

### 4. 三平台对比

| 维度 | 抖音 | 快手 | 小红书 |
|------|------|------|--------|
| **解析方式** | 网页 HTML 抓取 | 网页 HTML 抓取 | xhs-dl API 调用 |
| **数据来源** | `window._ROUTER_DATA` | `window.__APOLLO_STATE__` | 第三方 API |
| **反爬难度** | 中等 | 中等 | 低（依赖 API） |
| **短链支持** | ✅ 自动跳转 | ✅ 自动跳转 | ✅ API 处理 |
| **无水印视频** | ✅ URL 替换 | ✅ 直接获取 | ✅ API 返回 |
| **图文笔记** | ❌ 仅视频 | ❌ 仅视频 | ✅ 支持 |
| **额外依赖** | 无 | 无 | xhs-dl 服务 |
| **失败重试** | 可切换浏览器模式 | 暂无 | 依赖 API 可用性 |

---

## 第二部分：ASR 语音转文字方案

### 三种实现方案概览

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

只需要输入apikey+model，无需baseurl，skd封装好了。

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

apikey
url=https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions
model=qwen3-asr-flash

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

### 平台选择
```
抖音视频 → 直接解析（网页抓取）
快手视频 → 直接解析（网页抓取）
小红书视频 → 配置 xhs-dl API 服务后解析
小红书图文 → 直接提取文案（无需 ASR）
```

### ASR 模式选择
```
视频 < 2 分钟 + 无网络/隐私敏感 → 本地模式（faster-whisper）
视频 > 4 分钟 + 追求简洁 → API-Transcription（paraformer-v2）
视频 2-30 分钟 + 追求速度 → API-ChatCompletion（qwen3-asr-flash）
```

---

## 配置说明

### 小红书 API 配置
在「⚙️ 系统配置」→「抖音/快手/小红书视频解析」中配置：

```yaml
小红书 API 地址: http://127.0.0.1:5556/xhs/detail  # 本地服务
# 或
小红书 API 地址: http://your-server:5556/xhs/detail  # 远程服务
```

### ASR 模式配置
在同一配置面板中切换：
- **本地模式**：无需额外配置，自动加载 faster-whisper base 模型
- **API-Transcription**：配置 DashScope API Key，选择 paraformer-v2 模型
- **API-ChatCompletion**：配置 Base URL、API Key 和模型名称

---

## 技术架构总结

```
┌────────────────────────────────────────────────────────────┐
│                      用户界面层                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │ 视频链接输入 │  │ ASR 模式选择 │  │   API 配置面板      │  │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘  │
└─────────┼────────────────┼──────────────────┼───────────────┘
          │                │                  │
          ▼                ▼                  ▼
┌────────────────────────────────────────────────────────────┐
│                      平台解析层                             │
│     抖音解析        快手解析         小红书 API 调用        │
│   (HTML 抓取)    (HTML 抓取)      (xhs-dl 服务)            │
└─────────┬────────────────────────────────────────────────────┘
          │
          ▼
┌────────────────────────────────────────────────────────────┐
│                      ASR 处理层                             │
│  ┌─────────────┐  ┌───────────────┐  ┌─────────────────┐   │
│  │ faster-whisper│  │ paraformer-v2 │  │ qwen3-asr-flash │   │
│  │   (本地)     │  │  (DashScope)   │  │  (DashScope)     │   │
│  └─────────────┘  └───────────────┘  └─────────────────┘   │
└────────────────────────────────────────────────────────────┘
```

---

## 文件位置

- **核心代码**: `web/pipelines/douyin_parser.py`
- **配置管理**: `pixelle_video/config/manager.py`
- **配置 Schema**: `pixelle_video/config/schema.py`
- **配置文件**: `config.yaml`

当前实现（`web/pipelines/douyin_parser.py`）同时支持抖音/快手/小红书三大平台，本地模式和 API-Transcription 两种 ASR 方案，用户可在页面自由切换配置。
