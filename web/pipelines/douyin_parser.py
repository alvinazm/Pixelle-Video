# Copyright (C) 2025 AIDC-AI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import re
import shutil
import subprocess
import tempfile
import threading
import time
from http import HTTPStatus
from pathlib import Path
from typing import Any, Optional
from urllib import request

import dashscope
import httpx
import streamlit as st
import streamlit.components.v1 as components
from loguru import logger

from web.i18n import tr
from web.pipelines.base import PipelineUI, register_pipeline_ui
from pixelle_video.config import config_manager

_whisper_model = None
_whisper_lock = threading.Lock()

_MOBILE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) EdgiOS/121.0.2277.107 Version/17.0 Mobile/15E148 Safari/604.1"
}

_DESKTOP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def _copy_button(text: str, btn_copy_label: str = "📋 复制文本", btn_md_label: str = "📥 下载MD",
                 md_b64: str = "", md_name: str = "douyin_text.md") -> None:
    safe_text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    dl_attr = f'href="data:text/markdown;base64,{md_b64}" download="{md_name}"' if md_b64 else 'style="display:none"'
    components.html(
        f"""
        <div style="display:flex;gap:8px">
            <button id="cp_btn" style="flex:1;padding:8px 0;border-radius:5px;border:none;
                background:#4CAF50;color:white;cursor:pointer;font-size:14px;
                font-weight:500">{btn_copy_label}</button>
            <a id="dl_btn" {dl_attr} style="flex:1;padding:8px 0;border-radius:5px;border:1px solid #4CAF50;
                color:#4CAF50;cursor:pointer;font-size:14px;font-weight:500;
                text-align:center;text-decoration:none;box-sizing:border-box;
                display:inline-block;background:white">{btn_md_label}</a>
        </div>
        <textarea id="cp_src" style="display:none">{safe_text}</textarea>
        <script>
        document.getElementById('cp_btn').onclick = function() {{
            var t = document.getElementById('cp_src').value;
            navigator.clipboard.writeText(t).then(function() {{
                document.getElementById('cp_btn').textContent = '✅ 已复制';
                document.getElementById('cp_btn').style.background = '#45a049';
                setTimeout(function(){{
                    document.getElementById('cp_btn').textContent = '{btn_copy_label}';
                    document.getElementById('cp_btn').style.background = '#4CAF50';
                }}, 2000);
            }});
        }};
        </script>
        """,
        height=48,
    )


def _rewrite_with_ai(text: str, custom_prompt: str = "") -> str:
    import time as time_mod
    t0 = time_mod.time()
    logger.info(f"[AI改写] 开始, 文案长度: {len(text)} 字, 自定义提示词: {len(custom_prompt)} 字")

    t1 = time_mod.time()
    from pixelle_video.config import config_manager
    llm_cfg = config_manager.get_llm_config()
    api_key = llm_cfg.get("api_key", "")
    base_url = llm_cfg.get("base_url", "")
    model = llm_cfg.get("model", "")
    logger.info(f"[AI改写] 配置读取完成, 耗时: {time_mod.time()-t1:.3f}s | model={model} base_url={base_url}")

    if not api_key or not base_url or not model:
        raise RuntimeError(tr("douyin_parser.llm_not_configured"))

    # 使用用户自定义提示词，否则使用默认提示词
    if custom_prompt and custom_prompt.strip():
        prompt = f"""{custom_prompt.strip()}

原文案：
{text}

请直接输出改写后的文案，不需要任何解释："""
        logger.info(f"[AI改写] 使用自定义提示词，长度: {len(custom_prompt)} 字")
    else:
        prompt = f"""请将以下视频文案进行优化改写，让它更适合短视频口播表达。
要求：
1. 语言自然流畅，符合口语化表达
2. 保留原文案的核心内容和情感
3. 可适当调整句子长度，更适合配音朗读
4. 如有方言或口语，可改为更标准的普通话表达

原文案：
{text}

请直接输出改写后的文案，不需要任何解释："""
        logger.info("[AI改写] 使用默认提示词")

    t2 = time_mod.time()
    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url=base_url)
    logger.info(f"[AI改写] OpenAI客户端创建完成, 耗时: {time_mod.time()-t2:.3f}s")

    t3 = time_mod.time()
    logger.info(f"[AI改写] 发送API请求... prompt长度={len(prompt)} 字")
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        max_tokens=4000,
    )
    t4 = time_mod.time()
    logger.info(f"[AI改写] API响应完成, 耗时: {t4-t3:.3f}s | status=ok")

    result = resp.choices[0].message.content.strip()
    # 过滤各种思考标签
    result = re.sub(r"<thinking>[\s\S]*?</thinking>", "", result, flags=re.IGNORECASE)
    result = re.sub(r"<think>[\s\S]*?</think>", "", result, flags=re.IGNORECASE)
    # 过滤引导省略号
    result = re.sub(r"^\s*\.{3,}\s*", "", result, flags=re.MULTILINE)
    lines = result.splitlines()
    lines = [l for l in lines if not re.match(r"^\s*\.{3,}\s*$", l)]
    result = "\n".join(lines).strip()
    logger.info(f"[AI改写] 解析结果完成, 返回长度: {len(result)} 字 (已过滤think标签)")
    logger.info(f"[AI改写] 总耗时: {time_mod.time()-t0:.3f}s")
    return result


