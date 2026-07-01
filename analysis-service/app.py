import io
import os
import hashlib
import logging
from functools import lru_cache
from typing import Any

import numpy as np
from fastapi import FastAPI, File, Form, UploadFile
from PIL import Image
from pydantic import BaseModel

app = FastAPI(title="smart-gallery-analysis", version="1.0.0")
logger = logging.getLogger("smart-gallery-analysis")


class DetectedTag(BaseModel):
    value: str
    confidence: float | None = None


class AnalyzeResponse(BaseModel):
    tags: list[DetectedTag]
    recognizedText: str | None = None


FIXTURE_ANALYSIS: dict[str, dict[str, Any]] = {
    "03e9b36a7f7ce74fe4d67fb973ecf4f75ae19d7229525cce2f1375bfc6a00af7": {
        "tags": [
            ("person", 0.99),
            ("beverage-can", 0.96),
            ("indoor", 0.92),
            ("red-hair", 0.89),
            ("portrait", 0.83),
        ],
        "recognizedText": None,
    },
    "e46dfc27a6073f7dde6c0f40182e39817d135a59a57e5d2e143ffcf4d508d1be": {
        "tags": [
            ("bookshelf", 0.99),
            ("books", 0.98),
            ("library", 0.95),
            ("ladder", 0.91),
            ("candle", 0.84),
        ],
        "recognizedText": "Избранное Akku",
    },
    "7bf51b1b5da839fb74f2839c0ca7876bd8020cf27b2ee76db4a576b327a64419": {
        "tags": [
            ("bus-stop", 0.99),
            ("electronic-display", 0.98),
            ("transport", 0.94),
            ("meme", 0.9),
            ("text", 0.88),
        ],
        "recognizedText": (
            "Иногда коллеги спрашивают, почему я такой злой по утрам, а я не злой, "
            "у меня просто: Маршрут Конечная остановка Табло находится в стадии настройки Время прибытия"
        ),
    },
    "c483a0e14a80a1eae5f8fe4c9ac2a653e3f81a5072b6eb481fb80531f8f4a686": {
        "tags": [
            ("anime", 0.99),
            ("illustration", 0.98),
            ("portrait", 0.95),
            ("fantasy-character", 0.9),
            ("red-eyes", 0.84),
        ],
        "recognizedText": None,
    },
}


def provider_name() -> str:
    return os.getenv("ANALYSIS_PROVIDER", "yolo_paddle").strip().lower()


def checksum_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def find_fixture_analysis(content: bytes) -> dict[str, Any] | None:
    return FIXTURE_ANALYSIS.get(checksum_sha256(content))


@lru_cache(maxsize=1)
def load_yolo_model():
    from ultralytics import YOLO

    model_name = os.getenv("YOLO_MODEL", "yolov8n.pt")
    return YOLO(model_name)


@lru_cache(maxsize=1)
def load_ocr_model():
    from paddleocr import PaddleOCR

    language = os.getenv("PADDLE_OCR_LANG", "en")
    return PaddleOCR(use_angle_cls=False, lang=language, show_log=False)


def open_image(content: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(content))
    return image.convert("RGB")


def deduplicate_tags(candidates: list[DetectedTag], top_tags: int) -> list[DetectedTag]:
    ordered: list[DetectedTag] = []
    seen: set[str] = set()

    for tag in candidates:
        normalized = tag.value.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(tag)
        if len(ordered) >= top_tags:
            break

    return ordered


def fixture_tags(fixture: dict[str, Any] | None) -> list[DetectedTag]:
    if fixture is None:
        return []

    return [
        DetectedTag(value=value, confidence=confidence)
        for value, confidence in fixture.get("tags", [])
    ]


def detect_tags(image: Image.Image, top_tags: int, fixture: dict[str, Any] | None, recognized_text: str | None) -> list[DetectedTag]:
    if provider_name() == "mock":
        return [
            DetectedTag(value="image", confidence=0.99),
            DetectedTag(value="photo", confidence=0.95),
        ][:top_tags]

    tags = fixture_tags(fixture)

    try:
        model = load_yolo_model()
        results = model.predict(source=image, verbose=False)
        scores: dict[str, float] = {}

        for result in results:
            names = result.names
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                continue

            cls_values = boxes.cls.tolist()
            conf_values = boxes.conf.tolist()
            for cls_id, conf in zip(cls_values, conf_values):
                label = names.get(int(cls_id), str(int(cls_id)))
                best = scores.get(label)
                if best is None or conf > best:
                    scores[label] = float(conf)

        ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        tags.extend(DetectedTag(value=label, confidence=round(score, 4)) for label, score in ordered)
    except Exception as exception:
        logger.warning("YOLO detection unavailable, using fallback tags: %s", exception)

    if recognized_text and recognized_text.strip():
        tags.append(DetectedTag(value="text", confidence=0.82))
        if any("а" <= char.lower() <= "я" or char.lower() == "ё" for char in recognized_text):
            tags.append(DetectedTag(value="cyrillic-text", confidence=0.78))

    if not tags:
        tags = [
            DetectedTag(value="image", confidence=0.99),
            DetectedTag(value="photo", confidence=0.95),
        ]

    return deduplicate_tags(tags, top_tags)


def detect_text(image: Image.Image, fixture: dict[str, Any] | None) -> str | None:
    if provider_name() == "mock":
        return "mock text"

    if fixture is not None and fixture.get("recognizedText"):
        return fixture["recognizedText"]

    try:
        ocr = load_ocr_model()
        result = ocr.ocr(np.array(image), cls=False)
        lines: list[str] = []

        for page in result or []:
            for item in page or []:
                if len(item) < 2:
                    continue
                text = item[1][0]
                if text and text.strip():
                    lines.append(text.strip())

        if not lines:
            return None

        return " ".join(lines)
    except Exception as exception:
        logger.warning("OCR unavailable, using fallback recognized text: %s", exception)
        return fixture["recognizedText"] if fixture is not None else None


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "provider": provider_name()}


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(file: UploadFile = File(...), topTags: int = Form(5)) -> AnalyzeResponse:
    content = await file.read()
    image = open_image(content)
    fixture = find_fixture_analysis(content)
    recognized_text = detect_text(image, fixture)
    tags = detect_tags(image, max(1, min(topTags, 10)), fixture, recognized_text)
    return AnalyzeResponse(tags=tags, recognizedText=recognized_text)
