import asyncio
import tomllib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from loguru import logger

_pool = ThreadPoolExecutor(max_workers=1)


def run_async(coro):
    loop = None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        pass

    if loop is not None:
        f = asyncio.ensure_future(coro)

        def _sync_wait():
            return _pool.submit(loop.run_until_complete, f).result()

        return _sync_wait()

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(coro)


def get_project_version():
    try:
        web_dir = Path(__file__).resolve().parent.parent
        project_root = web_dir.parent
        pyproject_path = project_root / "pyproject.toml"

        if pyproject_path.exists():
            with open(pyproject_path, "rb") as f:
                pyproject_data = tomllib.load(f)
                return pyproject_data.get("project", {}).get("version", "Unknown")
    except Exception as e:
        logger.warning(f"Failed to read version from pyproject.toml: {e}")
    return "Unknown"