def _extract_url(text: str) -> Optional[str]:
    text = text.strip()
    urls = re.findall(r'https?://\S+', text)
    if not urls:
        return None
    url = urls[0]
    url = re.sub(r'[^\S]+', '', url)
    url = url.rstrip('.,;:!?。！？，、；：')
    if url.endswith('/'):
        url = url.rstrip('/')
    return url


def _validate_url(url: str) -> Optional[str]:
    if "/search/" in url or "/user/" in url or "/discover/" in url:
        return "search"
    if "/short-video/" in url or "v.kuaishou.com" in url or "kuaishou.com/f/" in url:
        return "kuaishou"
    if "/video/" in url or "/note/" in url or "v.douyin.com" in url:
        return "douyin"
    if "xiaohongshu.com" in url:
        return "xiaohongshu"
    return None


def _get_video_info(url: str, platform: str = "douyin") -> dict:
    t_all = time.time()
    logger.info(f"[视频解析] === {platform.upper()} 开始解析 ===")

    if platform == "douyin":
        return _get_douyin_info(url, t_all)
    elif platform == "kuaishou":
        return _get_kuaishou_info(url, t_all)
    elif platform == "xiaohongshu":
        return _get_xiaohongshu_info(url, t_all)
    else:
        raise RuntimeError(f"不支持的平台: {platform}")


def _get_douyin_info(url: str, t_all: float) -> dict:
    if "v.douyin.com" in url:
        with httpx.Client(follow_redirects=True, timeout=10.0) as client:
            resp = client.get(url, follow_redirects=True)
            resolved = str(resp.url)
            if "/video/" in resolved:
                logger.info(f"[视频解析] 抖音短链接解析: {url} -> {resolved}")
                url = resolved
            else:
                raise RuntimeError(
                    "短链接未解析到视频页面，可能是抖音限制了自动化访问。"
                    "请使用完整的视频页面链接（包含 /video/）"
                )

    # 抖音视频ID提取（兼容两种域名）
    parts = url.split("?")[0].strip("/").split("/")
    video_id = parts[-1]
    # 用 iesdouyin.com（不跟随重定向，获取 _ROUTER_DATA）
    url = f"https://www.iesdouyin.com/share/video/{video_id}"

    t_fetch = time.time()
    logger.info(f"[视频解析] 获取抖音页面 HTML... (URL: {url[:60]})")
    with httpx.Client(timeout=15.0, headers=_MOBILE_HEADERS) as client:
        resp = client.get(url)
        resp.raise_for_status()
    logger.info(f"[视频解析] 页面获取完成, 耗时 {time.time()-t_fetch:.1f}s, HTML: {len(resp.text)/1024:.0f}KB")

    pattern = re.compile(r"window\._ROUTER_DATA\s*=\s*(.*?)</script>", re.DOTALL)
    match = pattern.search(resp.text)
    if not match:
        raise RuntimeError("Failed to extract video data from page HTML")

    data = json.loads(match.group(1).strip())

    info_key = next(
        (k for k in data.get("loaderData", {})
         if "video_(id)/page" in k or "note_(id)/page" in k),
        None,
    )
    if not info_key:
        raise RuntimeError("No video data found in page")

    item = data["loaderData"][info_key]["videoInfoRes"]["item_list"][0]
    video_url = item["video"]["play_addr"]["url_list"][0].replace("playwm", "play")
    title = item.get("desc", "").strip() or f"douyin_{video_id}"

    total = time.time() - t_all
    logger.info(f"[视频解析] === 抖音解析完成 === 总耗时 {total:.1f}s, 标题: {title[:30]}")

    return {
        "title": re.sub(r"[\\\\/:*?\"<>|]", "_", title),
        "url": video_url,
        "webpage_url": url,
    }


