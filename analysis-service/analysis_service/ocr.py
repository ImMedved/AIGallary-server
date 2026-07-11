from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from .image_utils import polygon_to_bbox
from .runtime import elapsed_ms, now_ms, preview_text
from .schemas import AnalysisDebugPayload, OcrBlock, OcrCandidateDebug
from .settings import AnalysisMode, OcrPolicy, Settings

logger = logging.getLogger("smart_gallery_analysis.ocr")


@dataclass
class OcrCandidateResult:
    name: str
    text: str | None
    blocks: list[OcrBlock]
    debug: OcrCandidateDebug


CYR = "а-яА-ЯёЁ"
LAT = "a-zA-Z"
VALID_TEXT_RE = re.compile(rf"[0-9{CYR}{LAT}\s.,:;!?()\[\]{{}}<>/\\'\"«»„“”‘’\-–—+*=#@%&|_№$€₽]", re.UNICODE)
TOKEN_RE = re.compile(rf"[0-9{CYR}{LAT}_-]+", re.UNICODE)


def cleanup_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"\s+", " ", value).strip()
    return normalized or None


def selected_ocr_engines(settings: Settings, mode: AnalysisMode) -> list[str]:
    engine = settings.ocr_engine
    if engine in {"easyocr", "paddle"}:
        return [engine]
    if engine == "none":
        return []
    if mode == "best":
        return ["easyocr", "paddle"]
    return ["easyocr"]


def should_run_ocr(image_kind: str, policy: OcrPolicy) -> bool:
    if policy == "skip":
        return False
    if policy == "always":
        return True
    return image_kind in {"screenshot", "document", "meme"}


@lru_cache(maxsize=4)
def load_paddle_ocr_model(lang: str):
    from paddleocr import PaddleOCR

    try:
        logger.info("Loading PaddleOCR lang=%s with v3-style arguments", lang)
        return PaddleOCR(lang=lang, use_textline_orientation=True)
    except TypeError:
        logger.info("Falling back to PaddleOCR v2-style constructor for lang=%s", lang)
        return PaddleOCR(use_angle_cls=True, lang=lang)


@lru_cache(maxsize=4)
def load_easyocr_reader(languages_key: str, gpu: bool):
    import easyocr

    languages = [item for item in languages_key.split(",") if item]
    logger.info("Loading EasyOCR languages=%s gpu=%s", languages, gpu)
    return easyocr.Reader(languages, gpu=gpu, verbose=False)


def resize_for_ocr(image: Image.Image, image_kind: str, settings: Settings) -> Image.Image:
    width, height = image.size
    max_side = max(width, height)
    min_side = min(width, height)

    target = image
    if max_side > settings.ocr_max_side:
        scale = settings.ocr_max_side / max_side
        target = image.resize((max(1, int(width * scale)), max(1, int(height * scale))), Image.Resampling.LANCZOS)
    elif min_side < 900 and image_kind in {"screenshot", "document", "meme"}:
        scale = min(2.0, 1100 / max(min_side, 1))
        target = image.resize((max(1, int(width * scale)), max(1, int(height * scale))), Image.Resampling.LANCZOS)
    return target


def build_ocr_candidates(image: Image.Image, image_kind: str, settings: Settings, mode: AnalysisMode) -> list[tuple[str, Image.Image]]:
    base = resize_for_ocr(image, image_kind, settings)
    gray = ImageOps.grayscale(base)
    autocontrasted = ImageOps.autocontrast(gray)
    mild_contrast = ImageEnhance.Contrast(autocontrasted).enhance(1.35 if image_kind in {"screenshot", "document"} else 1.65)
    sharpened = mild_contrast.filter(ImageFilter.SHARPEN)

    candidates: list[tuple[str, Image.Image]] = [
        ("base", base),
        ("gray_autocontrast", autocontrasted.convert("RGB")),
        ("contrast_sharpen", sharpened.convert("RGB")),
    ]

    if mode in {"quality", "best"} or image_kind in {"screenshot", "document", "meme"}:
        threshold = mild_contrast.point(lambda pixel: 255 if pixel > 155 else 0)
        candidates.append(("threshold", threshold.convert("RGB")))

    if mode == "best":
        inverted = ImageOps.invert(autocontrasted)
        candidates.append(("inverted", inverted.convert("RGB")))

    return candidates


