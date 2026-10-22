from pathlib import Path

import pytest

from app.orchestration.tools_doc import extract_document_text

FIXTURE = Path(__file__).parent / "fixtures"


def test_image_goes_to_ocr(monkeypatch, tmp_path: Path):
    seen = {}

    def fake(data: bytes, mime: str) -> str:
        seen["mime"] = mime
        seen["size"] = len(data)
        return "锅圈食汇 实付 128.50 元"

    monkeypatch.setattr("app.orchestration.tools_ocr.recognize", fake)
    image = tmp_path / "slip.png"
    image.write_bytes(b"\x89PNG\r\nnot-a-real-image")
    # extract imports recognize inside the function from tools_ocr
    text = extract_document_text(image)
    assert "128.50" in text
    assert seen["mime"] == "image/png"


def test_text_pdf_does_not_call_ocr(monkeypatch):
    called = {"n": 0}

    def fake(*_a, **_k):
        called["n"] += 1
        return "不应走到这里"

    monkeypatch.setattr("app.orchestration.tools_ocr.recognize", fake)
    sample = FIXTURE / "text_layer.pdf"
    if not sample.exists():
        pytest.skip("缺少文字版 PDF 夹具")
    text = extract_document_text(sample)
    assert "nianjia" in text
    assert called["n"] == 0


def test_image_pdf_uses_ocr(monkeypatch):
    monkeypatch.setattr("app.orchestration.tools_ocr.recognize", lambda *_a, **_k: "扫描件 实付 88 元")
    sample = FIXTURE / "scan_page.pdf"
    if not sample.exists():
        pytest.skip("缺少扫描版 PDF 夹具")
    text = extract_document_text(sample)
    assert "88" in text