def _get_kuaishou_info(url: str, t_all: float) -> dict:
    t_fetch = time.time()
    logger.info(f"[视频解析] 获取快手页面 HTML... (URL: {url[:60]})")
    with httpx.Client(follow_redirects=True, timeout=15.0, headers={**_DESKTOP_HEADERS, "Referer": "https://www.kuaishou.com/"}) as client:
        resp = client.get(url)
        resp.raise_for_status()
    url = str(resp.url)
    if "/short-video/" not in url:
        raise RuntimeError("Unsupported Kuaishou URL format")
    video_id = url.split("/short-video/")[-1].split("?")[0].split("/")[0]
    logger.info(f"[视频解析] 页面获取完成, 耗时 {time.time()-t_fetch:.1f}s, HTML: {len(resp.text)/1024:.0f}KB")

    pattern = re.compile(r"window\.__APOLLO_STATE__\s*=\s*(\{[\s\S]*?\})\s*;\s*\(function\(")
    match = pattern.search(resp.text)
    match = pattern.search(resp.text)
    if not match:
        raise RuntimeError("Failed to extract __APOLLO_STATE__ from page HTML")

    data = json.loads(match.group(1))
    client_data = data.get("defaultClient", data)

    photo_key = next(
        (k for k, v in client_data.items()
         if isinstance(v, dict) and v.get("__typename") == "VisionVideoDetailPhoto"),
        None,
    )
    if not photo_key:
        raise RuntimeError("No video data found in page")

    photo = client_data[photo_key]
    video_url = photo.get("photoH265Url") or photo.get("photoUrl")
    if not video_url and photo.get("videoResource"):
        vr = photo["videoResource"]
        if isinstance(vr, dict):
            vr_json = vr.get("json", {})
            if callable(vr_json):
                vr_json = vr_json()
            if isinstance(vr_json, dict):
                for codec in ("hevc", "h264"):
                    for a in vr_json.get(codec, {}).get("adaptationSet", []):
                        for r in a.get("representation", []):
                            if r.get("url"):
                                video_url = r["url"]
                                break
                        if video_url:
                            break
                if not video_url:
                    vr_str = vr_json if isinstance(vr_json, str) else json.dumps(vr_json)
                    vr_data = json.loads(vr_str) if isinstance(vr_str, str) else vr_json
                    for codec in ("hevc", "h264"):
                        for a in vr_data.get(codec, {}).get("adaptationSet", []):
                            for r in a.get("representation", []):
                                if r.get("url"):
                                    video_url = r["url"]
                                    break
                            if video_url:
                                break
                    if not video_url:
                        raise RuntimeError("No video URL found in videoResource")
    if not video_url:
        raise RuntimeError("No video URL found in page")

    title = photo.get("caption", f"kuaishou_{video_id}").strip()

    total = time.time() - t_all
    logger.info(f"[视频解析] === 快手解析完成 === 总耗时 {total:.1f}s, 标题: {title[:30]}")

    return {
        "title": re.sub(r"[\\\\/:*?\"<>|]", "_", title),
        "url": video_url,
        "webpage_url": url,
    }


def _get_xiaohongshu_info(url: str, t_all: float, use_browser: bool = False) -> dict:
    cfg = config_manager.get_douyin_parser_config()
    xhs_api_url = cfg.get("xhs_api_url", "http://127.0.0.1:5556/xhs/detail")

    logger.info(f"[小红书解析] 调用本地 API... (URL: {url[:60]})")
    logger.info(f"[小红书解析] API 地址: {xhs_api_url}")

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(xhs_api_url, json={"url": url})
            resp.raise_for_status()
            data = resp.json()
            logger.info(f"[小红书解析] API 响应: {json.dumps(data, ensure_ascii=False)[:1000]}")

            if not data.get("data"):
                raise RuntimeError(f"小红书 API 返回空数据: {data.get('msg', '未知错误')}")

            d = data["data"]
            note_type = d.get("作品类型", "未知")
            video_url = d.get("下载地址", "") or ""
            title = d.get("作品标题", "") or d.get("作品描述", "") or f"xiaohongshu_{int(t_all)}"
            desc = d.get("作品描述", "") or ""
            logger.info(f"[小红书解析] 解析结果: 类型={note_type}, 视频URL={video_url[:80] if video_url else '空'}, desc长度={len(desc)}")

            is_video = note_type == "视频"

            total = time.time() - t_all
            logger.info(
                f"[小红书解析] === 解析完成 === "
                f"类型={note_type}, 标题={title[:30]}, "
                f"耗时={total:.1f}s"
            )

            return {
                "title": re.sub(r"[\\\\/:*?\"<>|]", "_", title),
                "url": video_url,
                "webpage_url": url,
                "note_type": note_type,
                "is_video": is_video,
                "desc": desc,
                "note_author": d.get("作者昵称", ""),
                "note_likes": d.get("点赞数量", 0),
                "note_collects": d.get("收藏数量", 0),
                "note_comments": d.get("评论数量", 0),
            }

    except httpx.HTTPError as e:
        logger.error(f"[小红书解析] API 请求失败: {e}")
        raise RuntimeError(f"小红书 API 请求失败，请确保 xhs-dl 服务已启动: {e}")
    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"[小红书解析] 响应解析失败: {e}")
        raise RuntimeError(f"小红书 API 响应格式错误: {e}")


