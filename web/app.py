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
Pixelle-Video Web UI - Main Entry Point

This is the entry point for the Streamlit multi-page application.
Uses st.navigation to define pages and set the default page to Home (首页).
"""

import sys
from pathlib import Path

# Add project root to sys.path for module imports
_script_dir = Path(__file__).resolve().parent
_project_root = _script_dir.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import streamlit as st
from loguru import logger

log_file = _project_root / "web.log"
logger.add(log_file, rotation="10 MB", retention="7 days", level="INFO",
           format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}")


def main():
    home_page = st.Page(
        "pages/1_🎬_Home.py",
        title="首页",
        icon="🎬",
        default=True
    )

    history_page = st.Page(
        "pages/2_📚_History.py",
        title="历史记录",
        icon="📚"
    )

    pipeline_pages = [
        st.Page("pages/3_Douyin_Parser.py", title="文案提取", icon="🔍"),
        st.Page("pages/4_Quick_Create.py", title="文生视频", icon="⚡"),
        st.Page("pages/5_Custom_Media.py", title="自定义素材", icon="🎨"),
        st.Page("pages/6_Digital_Human.py", title="数字人口播", icon="🤖"),
        st.Page("pages/7_Image_To_Video.py", title="图生视频", icon="🎥"),
        st.Page("pages/8_Action_Transfer.py", title="动作迁移", icon="💃"),
        st.Page("pages/9_Video_LipSync.py", title="视频对口型", icon="🎙️"),
    ]

    pg = st.navigation(
        {
            "": [home_page],
            "📺 流水线": pipeline_pages,
            "🗂️ 历史": [history_page],
        }
    )
    pg.run()


if __name__ == "__main__":
    main()
