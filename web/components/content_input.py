# Copyright (C) 2025 AIDC-AI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Content input components for web UI (left column)
"""

import os
import re
import streamlit as st

from web.i18n import tr
from web.utils.async_helpers import get_project_version

MAX_FIXED_SEGMENTS = 50


@st.dialog(tr("video.dialog_over_limit_title"))
def _segment_limit_dialog():
    st.error(tr("video.frames_fixed_mode_over_limit", max=MAX_FIXED_SEGMENTS))
    st.write("")
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button(tr("btn.dialog_confirm"), use_container_width=True, type="primary"):
            st.session_state["_show_segment_limit_dialog"] = False
            st.rerun()
    with col2:
        if st.button(tr("btn.dialog_continue_editing"), use_container_width=True):
            st.session_state["_show_segment_limit_dialog"] = False
            st.rerun()


def _count_segments(text: str, split_mode: str) -> int:
    """Preview segment count for fixed mode text."""
    if not text or not text.strip():
        return 0
    if split_mode == "paragraph":
        paragraphs = re.split(r"\n\s*\n", text)
        return sum(1 for p in paragraphs if p.strip())
    elif split_mode == "line":
        return sum(1 for line in text.split("\n") if line.strip())
    elif split_mode == "sentence":
        cleaned = re.sub(r"\s+", " ", text.strip())
        sentences = re.split(r"(?<=[。.!?！？])\s*", cleaned)
        return sum(1 for s in sentences if s.strip())
    return 0


def render_content_input():
    """Render content input section (left column) with batch support"""
    with st.container(border=True):
        st.markdown(f"**{tr('section.content_input')}**")

        retry_params = st.session_state.get("retry_params")

        # ====================================================================
        # Step 1: Batch mode toggle (highest priority)
        # ====================================================================
        batch_mode = st.checkbox(
            tr("batch.mode_label"),
            value=False,
            help=tr("batch.mode_help")
        )
        
        if not batch_mode:
            # ================================================================
            # Single task mode (original logic, unchanged)
            # ================================================================
            mode_val = 1
            if retry_params:
                mode_val = 0 if retry_params.get("mode") == "generate" else 1
            
            mode = st.radio(
                "Processing Mode",
                ["generate", "fixed"],
                horizontal=True,
                format_func=lambda x: tr(f"mode.{x}"),
                label_visibility="collapsed",
                index=mode_val,
                key="content_mode_radio"
            )
            
            default_text = retry_params.get("text", "") if retry_params else ""
            
            # Text input (unified for both modes)
            text_placeholder = tr("input.topic_placeholder") if mode == "generate" else tr("input.content_placeholder")
            text_height = 120 if mode == "generate" else 200
            text_help = tr("input.text_help_generate") if mode == "generate" else tr("input.text_help_fixed")
            
            text = st.text_area(
                tr("input.text"),
                value=default_text,
                placeholder=text_placeholder,
                height=text_height,
                help=text_help
            )
            
            # Split mode selector (only show in fixed mode)
            if mode == "fixed":
                split_mode_options = {
                    "paragraph": tr("split.mode_paragraph"),
                    "line": tr("split.mode_line"),
                    "sentence": tr("split.mode_sentence"),
                }
                split_mode = st.selectbox(
                    tr("split.mode_label"),
                    options=list(split_mode_options.keys()),
                    format_func=lambda x: split_mode_options[x],
                    index=0,  # Default to paragraph mode
                    help=tr("split.mode_help")
                )
            else:
                split_mode = "paragraph"  # Default for generate mode (not used)
            
            # Title input (optional for both modes)
            default_title = retry_params.get("title", "") if retry_params else ""
            title = st.text_input(
                tr("input.title"),
                value=default_title,
                placeholder=tr("input.title_placeholder"),
                help=tr("input.title_help")
            )
            
            # Number of scenes (only show in generate mode)
            if mode == "generate":
                default_n = retry_params.get("n_scenes", 3) if retry_params else 3
                n_scenes = st.slider(
                    tr("video.frames"),
                    min_value=3,
                    max_value=30,
                    value=default_n,
                    help=tr("video.frames_help"),
                    label_visibility="collapsed"
                )
                st.caption(tr("video.frames_label", n=n_scenes))
            else:
                # Fixed mode: n_scenes is ignored, set default value
                n_scenes = 5
                st.info(tr("video.frames_fixed_mode_hint"))
                seg_count = _count_segments(text, split_mode)
                if seg_count > 0:
                    st.caption(tr("video.frames_fixed_mode_preview", n=seg_count))
                if seg_count > MAX_FIXED_SEGMENTS:
                    key = "_segment_dialog_dismissed"
                    dismissed = st.session_state.get(key, False)
                    if not dismissed:
                        _segment_limit_dialog()
                    # Mark as dismissed after dialog is closed
                    if key not in st.session_state:
                        st.session_state[key] = True
                else:
                    # Reset dismissed flag when back under limit
                    st.session_state.pop("_segment_dialog_dismissed", None)
            
            return {
                "batch_mode": False,
                "mode": mode,
                "text": text,
                "title": title,
                "n_scenes": n_scenes,
                "split_mode": split_mode
            }
        
        else:
            # ================================================================
            # Batch mode (simplified YAGNI version)
            # ================================================================
            st.markdown(f"**{tr('batch.section_title')}**")
            
            # Batch rules info
            st.info(f"""