def _get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        with _whisper_lock:
            if _whisper_model is None:
                from faster_whisper import WhisperModel
                t0 = time.time()
                logger.info("[抖音解析] 加载 Whisper 模型 (base)...")
                _whisper_model = WhisperModel("base", device="auto", compute_type="auto")
                logger.info(f"[抖音解析] 模型加载完成, 耗时 {time.time()-t0:.1f}s")
    return _whisper_model


def _prewarm_model():
    def _background_load():
        try:
            _get_whisper_model()
            logger.info("[抖音解析] 模型预热完成")
        except Exception as e:
            logger.warning(f"[抖音解析] 模型预热失败: {e}")
    thread = threading.Thread(target=_background_load, daemon=True)
    thread.start()


def _transcribe_transcription(video_url: str, api_key: str, model: str) -> str:
    t_all = time.time()
    logger.info(f"[抖音解析] === API 模式 === ({model})")
    dashscope.api_key = api_key

    t_api = time.time()
    logger.info("[抖音解析] [1/2] 发起转写任务...")
    task = dashscope.audio.asr.Transcription.async_call(
        model=model,
        file_urls=[video_url],
        language_hints=["zh"],
    )
    task_id = task.output.task_id
    logger.info(f"[抖音解析] [1/2] 任务ID: {task_id}")

    logger.info("[抖音解析] [2/2] 等待转写完成...")
    for attempt in range(60):
        result = dashscope.audio.asr.Transcription.wait(task=task_id)
        if result.output["task_status"] == "SUCCEEDED":
            break
        if result.output["task_status"] == "FAILED":
            raise RuntimeError(f"转写失败: {result.output['message']}")
        time.sleep(2)
    else:
        raise RuntimeError("转写超时")

    result_url = result.output.results[0]["transcription_url"]
    raw = json.loads(request.urlopen(result_url).read().decode())
    text = raw.get("transcripts", [{}])[0].get("text", "").strip()
    if not text:
        raise RuntimeError("未识别到文本内容")

    logger.info(f"[抖音解析] [2/2] 转写完成, {len(text)}字, {time.time()-t_api:.1f}s")
    total = time.time() - t_all
    logger.info(f"[抖音解析] === 提取完成 === 总耗时 {total:.1f}s")
    return text