def parse_paddle_result(result: Any) -> tuple[str | None, list[OcrBlock]]:
    blocks: list[OcrBlock] = []
    for page in result or []:
        if hasattr(page, "json"):
            json_value = getattr(page, "json")
            payload = json_value.get("res", json_value) if isinstance(json_value, dict) else None
        elif isinstance(page, dict):
            payload = page.get("res", page)
        else:
            payload = page

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

    return cleanup_text(" ".join(block.text for block in blocks)), blocks


def parse_easyocr_result(result: Any) -> tuple[str | None, list[OcrBlock]]:
    blocks: list[OcrBlock] = []
    for item in result or []:
        try:
            if len(item) < 3:
                continue
            bbox = polygon_to_bbox(item[0])
            text = str(item[1]).strip()
            confidence = float(item[2])
            if text:
                blocks.append(OcrBlock(text=text, confidence=confidence, bbox=bbox))
        except Exception:
            continue
    return cleanup_text(" ".join(block.text for block in blocks)), blocks


def run_ocr_engine(engine: str, candidate: Image.Image, settings: Settings) -> tuple[str | None, list[OcrBlock]]:
    image_array = np.array(candidate)
    if engine == "easyocr":
        reader = load_easyocr_reader(",".join(settings.ocr_languages), settings.easyocr_gpu)
        result = reader.readtext(image_array, detail=1, paragraph=False, decoder="beamsearch")
        return parse_easyocr_result(result)

    ocr = load_paddle_ocr_model(settings.paddle_ocr_lang)
    if hasattr(ocr, "predict"):
        try:
            result = ocr.predict(
                image_array,
                use_textline_orientation=True,
                text_det_limit_side_len=max(candidate.size),
                text_rec_score_thresh=max(0.01, settings.ocr_block_min_confidence - 0.10),
            )
            return parse_paddle_result(result)
        except TypeError:
            pass
    return parse_paddle_result(ocr.ocr(image_array, cls=True))


def token_script_stats(text: str) -> tuple[float, float]:
    chars = [char for char in text if not char.isspace()]
    if not chars:
        return 0.0, 0.0
    valid = sum(1 for char in chars if VALID_TEXT_RE.fullmatch(char))
    valid_ratio = valid / max(1, len(chars))

    tokens = TOKEN_RE.findall(text)
    if not tokens:
        return valid_ratio, 0.0

    mixed = 0
    for token in tokens:
        has_cyr = bool(re.search(rf"[{CYR}]", token))
        has_lat = bool(re.search(rf"[{LAT}]", token))
        # OCR often confuses Latin/Cyrillic inside one word. URLs/code are allowed to mix less strictly.
        if has_cyr and has_lat and not re.search(r"[_\-0-9]", token):
            mixed += 1
    return valid_ratio, mixed / max(1, len(tokens))


def suspicious_repetition_ratio(text: str) -> float:
    if len(text) < 12:
        return 0.0
    repeated = sum(1 for left, right in zip(text, text[1:]) if left == right and not left.isspace())
    return repeated / max(1, len(text) - 1)


def score_ocr_blocks(blocks: list[OcrBlock]) -> tuple[float, str | None, float, float, float | None]:
    if not blocks:
        return 0.0, "no text blocks", 0.0, 0.0, None

    text = cleanup_text(" ".join(block.text for block in blocks)) or ""
    char_count = len(text)
    confidence_values = [block.confidence for block in blocks if block.confidence is not None]
    avg_conf = sum(confidence_values) / len(confidence_values) if confidence_values else 0.50
    valid_ratio, mixed_ratio = token_script_stats(text)
    repetition = suspicious_repetition_ratio(text)

    if char_count < 2:
        return 0.0, "too few characters", valid_ratio, mixed_ratio, avg_conf
    if valid_ratio < 0.72:
        return 0.0, f"valid character ratio too low: {valid_ratio:.2f}", valid_ratio, mixed_ratio, avg_conf
    if mixed_ratio > 0.38:
        return 0.0, f"mixed script token ratio too high: {mixed_ratio:.2f}", valid_ratio, mixed_ratio, avg_conf
    if repetition > 0.18:
        return 0.0, f"repetition ratio too high: {repetition:.2f}", valid_ratio, mixed_ratio, avg_conf

    # Do not let long garbage win purely by length.
    length_score = min(char_count, 320) * 0.65
    line_score = min(len(blocks), 25) * 2.5
    quality_score = avg_conf * 100.0 + valid_ratio * 35.0 - mixed_ratio * 45.0 - repetition * 50.0
    return round(length_score + line_score + quality_score, 4), None, valid_ratio, mixed_ratio, avg_conf


