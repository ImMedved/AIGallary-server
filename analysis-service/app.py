import base64
import hashlib
import io
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import numpy as np
from fastapi import FastAPI, File, Form, UploadFile
from fastapi import Request
from PIL import Image, ImageEnhance, ImageFilter, ImageOps, ImageStat
from pydantic import BaseModel, Field

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

app = FastAPI(title="smart-gallery-analysis", version="2.0.0")
logger = logging.getLogger("smart-gallery-analysis")
job_logger = logging.getLogger("smart-gallery-analysis.jobs")

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

DEFAULT_CLIP_TAGS = [
    "photo", "screenshot", "document", "receipt", "invoice", "meme", "text", "code screenshot",
    "chat screenshot", "game screenshot", "anime", "illustration", "portrait", "selfie", "group photo",
    "cat", "dog", "pet", "food", "drink", "street", "city", "transport", "car", "bus", "train",
    "nature", "forest", "mountain", "sea", "beach", "home", "indoor", "office", "computer",
    "book", "bookshelf", "monitor", "keyboard", "phone", "table", "sofa", "bedroom", "kitchen",
]

FIXTURE_ANALYSIS: dict[str, dict[str, Any]] = {
    "03e9b36a7f7ce74fe4d67fb973ecf4f75ae19d7229525cce2f1375bfc6a00af7": {
        "tags": [("person", 0.99), ("beverage-can", 0.96), ("indoor", 0.92), ("red-hair", 0.89), ("portrait", 0.83)],
        "recognizedText": None,
    },
    "e46dfc27a6073f7dde6c0f40182e39817d135a59a57e5d2e143ffcf4d508d1be": {
        "tags": [("bookshelf", 0.99), ("books", 0.98), ("library", 0.95), ("ladder", 0.91), ("candle", 0.84)],
        "recognizedText": "Избранное Akku",
    },
    "7bf51b1b5da839fb74f2839c0ca7876bd8020cf27b2ee76db4a576b327a64419": {
        "tags": [("bus-stop", 0.99), ("electronic-display", 0.98), ("transport", 0.94), ("meme", 0.90), ("text", 0.88)],
        "recognizedText": "Иногда коллеги спрашивают, почему я такой злой по утрам, а я не злой, у меня просто: Маршрут Конечная остановка Табло находится в стадии настройки Время прибытия",
    },
    "c483a0e14a80a1eae5f8fe4c9ac2a653e3f81a5072b6eb481fb80531f8f4a686": {
        "tags": [("anime", 0.99), ("illustration", 0.98), ("portrait", 0.95), ("fantasy-character", 0.90), ("red-eyes", 0.84)],
        "recognizedText": None,
    },
}


class DetectedTag(BaseModel):
    value: str
    confidence: float | None = None
    source: str | None = None
    reason: str | None = None


class OcrBlock(BaseModel):
    text: str
    confidence: float | None = None
    bbox: list[float] | None = None


class OcrCandidateDebug(BaseModel):
    name: str
    width: int
    height: int
    lineCount: int
    charCount: int
    averageConfidence: float | None = None
    score: float
    preview: str | None = None
    error: str | None = None


class YoloDetectionDebug(BaseModel):
    label: str
    confidence: float
    count: int


class ClipCandidateDebug(BaseModel):
    tag: str
    confidence: float
    prompt: str


class AnalysisDebugPayload(BaseModel):
    checksum: str
    filename: str | None = None
    imageWidth: int
    imageHeight: int
    provider: str
    imageKind: str
    timingsMs: dict[str, int] = Field(default_factory=dict)
    ocrCandidates: list[OcrCandidateDebug] = Field(default_factory=list)
    ocrBlocks: list[OcrBlock] = Field(default_factory=list)
    rawYoloLabels: list[YoloDetectionDebug] = Field(default_factory=list)
    clipScores: list[ClipCandidateDebug] = Field(default_factory=list)
    finalTagReasons: list[DetectedTag] = Field(default_factory=list)
    vlmCaption: str | None = None
    errors: list[str] = Field(default_factory=list)


class AnalyzeResponse(BaseModel):
    tags: list[DetectedTag]
    recognizedText: str | None = None
    caption: str | None = None
    ocrBlocks: list[OcrBlock] | None = None
    debug: AnalysisDebugPayload | None = None


@dataclass
class OcrCandidateResult:
    name: str
    text: str | None
    blocks: list[OcrBlock]
    debug: OcrCandidateDebug


@dataclass
class TagCandidate:
    value: str
    confidence: float | None
    source: str
    reason: str


def bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def provider_name() -> str:
    return os.getenv("ANALYSIS_PROVIDER", "yolo_paddle_clip").strip().lower()


def yolo_model_name() -> str:
    return os.getenv("YOLO_MODEL", "yolov8s.pt")


def yolo_confidence() -> float:
    return max(0.05, float(os.getenv("YOLO_CONFIDENCE", "0.18")))


def yolo_image_size() -> int:
    return max(640, int(os.getenv("YOLO_IMAGE_SIZE", "960")))


def ocr_language() -> str:
    return os.getenv("PADDLE_OCR_LANG", "ru")


def clip_enabled() -> bool:
    return bool_env("ENABLE_CLIP", True) and provider_name() != "mock"


def clip_model_name() -> str:
    return os.getenv("CLIP_MODEL", "ViT-B-32")


def clip_pretrained_name() -> str:
    return os.getenv("CLIP_PRETRAINED", "openai")


def clip_min_confidence() -> float:
    return float(os.getenv("CLIP_MIN_CONFIDENCE", "0.12"))


def clip_top_k() -> int:
    return max(1, int(os.getenv("CLIP_TOP_K", "8")))


def clip_tags() -> list[str]:
    raw = os.getenv("CLIP_TAGS")
    if not raw:
        return DEFAULT_CLIP_TAGS
    return [tag.strip() for tag in raw.split(",") if tag.strip()]


def save_debug_enabled() -> bool:
    return bool_env("ANALYSIS_SAVE_DEBUG", True)


def include_debug_by_default() -> bool:
    return bool_env("ANALYSIS_INCLUDE_DEBUG_IN_RESPONSE", False)


def debug_dir() -> Path:
    return Path(os.getenv("ANALYSIS_DEBUG_DIR", "/tmp/smart-gallery-analysis-debug"))


def vlm_enabled() -> bool:
    return bool_env("ENABLE_VLM", False) and provider_name() != "mock"


def vlm_model_name() -> str:
    return os.getenv("VLM_MODEL", "llava:7b")


def ollama_url() -> str:
    return os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")


def checksum_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def find_fixture_analysis(content: bytes) -> dict[str, Any] | None:
    return FIXTURE_ANALYSIS.get(checksum_sha256(content))


def short_checksum(value: str) -> str:
    return value[:12]


def preview_text(value: str | None, limit: int = 120) -> str | None:
    if value is None:
        return None
    if len(value) <= limit:
        return value
    return value[:limit] + "..."


def cleanup_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"\s+", " ", value).strip()
    return normalized or None


def open_image(content: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(content))
    return image.convert("RGB")


def serialize_tags(tags: list[DetectedTag]) -> list[str]:
    return [f"{tag.value}:{tag.confidence:.3f}" if tag.confidence is not None else tag.value for tag in tags]


def now_ms() -> int:
    return int(time.perf_counter() * 1000)


def elapsed_ms(start_ms: int) -> int:
    return max(0, now_ms() - start_ms)


@app.middleware("http")
async def api_request_logging_middleware(request: Request, call_next):
    path = request.url.path
    if path == "/health":
        return await call_next(request)

    started_at = now_ms()
    job_logger.info("API request started method=%s path=%s", request.method, path)
    try:
        response = await call_next(request)
        job_logger.info(
            "API request completed method=%s path=%s status=%s durationMs=%s",
            request.method,
            path,
            response.status_code,
            elapsed_ms(started_at),
        )
        return response
    except Exception as exception:
        job_logger.exception(
            "API request failed method=%s path=%s durationMs=%s error=%s",
            request.method,
            path,
            elapsed_ms(started_at),
            exception,
        )
        raise


@lru_cache(maxsize=1)
def load_yolo_model():
    from ultralytics import YOLO

    logger.info("Loading YOLO model %s", yolo_model_name())
    return YOLO(yolo_model_name())


@lru_cache(maxsize=1)
def load_ocr_model():
    from paddleocr import PaddleOCR

    try:
        logger.info("Loading PaddleOCR lang=%s with v3-style arguments", ocr_language())
        return PaddleOCR(lang=ocr_language(), use_textline_orientation=True)
    except TypeError:
        logger.info("Falling back to PaddleOCR v2-style constructor for lang=%s", ocr_language())
        return PaddleOCR(use_angle_cls=True, lang=ocr_language())


@lru_cache(maxsize=1)
def load_clip_model():
    import open_clip
    import torch

    logger.info("Loading OpenCLIP model=%s pretrained=%s", clip_model_name(), clip_pretrained_name())
    model, _, preprocess = open_clip.create_model_and_transforms(
        clip_model_name(), pretrained=clip_pretrained_name()
    )
    tokenizer = open_clip.get_tokenizer(clip_model_name())
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = model.to(device).eval()
    return model, preprocess, tokenizer, device


def classify_image_kind(image: Image.Image) -> Literal["screenshot", "document", "photo"]:
    width, height = image.size
    gray = ImageOps.grayscale(image.resize((min(width, 512), min(height, 512))))
    stat = ImageStat.Stat(gray)
    stddev = stat.stddev[0] if stat.stddev else 0
    mean = stat.mean[0] if stat.mean else 0

    # Простая эвристика: документы обычно светлые и контрастные, скриншоты часто имеют мало шумовой текстуры.
    if mean > 180 and stddev > 45:
        return "document"
    if width >= 900 and height >= 500 and stddev < 75:
        return "screenshot"
    return "photo"


def build_ocr_candidates(image: Image.Image, image_kind: str) -> list[tuple[str, Image.Image]]:
    width, height = image.size
    max_side = max(width, height)

    if image_kind in {"screenshot", "document"}:
        scale = 2 if max_side < 2200 else 1
    else:
        scale = 2 if max_side < 1400 else 1

    base = image.resize((width * scale, height * scale), Image.LANCZOS) if scale > 1 else image
    gray = ImageOps.grayscale(base)
    autocontrasted = ImageOps.autocontrast(gray)
    contrasted = ImageEnhance.Contrast(autocontrasted).enhance(2.0 if image_kind == "photo" else 1.45)
    sharpened = contrasted.filter(ImageFilter.SHARPEN)
    threshold_soft = contrasted.point(lambda pixel: 255 if pixel > 150 else 0)
    inverted = ImageOps.invert(autocontrasted)

    candidates: list[tuple[str, Image.Image]] = [
        ("base", base),
        ("gray_autocontrast", autocontrasted.convert("RGB")),
        ("contrast_sharpen", sharpened.convert("RGB")),
    ]

    if image_kind in {"screenshot", "document"}:
        candidates.append(("threshold_soft", threshold_soft.convert("RGB")))
        candidates.append(("inverted", inverted.convert("RGB")))
    else:
        candidates.append(("threshold_soft", threshold_soft.convert("RGB")))

    return candidates


def polygon_to_bbox(polygon: Any) -> list[float] | None:
    if polygon is None:
        return None
    try:
        arr = np.array(polygon, dtype=float)
        if arr.ndim == 1 and arr.size >= 4:
            return [float(arr[0]), float(arr[1]), float(arr[2]), float(arr[3])]
        if arr.ndim >= 2 and arr.shape[-1] >= 2:
            xs = arr[..., 0]
            ys = arr[..., 1]
            return [float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())]
    except Exception:
        return None
    return None


def parse_ocr_result(result: Any) -> tuple[str | None, list[OcrBlock]]:
    blocks: list[OcrBlock] = []

    for page in result or []:
        payload: Any
        if hasattr(page, "json"):
            json_value = getattr(page, "json")
            payload = json_value.get("res", json_value) if isinstance(json_value, dict) else None
        elif isinstance(page, dict):
            payload = page.get("res", page)
        else:
            payload = page

        # PaddleOCR v3-like dictionary result.
        if isinstance(payload, dict):
            texts = payload.get("rec_texts", []) or []
            scores = payload.get("rec_scores", []) or payload.get("rec_score", []) or []
            boxes = payload.get("rec_polys", []) or payload.get("rec_boxes", []) or payload.get("dt_polys", []) or []
            for index, text in enumerate(texts):
                if not isinstance(text, str) or not text.strip():
                    continue
                score = scores[index] if index < len(scores) else None
                bbox = polygon_to_bbox(boxes[index]) if index < len(boxes) else None
                blocks.append(OcrBlock(text=text.strip(), confidence=float(score) if score is not None else None, bbox=bbox))
            continue

        # PaddleOCR v2-like list: [bbox, (text, confidence)].
        for item in payload or []:
            try:
                if len(item) < 2:
                    continue
                bbox = polygon_to_bbox(item[0])
                text = item[1][0]
                confidence = item[1][1] if len(item[1]) > 1 else None
                if text and str(text).strip():
                    blocks.append(OcrBlock(text=str(text).strip(), confidence=float(confidence) if confidence is not None else None, bbox=bbox))
            except Exception:
                continue

    text = cleanup_text(" ".join(block.text for block in blocks))
    return text, blocks


def score_ocr_blocks(blocks: list[OcrBlock]) -> float:
    if not blocks:
        return 0.0
    char_count = sum(len(block.text) for block in blocks)
    confidence_values = [block.confidence for block in blocks if block.confidence is not None]
    avg_conf = sum(confidence_values) / len(confidence_values) if confidence_values else 0.50
    return char_count * avg_conf + min(len(blocks), 20) * 4


def run_ocr(ocr: Any, candidate: Image.Image) -> Any:
    image_array = np.array(candidate)
    if hasattr(ocr, "predict"):
        try:
            return ocr.predict(
                image_array,
                use_textline_orientation=True,
                text_det_limit_side_len=max(candidate.size),
                text_rec_score_thresh=float(os.getenv("OCR_REC_SCORE_THRESHOLD", "0.35")),
            )
        except TypeError:
            pass
    return ocr.ocr(image_array, cls=True)


def detect_text(image: Image.Image, fixture: dict[str, Any] | None, debug: AnalysisDebugPayload) -> tuple[str | None, list[OcrBlock]]:
    if provider_name() == "mock":
        logger.info("OCR skipped because ANALYSIS_PROVIDER=mock")
        debug.ocrCandidates.append(OcrCandidateDebug(name="mock", width=image.width, height=image.height, lineCount=1, charCount=9, averageConfidence=1.0, score=1.0, preview="mock text"))
        return "mock text", []

    if fixture is not None and fixture.get("recognizedText"):
        recognized_text = cleanup_text(fixture["recognizedText"])
        logger.info("OCR fixture hit, returning recognizedText='%s'", preview_text(recognized_text))
        debug.ocrCandidates.append(OcrCandidateDebug(name="fixture", width=image.width, height=image.height, lineCount=1, charCount=len(recognized_text or ""), averageConfidence=1.0, score=float(len(recognized_text or "")), preview=preview_text(recognized_text)))
        return recognized_text, []

    start = now_ms()
    best: OcrCandidateResult | None = None
    image_kind = debug.imageKind

    try:
        ocr = load_ocr_model()
        for candidate_name, candidate in build_ocr_candidates(image, image_kind):
            candidate_start = now_ms()
            try:
                result = run_ocr(ocr, candidate)
                text, blocks = parse_ocr_result(result)
                score = score_ocr_blocks(blocks)
                confidences = [block.confidence for block in blocks if block.confidence is not None]
                average_confidence = sum(confidences) / len(confidences) if confidences else None
                candidate_debug = OcrCandidateDebug(
                    name=candidate_name,
                    width=candidate.width,
                    height=candidate.height,
                    lineCount=len(blocks),
                    charCount=len(text or ""),
                    averageConfidence=round(average_confidence, 4) if average_confidence is not None else None,
                    score=round(score, 4),
                    preview=preview_text(text),
                )
                debug.ocrCandidates.append(candidate_debug)
                logger.info(
                    "OCR candidate=%s kind=%s size=%sx%s lines=%s chars=%s avgConf=%s score=%s preview='%s' elapsedMs=%s",
                    candidate_name,
                    image_kind,
                    candidate.width,
                    candidate.height,
                    len(blocks),
                    len(text or ""),
                    candidate_debug.averageConfidence,
                    candidate_debug.score,
                    preview_text(text),
                    elapsed_ms(candidate_start),
                )
                current = OcrCandidateResult(name=candidate_name, text=text, blocks=blocks, debug=candidate_debug)
                if best is None or current.debug.score > best.debug.score:
                    best = current
            except Exception as exception:
                debug.ocrCandidates.append(OcrCandidateDebug(name=candidate_name, width=candidate.width, height=candidate.height, lineCount=0, charCount=0, score=0.0, error=str(exception)))
                logger.exception("OCR candidate=%s failed: %s", candidate_name, exception)

        debug.timingsMs["ocr"] = elapsed_ms(start)
        if best is None:
            logger.info("OCR final text is empty")
            return None, []

        min_block_conf = float(os.getenv("OCR_BLOCK_MIN_CONFIDENCE", "0.30"))
        filtered_blocks = [
            block for block in best.blocks
            if block.confidence is None or block.confidence >= min_block_conf
        ]
        final_text = cleanup_text(" ".join(block.text for block in filtered_blocks))
        debug.ocrBlocks = filtered_blocks
        logger.info("OCR final candidate=%s text length=%s blocks=%s preview='%s'", best.name, len(final_text or ""), len(filtered_blocks), preview_text(final_text))
        return final_text, filtered_blocks
    except Exception as exception:
        fallback_text = cleanup_text(fixture["recognizedText"]) if fixture is not None else None
        debug.errors.append(f"ocr: {exception}")
        logger.exception("OCR unavailable, using fallback recognized text preview='%s': %s", preview_text(fallback_text), exception)
        return fallback_text, []


def fixture_tags(fixture: dict[str, Any] | None) -> list[TagCandidate]:
    if fixture is None:
        return []
    return [TagCandidate(value=value, confidence=confidence, source="FIXTURE", reason="checksum fixture") for value, confidence in fixture.get("tags", [])]


def yolo_tag_candidates(image: Image.Image, top_tags: int, debug: AnalysisDebugPayload) -> tuple[list[TagCandidate], dict[str, float], dict[str, int]]:
    raw_scores: dict[str, float] = {}
    raw_counts: dict[str, int] = {}
    candidates: list[TagCandidate] = []
    start = now_ms()

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

        ordered = sorted(raw_scores.items(), key=lambda item: (item[1], raw_counts.get(item[0], 0)), reverse=True)
        debug.rawYoloLabels = [
            YoloDetectionDebug(label=label, confidence=round(score, 4), count=raw_counts.get(label, 0))
            for label, score in ordered[:25]
        ]
        candidates.extend(
            TagCandidate(value=label, confidence=round(score, 4), source="YOLO", reason=f"object detector count={raw_counts.get(label, 0)}")
            for label, score in ordered
        )
        logger.info("YOLO detections raw=%s counts=%s", {label: round(score, 4) for label, score in ordered[:10]}, raw_counts)
    except Exception as exception:
        debug.errors.append(f"yolo: {exception}")
        logger.exception("YOLO detection unavailable, using fallback tags: %s", exception)
    finally:
        debug.timingsMs["yolo"] = elapsed_ms(start)

    return candidates, raw_scores, raw_counts


def contextual_tag_candidates(image: Image.Image, raw_scores: dict[str, float], raw_counts: dict[str, int], recognized_text: str | None) -> list[TagCandidate]:
    tags: list[TagCandidate] = []
    labels = set(raw_scores.keys())

    for label, score in sorted(raw_scores.items(), key=lambda item: item[1], reverse=True):
        for hint, confidence in TAG_HINTS.get(label, []):
            tags.append(TagCandidate(value=hint, confidence=round(min(score, confidence), 4), source="CONTEXT", reason=f"hint from YOLO label '{label}'"))

    if labels & TRANSPORT_LABELS:
        tags.append(TagCandidate(value="transport", confidence=0.81, source="CONTEXT", reason="transport object labels present"))
    if labels & ANIMAL_LABELS:
        tags.append(TagCandidate(value="animal", confidence=0.80, source="CONTEXT", reason="animal object labels present"))
    if labels & FURNITURE_LABELS:
        tags.append(TagCandidate(value="interior", confidence=0.76, source="CONTEXT", reason="furniture object labels present"))
    if labels & ELECTRONICS_LABELS:
        tags.append(TagCandidate(value="electronics", confidence=0.78, source="CONTEXT", reason="electronics object labels present"))
    if labels & DOCUMENT_LABELS:
        tags.append(TagCandidate(value="printed-object", confidence=0.73, source="CONTEXT", reason="document-like object labels present"))

    person_count = raw_counts.get("person", 0)
    if person_count >= 2:
        tags.append(TagCandidate(value="group", confidence=0.80, source="CONTEXT", reason="two or more people detected"))
    elif person_count == 1 and image.height >= image.width:
        tags.append(TagCandidate(value="portrait", confidence=0.78, source="CONTEXT", reason="single person in portrait-oriented image"))

    if recognized_text:
        tags.append(TagCandidate(value="text", confidence=0.84, source="OCR", reason="OCR recognized non-empty text"))
        if len(recognized_text) >= 20:
            tags.append(TagCandidate(value="document", confidence=0.76, source="OCR", reason="recognized text length >= 20"))
        lowered = recognized_text.lower()
        if any("а" <= char <= "я" or char == "ё" for char in lowered):
            tags.append(TagCandidate(value="cyrillic-text", confidence=0.80, source="OCR", reason="recognized text contains Cyrillic characters"))

    return tags


def clip_prompts(tag: str) -> list[str]:
    return [
        f"a photo of {tag}",
        f"an image of {tag}",
        f"a screenshot of {tag}",
    ]


def clip_tag_candidates(image: Image.Image, debug: AnalysisDebugPayload) -> list[TagCandidate]:
    if not clip_enabled():
        return []

    start = now_ms()
    candidates: list[TagCandidate] = []
    try:
        import torch

        model, preprocess, tokenizer, device = load_clip_model()
        tags = clip_tags()

        prompts: list[tuple[str, str]] = []
        for tag in tags:
            for prompt in clip_prompts(tag):
                prompts.append((tag, prompt))

        image_input = preprocess(image).unsqueeze(0).to(device)
        text_input = tokenizer([prompt for _, prompt in prompts]).to(device)

        with torch.no_grad():
            image_features = model.encode_image(image_input)
            text_features = model.encode_text(text_input)
            image_features = image_features / image_features.norm(dim=-1, keepdim=True)
            text_features = text_features / text_features.norm(dim=-1, keepdim=True)
            scores = (100.0 * image_features @ text_features.T).softmax(dim=-1)[0]

        best_by_tag: dict[str, tuple[float, str]] = {}
        for index, (tag, prompt) in enumerate(prompts):
            score = float(scores[index].item())
            previous = best_by_tag.get(tag)
            if previous is None or score > previous[0]:
                best_by_tag[tag] = (score, prompt)

        ordered = sorted(best_by_tag.items(), key=lambda item: item[1][0], reverse=True)[:clip_top_k()]
        for tag, (score, prompt) in ordered:
            rounded = round(score, 4)
            debug.clipScores.append(ClipCandidateDebug(tag=tag, confidence=rounded, prompt=prompt))
            if score >= clip_min_confidence():
                candidates.append(TagCandidate(value=tag, confidence=rounded, source="CLIP", reason=f"semantic image/text similarity prompt='{prompt}'"))

        logger.info("CLIP scores=%s", [(item.tag, item.confidence) for item in debug.clipScores[:10]])
    except Exception as exception:
        debug.errors.append(f"clip: {exception}")
        logger.exception("CLIP tagging unavailable: %s", exception)
    finally:
        debug.timingsMs["clip"] = elapsed_ms(start)

    return candidates


def caption_to_tag_candidates(caption: str | None) -> list[TagCandidate]:
    if not caption:
        return []
    tags: list[TagCandidate] = [TagCandidate(value="captioned", confidence=0.70, source="VLM", reason="VLM caption generated")]
    lowered = caption.lower()
    for word, tag in [
        ("cat", "cat"), ("dog", "dog"), ("sofa", "sofa"), ("computer", "computer"),
        ("document", "document"), ("receipt", "receipt"), ("street", "street"), ("car", "car"),
        ("food", "food"), ("table", "table"), ("person", "person"), ("people", "group"),
    ]:
        if word in lowered:
            tags.append(TagCandidate(value=tag, confidence=0.62, source="VLM", reason=f"keyword '{word}' found in caption"))
    return tags


def deduplicate_tag_candidates(candidates: list[TagCandidate], top_tags: int) -> list[DetectedTag]:
    best_by_value: dict[str, TagCandidate] = {}
    for candidate in candidates:
        normalized = candidate.value.strip().lower()
        if not normalized:
            continue
        previous = best_by_value.get(normalized)
        previous_confidence = previous.confidence if previous and previous.confidence is not None else -1.0
        candidate_confidence = candidate.confidence if candidate.confidence is not None else 0.0
        if previous is None or candidate_confidence > previous_confidence:
            best_by_value[normalized] = candidate

    ordered = sorted(
        best_by_value.values(),
        key=lambda item: item.confidence if item.confidence is not None else 0.0,
        reverse=True,
    )
    return [
        DetectedTag(value=item.value, confidence=item.confidence, source=item.source, reason=item.reason)
        for item in ordered[:top_tags]
    ]


def ensure_minimum_tags(candidates: list[TagCandidate], top_tags: int, recognized_text: str | None) -> list[DetectedTag]:
    detected = deduplicate_tag_candidates(candidates, top_tags)
    if len(detected) >= min(3, top_tags):
        return detected

    existing = {tag.value.lower() for tag in detected}
    supplements: list[TagCandidate] = []
    if recognized_text and "text" not in existing:
        supplements.append(TagCandidate(value="text", confidence=0.78, source="FALLBACK", reason="recognized text exists"))
    if "photo" not in existing:
        supplements.append(TagCandidate(value="photo", confidence=0.70, source="FALLBACK", reason="minimum tag fallback"))
    if "image" not in existing:
        supplements.append(TagCandidate(value="image", confidence=0.68, source="FALLBACK", reason="minimum tag fallback"))
    return deduplicate_tag_candidates(candidates + supplements, top_tags)


def generate_caption_with_ollama(image: Image.Image, debug: AnalysisDebugPayload) -> str | None:
    if not vlm_enabled():
        return None

    start = now_ms()
    try:
        buffer = io.BytesIO()
        image.thumbnail((1280, 1280))
        image.save(buffer, format="JPEG", quality=88)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        payload = {
            "model": vlm_model_name(),
            "prompt": "Describe this image in one short factual English sentence. Do not invent details.",
            "images": [encoded],
            "stream": False,
        }
        request = urllib.request.Request(
            f"{ollama_url()}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=float(os.getenv("VLM_TIMEOUT_SECONDS", "45"))) as response:
            raw = response.read().decode("utf-8")
        result = json.loads(raw)
        caption = cleanup_text(result.get("response"))
        debug.vlmCaption = caption
        logger.info("VLM caption='%s'", preview_text(caption))
        return caption
    except (urllib.error.URLError, TimeoutError, Exception) as exception:
        debug.errors.append(f"vlm: {exception}")
        logger.exception("VLM caption unavailable: %s", exception)
        return None
    finally:
        debug.timingsMs["vlm"] = elapsed_ms(start)


def detect_tags(
    image: Image.Image,
    top_tags: int,
    fixture: dict[str, Any] | None,
    recognized_text: str | None,
    caption: str | None,
    debug: AnalysisDebugPayload,
) -> list[DetectedTag]:
    if provider_name() == "mock":
        tags = ensure_minimum_tags(
            [
                TagCandidate(value="image", confidence=0.99, source="MOCK", reason="mock provider"),
                TagCandidate(value="photo", confidence=0.95, source="MOCK", reason="mock provider"),
                TagCandidate(value="digital-media", confidence=0.82, source="MOCK", reason="mock provider"),
            ],
            top_tags,
            recognized_text,
        )
        debug.finalTagReasons = tags
        return tags

    candidates: list[TagCandidate] = []
    candidates.extend(fixture_tags(fixture))

    yolo_candidates, raw_scores, raw_counts = yolo_tag_candidates(image, top_tags, debug)
    candidates.extend(yolo_candidates)
    candidates.extend(contextual_tag_candidates(image, raw_scores, raw_counts, recognized_text))
    candidates.extend(clip_tag_candidates(image, debug))
    candidates.extend(caption_to_tag_candidates(caption))

    if not candidates:
        candidates.extend([
            TagCandidate(value="image", confidence=0.99, source="FALLBACK", reason="no model tags were produced"),
            TagCandidate(value="photo", confidence=0.95, source="FALLBACK", reason="no model tags were produced"),
        ])

    final_tags = ensure_minimum_tags(candidates, top_tags, recognized_text)
    debug.finalTagReasons = final_tags
    logger.info("Final tags: %s", serialize_tags(final_tags))
    return final_tags


def save_debug_payload(debug: AnalysisDebugPayload) -> None:
    if not save_debug_enabled():
        return
    try:
        directory = debug_dir()
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{debug.checksum}.json"
        target.write_text(debug.model_dump_json(indent=2), encoding="utf-8")
        logger.info("Analysis debug payload saved: %s", target)
    except Exception as exception:
        logger.exception("Failed to save analysis debug payload: %s", exception)


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "provider": provider_name(),
        "yoloModel": yolo_model_name(),
        "ocrLanguage": ocr_language(),
        "clipEnabled": clip_enabled(),
        "clipModel": clip_model_name() if clip_enabled() else None,
        "vlmEnabled": vlm_enabled(),
        "vlmModel": vlm_model_name() if vlm_enabled() else None,
        "debugSaveEnabled": save_debug_enabled(),
        "debugDir": str(debug_dir()),
    }


@app.post("/analyze", response_model=AnalyzeResponse, response_model_exclude_none=True)
async def analyze(
    file: UploadFile = File(...),
    topTags: int = Form(8),
    includeDebug: bool = Form(False),
    enhance: bool = Form(False),
) -> AnalyzeResponse:
    total_start = now_ms()
    content = await file.read()
    checksum = checksum_sha256(content)
    image = open_image(content)
    fixture = find_fixture_analysis(content)
    image_kind = classify_image_kind(image)
    debug = AnalysisDebugPayload(
        checksum=checksum,
        filename=file.filename,
        imageWidth=image.width,
        imageHeight=image.height,
        provider=provider_name(),
        imageKind=image_kind,
    )
    job_id = short_checksum(checksum)

    job_logger.info(
        "Analysis job started jobId=%s filename='%s' contentType='%s' bytes=%s size=%sx%s topTags=%s fixtureHit=%s provider=%s kind=%s enhance=%s",
        job_id,
        file.filename,
        file.content_type,
        len(content),
        image.width,
        image.height,
        topTags,
        fixture is not None,
        provider_name(),
        image_kind,
        enhance,
    )

    try:
        recognized_text, ocr_blocks = detect_text(image, fixture, debug)
        caption = generate_caption_with_ollama(image.copy(), debug) if enhance else None
        tags = detect_tags(image, max(1, min(topTags, 20)), fixture, recognized_text, caption, debug)
        debug.timingsMs["total"] = elapsed_ms(total_start)
        save_debug_payload(debug)

        job_logger.info(
            "Analysis job completed jobId=%s recognizedText='%s' caption='%s' tags=%s totalMs=%s",
            job_id,
            preview_text(recognized_text),
            preview_text(caption),
            serialize_tags(tags),
            debug.timingsMs.get("total"),
        )

        return AnalyzeResponse(
            tags=tags,
            recognizedText=recognized_text,
            caption=caption,
            ocrBlocks=ocr_blocks if includeDebug or include_debug_by_default() else None,
            debug=debug if includeDebug or include_debug_by_default() else None,
        )
    except Exception as exception:
        debug.timingsMs["total"] = elapsed_ms(total_start)
        job_logger.exception(
            "Analysis job failed jobId=%s filename='%s' totalMs=%s error=%s",
            job_id,
            file.filename,
            debug.timingsMs.get("total"),
            exception,
        )
        raise