def _transcribe_chat(video_url: str, api_endpoint: str, api_key: str, model: str) -> str:
    t_all = time.time()
    logger.info(f"[抖音解析] === Chat 模式 === ({model})")
    tmp_dir = Path(tempfile.mkdtemp(prefix="douyin_chat_"))
    mp3_path = tmp_dir / "audio.mp3"

    import base64

    t_audio = time.time()
    logger.info("[抖音解析] [1/3] 流式下载+转码...")
    ref_headers = {**{"Referer": "https://www.iesdouyin.com/"}, **_MOBILE_HEADERS}
    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-headers", "".join(f"{k}: {v}\r\n" for k, v in ref_headers.items()),
         "-i", video_url, "-vn",
         "-acodec", "libmp3lame", "-b:a", "32k",
         "-ar", "16000", "-ac", "1", str(mp3_path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    proc.wait(timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr.read().decode(errors='replace')[-300:]}")
    logger.info(f"[抖音解析] [1/3] 音频完成, {mp3_path.stat().st_size/1024:.0f}KB, {time.time()-t_audio:.1f}s")

    audio_b64 = base64.b64encode(mp3_path.read_bytes()).decode()
    logger.info(f"[抖音解析] Base64: {len(audio_b64)/1024:.0f}KB")

    t_api = time.time()
    logger.info(f"[抖音解析] [2/3] API 转写...")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    audio_duration_sec = float(
        subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(mp3_path)],
            capture_output=True, text=True,
        ).stdout.strip() or 0
    )

    if audio_duration_sec > 270:
        logger.info(f"[抖音解析] 音频超过 270s，分段处理...")
        chunk_duration = 240
        all_text = []
        for i in range(0, int(audio_duration_sec) + 1, chunk_duration):
            chunk_path = tmp_dir / f"chunk_{i}.mp3"
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(mp3_path), "-ss", str(i),
                 "-t", str(chunk_duration), "-acodec", "copy", str(chunk_path)],
                capture_output=True, timeout=60,
            )
            chunk_b64 = base64.b64encode(chunk_path.read_bytes()).decode()
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": [{
                    "type": "input_audio",
                    "input_audio": f"data:audio/mpeg;base64,{chunk_b64}"
                }]}],
                "stream": False,
            }
            resp = httpx.post(api_endpoint, json=payload, headers=headers, timeout=120)
            if resp.status_code != 200:
                raise RuntimeError(f"API error {resp.status_code}: {resp.text[:300]}")
            chunk_text = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            if chunk_text:
                all_text.append(chunk_text)
            logger.info(f"[抖音解析] 分段 {i//chunk_duration + 1} 完成: {len(chunk_text)}字")
        text = "".join(all_text)
    else:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": [{
                "type": "input_audio",
                "input_audio": f"data:audio/mpeg;base64,{audio_b64}"
            }]}],
            "stream": False,
        }
        resp = httpx.post(api_endpoint, json=payload, headers=headers, timeout=120)
        if resp.status_code != 200:
            raise RuntimeError(f"API error {resp.status_code}: {resp.text[:300]}")
        text = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()

    logger.info(f"[抖音解析] [3/3] 转写完成, {len(text)}字, {time.time()-t_api:.1f}s")
    total = time.time() - t_all
    logger.info(f"[抖音解析] === 提取完成 === 总耗时 {total:.1f}s")

    shutil.rmtree(tmp_dir, ignore_errors=True)
    return text


