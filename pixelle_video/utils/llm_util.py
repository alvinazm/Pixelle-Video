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
LLM utility functions for model discovery and connection testing.

Uses the standard OpenAI-compatible /v1/models endpoint.
"""

from typing import List, Tuple
import httpx
from loguru import logger


def fetch_available_models(api_key: str, base_url: str, timeout: float = 10.0) -> List[str]:
    base_url = base_url.rstrip("/")
    if base_url.endswith("/v1"):
        models_url = f"{base_url}/models"
    else:
        models_url = f"{base_url}/v1/models"

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    logger.debug(f"Fetching models from: {models_url}")

    with httpx.Client(timeout=timeout) as client:
        response = client.get(models_url, headers=headers)
        if response.status_code == 404:
            logger.debug("Provider does not support /v1/models endpoint")
            return []
        response.raise_for_status()
        data = response.json()
        models = [m["id"] for m in data.get("data", [])]
        models.sort()
        logger.debug(f"Fetched {len(models)} models")
        return models


def _fetch_models_via_chat_completion(
    api_key: str, base_url: str, timeout: float = 10.0
) -> List[str]:
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        chat_url = f"{base}/chat/completions"
    else:
        chat_url = f"{base}/v1/chat/completions"

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "list models"}],
        "max_tokens": 5,
    }

    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(chat_url, headers=headers, json=payload)
        if response.status_code == 401:
            return []
        if response.status_code in (400, 200):
            return []
        return []
    except Exception:
        return []


def test_llm_connection(
    api_key: str, base_url: str, timeout: float = 10.0
) -> Tuple[bool, str, int]:
    try:
        models = fetch_available_models(api_key, base_url, timeout)
        return True, f"Connection successful! {len(models)} models available.", len(models)
    except httpx.HTTPStatusError as e:
        status_code = e.response.status_code
        if status_code == 401:
            return False, "Authentication failed: Invalid API Key", 0
        elif status_code == 403:
            return False, "Access forbidden: Check your API Key permissions", 0
        elif status_code == 404:
            return _test_connection_via_chat_completion(api_key, base_url, timeout)
        else:
            return False, f"API error: HTTP {status_code}", 0
    except httpx.ConnectError:
        return False, "Connection failed: Cannot reach the server", 0
    except httpx.TimeoutException:
        return False, "Connection timeout: Server did not respond in time", 0
    except Exception as e:
        logger.error(f"LLM connection test error: {e}")
        return False, f"Error: {str(e)}", 0


def _test_connection_via_chat_completion(
    api_key: str, base_url: str, timeout: float = 10.0
) -> Tuple[bool, str, int]:
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        chat_url = f"{base}/chat/completions"
    else:
        chat_url = f"{base}/v1/chat/completions"

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 5,
    }

    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(chat_url, headers=headers, json=payload)
        if response.status_code == 401:
            return False, "Authentication failed: Invalid API Key", 0
        if response.status_code == 400:
            return True, "Connection successful (API reachable, model name may need adjustment).", 0
        if response.status_code == 200:
            return True, "Connection successful!", 0
        return False, f"API error: HTTP {response.status_code}", 0
    except httpx.ConnectError:
        return False, "Connection failed: Cannot reach the server", 0
    except httpx.TimeoutException:
        return False, "Connection timeout: Server did not respond in time", 0
    except Exception:
        return False, "API endpoint not found: Check your Base URL", 0
