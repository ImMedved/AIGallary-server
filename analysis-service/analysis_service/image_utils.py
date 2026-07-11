from __future__ import annotations

import hashlib
import io
from typing import Any, Literal

import numpy as np
from PIL import Image, ImageFilter, ImageOps, ImageStat

ImageKind = Literal["photo", "screenshot", "document", "meme"]


def checksum_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def short_checksum(value: str) -> str:
    return value[:12]


def open_image(content: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(content))
    image.load()
    return image.convert("RGB")


def classify_image_kind(image: Image.Image) -> ImageKind:
    width, height = image.size
    sample = image.copy()
    sample.thumbnail((512, 512), Image.Resampling.LANCZOS)
    gray = ImageOps.grayscale(sample)
    stat = ImageStat.Stat(gray)
    stddev = stat.stddev[0] if stat.stddev else 0.0
    mean = stat.mean[0] if stat.mean else 0.0

    edges = gray.filter(ImageFilter.FIND_EDGES)
    edge_stat = ImageStat.Stat(edges)
    edge_mean = edge_stat.mean[0] if edge_stat.mean else 0.0

    aspect = width / max(height, 1)
    light_document = mean > 178 and stddev > 36 and edge_mean > 12
    screen_like = width >= 720 and height >= 360 and stddev < 82
    meme_like = width >= 450 and height >= 300 and edge_mean > 14 and stddev > 45 and (aspect > 1.15 or aspect < 0.85)

    if light_document:
        return "document"
    if meme_like and mean > 95:
        return "meme"
    if screen_like:
        return "screenshot"
    return "photo"


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
