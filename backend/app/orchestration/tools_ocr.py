"""扫描件和图片转文字。只给这一小步用，不进对话模型列表。"""
from __future__ import annotations

import base64
import re

import httpx

from ..core.llm import LlmError, resolve_model

OCR_MODEL_ID = "deepseek-ocr"
_PROMPT = "<image>\nFree OCR."
_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


def recognize_path(path, *, transport: httpx.BaseTransport | None = None) -> str:
    """读一张已落盘的图片并识别。不是图片或读失败时如实抛错。"""
    from pathlib import Path

    file = Path(path)
    mime = _MIME.get(file.suffix.lower())
    if mime is None:
        raise ValueError(f"不是可识别的图片：{file.name}")
    return recognize(file.read_bytes(), mime, transport=transport)


def recognize(data: bytes, mime: str, *, transport: httpx.BaseTransport | None = None) -> str:
    """把一页图片交给 DeepSeek-OCR。失败如实抛错，不编造文字。"""
    if not data:
        raise ValueError("图片是空的")
    if len(data) > 4_000_000:
        raise ValueError("图片超过 4MB，请先裁成单页再识别")
    try:
        base_url, api_key, _api_model = resolve_model(OCR_MODEL_ID)
    except LlmError as e:
        raise RuntimeError(f"扫描识别不可用：{e}") from e
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": "deepseek-ai/DeepSeek-OCR",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{base64.b64encode(data).decode()}"},
                    },
                ],
            }
        ],
        "temperature": 0,
    }
    last_error = "扫描识别没有读到文字"
    for _ in range(2):
        try:
            with httpx.Client(timeout=60, transport=transport) as client:
                resp = client.post(url, json=payload, headers={"Authorization": f"Bearer {api_key}"})
        except httpx.HTTPError as e:
            raise RuntimeError(f"扫描识别请求失败：{type(e).__name__}") from e
        if resp.status_code != 200:
            raise RuntimeError(f"扫描识别返回 {resp.status_code}")
        try:
            content = resp.json()["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError, ValueError) as e:
            raise RuntimeError("扫描识别响应里没有文字") from e
        text = str(content).strip().lstrip("}").strip()
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", text).strip()
        useful = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", text)
        if len(useful) >= 4:
            return text
        last_error = "扫描识别没有读到文字"
    raise RuntimeError(last_error)
