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

import asyncio
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

import streamlit as st
from loguru import logger

from web.i18n import tr, get_language
from web.pipelines.base import PipelineUI, register_pipeline_ui
from web.components.content_input import render_bgm_section, render_version_info
from web.utils.async_helpers import run_async
from web.utils.streamlit_helpers import check_and_warn_selfhost_workflow
from pixelle_video.config import config_manager
from pixelle_video.utils.os_util import create_task_output_dir


class VideoLipSyncPipelineUI(PipelineUI):
    name = "video_lipsync"
    icon = "🎙️"

    @property
    def display_name(self):
        return tr("pipeline.video_lipsync.name")

    @property
    def description(self):
        return tr("pipeline.video_lipsync.description")

    def render(self, pixelle_video: Any):
        left_col, middle_col, right_col = st.columns([1, 1, 1])

        with left_col:
            video_params = self._render_video_upload()
            bgm_params = render_bgm_section(key_prefix="lipsync_")
            render_version_info()

        with middle_col:
            audio_params = self._render_audio_config(pixelle_video)
            lipsync_params = self._render_lipsync_config()

        with right_col:
            all_params = {
                **video_params,
                **bgm_params,
                **audio_params,
                **lipsync_params,
            }
            self._render_output_preview(pixelle_video, all_params)

    def _render_video_upload(self) -> dict:
        with st.container(border=True):
            st.markdown(f"**{tr('video_lipsync.video_upload')}**")

            with st.expander(tr("help.feature_description"), expanded=False):
                st.markdown(tr("video_lipsync.video_upload_what"))
                st.markdown(tr("video_lipsync.video_upload_how"))

            uploaded_file = st.file_uploader(
                tr("video_lipsync.video_upload_button"),
                type=["mp4", "mkv", "mov"],
                help=tr("video_lipsync.video_upload_help"),
                key="lipsync_video_file"
            )

            video_path = None
            video_duration = 0

            if uploaded_file is not None:
                session_id = str(uuid.uuid4()).replace('-', '')[:12]
                temp_dir = Path(f"temp/lipsync_{session_id}")
                temp_dir.mkdir(parents=True, exist_ok=True)

                file_path = temp_dir / uploaded_file.name
                with open(file_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                video_path = str(file_path.absolute())

                st.success(tr("video_lipsync.video_uploaded"))
                st.video(uploaded_file)

                try:
                    from moviepy.editor import VideoFileClip
                    clip = VideoFileClip(video_path)
                    video_duration = clip.duration
                    clip.close()
                    st.info(tr("video_lipsync.video_duration", duration=f"{video_duration:.1f}s"))
                except Exception as e:
                    logger.warning(f"Failed to get video duration: {e}")
            else:
                st.info(tr("video_lipsync.video_empty_hint"))

            return {
                "video_path": video_path,
                "video_duration": video_duration,
            }

    def _render_audio_config(self, pixelle_video) -> dict:
        comfyui_config = config_manager.get_comfyui_config()
        tts_config = comfyui_config.get("tts", {})

        with st.container(border=True):
            st.markdown(f"**{tr('section.tts')}**")

            with st.expander(tr("help.feature_description"), expanded=False):
                st.markdown(tr("video_lipsync.tts_what"))
                st.markdown(tr("video_lipsync.tts_how"))

            tts_mode = st.radio(
                tr("tts.inference_mode"),
                ["local", "comfyui"],
                horizontal=True,
                format_func=lambda x: tr(f"tts.mode.{x}"),
                index=0 if tts_config.get("inference_mode", "local") == "local" else 1,
                key="lipsync_tts_mode"
            )

            selected_voice = None
            tts_speed = None
            tts_workflow_key = None

            if tts_mode == "local":
                from pixelle_video.tts_voices import EDGE_TTS_VOICES, get_voice_display_name

                local_config = tts_config.get("local", {})
                saved_voice = local_config.get("voice", "zh-CN-YunjianNeural")
                saved_speed = local_config.get("speed", 1.2)

                voice_options = []
                voice_ids = []
                default_voice_index = 0

                for idx, vc in enumerate(EDGE_TTS_VOICES):
                    voice_id = vc["id"]
                    display_name = get_voice_display_name(voice_id, tr, get_language())
                    voice_options.append(display_name)
                    voice_ids.append(voice_id)
                    if voice_id == saved_voice:
                        default_voice_index = idx

                voice_col, speed_col = st.columns([1, 1])
                with voice_col:
                    selected_voice_display = st.selectbox(
                        tr("tts.voice_selector"),
                        voice_options,
                        index=default_voice_index,
                        key="lipsync_tts_voice"
                    )
                    selected_voice_index_local = voice_options.index(selected_voice_display)
                    selected_voice = voice_ids[selected_voice_index_local]

                with speed_col:
                    tts_speed = st.slider(
                        tr("tts.speed"),
                        min_value=0.5,
                        max_value=2.0,
                        value=saved_speed,
                        step=0.1,
                        format="%.1fx",
                        key="lipsync_tts_speed"
                    )
                    st.caption(tr("tts.speed_label", speed=f"{tts_speed:.1f}"))
            else:
                tts_workflows = pixelle_video.tts.list_workflows()
                tts_workflow_options = [wf["display_name"] for wf in tts_workflows]
                tts_workflow_keys = [wf["key"] for wf in tts_workflows]

                default_idx = 0
                if tts_workflow_options:
                    if "runninghub/tts_edge.json" in tts_workflow_keys:
                        default_idx = tts_workflow_keys.index("runninghub/tts_edge.json")

                tts_workflow_display = st.selectbox(
                    tr("tts.workflow_label"),
                    tts_workflow_options if tts_workflow_options else [tr("tts.no_workflows")],
                    index=default_idx,
                    key="lipsync_tts_workflow"
                )
                if tts_workflow_options:
                    tts_selected_idx = tts_workflow_options.index(tts_workflow_display)
                    tts_workflow_key = tts_workflow_keys[tts_selected_idx]

            narration_text = st.text_area(
                tr("video_lipsync.narration_text"),
                placeholder=tr("video_lipsync.narration_placeholder"),
                height=150,
                key="lipsync_narration_text"
            )

            if st.button(tr("video_lipsync.preview_audio"), key="lipsync_preview_audio", use_container_width=True):
                if not narration_text:
                    st.warning(tr("video_lipsync.narration_empty_warning"))
                else:
                    with st.spinner(tr("tts.previewing")):
                        try:
                            async def do_preview():
                                kit = await pixelle_video._get_or_create_comfykit()

                                if tts_mode == "local":
                                    # Direct Edge-TTS
                                    import edge_tts
                                    output_file = Path("output") / f"{uuid.uuid4().hex}.mp3"
                                    Path("output").mkdir(exist_ok=True)
                                    rate_str = f"+{int((tts_speed - 1) * 100)}%" if tts_speed != 1.0 else "+0%"
                                    communicate = edge_tts.Communicate(
                                        narration_text,
                                        selected_voice or "zh-CN-XiaoxiaoNeural",
                                        rate=rate_str
                                    )
                                    await communicate.save(str(output_file))
                                    return str(output_file)
                                else:
                                    # Direct ComfyKit call (same pattern as action_transfer.py)
                                    workflow_key = tts_workflow_key or "runninghub/tts_edge.json"
                                    workflow_path = Path("workflows") / workflow_key

                                    with open(workflow_path, 'r', encoding='utf-8') as f:
                                        workflow_config = json.load(f)

                                    if workflow_config.get("source") == "runninghub" and "workflow_id" in workflow_config:
                                        workflow_input = workflow_config["workflow_id"]
                                        logger.info(f"🚀 [RunningHub] TTS Preview (ID: {workflow_input})")
                                    else:
                                        workflow_input = str(workflow_path)
                                        logger.info(f"🔧 [Selfhost] TTS Preview: {workflow_input}")

                                    result = await kit.execute(workflow_input, {"text": narration_text})

                                    audio_path = None
                                    if hasattr(result, 'audios') and result.audios:
                                        audio_path = result.audios[0]
                                    elif hasattr(result, 'outputs'):
                                        for node_output in result.outputs.values():
                                            if isinstance(node_output, dict):
                                                if node_output.get('audios'):
                                                    audio_path = node_output['audios'][0]
                                                    break
                                                if node_output.get('audio'):
                                                    audio_path = node_output['audio']
                                                    break

                                    if not audio_path:
                                        raise Exception(tr("tts.error.no_audio"))

                                    if audio_path.startswith("http"):
                                        import httpx
                                        output_file = Path("output") / f"{uuid.uuid4().hex}.mp3"
                                        Path("output").mkdir(exist_ok=True)
                                        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
                                            resp = await client.get(audio_path)
                                            resp.raise_for_status()
                                            with open(output_file, 'wb') as f:
                                                f.write(resp.content)
                                        return str(output_file)

                                    return audio_path

                            audio_path = run_async(do_preview())

                            if audio_path and os.path.exists(audio_path):
                                st.success(tr("tts.preview_success"))
                                st.audio(audio_path)
                        except Exception as e:
                            st.error(tr("tts.preview_failed", error=str(e)))
                            logger.exception(e)

            return {
                "narration_text": narration_text,
                "tts_mode": tts_mode,
                "tts_voice": selected_voice,
                "tts_speed": tts_speed,
                "tts_workflow": tts_workflow_key,
            }

    def _render_lipsync_config(self) -> dict:
        with st.container(border=True):
            st.markdown(f"**{tr('video_lipsync.lipsync_params')}**")

            with st.expander(tr("help.feature_description"), expanded=False):
                st.markdown(tr("video_lipsync.lipsync_what"))
                st.markdown(tr("video_lipsync.lipsync_how"))

            lipsync_workflows = []
            for source in ("runninghub", "selfhost"):
                dir_path = os.path.join("workflows", source)
                if not os.path.isdir(dir_path):
                    continue
                for fname in os.listdir(dir_path):
                    if fname.startswith("lip_sync_video_") and fname.endswith(".json"):
                        label = "RunningHub" if source == "runninghub" else "Selfhost"
                        lipsync_workflows.append({
                            "key": f"{source}/{fname}",
                            "display": f"{fname} ({label})",
                        })
            workflow_options = [wf["display"] for wf in lipsync_workflows]
            default_idx = 0
            if not workflow_options:
                workflow_options = [tr("video_lipsync.no_lipsync_workflows")]
                workflow_key = "runninghub/lip_sync_video_latentsync1.5.json"
            else:
                default_idx = next(
                    (i for i, wf in enumerate(lipsync_workflows)
                     if wf["key"] == "runninghub/lip_sync_video_latentsync1.5.json"), 0
                )
            workflow_display = st.selectbox(
                tr("video_lipsync.workflow"),
                workflow_options,
                index=default_idx,
                key="lipsync_workflow_select"
            )
            workflow_key = "runninghub/lip_sync_video_latentsync1.5.json"
            for wf in lipsync_workflows:
                if wf["display"] == workflow_display:
                    workflow_key = wf["key"]
                    break

            check_and_warn_selfhost_workflow(workflow_key)

            col1, col2 = st.columns([1, 1])
            with col1:
                seed = st.number_input(
                    tr("video_lipsync.seed"),
                    value=1234,
                    step=1,
                    key="lipsync_seed"
                )

            with col2:
                lips_expression = st.slider(
                    tr("video_lipsync.lips_expression"),
                    min_value=0.5,
                    max_value=3.0,
                    value=1.5,
                    step=0.1,
                    key="lipsync_lips_expression"
                )
                st.caption(tr("video_lipsync.lips_expression_hint"))

            inference_steps = st.slider(
                tr("video_lipsync.inference_steps"),
                min_value=5,
                max_value=50,
                value=25,
                step=1,
                key="lipsync_inference_steps"
            )
            st.caption(tr("video_lipsync.inference_steps_hint"))

            return {
                "workflow_key": workflow_key,
                "seed": int(seed),
                "lips_expression": float(lips_expression),
                "inference_steps": int(inference_steps),
            }

    def _render_output_preview(self, pixelle_video: Any, params: dict):
        with st.container(border=True):
            st.markdown(f"**{tr('section.video_generation')}**")

            if not config_manager.validate():
                st.warning(tr("settings.not_configured"))

            video_path = params.get("video_path")
            narration_text = params.get("narration_text", "")

            missing = []
            if not video_path:
                missing.append(tr("video_lipsync.video_upload"))
            if not narration_text:
                missing.append(tr("video_lipsync.narration_text"))

            if missing:
                for msg in missing:
                    st.info(msg)
                st.button(
                    tr("btn.generate"),
                    type="primary",
                    use_container_width=True,
                    disabled=True,
                    key="lipsync_generate_disabled"
                )
                return

            if st.button(tr("btn.generate"), type="primary", use_container_width=True, key="lipsync_generate"):
                if not config_manager.validate():
                    st.error(tr("settings.not_configured"))
                    st.stop()

                progress_bar = st.progress(0)
                status_text = st.empty()
                start_time = time.time()

                try:
                    async def generate_lipsync_video():
                        task_dir, task_id = create_task_output_dir()

                        async def update_progress(percent, message):
                            status_text.text(message)
                            progress_bar.progress(percent / 100.0)

                        await update_progress(5, tr("progress.generation"))

                        tts_audio_path = await self._generate_tts_audio(
                            pixelle_video,
                            narration_text,
                            params.get("tts_mode", "local"),
                            params.get("tts_voice"),
                            params.get("tts_speed", 1.0),
                            params.get("tts_workflow"),
                            task_dir,
                        )

                        await update_progress(30, tr("video_lipsync.running_lipsync"))

                        lip_synced = await self._run_lipsync_workflow(
                            pixelle_video,
                            video_path,
                            tts_audio_path,
                            params.get("seed", 1234),
                            params.get("lips_expression", 1.5),
                            params.get("inference_steps", 25),
                            params.get("workflow_key", "runninghub/lip_sync_video_latentsync1.5.json"),
                            task_dir,
                        )

                        await update_progress(70, tr("video_lipsync.mixing_bgm"))

                        if params.get("bgm_path"):
                            final = await self._mix_with_bgm(
                                lip_synced,
                                tts_audio_path,
                                params.get("bgm_path"),
                                params.get("bgm_volume", 0.2),
                                task_dir,
                            )
                        else:
                            import shutil
                            final = Path(task_dir) / "final.mp4"
                            shutil.copy(lip_synced, final)

                        await update_progress(100, tr("status.success"))
                        return str(final)

                    final_path = run_async(generate_lipsync_video())

                    total_time = time.time() - start_time
                    progress_bar.progress(100)
                    status_text.text(tr("status.success"))

                    if os.path.exists(final_path):
                        file_size_mb = os.path.getsize(final_path) / (1024 * 1024)
                        info_text = (
                            f"⏱️ {tr('info.generation_time')} {total_time:.1f}s   "
                            f"📦 {file_size_mb:.2f}MB"
                        )
                        st.caption(info_text)

                        st.markdown("---")
                        st.video(final_path)

                        with open(final_path, "rb") as vf:
                            st.download_button(
                                label="⬇️ 下载视频" if get_language() == "zh_CN" else "⬇️ Download Video",
                                data=vf.read(),
                                file_name=os.path.basename(final_path),
                                mime="video/mp4",
                                use_container_width=True,
                            )
                    else:
                        st.error(tr("status.video_not_found", path=final_path))

                except Exception as e:
                    logger.exception(e)
                    status_text.text("")
                    progress_bar.empty()
                    st.error(tr("status.error", error=str(e)))
                    st.stop()

    async def _generate_tts_audio(self, pixelle_video, text, tts_mode, voice, speed, workflow_key, task_dir):
        if tts_mode == "local":
            import edge_tts
            output_file = Path(task_dir) / "narration.wav"
            rate_str = f"+{int((speed - 1) * 100)}%" if speed != 1.0 else "+0%"
            communicate = edge_tts.Communicate(text, voice or "zh-CN-XiaoxiaoNeural", rate=rate_str)
            await communicate.save(str(output_file))
            return str(output_file)
        else:
            kit = await pixelle_video._get_or_create_comfykit()
            workflow_path = Path("workflows") / (workflow_key or "runninghub/tts_edge.json")
            with open(workflow_path, 'r', encoding='utf-8') as f:
                workflow_config = json.load(f)

            if workflow_config.get("source") == "runninghub" and "workflow_id" in workflow_config:
                workflow_input = workflow_config["workflow_id"]
            else:
                workflow_input = str(workflow_path)

            result = await kit.execute(workflow_input, {"text": text})

            audio_path = None
            if hasattr(result, 'audios') and result.audios:
                audio_path = result.audios[0]
            elif hasattr(result, 'outputs'):
                for node_output in result.outputs.values():
                    if isinstance(node_output, dict):
                        if node_output.get('audios'):
                            audio_path = node_output['audios'][0]
                            break
                        if node_output.get('audio'):
                            audio_path = node_output['audio']
                            break

            if not audio_path:
                raise Exception(tr("tts.error.no_audio"))

            if audio_path.startswith("http"):
                import httpx
                output_file = Path(task_dir) / "narration.wav"
                timeout = httpx.Timeout(120.0)
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.get(audio_path)
                    resp.raise_for_status()
                    with open(output_file, 'wb') as f:
                        f.write(resp.content)
                return str(output_file)

            return audio_path

    async def _run_lipsync_workflow(
        self, pixelle_video, video_path, audio_path,
        seed, lips_expression, inference_steps, workflow_key, task_dir
    ):
        import httpx, time
        from comfykit.comfyui.runninghub_client import RunningHubClient

        with open("workflows/runninghub/lip_sync_video_latentsync1.5.json") as f:
            wf_config = json.load(f)
        workflow_id = wf_config["workflow_id"]

        pv_config = pixelle_video.config.get("comfyui", {})
        rh_api_key = pv_config.get("runninghub_api_key")
        if not rh_api_key:
            raise Exception(tr("video_lipsync.runninghub_api_key_required"))

        rh_client = RunningHubClient(api_key=rh_api_key)

        video_filename = await rh_client.upload_file(video_path)
        audio_filename = await rh_client.upload_file(audio_path)

        node_info_list = [
            {"nodeId": "40", "fieldName": "video", "fieldValue": video_filename},
            {"nodeId": "82", "fieldName": "audio", "fieldValue": audio_filename},
            {"nodeId": "74", "fieldName": "seed", "fieldValue": int(seed)},
            {"nodeId": "84", "fieldName": "value", "fieldValue": float(lips_expression)},
            {"nodeId": "88", "fieldName": "value", "fieldValue": int(inference_steps)},
        ]

        logger.info(
            f"🎬 LatentSync RunningHub Request\n"
            f"   ├─ Workflow ID  : {workflow_id}\n"
            f"   ├─ Local Video  : {video_path}\n"
            f"   ├─ Local Audio  : {audio_path}\n"
            f"   ├─ RH Video Name: {video_filename}\n"
            f"   ├─ RH Audio Name: {audio_filename}\n"
            f"   ├─ Seed        : {seed}\n"
            f"   ├─ Lips Expr.  : {lips_expression}\n"
            f"   ├─ Inference   : {inference_steps}\n"
            f"   └─ Node List   : {node_info_list}"
        )

        task_data = await rh_client.create_task(workflow_id, node_info_list)
        task_id = task_data.get("taskId")
        if not task_id:
            raise Exception(tr("video_lipsync.create_task_failed", data=task_data))

        logger.info(f"✅ LatentSync task created: {task_id}")

        output_video = None
        check_interval = 3
        while True:
            status_info = await rh_client.query_task_status(task_id)
            task_status = status_info.get("status")
            status_msg = status_info.get("msg", "")

            if task_status == "SUCCESS":
                result_data = await rh_client.query_task_result(task_id)
                if isinstance(result_data, list):
                    for item in result_data:
                        if isinstance(item, dict):
                            url = item.get("fileUrl", "")
                            ftype = (item.get("fileType") or "").lower()
                            if "video" in ftype or url.endswith(".mp4"):
                                output_video = url
                                break
                logger.info(f"✅ LatentSync task succeeded: {task_id}")
                break
            elif task_status == "FAILED":
                raise Exception(tr("video_lipsync.task_failed", msg=status_msg))
            else:
                logger.info(f"⏳ LatentSync task {task_id} status: {task_status} ({status_msg})")

            await asyncio.sleep(check_interval)

        if not output_video:
            raise Exception(tr("video_lipsync.no_video_result"))

        output_file = Path(task_dir) / "lipsync_output.mp4"
        timeout = httpx.Timeout(600.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(output_video)
            resp.raise_for_status()
            with open(output_file, 'wb') as f:
                f.write(resp.content)

        return str(output_file)

    async def _mix_with_bgm(self, video_path, narration_path, bgm_path, bgm_volume, task_dir):
        from moviepy.editor import VideoFileClip, AudioFileClip, CompositeAudioClip
        from moviepy.audio.fx.audio_loop import audio_loop
        from pixelle_video.utils.os_util import get_resource_path

        bgm_full_path = get_resource_path("bgm", bgm_path)
        logger.info(
            f"🎵 Mixing with BGM\n"
            f"   ├─ Video   : {video_path}\n"
            f"   ├─ Narration: {narration_path}\n"
            f"   ├─ BGM     : {bgm_full_path}\n"
            f"   └─ Volume  : {bgm_volume}"
        )

        video = VideoFileClip(video_path)
        narration = AudioFileClip(narration_path)
        bgm = AudioFileClip(bgm_full_path)

        bgm_loop = bgm.fx(audio_loop, duration=narration.duration).volumex(bgm_volume)
        logger.info(f"   BGM loop duration: {narration.duration}s, narration duration: {narration.duration}s")

        composite = CompositeAudioClip([narration, bgm_loop])
        video = video.set_audio(composite)

        output_file = Path(task_dir) / "final.mp4"
        video.write_videofile(
            str(output_file), codec='libx264', audio_codec='aac',
            audio_bitrate='192k', verbose=False, logger=None
        )

        video.close()
        narration.close()
        bgm.close()

        logger.info(f"   ✅ BGM mix saved: {output_file}")
        return str(output_file)


register_pipeline_ui(VideoLipSyncPipelineUI)