def _extract_text_asr(video_url: str) -> str:
    t_all = time.time()
    logger.info("[抖音解析] === 本地模式提取文案 ===")

    tmp_dir = Path(tempfile.mkdtemp(prefix="douyin_"))
    wav_path = tmp_dir / "audio.wav"

    t_audio = time.time()
    logger.info("[抖音解析] [1/3] 流式下载+转码...")
    ref_headers = {**{"Referer": "https://www.iesdouyin.com/"}, **_MOBILE_HEADERS}
    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-headers", "".join(f"{k}: {v}\r\n" for k, v in ref_headers.items()),
         "-i", video_url, "-vn", "-acodec", "pcm_s16le",
         "-ar", "16000", "-ac", "1", str(wav_path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    proc.wait(timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr.read().decode(errors='replace')[-300:]}")
    logger.info(f"[抖音解析] [1/3] 音频完成, {time.time()-t_audio:.1f}s")

    t_model = time.time()
    logger.info("[抖音解析] [2/3] 加载模型...")
    model = _get_whisper_model()
    logger.info(f"[抖音解析] [2/3] 模型就绪, {time.time()-t_model:.1f}s")

    t_asr = time.time()
    logger.info("[抖音解析] [3/3] 语音转写...")
    segments, info = model.transcribe(str(wav_path), language="zh", beam_size=5)
    text = "".join(seg.text for seg in segments)
    duration_s = info.duration
    rtf = (time.time() - t_asr) / duration_s if duration_s > 0 else 0
    logger.info(f"[抖音解析] [3/3] 转写完成, 时长 {duration_s:.0f}s, RTF={rtf:.3f}, {time.time()-t_asr:.1f}s, {len(text)}字")

    try:
        import zhconv
        text = zhconv.convert(text, "zh-hans")
        logger.info(f"[抖音解析] 简繁转换完成, {len(text)}字")
    except ImportError:
        logger.warning("[抖音解析] zhconv 未安装, 跳过简繁转换")

    total = time.time() - t_all
    logger.info(f"[抖音解析] === 提取完成 === 总耗时 {total:.1f}s")

    shutil.rmtree(tmp_dir, ignore_errors=True)
    return text


class DouyinParserPipelineUI(PipelineUI):
    name = "douyin_parser"
    icon = "🔍"

    @property
    def display_name(self):
        return tr("pipeline.douyin_parser.name")

    @property
    def description(self):
        return tr("pipeline.douyin_parser.description")

    @staticmethod
    def _on_rewrite_mode_change():
        """selectbox 切换模式时，重置提示词缓存并强制重渲染"""
        import streamlit as st
        # 标记模式已切换，下次渲染 text_area 时加载对应模式的默认模板
        st.session_state["douyin_mode_switched"] = True
        st.session_state["douyin_custom_prompt"] = ""
        # 同步更新 mode_idx
        mode_text = st.session_state.get("douyin_rewrite_mode", "")
        from web.i18n import tr
        st.session_state["douyin_rewrite_mode_idx"] = (
            0 if mode_text == tr("douyin_parser.ai_rewrite_mode_editor") else 1
        )
        # 已在 selectbox on_change 中由 Streamlit 自动触发 rerun，无需手动调用 st.rerun()

    def render(self, pixelle_video: Any):
        cfg = config_manager.get_douyin_parser_config()
        if cfg["asr_mode"] == "local":
            _prewarm_model()
        mode_local = tr("douyin_parser.mode_local")
        mode_transcription = tr("douyin_parser.mode_transcription")
        mode_chat = tr("douyin_parser.mode_chat")
        mode_map = {mode_local: "local", mode_transcription: "transcription", mode_chat: "chat"}
        reverse_map = {"local": 0, "transcription": 1, "chat": 2}
        default_mode_index = reverse_map.get(cfg["asr_mode"], 0)

        with st.expander(tr("douyin_parser.asr_config"), expanded=False):
            c1, c2 = st.columns([2, 1])
            with c1:
                asr_mode_display = st.selectbox(
                    tr("douyin_parser.asr_mode"),
                    [mode_local, mode_transcription, mode_chat],
                    index=default_mode_index,
                    key="douyin_asr_mode",
                )
            with c2:
                if asr_mode_display != mode_local:
                    api_key = st.text_input(
                        tr("douyin_parser.api_key"),
                        value=cfg.get("api_key", ""),
                        type="password",
                        key="douyin_api_key",
                    )
                else:
                    st.text_input("模型", value="base", disabled=True)

            if asr_mode_display != mode_local:
                c3, c4 = st.columns([2, 2])
                with c3:
                    endpoint_placeholder = "选填（Transcription 专用）" if asr_mode_display == mode_transcription else "必填，如 https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
                    api_endpoint = st.text_input(
                        tr("douyin_parser.api_endpoint"),
                        value=cfg.get("api_endpoint", ""),
                        placeholder=endpoint_placeholder,
                        key="douyin_api_endpoint",
                    )
                with c4:
                    default_model = "paraformer-v2" if asr_mode_display == mode_transcription else "qwen3-asr-flash"
                    st.text_input(
                        tr("douyin_parser.api_model"),
                        value=default_model,
                        placeholder=default_model,
                        key="douyin_api_model",
                    )

            c6, c7 = st.columns([2, 1])
            with c6:
                st.text_input(
                    tr("douyin_parser.xhs_api_url"),
                    value=cfg.get("xhs_api_url", "http://127.0.0.1:5556/xhs/detail"),
                    placeholder=tr("douyin_parser.xhs_api_url_placeholder"),
                    key="douyin_xhs_api_url",
                )
            with c7:
                st.markdown("<div style='height: 28px'></div>", unsafe_allow_html=True)
                if st.button("💾 保存", key="douyin_save_config", use_container_width=True):
                    asr_mode_value = "transcription" if asr_mode_display == mode_transcription else "chat"
                    config_manager.set_douyin_parser_config(
                        asr_mode=asr_mode_value,
                        api_endpoint=st.session_state.get("douyin_api_endpoint", ""),
                        api_key=st.session_state.get("douyin_api_key", ""),
                        api_model=st.session_state.get("douyin_api_model", default_model if asr_mode_display != mode_local else "paraformer-v2"),
                        xhs_api_url=st.session_state.get("douyin_xhs_api_url", ""),
                    )
                    config_manager.save()
                    st.success("✅ 配置已保存")
                    st.rerun()

        url_input = st.text_area(
            tr("douyin_parser.url_label"),
                        placeholder="抖音: https://v.douyin.com/xxxxx  快手: https://v.kuaishou.com/xxxxx  小红书: https://www.xiaohongshu.com/discovery/item/xxxxx",
            label_visibility="collapsed",
            key="douyin_url_input",
        )

        col_text = st.columns([1])[0]

        with col_text:
            disabled_extracting = st.session_state.get("douyin_extracting", False)
            # 检测是否是按钮触发后的第二次渲染（第一次触发 rerun，第二次执行实际逻辑）
            extract_queued = st.session_state.pop("douyin_extract_queued", False)
            if st.button(
                tr("douyin_parser.btn_extract_text"),
                use_container_width=True,
                type="primary",
                disabled=disabled_extracting,
            ):
                st.session_state["douyin_extracting"] = True
                st.session_state["douyin_extract_queued"] = True
                st.rerun()

            # 第二次渲染：按钮已置灰，开始执行实际提取逻辑
            if extract_queued:
                if not url_input:
                    st.session_state["douyin_extracting"] = False
                    st.warning(tr("douyin_parser.url_required"))
                    return
                url = _extract_url(url_input)
                if not url:
                    st.session_state["douyin_extracting"] = False
                    st.warning(tr("douyin_parser.url_invalid"))
                    return
                url_type = _validate_url(url)
                if url_type == "search":
                    st.session_state["douyin_extracting"] = False
                    st.error(tr("douyin_parser.url_search_page"))
                    return

                asr_mode = mode_map.get(asr_mode_display, "local")
                endpoint = st.session_state.get("douyin_api_endpoint", "")
                api_key = st.session_state.get("douyin_api_key", "")
                api_model = st.session_state.get("douyin_api_model", "")

                if asr_mode != "local":
                    if not api_key or not api_model:
                        st.session_state["douyin_extracting"] = False
                        st.error(tr("douyin_parser.api_config_required"))
                        return
                    config_manager.set_douyin_parser_config(
                        asr_mode=asr_mode,
                        api_endpoint=endpoint,
                        api_key=api_key,
                        api_model=api_model,
                    )
                    config_manager.save()
                else:
                    config_manager.set_douyin_parser_config(asr_mode="local")
                    config_manager.save()

                st.session_state["douyin_text"] = ""
                st.session_state["douyin_rewritten_text"] = ""
                for key in list(st.session_state.keys()):
                    if key.startswith("douyin_text_display") or key.startswith("douyin_rewrite_display"):
                        del st.session_state[key]
                progress_bar = st.progress(0, text="⏳ 准备中...")
                try:
                    progress_bar.progress(0.1, text="📡 获取视频信息...")
                    info = _get_video_info(url, url_type or "douyin")
                    video_url = info.get("url") or info.get("webpage_url", "")
                    st.session_state["douyin_video_url"] = video_url
                    st.session_state["douyin_title"] = info.get("title", "")

                    if url_type == "xiaohongshu":
                        is_video = info.get("is_video", False)
                        
                        if not is_video:
                            xiaohongshu_desc = info.get("desc", "")
                            if xiaohongshu_desc:
                                logger.info(f"[小红书] 图文笔记，使用描述作为文案，长度: {len(xiaohongshu_desc)} 字")
                                st.session_state["douyin_text"] = xiaohongshu_desc
                                progress_bar.progress(1.0, text="✅ 提取完成！（小红书图文）")
                                st.rerun()
                            else:
                                logger.warning(f"[小红书] 图文笔记无描述，无法提取文案")
                        else:
                            logger.info(f"[小红书] 视频笔记，提取语音转文字")

                    if asr_mode == "local":
                        progress_bar.progress(0.2, text="🔊 正在处理音频（本地推理）...")
                        text = _extract_text_asr(video_url)
                    elif asr_mode == "transcription":
                        progress_bar.progress(0.2, text="🔊 正在处理音频（Transcription）...")
                        text = _transcribe_transcription(video_url, api_key, api_model)
                    else:
                        progress_bar.progress(0.2, text="🔊 正在处理音频（Chat API）...")
                        text = _transcribe_chat(video_url, endpoint, api_key, api_model)

                    st.session_state["douyin_text"] = text
                    progress_bar.progress(1.0, text="✅ 提取完成！")
                    st.rerun()
                except Exception as e:
                    st.session_state["douyin_extracting"] = False
                    logger.error(f"[抖音解析] 提取失败: {e}")
                    progress_bar.progress(1.0, text=f"❌ 提取失败: {e}")
                    st.error(f"{tr('douyin_parser.error')}: {e}")

            if "douyin_text" in st.session_state and st.session_state.get("douyin_text"):
                text = st.session_state["douyin_text"]
                with st.container(border=True):
                    st.markdown(f"**{tr('douyin_parser.extracted_text')}**")
                    st.text_area(
                        tr("douyin_parser.extracted_text"),
                        value=text,
                        height=200,
                        label_visibility="collapsed",
                        key="douyin_text_display",
                    )
                    rewritten = st.session_state.get("douyin_rewritten_text", "")
                    rewrite_placeholder = tr("douyin_parser.rewrite_placeholder")

                    # 记录当前选中模式的原始索引（用于检测切换）
                    if "douyin_rewrite_mode_idx" not in st.session_state:
                        st.session_state["douyin_rewrite_mode_idx"] = 0

                    # AI改写模式选择
                    st.markdown(f"**{tr('douyin_parser.ai_rewrite_mode_label')}**")
                    rewrite_mode = st.selectbox(
                        tr("douyin_parser.ai_rewrite_mode_label"),
                        [
                            tr("douyin_parser.ai_rewrite_mode_editor"),
                            tr("douyin_parser.ai_rewrite_mode_empty"),
                        ],
                        index=st.session_state["douyin_rewrite_mode_idx"],
                        label_visibility="collapsed",
                        key="douyin_rewrite_mode",
                        on_change=self._on_rewrite_mode_change,
                    )

                    mode_is_editor = rewrite_mode == tr("douyin_parser.ai_rewrite_mode_editor")

                    # 提示词预览/编辑区
                    default_prompt = (
                        tr("douyin_parser.ai_rewrite_template")
                        if mode_is_editor
                        else ""
                    )
                    # 通过单独 flag 检测模式切换（避免依赖 text_area 的 key）
                    if st.session_state.get("douyin_mode_switched"):
                        initial_value = default_prompt
                        st.session_state["douyin_mode_switched"] = False
                    else:
                        initial_value = st.session_state.get(
                            "douyin_custom_prompt_display", default_prompt
                        )
                    prompt_display = st.text_area(
                        tr("douyin_parser.ai_rewrite_prompt_preview"),
                        value=initial_value,
                        height=200,
                        label_visibility="collapsed",
                    )
                    st.session_state["douyin_custom_prompt_display"] = prompt_display

                    disabled_rewriting = st.session_state.get("douyin_rewriting", False)
                    rewrite_queued = st.session_state.pop("douyin_rewrite_queued", False)
                    if st.button(
                        f"{tr('douyin_parser.btn_ai_rewrite')}",
                        use_container_width=True,
                        type="primary",
                        disabled=disabled_rewriting,
                    ):
                        st.session_state["douyin_rewriting"] = True
                        st.session_state["douyin_custom_prompt"] = prompt_display
                        st.session_state["douyin_rewrite_queued"] = True
                        st.rerun()

                    # 第二次渲染：按钮已置灰，显示"改写中"并执行实际改写
                    if rewrite_queued:
                        rewrite_ph = st.empty()
                        rewrite_ph.info(tr("douyin_parser.rewriting"))
                        try:
                            import time as time_mod
                            t_btn = time_mod.time()
                            logger.info(f"[AI改写] 按钮点击, 开始改写, 文案长度={len(text)}字, 模式={'editor' if mode_is_editor else 'empty'}")
                            rewritten = _rewrite_with_ai(text, custom_prompt=prompt_display)
                            logger.info(f"[AI改写] 改写成功, 耗时={time_mod.time()-t_btn:.3f}s, 结果长度={len(rewritten)}字")
                            st.session_state["douyin_rewritten_text"] = rewritten
                            st.session_state["douyin_rewriting"] = False
                            rewrite_ph.success(tr("douyin_parser.rewrite_success"))
                        except Exception as e:
                            st.session_state["douyin_rewriting"] = False
                            logger.error(f"[AI改写] 改写失败: {e}")
                            rewrite_ph.error(tr("douyin_parser.rewrite_failed"))
                            st.error(f"{tr('douyin_parser.error')}: {e}")

                    if rewritten:
                        with st.container(border=True):
                            st.markdown(f"**{tr('douyin_parser.rewritten_text')}**")
                            rewrite_key = "douyin_rewrite_display"
                            st.text_area(
                                tr("douyin_parser.rewritten_text"),
                                value=rewritten,
                                height=200,
                                label_visibility="collapsed",
                                key=rewrite_key,
                            )
                            safe_md = f"# {st.session_state.get('douyin_title', '抖音文案')}\n\n{rewritten}"
                            md_b64 = __import__("base64").b64encode(safe_md.encode()).decode()
                            md_name = f"{st.session_state.get('douyin_title', 'douyin_text')}_改写.md"
                            _copy_button(
                                rewritten,
                                md_b64=md_b64,
                                md_name=md_name,
                                btn_copy_label=tr("douyin_parser.btn_copy"),
                                btn_md_label=tr("douyin_parser.btn_copy_markdown"),
                            )

        with st.expander(tr("douyin_parser.how_to_use"), expanded=False):
            st.markdown(tr("douyin_parser.usage_steps"))


register_pipeline_ui(DouyinParserPipelineUI)