**{tr('batch.rules_title')}**
- ✅ {tr('batch.rule_1')}
- ✅ {tr('batch.rule_2')}
- ✅ {tr('batch.rule_3')}
            """)
            
            # Batch topics input
            text_input = st.text_area(
                tr("batch.topics_label"),
                height=300,
                placeholder=tr("batch.topics_placeholder"),
                help=tr("batch.topics_help")
            )
            
            # Split topics by newline
            if text_input:
                # Simple split by newline, filter empty lines
                topics = [
                    line.strip() 
                    for line in text_input.strip().split('\n') 
                    if line.strip()
                ]
                
                if topics:
                    # Check count limit
                    if len(topics) > 100:
                        st.error(tr("batch.count_error", count=len(topics)))
                        topics = []
                    else:
                        st.success(tr("batch.count_success", count=len(topics)))
                        
                        # Preview topics list
                        with st.expander(tr("batch.preview_title"), expanded=False):
                            for i, topic in enumerate(topics, 1):
                                st.markdown(f"`{i}.` {topic}")
                else:
                    topics = []
            else:
                topics = []
            
            st.markdown("---")
            
            # Title prefix (optional)
            title_prefix = st.text_input(
                tr("batch.title_prefix_label"),
                placeholder=tr("batch.title_prefix_placeholder"),
                help=tr("batch.title_prefix_help")
            )
            
            # Number of scenes (unified for all videos)
            n_scenes = st.slider(
                tr("batch.n_scenes_label"),
                min_value=3,
                max_value=30,
                value=5,
                help=tr("batch.n_scenes_help")
            )
            st.caption(tr("batch.n_scenes_caption", n=n_scenes))
            
            # Config info
            st.info(f"📌 {tr('batch.config_info')}")
            
            return {
                "batch_mode": True,
                "topics": topics,
                "mode": "generate",  # Fixed to AI generate content
                "title_prefix": title_prefix,
                "n_scenes": n_scenes,
            }


def render_bgm_section(key_prefix=""):
    """Render BGM selection section"""
    with st.container(border=True):
        st.markdown(f"**{tr('section.bgm')}**")
        
        with st.expander(tr("help.feature_description"), expanded=False):
            st.markdown(f"**{tr('help.what')}**")
            st.markdown(tr("bgm.what"))
            st.markdown(f"**{tr('help.how')}**")
            st.markdown(tr("bgm.how"))
        
        from pixelle_video.utils.os_util import list_resource_files
        
        # ── 自定义上传区域 ──────────────────────────────────────────────
        custom_upload_label = tr("bgm.custom_title")
        with st.expander(custom_upload_label, expanded=False):
            # 读取已上传的自定义文件
            from pixelle_video.utils.os_util import get_pixelle_video_root_path
            root = get_pixelle_video_root_path()
            custom_dir = os.path.join(root, "bgm", "custom")
            os.makedirs(custom_dir, exist_ok=True)

            audio_extensions = ('.mp3', '.wav', '.flac', '.m4a', '.aac', '.ogg')
            existing_custom = []
            if os.path.isdir(custom_dir):
                existing_custom = sorted([
                    f for f in os.listdir(custom_dir)
                    if f.lower().endswith(audio_extensions)
                ])

            # 上传 widget
            uploaded = st.file_uploader(
                tr("bgm.custom_upload"),
                type=["mp3", "wav", "flac", "m4a", "aac", "ogg"],
                key=f"{key_prefix}bgm_custom_upload",
                label_visibility="collapsed",
            )

            if uploaded:
                safe_name = uploaded.name
                dest_path = os.path.join(custom_dir, safe_name)
                with open(dest_path, "wb") as f:
                    f.write(uploaded.getbuffer())
                st.success(tr("bgm.custom_upload_success") + f" - {safe_name}")
                # 立即刷新列表
                if safe_name not in existing_custom:
                    existing_custom.append(safe_name)
                    existing_custom.sort()

            if existing_custom:
                st.caption(tr("bgm.custom_uploaded_count", n=len(existing_custom)))
        
        # ── 内置音乐扫描 ───────────────────────────────────────────────
        try:
            all_files = list_resource_files("bgm")
            built_in_files = sorted([f for f in all_files if f.lower().endswith(audio_extensions)])
        except Exception as e:
            st.warning(f"Failed to load BGM files: {e}")
            built_in_files = []
        
        # ── 合并选项列表 ───────────────────────────────────────────────
        # 选项格式：(显示名, 实际值)，实际值为 None 表示"无音乐"
        none_label = tr("bgm.none")
        separator = "───────── 自定义音乐 ─────────"
        
        options_display = [none_label]                          # index 0
        options_value   = [None]
        
        if existing_custom:
            options_display.append(separator)
            options_value.append("__separator__")
            for f in existing_custom:
                display_name = f"☁️ {f}"
                options_display.append(display_name)
                options_value.append(("custom", f))
        
        for f in built_in_files:
            options_display.append(f)
            options_value.append(("built_in", f))
        
        # 当前选中索引（保持上次选择，retry_params优先）
        default_idx = 0
        retry_params = st.session_state.get("retry_params")
        if retry_params and retry_params.get("bgm_path"):
            retry_bgm = retry_params["bgm_path"]
            for i, val in enumerate(options_value):
                if val and val != "__separator__" and val[1] == os.path.basename(retry_bgm):
                    default_idx = i
                    break
        else:
            default_idx = st.session_state.get(f"{key_prefix}bgm_selector_idx", 0)
        default_idx = min(default_idx, len(options_display) - 1)
        
        selected_display = st.selectbox(
            tr("bgm.selector"),
            options_display,
            index=default_idx,
            label_visibility="collapsed",
            key=f"{key_prefix}bgm_selector",
        )
        selected_idx = options_display.index(selected_display)
        st.session_state[f"{key_prefix}bgm_selector_idx"] = selected_idx
        
        selected_value = options_value[selected_idx]
        
        # 解析 bgm_path：None = 无音乐，("built_in", fname) = 内置，("custom", fname) = 自定义
        if selected_value is None or selected_value == "__separator__":
            bgm_path = None
        elif selected_value[0] == "custom":
            bgm_path = os.path.join(custom_dir, selected_value[1])
        else:
            bgm_path = selected_value[1]
        
        # ── 音量控制（仅选中音乐时显示）────────────────────────────────
        if bgm_path:
            default_vol = 0.2
            if retry_params and retry_params.get("bgm_volume") is not None:
                default_vol = retry_params["bgm_volume"]
            bgm_volume = st.slider(
                tr("bgm.volume"),
                min_value=0.0,
                max_value=0.5,
                value=default_vol,
                step=0.01,
                format="%.2f",
                key=f"{key_prefix}bgm_volume_slider",
                help=tr("bgm.volume_help"),
            )
            # 预览按钮
            if st.button(tr("bgm.preview"), key=f"{key_prefix}preview_bgm", use_container_width=True):
                try:
                    from pixelle_video.utils.os_util import get_resource_path
                    # 内置音乐需要解析路径
                    if os.path.isabs(bgm_path) or os.path.exists(bgm_path):
                        st.audio(bgm_path)
                    else:
                        # built_in: 解析 resource 路径
                        st.audio(get_resource_path("bgm", bgm_path))
                except Exception as e:
                    st.error(f"{tr('bgm.preview_failed', file=os.path.basename(bgm_path))}: {e}")
        else:
            bgm_volume = 0.2
        
        return {
            "bgm_path": bgm_path,
            "bgm_volume": bgm_volume
        }


def render_version_info():
    """Render version info and GitHub link"""
    with st.container(border=True):
        st.markdown(f"**{tr('version.title')}**")
        version = get_project_version()
        github_url = "https://github.com/AIDC-AI/Pixelle-Video"
        
        # Version and GitHub link in one line
        github_url = "https://github.com/AIDC-AI/Pixelle-Video"
        badge_url = "https://img.shields.io/github/stars/AIDC-AI/Pixelle-Video"

        st.markdown(
            f'{tr("version.current")}: `{version}` &nbsp;&nbsp; '
            f'<a href="{github_url}" target="_blank">'
            f'<img src="{badge_url}" alt="GitHub stars" style="vertical-align: middle;">'
            f'</a>',
            unsafe_allow_html=True)

