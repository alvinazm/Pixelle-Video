import asyncio
import tomllib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from loguru import logger

_pool = ThreadPoolExecutor(max_workers=1)


def run_async(coro, timeout=10):
    loop = None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        pass

    if loop is not None:
        f = asyncio.ensure_future(coro)

        def _sync_wait():
            future = _pool.submit(loop.run_until_complete, f)
            try:
                return future.result(timeout=timeout)
            except TimeoutError:
                # Cancel the asyncio task to unblock the loop
                f.cancel()
                # Close browser to recover from stuck state
                from pixelle_video.services.frame_html import HTMLFrameGenerator
                import asyncio
                try:
                    loop.run_until_complete(HTMLFrameGenerator.close_browser())
                except Exception:
                    pass
                raise TimeoutError(f"Async operation timed out after {timeout}s")

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
