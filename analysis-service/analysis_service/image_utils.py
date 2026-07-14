from __future__ import annotations

import hashlib
import io
from typing import Any, Literal

import numpy as np
from PIL import Image, ImageFilter, ImageOps, ImageStat

ImageKind = Literal[
    "natural_photo",
    "screenshot",
    "meme",
    "document",
    "receipt",
    "code_screenshot",
    "chat_screenshot",
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


def classify_image_kind(image: Image.Image) -> ImageKind:
    width, height = image.size
    mean, stddev, edge_mean, bright_ratio, dark_ratio = _gray_features(image)
    aspect = width / max(height, 1)
    portrait_ratio = height / max(width, 1)

    receipt_like = portrait_ratio > 1.35 and bright_ratio > 0.58 and edge_mean > 10
    document_like = bright_ratio > 0.42 and stddev > 22 and edge_mean > 8
    screenshot_like = width >= 720 and height >= 420 and stddev < 88
    code_like = screenshot_like and (dark_ratio > 0.38 or bright_ratio > 0.62) and edge_mean > 14
    chat_like = screenshot_like and portrait_ratio > 1.35 and stddev < 74 and edge_mean > 9
    meme_like = screenshot_like and edge_mean > 13 and stddev > 34 and 0.8 <= aspect <= 1.7

    if receipt_like:
        return "receipt"
    if document_like and portrait_ratio > 1.05:
        return "document"
    if chat_like:
        return "chat_screenshot"
    if code_like:
        return "code_screenshot"
    if meme_like and mean > 90:
        return "meme"
    if screenshot_like:
        return "screenshot"
    if edge_mean > 4 or stddev > 18:
        return "natural_photo"
    return "unknown"


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