def filter_blocks(blocks: list[OcrBlock], settings: Settings) -> list[OcrBlock]:
    filtered = [block for block in blocks if block.confidence is None or block.confidence >= settings.ocr_block_min_confidence]
    kept: list[OcrBlock] = []
    for block in filtered:
        valid_ratio, mixed_ratio = token_script_stats(block.text)
        if len(block.text) >= 4 and valid_ratio < 0.65:
            continue
        if mixed_ratio > 0.60:
            continue
        kept.append(block)
    return kept


def detect_text(
    image: Image.Image,
    checksum_fixture_text: str | None,
    debug: AnalysisDebugPayload,
    settings: Settings,
    mode: AnalysisMode,
    policy: OcrPolicy,
) -> tuple[str | None, list[OcrBlock]]:
    if settings.provider == "mock":
        debug.ocrCandidates.append(OcrCandidateDebug(name="mock", width=image.width, height=image.height, lineCount=1, charCount=9, averageConfidence=1.0, score=1.0, accepted=True, preview="mock text"))
        return "mock text", []

    if checksum_fixture_text:
        text = cleanup_text(checksum_fixture_text)
        debug.ocrCandidates.append(OcrCandidateDebug(name="fixture", width=image.width, height=image.height, lineCount=1, charCount=len(text or ""), averageConfidence=1.0, validCharRatio=1.0, mixedScriptTokenRatio=0.0, score=float(len(text or "")), accepted=True, preview=preview_text(text)))
        return text, []

    if not should_run_ocr(debug.imageKind, policy):
        return None, []

    started = now_ms()
    best: OcrCandidateResult | None = None

    try:
        for engine in selected_ocr_engines(settings, mode):
            for candidate_name, candidate in build_ocr_candidates(image, debug.imageKind, settings, mode):
                full_name = f"{engine}:{candidate_name}"
                candidate_start = now_ms()
                try:
                    text, blocks = run_ocr_engine(engine, candidate, settings)
                    filtered = filter_blocks(blocks, settings)
                    final_text = cleanup_text(" ".join(block.text for block in filtered))
                    score, rejection, valid_ratio, mixed_ratio, avg_conf = score_ocr_blocks(filtered)
                    accepted = rejection is None and bool(final_text)
                    candidate_debug = OcrCandidateDebug(
                        name=full_name,
                        width=candidate.width,
                        height=candidate.height,
                        lineCount=len(filtered),
                        charCount=len(final_text or ""),
                        averageConfidence=round(avg_conf, 4) if avg_conf is not None else None,
                        validCharRatio=round(valid_ratio, 4),
                        mixedScriptTokenRatio=round(mixed_ratio, 4),
                        score=score,
                        accepted=accepted,
                        preview=preview_text(final_text),
                        rejectionReason=rejection,
                    )
                    debug.ocrCandidates.append(candidate_debug)
                    logger.debug(
                        "OCR candidate=%s lines=%s chars=%s score=%s accepted=%s reason=%s elapsedMs=%s preview='%s'",
                        full_name,
                        len(filtered),
                        len(final_text or ""),
                        score,
                        accepted,
                        rejection,
                        elapsed_ms(candidate_start),
                        preview_text(final_text),
                    )
                    current = OcrCandidateResult(name=full_name, text=final_text, blocks=filtered, debug=candidate_debug)
                    if accepted and (best is None or current.debug.score > best.debug.score):
                        best = current
                except Exception as exception:
                    debug.ocrCandidates.append(OcrCandidateDebug(name=full_name, width=candidate.width, height=candidate.height, lineCount=0, charCount=0, score=0.0, error=str(exception), rejectionReason="exception"))
                    debug.errors.append(f"ocr:{full_name}: {exception}")
                    logger.exception("OCR candidate=%s failed", full_name)

        debug.timingsMs["ocr"] = elapsed_ms(started)
        if best is None:
            return None, []
        debug.ocrBlocks = best.blocks
        logger.debug("OCR final candidate=%s text length=%s preview='%s'", best.name, len(best.text or ""), preview_text(best.text))
        return best.text, best.blocks
    except Exception as exception:
        debug.timingsMs["ocr"] = elapsed_ms(started)
        debug.errors.append(f"ocr: {exception}")
        logger.exception("OCR unavailable")
        return None, []
