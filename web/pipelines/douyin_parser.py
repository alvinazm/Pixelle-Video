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
import tempfile
import subprocess
import time
import threading
from pathlib import Path
from typing import Any, Optional

import httpx
import streamlit as st
from loguru import logger

from web.i18n import tr
from web.pipelines.base import PipelineUI, register_pipeline_ui

_whisper_model = None
_whisper_lock = threading.Lock()


def _get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        with _whisper_lock:
            if _whisper_model is None:
                from faster_whisper import WhisperModel
                logger.info("[抖音解析] 首次加载 Whisper 模型...")
                _whisper_model = WhisperModel("base", device="auto", compute_type="auto")
                logger.info("[抖音解析] Whisper 模型加载完成，已缓存")
    return _whisper_model


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


def _resolve_short_url(url: str) -> str:
    if "v.douyin.com" in url:
        with httpx.Client(follow_redirects=True, timeout=10.0) as client:
            resp = client.head(url)
            resolved = str(resp.url)
            if "douyin.com/video/" in resolved or "iesdouyin.com/share/video/" in resolved:
                return resolved
            raise RuntimeError(f"Short link did not resolve to video: {resolved}")
    return url


_HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) EdgiOS/121.0.2277.107 Version/17.0 Mobile/15E148 Safari/604.1"
}


def _get_video_info(url: str) -> dict:
    t0 = time.time()
    logger.info("[抖音解析] 开始解析视频信息...")
    url = _resolve_short_url(url)

    if "/video/" in url or "iesdouyin.com/share/video/" in url:
        parts = url.split("?")[0].strip("/").split("/")
        video_id = parts[-1]
        url = f"https://www.iesdouyin.com/share/video/{video_id}"
    else:
        raise RuntimeError("Unsupported Douyin URL format")

    with httpx.Client(timeout=15.0, headers=_HEADERS) as client:
        resp = client.get(url)
        resp.raise_for_status()

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

    logger.info(f"[抖音解析] 解析完成, 耗时 {time.time()-t0:.1f}s, 标题: {title[:30]}")

    return {
        "title": re.sub(r"[\\/:*?\"<>|]", "_", title),
        "url": video_url,
        "webpage_url": url,
    }


def _extract_text_asr(video_url: str) -> str:

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        mp4_path = tmp_path / "video.mp4"
        wav_path = tmp_path / "audio.wav"

        logger.info("[抖音解析] 开始下载视频...")
        t0 = time.time()
        with httpx.Client(follow_redirects=True, timeout=60.0, headers=_HEADERS) as client:
            with client.stream("GET", video_url) as resp:
                resp.raise_for_status()
                with open(mp4_path, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=8192):
                        f.write(chunk)
        size_mb = mp4_path.stat().st_size / 1024 / 1024
        logger.info(f"[抖音解析] 视频下载完成 {size_mb:.1f}MB, 耗时 {time.time()-t0:.1f}s")

        logger.info("[抖音解析] 开始提取音频...")
        t1 = time.time()
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(mp4_path), "-vn", "-acodec", "pcm_s16le",
             "-ar", "16000", "-ac", "1", str(wav_path)],
            capture_output=True, timeout=120,
        )
        if not wav_path.exists():
            raise RuntimeError("ffmpeg audio extraction failed")
        logger.info(f"[抖音解析] 音频提取完成, 耗时 {time.time()-t1:.1f}s")

        logger.info("[抖音解析] 获取 Whisper 模型...")
        t2 = time.time()
        model = _get_whisper_model()
        logger.info(f"[抖音解析] 模型就绪 (缓存), 耗时 {time.time()-t2:.1f}s")

        logger.info("[抖音解析] 开始语音转写...")
        t3 = time.time()
        segments, _ = model.transcribe(str(wav_path), language="zh", beam_size=5)
        logger.info(f"[抖音解析] 语音转写完成, 耗时 {time.time()-t3:.1f}s")
        text = "".join(seg.text for seg in segments)

        logger.info(f"[抖音解析] 总耗时 {time.time()-t0:.1f}s, 输出字符数 {len(text)}")

        try:
            import zhconv
            text = zhconv.convert(text, "zh-hans")
        except ImportError:
            pass

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
                else:
                    url = _extract_url(url_input)
                    if not url:
                        st.warning(tr("douyin_parser.url_invalid"))
                    else:
                        url_type = _validate_url(url)
                        if url_type == "search":
                            st.error(tr("douyin_parser.url_search_page"))
                        elif url_type == "video":
                            with st.spinner(tr("douyin_parser.status_parsing")):
                                try:
                                    info = _get_video_info(url)
                                    st.session_state["douyin_info"] = info
                                    st.session_state["douyin_video_url"] = info.get("url") or info.get("webpage_url", "")
                                    st.session_state["douyin_title"] = info.get("title", "")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"{tr('douyin_parser.error')}: {e}")

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
                else:
                    url = _extract_url(url_input)
                    if not url:
                        st.warning(tr("douyin_parser.url_invalid"))
                    else:
                        url_type = _validate_url(url)
                        if url_type == "search":
                            st.error(tr("douyin_parser.url_search_page"))
                        elif url_type == "video":
                            with st.spinner(tr("douyin_parser.status_extracting")):
                                try:
                                    info = _get_video_info(url)
                                    video_url = info.get("url") or info.get("webpage_url", "")
                                    text = _extract_text_asr(video_url)
                                    st.session_state["douyin_text"] = text
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"{tr('douyin_parser.error')}: {e}")

            if "douyin_text" in st.session_state:
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
