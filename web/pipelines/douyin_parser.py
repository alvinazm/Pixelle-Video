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
from loguru import logger

from web.i18n import tr
from web.pipelines.base import PipelineUI, register_pipeline_ui
from pixelle_video.config import config_manager

_whisper_model = None
_whisper_lock = threading.Lock()

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) EdgiOS/121.0.2277.107 Version/17.0 Mobile/15E148 Safari/604.1"
}


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
    if "/video/" in url or "/note/" in url or "v.douyin.com" in url:
        return "video"
    return None


def _get_video_info(url: str) -> dict:
    t_all = time.time()
    logger.info("[抖音解析] === 开始解析 ===")

    if "v.douyin.com" in url:
        with httpx.Client(follow_redirects=True, timeout=10.0) as client:
            resp = client.head(url, follow_redirects=True)
            resolved = str(resp.url)
            if "douyin.com/video/" in resolved or "iesdouyin.com/share/video/" in resolved:
                logger.info(f"[抖音解析] 短链接解析: {url} -> {resolved}")
                url = resolved
            else:
                raise RuntimeError(f"Short link did not resolve to video: {resolved}")

    if "/video/" in url or "iesdouyin.com/share/video/" in url:
        parts = url.split("?")[0].strip("/").split("/")
        video_id = parts[-1]
        url = f"https://www.iesdouyin.com/share/video/{video_id}"
    else:
        raise RuntimeError("Unsupported Douyin URL format")

    t_fetch = time.time()
    logger.info(f"[抖音解析] 获取页面 HTML... (URL: {url[:60]})")
    with httpx.Client(timeout=15.0, headers=_HEADERS) as client:
        resp = client.get(url)
        resp.raise_for_status()
    logger.info(f"[抖音解析] 页面获取完成, 耗时 {time.time()-t_fetch:.1f}s, HTML: {len(resp.text)/1024:.0f}KB")

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
    logger.info(f"[抖音解析] === 解析完成 === 总耗时 {total:.1f}s, 标题: {title[:30]}")

    return {
        "title": re.sub(r"[\\\\/:*?\"<>|]", "_", title),
        "url": video_url,
        "webpage_url": url,
    }


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
    ref_headers = {**{"Referer": "https://www.douyin.com/"}, **_HEADERS}
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
    mp4_path = tmp_dir / "video.mp4"
    wav_path = tmp_dir / "audio.wav"

    t_dl = time.time()
    logger.info("[抖音解析] [1/4] 下载视频...")
    with httpx.Client(follow_redirects=True, timeout=120.0, headers=_HEADERS) as client:
        with client.stream("GET", video_url) as resp:
            resp.raise_for_status()
            with open(mp4_path, "wb") as f:
                for chunk in resp.iter_bytes(chunk_size=65536):
                    f.write(chunk)
    size_mb = mp4_path.stat().st_size / 1024 / 1024
    speed_mbps = size_mb / (time.time() - t_dl)
    logger.info(f"[抖音解析] [1/4] 下载完成 {size_mb:.1f}MB, {time.time()-t_dl:.1f}s, {speed_mbps:.1f}MB/s")

    t_audio = time.time()
    logger.info("[抖音解析] [2/4] 提取音频...")
    ffmpeg_result = subprocess.run(
        ["ffmpeg", "-y", "-i", str(mp4_path), "-vn", "-acodec", "pcm_s16le",
         "-ar", "16000", "-ac", "1", str(wav_path)],
        capture_output=True, timeout=120,
    )
    if ffmpeg_result.returncode != 0:
        err = ffmpeg_result.stderr.decode(errors="replace")[-200:]
        raise RuntimeError(f"ffmpeg failed: {err}")
    logger.info(f"[抖音解析] [2/4] 音频完成, {time.time()-t_audio:.1f}s")

    t_model = time.time()
    logger.info("[抖音解析] [3/4] 加载模型...")
    model = _get_whisper_model()
    logger.info(f"[抖音解析] [3/4] 模型就绪, {time.time()-t_model:.1f}s")

    t_asr = time.time()
    logger.info("[抖音解析] [4/4] 语音转写...")
    segments, info = model.transcribe(str(wav_path), language="zh", beam_size=5)
    text = "".join(seg.text for seg in segments)
    duration_s = info.duration
    rtf = (time.time() - t_asr) / duration_s if duration_s > 0 else 0
    logger.info(f"[抖音解析] [4/4] 转写完成, 时长 {duration_s:.0f}s, RTF={rtf:.3f}, {time.time()-t_asr:.1f}s, {len(text)}字")

    try:
        import zhconv
        text = zhconv.convert(text, "zh-hans")
        logger.info(f"[抖音解析] 简繁转换完成, {len(text)}字")
    except ImportError:
        logger.warning("[抖音解析] zhconv 未安装, 跳过简繁转换")

    total = time.time() - t_all
    logger.info(f"[抖音解析] === 提取完成 === 总耗时 {total:.1f}s")

    out_dir = Path("output/download_video")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"douyin_{int(time.time())}.mp4"
    shutil.copy2(mp4_path, out_path)
    logger.info(f"[抖音解析] 视频已保存: {out_path}")

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
                c3, c4, c5 = st.columns([2, 2, 1])
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
                with c5:
                    st.markdown("<div style='height: 28px'></div>", unsafe_allow_html=True)
                    if st.button("💾 保存", key="douyin_save_config", use_container_width=True):
                        asr_mode_value = "transcription" if asr_mode_display == mode_transcription else "chat"
                        config_manager.set_douyin_parser_config(
                            asr_mode=asr_mode_value,
                            api_endpoint=st.session_state.get("douyin_api_endpoint", ""),
                            api_key=st.session_state.get("douyin_api_key", ""),
                            api_model=st.session_state.get("douyin_api_model", default_model),
                        )
                        config_manager.save()
                        st.success("✅ 配置已保存")
                        st.rerun()

        url_input = st.text_area(
            tr("douyin_parser.url_label"),
            placeholder="https://v.douyin.com/xxxxx  or  https://www.douyin.com/video/xxxxx",
            label_visibility="collapsed",
            key="douyin_url_input",
        )

        col_info, col_text = st.columns(2)

        with col_info:
            if st.button(tr("douyin_parser.btn_parse_info"), use_container_width=True, type="secondary"):
                if not url_input:
                    st.warning(tr("douyin_parser.url_required"))
                    return
                url = _extract_url(url_input)
                if not url:
                    st.warning(tr("douyin_parser.url_invalid"))
                    return
                url_type = _validate_url(url)
                if url_type == "search":
                    st.error(tr("douyin_parser.url_search_page"))
                    return

                progress_area = st.empty()
                progress_area.info("⏳ 正在解析视频信息...")
                try:
                    info = _get_video_info(url)
                    st.session_state["douyin_info"] = info
                    st.session_state["douyin_video_url"] = info.get("url") or info.get("webpage_url", "")
                    st.session_state["douyin_title"] = info.get("title", "")
                    st.session_state["douyin_text"] = ""
                    progress_area.success("✅ 解析完成")
                    st.rerun()
                except Exception as e:
                    logger.error(f"[抖音解析] 解析失败: {e}")
                    progress_area.error(f"❌ {e}")

            if "douyin_info" in st.session_state:
                info = st.session_state["douyin_info"]
                with st.container(border=True):
                    st.markdown(f"**{tr('douyin_parser.video_info')}**")
                    st.write(f"**{tr('douyin_parser.field_title')}:** {info.get('title', 'N/A')}")
                    if info.get("webpage_url"):
                        st.markdown(f"**{tr('douyin_parser.field_url')}:** [{info['webpage_url']}]({info['webpage_url']})")

        with col_text:
            if st.button(tr("douyin_parser.btn_extract_text"), use_container_width=True, type="primary"):
                if not url_input:
                    st.warning(tr("douyin_parser.url_required"))
                    return
                url = _extract_url(url_input)
                if not url:
                    st.warning(tr("douyin_parser.url_invalid"))
                    return
                url_type = _validate_url(url)
                if url_type == "search":
                    st.error(tr("douyin_parser.url_search_page"))
                    return

                asr_mode = mode_map.get(asr_mode_display, "local")
                endpoint = st.session_state.get("douyin_api_endpoint", "")
                api_key = st.session_state.get("douyin_api_key", "")
                api_model = st.session_state.get("douyin_api_model", "")

                if asr_mode != "local":
                    if not api_key or not api_model:
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

                progress_bar = st.progress(0, text="⏳ 准备中...")
                try:
                    progress_bar.progress(0.1, text="📡 获取视频信息...")
                    info = _get_video_info(url)
                    video_url = info.get("url") or info.get("webpage_url", "")
                    st.session_state["douyin_video_url"] = video_url
                    st.session_state["douyin_title"] = info.get("title", "")

                    if asr_mode == "local":
                        progress_bar.progress(0.2, text="⬇️ 下载视频中...")
                        text = _extract_text_asr(video_url)
                    elif asr_mode == "transcription":
                        progress_bar.progress(0.2, text="🔊 正在转写...")
                        text = _transcribe_transcription(video_url, api_key, api_model)
                    else:
                        progress_bar.progress(0.2, text="🔊 正在转写...")
                        text = _transcribe_chat(video_url, endpoint, api_key, api_model)

                    st.session_state["douyin_text"] = text
                    progress_bar.progress(1.0, text="✅ 提取完成！")
                    st.rerun()
                except Exception as e:
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
                    c1, c2 = st.columns(2)
                    c1.download_button(
                        tr("douyin_parser.btn_copy"),
                        text,
                        file_name="douyin_text.txt",
                        mime="text/plain",
                        use_container_width=True,
                    )
                    c2.download_button(
                        tr("douyin_parser.btn_copy_markdown"),
                        f"# {st.session_state.get('douyin_title', '抖音文案')}\n\n{text}",
                        file_name="douyin_text.md",
                        mime="text/markdown",
                        use_container_width=True,
                    )

        with st.expander(tr("douyin_parser.how_to_use"), expanded=False):
            st.markdown(tr("douyin_parser.usage_steps"))


register_pipeline_ui(DouyinParserPipelineUI)
