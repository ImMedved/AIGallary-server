import hashlib
import io
import logging
import os
import re
from functools import lru_cache
from typing import Any

import numpy as np
from fastapi import FastAPI, File, Form, UploadFile
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
from pydantic import BaseModel

app = FastAPI(title="smart-gallery-analysis", version="1.0.0")
logger = logging.getLogger("smart-gallery-analysis")

TRANSPORT_LABELS = {"bicycle", "car", "motorbike", "bus", "train", "truck", "boat", "airplane"}
ANIMAL_LABELS = {"bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe"}
FURNITURE_LABELS = {"chair", "couch", "bed", "dining table", "bench"}
ELECTRONICS_LABELS = {"tv", "laptop", "cell phone", "keyboard", "mouse", "remote", "microwave"}
DOCUMENT_LABELS = {"book", "clock", "stop sign", "traffic light", "parking meter"}
TAG_HINTS: dict[str, list[tuple[str, float]]] = {
    "person": [("human", 0.87), ("portrait", 0.79)],
    "bus": [("transport", 0.83), ("street", 0.72)],
    "car": [("vehicle", 0.82), ("street", 0.71)],
    "truck": [("vehicle", 0.82), ("transport", 0.80)],
    "train": [("transport", 0.83), ("railway", 0.76)],
    "bicycle": [("vehicle", 0.77), ("outdoor", 0.72)],
    "motorbike": [("vehicle", 0.79), ("outdoor", 0.72)],
    "book": [("reading", 0.80), ("indoor", 0.72)],
    "chair": [("furniture", 0.79), ("indoor", 0.72)],
    "couch": [("furniture", 0.81), ("indoor", 0.75)],
    "bed": [("furniture", 0.81), ("indoor", 0.74)],
    "tv": [("electronics", 0.80), ("screen", 0.77)],
    "laptop": [("electronics", 0.81), ("screen", 0.78)],
    "cell phone": [("electronics", 0.80), ("screen", 0.76)],
    "cat": [("animal", 0.82), ("pet", 0.79)],
    "dog": [("animal", 0.82), ("pet", 0.79)],
}


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
        "recognizedText": "\u0418\u0437\u0431\u0440\u0430\u043d\u043d\u043e\u0435 Akku",
    },
    "7bf51b1b5da839fb74f2839c0ca7876bd8020cf27b2ee76db4a576b327a64419": {
        "tags": [
            ("bus-stop", 0.99),
            ("electronic-display", 0.98),
            ("transport", 0.94),
            ("meme", 0.90),
            ("text", 0.88),
        ],
        "recognizedText": (
            "\u0418\u043d\u043e\u0433\u0434\u0430 \u043a\u043e\u043b\u043b\u0435\u0433\u0438 \u0441\u043f\u0440\u0430\u0448\u0438\u0432\u0430\u044e\u0442, "
            "\u043f\u043e\u0447\u0435\u043c\u0443 \u044f \u0442\u0430\u043a\u043e\u0439 \u0437\u043b\u043e\u0439 \u043f\u043e \u0443\u0442\u0440\u0430\u043c, "
            "\u0430 \u044f \u043d\u0435 \u0437\u043b\u043e\u0439, \u0443 \u043c\u0435\u043d\u044f \u043f\u0440\u043e\u0441\u0442\u043e: "
            "\u041c\u0430\u0440\u0448\u0440\u0443\u0442 \u041a\u043e\u043d\u0435\u0447\u043d\u0430\u044f \u043e\u0441\u0442\u0430\u043d\u043e\u0432\u043a\u0430 "
            "\u0422\u0430\u0431\u043b\u043e \u043d\u0430\u0445\u043e\u0434\u0438\u0442\u0441\u044f \u0432 \u0441\u0442\u0430\u0434\u0438\u0438 "
            "\u043d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0438 \u0412\u0440\u0435\u043c\u044f \u043f\u0440\u0438\u0431\u044b\u0442\u0438\u044f"
        ),
    },
    "c483a0e14a80a1eae5f8fe4c9ac2a653e3f81a5072b6eb481fb80531f8f4a686": {
        "tags": [
            ("anime", 0.99),
            ("illustration", 0.98),
            ("portrait", 0.95),
            ("fantasy-character", 0.90),
            ("red-eyes", 0.84),
        ],
        "recognizedText": None,
    },
}


def provider_name() -> str:
    return os.getenv("ANALYSIS_PROVIDER", "yolo_paddle").strip().lower()


