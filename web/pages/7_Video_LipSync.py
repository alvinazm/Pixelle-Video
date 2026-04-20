import sys
from pathlib import Path

_script_dir = Path(__file__).resolve().parent
_project_root = _script_dir.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import streamlit as st

from web.state.session import init_session_state, init_i18n, get_pixelle_video
from web.components.header import render_header
from web.components.settings import render_advanced_settings
from web.components.faq import render_faq_sidebar
from web.pipelines import get_pipeline_ui

st.set_page_config(
    page_title="Video LipSync - Pixelle-Video",
    page_icon="🎙️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

def main():
    init_session_state()
    init_i18n()
    render_header()
    render_faq_sidebar()
    render_advanced_settings()

    pixelle_video = get_pixelle_video()
    pipeline = get_pipeline_ui("video_lipsync")

    if pipeline.description:
        st.caption(pipeline.description)

    pipeline.render(pixelle_video)


if __name__ == "__main__":
    main()
