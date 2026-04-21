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
Uses st.navigation to define pages and set the default page to Home.
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
    """Main entry point with navigation"""
    # Define pages using st.Page
    home_page = st.Page(
        "pages/1_🎬_Home.py",
        title="Home",
        icon="🎬",
        default=True
    )

    history_page = st.Page(
        "pages/2_📚_History.py",
        title="History",
        icon="📚"
    )

    # Pipeline pages (sorted by display order)
    pipeline_pages = [
        st.Page("pages/2_Quick_Create.py", title="Quick Create", icon="⚡"),
        st.Page("pages/3_Custom_Media.py", title="Custom Media", icon="🎨"),
        st.Page("pages/4_Digital_Human.py", title="Digital Human", icon="🤖"),
        st.Page("pages/5_Image_To_Video.py", title="Image to Video", icon="🎥"),
        st.Page("pages/6_Action_Transfer.py", title="Action Transfer", icon="💃"),
        st.Page("pages/7_Video_LipSync.py", title="Video LipSync", icon="🎙️"),
        st.Page("pages/8_Douyin_Parser.py", title="Douyin Parser", icon="🔍"),
    ]

    # Set up navigation and run
    pg = st.navigation(
        {
            "": [home_page],
            "📺 Pipelines": pipeline_pages,
            "🗂️ History": [history_page],
        }
    )
    pg.run()


if __name__ == "__main__":
    main()