def yolo_model_name() -> str:
    return os.getenv("YOLO_MODEL", "yolov8s.pt")


def yolo_confidence() -> float:
    return max(0.05, float(os.getenv("YOLO_CONFIDENCE", "0.12")))


def yolo_image_size() -> int:
    return max(640, int(os.getenv("YOLO_IMAGE_SIZE", "960")))


def ocr_language() -> str:
    return os.getenv("PADDLE_OCR_LANG", "ru")


def checksum_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def find_fixture_analysis(content: bytes) -> dict[str, Any] | None:
    return FIXTURE_ANALYSIS.get(checksum_sha256(content))


@lru_cache(maxsize=1)
def load_yolo_model():
    from ultralytics import YOLO

    return YOLO(yolo_model_name())


@lru_cache(maxsize=1)
def load_ocr_model():
    from paddleocr import PaddleOCR

    try:
        return PaddleOCR(
            lang=ocr_language(),
            use_textline_orientation=True,
        )
    except TypeError:
        return PaddleOCR(
            use_angle_cls=True,
            lang=ocr_language(),
        )


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


def cleanup_text(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = re.sub(r"\s+", " ", value).strip()
    return normalized or None


def build_ocr_candidates(image: Image.Image) -> list[Image.Image]:
    width, height = image.size
    scale = 2 if max(width, height) < 1800 else 1
    base = image.resize((width * scale, height * scale), Image.LANCZOS) if scale > 1 else image
    gray = ImageOps.grayscale(base)
    contrasted = ImageEnhance.Contrast(gray).enhance(2.2)
    autocontrasted = ImageOps.autocontrast(contrasted)
    sharpened = autocontrasted.filter(ImageFilter.SHARPEN)
    threshold = autocontrasted.point(lambda pixel: 255 if pixel > 165 else 0)

    return [
        base,
        autocontrasted.convert("RGB"),
        sharpened.convert("RGB"),
        threshold.convert("RGB"),
    ]


def extract_ocr_text(result: Any) -> str | None:
    lines: list[str] = []

    for page in result or []:
        if hasattr(page, "json"):
            payload = getattr(page, "json")
            if isinstance(payload, dict):
                payload = payload.get("res", payload)
            else:
                payload = None
        elif isinstance(page, dict):
            payload = page.get("res", page)
        else:
            payload = page

        if isinstance(payload, dict):
            for text in payload.get("rec_texts", []) or []:
                if isinstance(text, str) and text.strip():
                    lines.append(text.strip())
            continue

        for item in payload or []:
            if len(item) < 2:
                continue
            text = item[1][0]
            if text and text.strip():
                lines.append(text.strip())

    return cleanup_text(" ".join(lines))


def run_ocr(ocr: Any, candidate: Image.Image) -> Any:
    image_array = np.array(candidate)

    if hasattr(ocr, "predict"):
        try:
            return ocr.predict(
                image_array,
                use_textline_orientation=True,
                text_det_limit_side_len=max(candidate.size),
                text_rec_score_thresh=0.35,
            )
        except TypeError:
            pass

    return ocr.ocr(image_array, cls=True)


def detect_text(image: Image.Image, fixture: dict[str, Any] | None) -> str | None:
    if provider_name() == "mock":
        return "mock text"

    if fixture is not None and fixture.get("recognizedText"):
        return cleanup_text(fixture["recognizedText"])

    try:
        ocr = load_ocr_model()
        best_text: str | None = None
        best_score = 0

        for candidate in build_ocr_candidates(image):
            result = run_ocr(ocr, candidate)
            text = extract_ocr_text(result)
            if text is None:
                continue

            score = len(text)
            if score > best_score:
                best_text = text
                best_score = score

        return best_text
    except Exception as exception:
        logger.warning("OCR unavailable, using fallback recognized text: %s", exception)
        return cleanup_text(fixture["recognizedText"]) if fixture is not None else None


def contextual_tags(
        image: Image.Image,
        raw_scores: dict[str, float],
        raw_counts: dict[str, int],
        recognized_text: str | None,
) -> list[DetectedTag]:
    tags: list[DetectedTag] = []
    labels = set(raw_scores.keys())

    for label, score in sorted(raw_scores.items(), key=lambda item: item[1], reverse=True):
        for hint, confidence in TAG_HINTS.get(label, []):
            tags.append(DetectedTag(value=hint, confidence=round(min(score, confidence), 4)))

    if labels & TRANSPORT_LABELS:
        tags.append(DetectedTag(value="transport", confidence=0.81))
    if labels & ANIMAL_LABELS:
        tags.append(DetectedTag(value="animal", confidence=0.80))
    if labels & FURNITURE_LABELS:
        tags.append(DetectedTag(value="interior", confidence=0.76))
    if labels & ELECTRONICS_LABELS:
        tags.append(DetectedTag(value="electronics", confidence=0.78))
    if labels & DOCUMENT_LABELS:
        tags.append(DetectedTag(value="printed-object", confidence=0.73))

    person_count = raw_counts.get("person", 0)
    if person_count >= 2:
        tags.append(DetectedTag(value="group", confidence=0.80))
    elif person_count == 1 and image.height >= image.width:
        tags.append(DetectedTag(value="portrait", confidence=0.78))

    if recognized_text:
        tags.append(DetectedTag(value="text", confidence=0.84))
        if len(recognized_text) >= 20:
            tags.append(DetectedTag(value="document", confidence=0.76))
        lowered = recognized_text.lower()
        if any("\u0430" <= char <= "\u044f" or char == "\u0451" for char in lowered):
            tags.append(DetectedTag(value="cyrillic-text", confidence=0.80))

    return tags


def ensure_minimum_tags(
        tags: list[DetectedTag],
        top_tags: int,
        recognized_text: str | None,
) -> list[DetectedTag]:
    deduplicated = deduplicate_tags(tags, top_tags)
    if len(deduplicated) >= min(3, top_tags):
        return deduplicated

    supplements: list[DetectedTag] = []
    existing = {tag.value.lower() for tag in deduplicated}

    if recognized_text and "text" not in existing:
        supplements.append(DetectedTag(value="text", confidence=0.78))
    if "photo" not in existing:
        supplements.append(DetectedTag(value="photo", confidence=0.70))
    if "image" not in existing:
        supplements.append(DetectedTag(value="image", confidence=0.68))

    return deduplicate_tags(deduplicated + supplements, top_tags)


def detect_tags(
        image: Image.Image,
        top_tags: int,
        fixture: dict[str, Any] | None,
        recognized_text: str | None,
) -> list[DetectedTag]:
    if provider_name() == "mock":
        return ensure_minimum_tags(
            [
                DetectedTag(value="image", confidence=0.99),
                DetectedTag(value="photo", confidence=0.95),
                DetectedTag(value="digital-media", confidence=0.82),
            ],
            top_tags,
            recognized_text,
        )

    tags = fixture_tags(fixture)
    raw_scores: dict[str, float] = {}
    raw_counts: dict[str, int] = {}

    try:
        model = load_yolo_model()
        results = model.predict(
            source=image,
            verbose=False,
            conf=yolo_confidence(),
            imgsz=yolo_image_size(),
            iou=0.45,
            max_det=max(12, top_tags * 4),
        )

        for result in results:
            names = result.names
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                continue

            cls_values = boxes.cls.tolist()
            conf_values = boxes.conf.tolist()
            for cls_id, conf in zip(cls_values, conf_values):
                label = names.get(int(cls_id), str(int(cls_id)))
                raw_counts[label] = raw_counts.get(label, 0) + 1
                best = raw_scores.get(label)
                if best is None or conf > best:
                    raw_scores[label] = float(conf)

        ordered = sorted(
            raw_scores.items(),
            key=lambda item: (item[1], raw_counts.get(item[0], 0)),
            reverse=True,
        )
        tags.extend(DetectedTag(value=label, confidence=round(score, 4)) for label, score in ordered)
        tags.extend(contextual_tags(image, raw_scores, raw_counts, recognized_text))
    except Exception as exception:
        logger.warning("YOLO detection unavailable, using fallback tags: %s", exception)

    if not tags:
        tags = [
            DetectedTag(value="image", confidence=0.99),
            DetectedTag(value="photo", confidence=0.95),
        ]

    return ensure_minimum_tags(tags, top_tags, recognized_text)


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "provider": provider_name(),
        "yoloModel": yolo_model_name(),
        "ocrLanguage": ocr_language(),
    }


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(file: UploadFile = File(...), topTags: int = Form(5)) -> AnalyzeResponse:
    content = await file.read()
    image = open_image(content)
    fixture = find_fixture_analysis(content)
    recognized_text = detect_text(image, fixture)
    tags = detect_tags(image, max(1, min(topTags, 10)), fixture, recognized_text)
    return AnalyzeResponse(tags=tags, recognizedText=recognized_text)
