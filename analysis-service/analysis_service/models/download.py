from __future__ import annotations

import json
import os

from ..ocr_runtime import load_easyocr_reader, load_paddle_ocr_model, selected_ocr_engines
from ..settings import load_settings
from ..vision import load_clip_model, load_yolo_model
from .registry import ModelRegistry


def main() -> None:
    os.environ["ANALYSIS_ALLOW_MODEL_DOWNLOAD"] = "true"
    settings = load_settings()
    registry = ModelRegistry(settings)
    loaded: list[str] = []
    errors: list[str] = []

    try:
        if settings.enable_yolo:
            load_yolo_model(settings)
            loaded.append("yolo")
    except Exception as exception:
        errors.append(f"yolo: {exception}")

    try:
        if settings.enable_clip:
            load_clip_model(settings)
            loaded.append("clip")
    except Exception as exception:
        errors.append(f"clip: {exception}")

    try:
        for engine in selected_ocr_engines(settings, settings.mode):
            if engine == "easyocr":
                load_easyocr_reader(settings)
            elif engine == "paddle":
                load_paddle_ocr_model(settings)
            loaded.append(engine)
    except Exception as exception:
        errors.append(f"ocr: {exception}")

    manifest = registry.write_manifest_lock()
    print(
        json.dumps(
            {
                "loaded": loaded,
                "errors": errors,
                "manifestPath": str(settings.model_manifest_path),
                "models": manifest.get("models", []),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
