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
from web.i18n import tr
from web.pipelines import get_all_pipeline_uis

st.set_page_config(
    page_title="Home - Pixelle-Video",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="collapsed",
)

name_to_page = {
    "quick_create": "pages/2_Quick_Create.py",
    "custom_media": "pages/3_Custom_Media.py",
    "digital_human": "pages/4_Digital_Human.py",
    "image_to_video": "pages/5_Image_To_Video.py",
    "action_transfer": "pages/6_Action_Transfer.py",
    "video_lipsync": "pages/7_Video_LipSync.py",
    "douyin_parser": "pages/8_Douyin_Parser.py",
}


def main():
    init_session_state()
    init_i18n()

    render_header()
    render_faq_sidebar()
    get_pixelle_video()
    render_advanced_settings()

    st.markdown("---")
    st.markdown(f"### {tr('nav.choose_pipeline')}")

    pipelines = get_all_pipeline_uis()

    name_order = [
        "quick_create", "custom_media", "digital_human",
        "image_to_video", "action_transfer", "video_lipsync",
        "douyin_parser"
    ]
    sorted_pipelines = sorted(
        pipelines,
        key=lambda p: name_order.index(p.name) if p.name in name_order else 99
    )

    cols = st.columns(2)
    for i, pipeline in enumerate(sorted_pipelines):
        with cols[i % 2]:
            page_path = name_to_page.get(pipeline.name, "")

            icon_col, text_col = st.columns([1, 10])
            with icon_col:
                st.markdown(
                    f"<div style='font-size:2rem;text-align:center;padding-top:0.3rem'>{pipeline.icon}</div>",
                    unsafe_allow_html=True,
                )
            with text_col:
                st.markdown(f"**{pipeline.display_name}**")
                st.caption(pipeline.description or "")

            st.page_link(page_path, label="进入", use_container_width=True)
            st.divider()


if __name__ == "__main__":
    main()
