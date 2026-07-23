from __future__ import annotations

import hashlib
import io
from typing import Any, Literal

import numpy as np
from PIL import Image, ImageFilter, ImageOps, ImageStat

ImageKind = Literal[
    "natural_photo",
    "photo_with_text",
    "screenshot",
    "meme",
    "poster",
    "document",
    "form",
    "receipt",
    "invoice",
    "web_screenshot",
    "ai_assistant_screenshot",
    "code_screenshot",
    "chat_screenshot",
    "game_screenshot",
    "unknown",
]


def checksum_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def short_checksum(value: str) -> str:
    return value[:12]


def open_image(content: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(content))
    image.load()
    image = ImageOps.exif_transpose(image)
    return image.convert("RGB")


def _gray_features(image: Image.Image) -> tuple[float, float, float, float, float]:
    sample = image.copy()
    sample.thumbnail((512, 512), Image.Resampling.LANCZOS)
    gray = ImageOps.grayscale(sample)
    stat = ImageStat.Stat(gray)
    stddev = stat.stddev[0] if stat.stddev else 0.0
    mean = stat.mean[0] if stat.mean else 0.0
    bright_ratio = np.mean(np.array(gray) > 225)
    dark_ratio = np.mean(np.array(gray) < 38)
    edges = gray.filter(ImageFilter.FIND_EDGES)
    edge_stat = ImageStat.Stat(edges)
    edge_mean = edge_stat.mean[0] if edge_stat.mean else 0.0
    return mean, stddev, edge_mean, float(bright_ratio), float(dark_ratio)


def estimate_text_likelihood(image: Image.Image) -> float:
    mean, stddev, edge_mean, bright_ratio, dark_ratio = _gray_features(image)
    score = 0.0
    score += min(edge_mean / 28.0, 1.0) * 0.35
    score += min(stddev / 95.0, 1.0) * 0.25
    score += min((bright_ratio + dark_ratio) * 1.8, 1.0) * 0.20
    score += min(abs(mean - 128.0) / 128.0, 1.0) * 0.20
    return round(min(score, 1.0), 4)


def image_subtype_distribution(image: Image.Image) -> dict[str, float]:
    width, height = image.size
    mean, stddev, edge_mean, bright_ratio, dark_ratio = _gray_features(image)
    aspect = width / max(height, 1)
    portrait_ratio = height / max(width, 1)
    text_likelihood = estimate_text_likelihood(image)
    screenshot_like = width >= 720 and height >= 420 and stddev < 88
    document_like = bright_ratio > 0.42 and stddev > 22 and edge_mean > 8
    portrait_document = portrait_ratio > 1.05 and document_like
    receipt_like = portrait_ratio > 1.35 and bright_ratio > 0.58 and edge_mean > 10
    chat_like = screenshot_like and portrait_ratio > 1.35 and stddev < 74 and edge_mean > 9
    code_like = screenshot_like and (dark_ratio > 0.38 or bright_ratio > 0.62) and edge_mean > 14
    meme_like = screenshot_like and edge_mean > 13 and stddev > 34 and 0.8 <= aspect <= 1.7 and mean > 90
    natural_texture = min(stddev / 95.0, 1.0) * (1.0 - min(bright_ratio, 0.82))

    scores = {
        "natural_photo": 0.20 + natural_texture * 0.90 + (0.18 if not screenshot_like and not portrait_document else 0.0),
        "photo_with_text": 0.10 + natural_texture * 0.45 + text_likelihood * 0.55,
        "meme": 0.12 + (0.85 if meme_like else 0.0) + (0.18 if text_likelihood > 0.45 and 0.75 <= aspect <= 1.8 else 0.0),
        "poster": 0.10 + (0.32 if document_like and 0.55 <= aspect <= 1.45 else 0.0) + text_likelihood * 0.25,
        "document": 0.08 + (0.72 if portrait_document else 0.0) + (0.25 if bright_ratio > 0.55 and text_likelihood > 0.45 else 0.0),
        "form": 0.04 + (0.42 if portrait_document and edge_mean > 14 else 0.0),
        "receipt": 0.04 + (0.78 if receipt_like else 0.0),
        "invoice": 0.03 + (0.34 if receipt_like and edge_mean > 15 and bright_ratio > 0.68 else 0.0),
        "chat_screenshot": 0.04 + (0.86 if chat_like else 0.0),
        "web_screenshot": 0.04 + (0.38 if screenshot_like and aspect >= 1.15 and bright_ratio > 0.28 else 0.0),
        "ai_assistant_screenshot": 0.03 + (0.22 if chat_like and bright_ratio > 0.42 else 0.0),
        "code_screenshot": 0.04 + (0.80 if code_like else 0.0),
        "game_screenshot": 0.03 + (0.28 if screenshot_like and stddev > 52 and dark_ratio > 0.18 else 0.0),
        "unknown": 0.08,
    }

    total = sum(max(0.0, value) for value in scores.values())
    if total <= 0:
        return {"unknown": 1.0}
    distribution = {key: round(max(0.0, value) / total, 4) for key, value in scores.items()}
    return dict(sorted(distribution.items(), key=lambda item: item[1], reverse=True))


def classify_image_route(distribution: dict[str, float]) -> str:
    confidence = max(distribution.values(), default=0.0)
    if confidence >= 0.80:
        return "specialized"
    if confidence >= 0.50:
        return "hybrid"
    return "generic"


def classify_image_kind(image: Image.Image) -> ImageKind:
    distribution = image_subtype_distribution(image)
    best = max(distribution.items(), key=lambda item: item[1], default=("unknown", 1.0))[0]
    if best in {"web_screenshot", "ai_assistant_screenshot", "game_screenshot"}:
        return "screenshot"
    if best in {"photo_with_text", "poster"}:
        return "natural_photo" if best == "photo_with_text" else "meme"
    if best in {"form", "invoice"}:
        return "document" if best == "form" else "receipt"
    return best  # type: ignore[return-value]


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
