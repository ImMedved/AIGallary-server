from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..settings import Settings

logger = logging.getLogger("smart_gallery_analysis.models")


@dataclass(frozen=True)
class ModelSpec:
    name: str
    version: str
    requiredFor: tuple[str, ...]
    artifactRoots: tuple[Path, ...]


@dataclass
class ArtifactStatus:
    path: str
    exists: bool
    fileCount: int
    sha256: str | None
    expectedSha256: str | None
    checksumMatched: bool | None


@dataclass
class ModelStatus:
    name: str
    version: str
    requiredFor: list[str]
    ready: bool
    checksumVerified: bool
    artifacts: list[ArtifactStatus]
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "requiredFor": self.requiredFor,
            "ready": self.ready,
            "checksumVerified": self.checksumVerified,
            "artifacts": [asdict(artifact) for artifact in self.artifacts],
            "notes": self.notes,
        }


class ModelRegistry:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def specs(self) -> list[ModelSpec]:
        specs: list[ModelSpec] = []
        if self.settings.enable_yolo:
            specs.append(
                ModelSpec(
                    name="yolo",
                    version=self.settings.yolo_model,
                    requiredFor=("fast",),
                    artifactRoots=(self.settings.yolo_config_dir,),
                )
            )
        if self.settings.enable_clip:
            specs.append(
                ModelSpec(
                    name="clip",
                    version=f"{self.settings.clip_model}:{self.settings.clip_pretrained}",
                    requiredFor=("optional",),
                    artifactRoots=(self.settings.hf_home, self.settings.hf_hub_cache, self.settings.torch_home, self.settings.xdg_cache_home),
                )
            )
        if self.settings.ocr_engine in {"auto", "easyocr", "both"}:
            specs.append(
                ModelSpec(
                    name="easyocr",
                    version=",".join(self.settings.ocr_languages),
                    requiredFor=("fast",),
                    artifactRoots=(self.settings.easyocr_module_path,),
                )
            )
        if self.settings.ocr_engine in {"auto", "paddle", "both"}:
            specs.append(
                ModelSpec(
                    name="paddleocr",
                    version=self.settings.paddle_ocr_lang,
                    requiredFor=("optional",),
                    artifactRoots=(self.settings.paddle_home,),
                )
            )
        return specs

    def manifest_path(self) -> Path:
        return self.settings.model_manifest_path

    def read_manifest(self) -> dict[str, Any]:
        path = self.manifest_path()
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("Failed to read model manifest lock file: %s", path)
            return {}

    def artifact_exists(self, root: Path) -> bool:
        return root.exists() and any(root.rglob("*"))

    def fingerprint_path(self, root: Path, include_hash: bool) -> tuple[int, str | None]:
        if not root.exists():
            return 0, None
        if root.is_file():
            if not include_hash:
                return 1, None
            digest = hashlib.sha256(root.read_bytes()).hexdigest()
            return 1, digest

        files = [path for path in root.rglob("*") if path.is_file()]
        if not files:
            return 0, None
        if not include_hash:
            return len(files), None
        digest = hashlib.sha256()
        for path in sorted(files):
            relative = path.relative_to(root).as_posix().encode("utf-8")
            digest.update(relative)
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
        return len(files), digest.hexdigest()

    def collect_statuses(self, verify_checksum: bool = True) -> list[ModelStatus]:
        manifest = self.read_manifest()
        manifest_entries = {item.get("name"): item for item in manifest.get("models", []) if isinstance(item, dict)}
        statuses: list[ModelStatus] = []
        for spec in self.specs():
            notes: list[str] = []
            artifacts: list[ArtifactStatus] = []
            manifest_entry = manifest_entries.get(spec.name, {})
            manifest_artifacts = {
                item.get("path"): item
                for item in manifest_entry.get("artifacts", [])
                if isinstance(item, dict) and item.get("path")
            }
            ready = True
            checksum_verified = True
            for root in spec.artifactRoots:
                file_count, sha256_value = self.fingerprint_path(root, include_hash=verify_checksum)
                exists = file_count > 0
                manifest_artifact = manifest_artifacts.get(str(root))
                expected_sha = manifest_artifact.get("sha256") if manifest_artifact else None
                checksum_matched = None
                if verify_checksum and expected_sha and sha256_value:
                    checksum_matched = sha256_value == expected_sha
                elif verify_checksum and expected_sha and not sha256_value:
                    checksum_matched = False
                if not exists:
                    ready = False
                    notes.append(f"missing artifacts under {root}")
                if checksum_matched is False:
                    ready = False
                    checksum_verified = False
                    notes.append(f"checksum mismatch for {root}")
                artifacts.append(
                    ArtifactStatus(
                        path=str(root),
                        exists=exists,
                        fileCount=file_count,
                        sha256=sha256_value,
                        expectedSha256=expected_sha,
                        checksumMatched=checksum_matched,
                    )
                )
            statuses.append(
                ModelStatus(
                    name=spec.name,
                    version=spec.version,
                    requiredFor=list(spec.requiredFor),
                    ready=ready,
                    checksumVerified=checksum_verified,
                    artifacts=artifacts,
                    notes=notes,
                )
            )
        return statuses

    def fast_models_ready(self) -> bool:
        statuses = self.collect_statuses(verify_checksum=False)
        return all(status.ready for status in statuses if "fast" in status.requiredFor)

    def manifest_payload(self) -> dict[str, Any]:
        return {"models": [status.to_dict() for status in self.collect_statuses(verify_checksum=True)]}

    def write_manifest_lock(self) -> dict[str, Any]:
        payload = self.manifest_payload()
        path = self.manifest_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload
