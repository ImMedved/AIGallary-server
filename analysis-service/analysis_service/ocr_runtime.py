from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from .errors import ModelUnavailableError
from .image_utils import estimate_text_likelihood, polygon_to_bbox
from .models.registry import ModelRegistry
from .runtime import elapsed_ms, now_ms, preview_text
from .schemas import AnalysisDebugPayload, OcrBlock, OcrCandidateDebug, OcrResult
from .settings import AnalysisMode, OcrPolicy, Settings

logger = logging.getLogger("smart_gallery_analysis.ocr")


@dataclass
class OcrCandidateResult:
    name: str
    result: OcrResult
    debug: OcrCandidateDebug


CYR = "а-яА-ЯёЁ"
LAT = "a-zA-Z"
VALID_TEXT_RE = re.compile(rf"[0-9{CYR}{LAT}\s.,:;!?()\[\]{{}}<>/\\'\"«»„“”‘’\-–—+*=#@%&|_№$€₽]", re.UNICODE)
TOKEN_RE = re.compile(rf"[0-9{CYR}{LAT}_.@:/\\-]+", re.UNICODE)
URL_RE = re.compile(r"(https?://|www\.|[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}|[a-z0-9._-]+\.[a-z0-9._-]+)", re.IGNORECASE)
CODE_TOKEN_RE = re.compile(r"[{}[\]();:=<>]|[_/\\]|[A-Za-z]+\.[A-Za-z0-9]+")

LAT_TO_CYR = str.maketrans({"A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К", "M": "М", "O": "О", "P": "Р", "T": "Т", "X": "Х", "Y": "У", "a": "а", "c": "с", "e": "е", "o": "о", "p": "р", "x": "х", "y": "у", "k": "к", "m": "м", "t": "т"})
CYR_TO_LAT = str.maketrans({"А": "A", "В": "B", "С": "C", "Е": "E", "Н": "H", "К": "K", "М": "M", "О": "O", "Р": "P", "Т": "T", "Х": "X", "У": "Y", "а": "a", "с": "c", "е": "e", "о": "o", "р": "p", "х": "x", "у": "y", "к": "k", "м": "m", "т": "t"})


def normalize_spaces(value: str | None, lowercase: bool = False) -> str | None:
    if value is None:
        return None
    normalized = unicodedata.normalize("NFKC", value)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if lowercase:
        normalized = normalized.lower()
    return normalized or None


def selected_ocr_engines(settings: Settings, mode: AnalysisMode) -> list[str]:
    engine = settings.ocr_engine
    if engine in {"easyocr", "paddle"}:
        return [engine]
    if engine == "both":
        return ["easyocr", "paddle"]
    if engine == "none":
        return []
    if mode == "best":
        return ["easyocr", "paddle"]
    return ["easyocr"]


def should_run_ocr(image_kind: str, policy: OcrPolicy, image: Image.Image) -> bool:
    if policy == "skip":
        return False
    if policy == "always":
        return True
    if image_kind in {"screenshot", "document", "meme", "receipt", "code_screenshot", "chat_screenshot"}:
        return True
    if image_kind == "natural_photo":
        return estimate_text_likelihood(image) >= 0.28
    return False


def _ensure_model_available(settings: Settings, name: str) -> None:
    statuses = {status.name: status for status in ModelRegistry(settings).collect_statuses(verify_checksum=False)}
    status = statuses.get(name)
    if status is None:
        return
    if status.ready or settings.allow_model_download:
        return
    raise ModelUnavailableError(f"Required OCR model '{name}' is not available in {settings.model_cache_dir}.")


@lru_cache(maxsize=4)
def _load_paddle_ocr_model_cached(lang: str):
    from paddleocr import PaddleOCR

    try:
        logger.info("Loading PaddleOCR lang=%s with v3-style arguments", lang)
        return PaddleOCR(lang=lang, use_textline_orientation=True)
    except TypeError:
        logger.info("Falling back to PaddleOCR v2-style constructor for lang=%s", lang)
        return PaddleOCR(use_angle_cls=True, lang=lang)


def load_paddle_ocr_model(settings: Settings):
    _ensure_model_available(settings, "paddleocr")
    return _load_paddle_ocr_model_cached(settings.paddle_ocr_lang)


@lru_cache(maxsize=4)
def _load_easyocr_reader_cached(languages_key: str, gpu: bool):
    import easyocr

    languages = [item for item in languages_key.split(",") if item]
    logger.info("Loading EasyOCR languages=%s gpu=%s", languages, gpu)
    return easyocr.Reader(languages, gpu=gpu, verbose=False)


def load_easyocr_reader(settings: Settings):
    _ensure_model_available(settings, "easyocr")
    return _load_easyocr_reader_cached(",".join(settings.ocr_languages), settings.easyocr_gpu)


def resize_for_ocr(image: Image.Image, image_kind: str, settings: Settings) -> Image.Image:
    width, height = image.size
    max_side = max(width, height)
    min_side = min(width, height)
    target = image
    if max_side > settings.ocr_max_side:
        scale = settings.ocr_max_side / max_side
        target = image.resize((max(1, int(width * scale)), max(1, int(height * scale))), Image.Resampling.LANCZOS)
    elif min_side < 900 and image_kind in {"screenshot", "document", "meme", "receipt", "code_screenshot", "chat_screenshot"}:
        scale = min(2.0, 1100 / max(min_side, 1))
        target = image.resize((max(1, int(width * scale)), max(1, int(height * scale))), Image.Resampling.LANCZOS)
    return target


def build_ocr_candidates(image: Image.Image, image_kind: str, settings: Settings) -> list[tuple[str, Image.Image]]:
    base = resize_for_ocr(image, image_kind, settings)
    gray = ImageOps.grayscale(base)
    autocontrasted = ImageOps.autocontrast(gray)
    mild_contrast = ImageEnhance.Contrast(autocontrasted).enhance(1.25 if image_kind in {"code_screenshot", "chat_screenshot"} else 1.45)
    sharpened = mild_contrast.filter(ImageFilter.SHARPEN)
    threshold = mild_contrast.point(lambda pixel: 255 if pixel > 155 else 0)

    if image_kind in {"code_screenshot", "chat_screenshot"}:
        return [("base", base), ("gray_autocontrast", autocontrasted.convert("RGB")), ("contrast_sharpen", sharpened.convert("RGB"))]
    if image_kind in {"screenshot", "document", "meme", "receipt"}:
        return [("base", base), ("gray_autocontrast", autocontrasted.convert("RGB")), ("threshold", threshold.convert("RGB"))]
    if image_kind == "natural_photo":
        return [("base", base)]
    return [("base", base), ("contrast_sharpen", sharpened.convert("RGB")), ("gray_autocontrast", autocontrasted.convert("RGB"))]


def parse_paddle_result(result: Any, engine: str, variant: str) -> list[OcrBlock]:
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
                raw = text.strip()
                blocks.append(OcrBlock(rawText=raw, displayText=raw, searchText=raw, text=raw, confidence=float(score) if score is not None else None, bbox=bbox, engine=engine, variant=variant))
            continue

        for item in payload or []:
            try:
                if len(item) < 2:
                    continue
                bbox = polygon_to_bbox(item[0])
                text = item[1][0]
                confidence = item[1][1] if len(item[1]) > 1 else None
                if text and str(text).strip():
                    raw = str(text).strip()
                    blocks.append(OcrBlock(rawText=raw, displayText=raw, searchText=raw, text=raw, confidence=float(confidence) if confidence is not None else None, bbox=bbox, engine=engine, variant=variant))
            except Exception:
                continue
    return blocks


def parse_easyocr_result(result: Any, engine: str, variant: str) -> list[OcrBlock]:
    blocks: list[OcrBlock] = []
    for item in result or []:
        try:
            if len(item) < 3:
                continue
            bbox = polygon_to_bbox(item[0])
            text = str(item[1]).strip()
            confidence = float(item[2])
            if text:
                blocks.append(OcrBlock(rawText=text, displayText=text, searchText=text, text=text, confidence=confidence, bbox=bbox, engine=engine, variant=variant))
        except Exception:
            continue
    return blocks


def run_ocr_engine(engine: str, candidate: Image.Image, settings: Settings, variant: str) -> list[OcrBlock]:
    image_array = np.array(candidate)
    if engine == "easyocr":
        reader = load_easyocr_reader(settings)
        result = reader.readtext(image_array, detail=1, paragraph=False, decoder="beamsearch")
        return parse_easyocr_result(result, engine, variant)

    ocr = load_paddle_ocr_model(settings)
    if hasattr(ocr, "predict"):
        try:
            result = ocr.predict(
                image_array,
                use_textline_orientation=True,
                text_det_limit_side_len=max(candidate.size),
                text_rec_score_thresh=max(0.01, settings.ocr_block_min_confidence - 0.10),
            )
            return parse_paddle_result(result, engine, variant)
        except TypeError:
            pass
    return parse_paddle_result(ocr.ocr(image_array, cls=True), engine, variant)


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
        if has_cyr and has_lat and not URL_RE.search(token) and not CODE_TOKEN_RE.search(token):
            mixed += 1
    return valid_ratio, mixed / max(1, len(tokens))


def suspicious_repetition_ratio(text: str) -> float:
    if len(text) < 12:
        return 0.0
    repeated = sum(1 for left, right in zip(text, text[1:]) if left == right and not left.isspace())
    return repeated / max(1, len(text) - 1)


def language_plausibility(text: str) -> float:
    if not text:
        return 0.0
    tokens = TOKEN_RE.findall(text)
    if not tokens:
        return 0.0
    plausible = 0
    for token in tokens:
        if URL_RE.search(token) or CODE_TOKEN_RE.search(token):
            plausible += 1
            continue
        letters = sum(1 for char in token if char.isalpha())
        digits = sum(1 for char in token if char.isdigit())
        if letters >= 2 or (letters >= 1 and digits >= 1):
            plausible += 1
    return plausible / max(1, len(tokens))


def geometry_score(blocks: list[OcrBlock]) -> float:
    bboxes = [block.bbox for block in blocks if block.bbox and len(block.bbox) == 4]
    if len(bboxes) < 2:
        return 1.0 if bboxes else 0.4
    heights = [max(1.0, bbox[3] - bbox[1]) for bbox in bboxes]
    widths = [max(1.0, bbox[2] - bbox[0]) for bbox in bboxes]
    height_ratio = min(heights) / max(heights)
    width_ratio = min(widths) / max(widths)
    return round((height_ratio * 0.65) + (width_ratio * 0.35), 4)


def line_consistency(blocks: list[OcrBlock]) -> float:
    lengths = [len(block.rawText.strip()) for block in blocks if block.rawText.strip()]
    if len(lengths) < 2:
        return 1.0 if lengths else 0.3
    avg = sum(lengths) / len(lengths)
    variance = sum((value - avg) ** 2 for value in lengths) / len(lengths)
    normalized = min(variance / max(10.0, avg * avg), 1.0)
    return round(1.0 - normalized, 4)


def quality_from_score(score: float) -> str:
    if score >= 150:
        return "strong"
    if score >= 120:
        return "moderate"
    if score >= 80:
        return "weak"
    return "rejected"


def score_ocr_blocks(blocks: list[OcrBlock]) -> tuple[float, str | None, float, float, float | None, float, float, float]:
    if not blocks:
        return 0.0, "no text blocks", 0.0, 0.0, None, 0.0, 0.0, 0.0
    text = normalize_spaces(" ".join(block.rawText for block in blocks)) or ""
    char_count = len(text)
    confidence_values = [block.confidence for block in blocks if block.confidence is not None]
    avg_conf = sum(confidence_values) / len(confidence_values) if confidence_values else 0.50
    valid_ratio, mixed_ratio = token_script_stats(text)
    repetition = suspicious_repetition_ratio(text)
    plausibility = language_plausibility(text)
    geometry = geometry_score(blocks)
    consistency = line_consistency(blocks)
    if char_count < 2:
        return 0.0, "too few characters", valid_ratio, mixed_ratio, avg_conf, repetition, plausibility, geometry
    if valid_ratio < 0.70:
        return 0.0, f"valid character ratio too low: {valid_ratio:.2f}", valid_ratio, mixed_ratio, avg_conf, repetition, plausibility, geometry
    if mixed_ratio > 0.36:
        return 0.0, f"mixed script token ratio too high: {mixed_ratio:.2f}", valid_ratio, mixed_ratio, avg_conf, repetition, plausibility, geometry
    if repetition > 0.18:
        return 0.0, f"repetition ratio too high: {repetition:.2f}", valid_ratio, mixed_ratio, avg_conf, repetition, plausibility, geometry
    if plausibility < 0.38:
        return 0.0, f"language plausibility too low: {plausibility:.2f}", valid_ratio, mixed_ratio, avg_conf, repetition, plausibility, geometry
    length_score = min(char_count, 240) * 0.42
    line_score = min(len(blocks), 18) * 2.2
    quality_score = (
        avg_conf * 100.0
        + valid_ratio * 28.0
        + plausibility * 26.0
        + geometry * 18.0
        + consistency * 16.0
        - mixed_ratio * 48.0
        - repetition * 54.0
    )
    return round(length_score + line_score + quality_score, 4), None, valid_ratio, mixed_ratio, avg_conf, repetition, plausibility, geometry


def dominant_script(token: str) -> str | None:
    cyr = len(re.findall(rf"[{CYR}]", token))
    lat = len(re.findall(rf"[{LAT}]", token))
    if cyr == lat == 0:
        return None
    return "cyr" if cyr > lat else "lat"


def correct_mixed_script_token(token: str) -> tuple[str, str | None]:
    if URL_RE.search(token) or CODE_TOKEN_RE.search(token):
        return token, None
    has_cyr = bool(re.search(rf"[{CYR}]", token))
    has_lat = bool(re.search(rf"[{LAT}]", token))
    if not (has_cyr and has_lat):
        return token, None
    script = dominant_script(token)
    if script == "cyr":
        corrected = token.translate(LAT_TO_CYR)
    elif script == "lat":
        corrected = token.translate(CYR_TO_LAT)
    else:
        corrected = token
    if corrected != token:
        return corrected, f"{token}->{corrected}"
    return token, None


def normalize_block(block: OcrBlock, image_kind: str) -> OcrBlock:
    raw = unicodedata.normalize("NFKC", block.rawText)
    tokens = raw.split()
    correction_trace: list[str] = []
    normalized_tokens: list[str] = []
    for token in tokens:
        corrected, trace = correct_mixed_script_token(token)
        normalized_tokens.append(corrected)
        if trace:
            correction_trace.append(trace)
    display = re.sub(r"\s+", " ", " ".join(normalized_tokens)).strip()
    preserve_case = image_kind in {"code_screenshot", "chat_screenshot"}
    search = normalize_spaces(display, lowercase=not preserve_case) or ""
    language = "ru" if re.search(rf"[{CYR}]", display) else "en" if re.search(rf"[{LAT}]", display) else None
    return OcrBlock(rawText=raw, displayText=display, searchText=search, text=display, confidence=block.confidence, bbox=block.bbox, language=language, quality=block.quality, engine=block.engine, variant=block.variant, correctionTrace=correction_trace)


def order_blocks(blocks: list[OcrBlock], image_kind: str) -> list[OcrBlock]:
    def sort_key(block: OcrBlock) -> tuple[float, float]:
        if not block.bbox or len(block.bbox) != 4:
            return (1e9, 1e9)
        return (block.bbox[1], block.bbox[0])

    return sorted(blocks, key=sort_key)


def filter_blocks(blocks: list[OcrBlock], settings: Settings) -> tuple[list[OcrBlock], int]:
    kept: list[OcrBlock] = []
    rejected = 0
    for block in blocks:
        valid_ratio, mixed_ratio = token_script_stats(block.rawText)
        repetition = suspicious_repetition_ratio(block.rawText)
        plausibility = language_plausibility(block.rawText)
        low_conf = block.confidence is not None and block.confidence < settings.ocr_block_min_confidence
        if low_conf and valid_ratio < 0.70:
            rejected += 1
            continue
        if mixed_ratio > 0.60 or repetition > 0.32 or plausibility < 0.25:
            rejected += 1
            continue
        kept.append(block)
    return kept, rejected


def build_text_result(blocks: list[OcrBlock], image_kind: str) -> OcrResult:
    normalized = [normalize_block(block, image_kind) for block in blocks if block.displayText.strip()]
    normalized = order_blocks(normalized, image_kind)
    display_parts = [block.displayText for block in normalized if block.displayText]
    search_parts = [block.searchText for block in normalized if block.searchText]
    raw_parts = [block.rawText for block in normalized if block.rawText]
    average_confidence = None
    confidence_values = [block.confidence for block in normalized if block.confidence is not None]
    if confidence_values:
        average_confidence = round(sum(confidence_values) / len(confidence_values), 4)
    language_hints = sorted({block.language for block in normalized if block.language})
    score, _, _, _, avg_conf, _, _, _ = score_ocr_blocks(normalized)
    quality = quality_from_score(score)
    if average_confidence is None and avg_conf is not None:
        average_confidence = round(avg_conf, 4)
    joiner = "\n\n" if image_kind == "chat_screenshot" else "\n"
    return OcrResult(rawText=joiner.join(raw_parts) if raw_parts else None, displayText=joiner.join(display_parts) if display_parts else None, searchText=joiner.join(search_parts) if search_parts else None, languageHints=language_hints, averageConfidence=average_confidence, quality=quality, blocks=normalized, warnings=[])


def rerun_photo_regions(image: Image.Image, blocks: list[OcrBlock], engine: str, settings: Settings) -> list[OcrBlock]:
    rerun_blocks: list[OcrBlock] = []
    for index, block in enumerate(blocks[:12]):
        if not block.bbox or len(block.bbox) != 4:
            rerun_blocks.append(block)
            continue
        left, top, right, bottom = block.bbox
        pad = 8
        crop = image.crop((max(0, int(left) - pad), max(0, int(top) - pad), min(image.width, int(right) + pad), min(image.height, int(bottom) + pad)))
        crop_blocks = run_ocr_engine(engine, crop, settings, f"region_{index + 1}")
        if not crop_blocks:
            rerun_blocks.append(block)
            continue
        better = crop_blocks[0]
        better.bbox = block.bbox
        rerun_blocks.append(better)
    return rerun_blocks


def detect_text(image: Image.Image, checksum_fixture_text: str | None, debug: AnalysisDebugPayload, settings: Settings, mode: AnalysisMode, policy: OcrPolicy) -> tuple[OcrResult | None, list[OcrBlock], int]:
    if settings.provider == "mock":
        result = OcrResult(rawText="mock text", displayText="mock text", searchText="mock text", averageConfidence=1.0, quality="strong")
        debug.ocrCandidates.append(OcrCandidateDebug(name="mock", width=image.width, height=image.height, lineCount=1, charCount=9, averageConfidence=1.0, score=1.0, accepted=True, preview="mock text"))
        return result, [], 0
    if checksum_fixture_text:
        text = normalize_spaces(checksum_fixture_text)
        result = OcrResult(rawText=text, displayText=text, searchText=text, averageConfidence=1.0, quality="strong")
        debug.ocrCandidates.append(OcrCandidateDebug(name="fixture", width=image.width, height=image.height, lineCount=1, charCount=len(text or ""), averageConfidence=1.0, validCharRatio=1.0, mixedScriptTokenRatio=0.0, repetitionRatio=0.0, languagePlausibility=1.0, geometryScore=1.0, lineConsistency=1.0, score=float(len(text or "")), accepted=True, preview=preview_text(text)))
        return result, [], 0
    if not should_run_ocr(debug.imageKind, policy, image):
        return None, [], 0
    started = now_ms()
    best: OcrCandidateResult | None = None
    rejected_blocks = 0
    try:
        for engine in selected_ocr_engines(settings, mode):
            for candidate_name, candidate in build_ocr_candidates(image, debug.imageKind, settings):
                full_name = f"{engine}:{candidate_name}"
                candidate_start = now_ms()
                try:
                    blocks = run_ocr_engine(engine, candidate, settings, candidate_name)
                    if debug.imageKind == "natural_photo":
                        blocks = rerun_photo_regions(candidate, blocks, engine, settings)
                    filtered, rejected = filter_blocks(blocks, settings)
                    rejected_blocks += rejected
                    result = build_text_result(filtered, debug.imageKind)
                    score, rejection, valid_ratio, mixed_ratio, avg_conf, repetition, plausibility, geometry = score_ocr_blocks(result.blocks)
                    accepted = rejection is None and bool(result.displayText)
                    candidate_debug = OcrCandidateDebug(name=full_name, width=candidate.width, height=candidate.height, lineCount=len(result.blocks), charCount=len(result.displayText or ""), averageConfidence=round(avg_conf, 4) if avg_conf is not None else None, validCharRatio=round(valid_ratio, 4), mixedScriptTokenRatio=round(mixed_ratio, 4), repetitionRatio=round(repetition, 4), languagePlausibility=round(plausibility, 4), geometryScore=round(geometry, 4), lineConsistency=round(line_consistency(result.blocks), 4), score=score, accepted=accepted, preview=preview_text(result.displayText), rejectionReason=rejection)
                    debug.ocrCandidates.append(candidate_debug)
                    logger.debug("OCR candidate=%s lines=%s chars=%s score=%s accepted=%s reason=%s elapsedMs=%s preview='%s'", full_name, len(result.blocks), len(result.displayText or ""), score, accepted, rejection, elapsed_ms(candidate_start), preview_text(result.displayText))
                    if accepted:
                        current = OcrCandidateResult(name=full_name, result=result, debug=candidate_debug)
                        if best is None or current.debug.score > best.debug.score:
                            best = current
                except Exception as exception:
                    debug.ocrCandidates.append(OcrCandidateDebug(name=full_name, width=candidate.width, height=candidate.height, lineCount=0, charCount=0, score=0.0, accepted=False, error=str(exception), rejectionReason="exception"))
                    debug.errors.append(f"ocr:{full_name}: {exception}")
                    logger.exception("OCR candidate=%s failed", full_name)
        debug.timingsMs["ocr"] = elapsed_ms(started)
        if best is None:
            return None, [], rejected_blocks
        debug.ocrBlocks = best.result.blocks
        logger.debug("OCR final candidate=%s text length=%s preview='%s'", best.name, len(best.result.displayText or ""), preview_text(best.result.displayText))
        return best.result, best.result.blocks, rejected_blocks
    except Exception as exception:
        debug.timingsMs["ocr"] = elapsed_ms(started)
        debug.errors.append(f"ocr: {exception}")
        logger.exception("OCR unavailable")
        return None, [], rejected_blocks
