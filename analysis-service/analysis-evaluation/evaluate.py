from __future__ import annotations

import argparse
import io
import json
import math
import mimetypes
import os
import statistics
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, request


ROOT = Path(__file__).resolve().parent
DEFAULT_IMAGES_DIR = ROOT / "images"
DEFAULT_EXPECTED_DIR = ROOT / "expected"
DEFAULT_RESULTS_DIR = ROOT / "results"
DEFAULT_REPORTS_DIR = ROOT / "reports"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate Smart Gallery analysis-service baseline.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8090", help="Analysis service base URL.")
    parser.add_argument("--top-tags", type=int, default=5, help="Number of tags requested from the service.")
    parser.add_argument("--mode", default=None, help="Optional analysis mode override.")
    parser.add_argument("--ocr-policy", default=None, help="Optional OCR policy override.")
    parser.add_argument("--report-name", default=None, help="Optional explicit report basename.")
    parser.add_argument("--comparison-json", default=None, help="Optional previous aggregate report for comparison.")
    parser.add_argument("--images-dir", default=str(DEFAULT_IMAGES_DIR), help="Directory with images to evaluate.")
    parser.add_argument("--expected-dir", default=str(DEFAULT_EXPECTED_DIR), help="Directory with expected JSON files.")
    parser.add_argument("--results-dir", default=str(DEFAULT_RESULTS_DIR), help="Directory for per-image raw responses.")
    parser.add_argument("--reports-dir", default=str(DEFAULT_REPORTS_DIR), help="Directory for aggregate reports.")
    parser.add_argument("--allow-missing-expected", action="store_true", help="Evaluate images without expected JSON as unlabeled baseline cases.")
    parser.add_argument("--max-retries", type=int, default=20, help="Maximum retries for transient queue saturation.")
    parser.add_argument("--retry-after-default", type=float, default=15.0, help="Fallback retry delay in seconds.")
    return parser.parse_args()


def read_expected(image_path: Path, expected_dir: Path, allow_missing: bool) -> dict[str, Any]:
    expected_path = expected_dir / f"{image_path.stem}.json"
    if expected_path.exists():
        payload = json.loads(expected_path.read_text(encoding="utf-8"))
        payload["hasExpected"] = True
        return payload
    if not allow_missing:
        raise FileNotFoundError(f"Missing expected JSON for {image_path.name}: {expected_path}")
    return {
        "hasExpected": False,
        "imageKind": "unlabeled",
        "expectedText": "",
        "requiredTags": [],
        "allowedTags": [],
        "forbiddenTags": [],
        "notes": "No expected JSON; included for raw baseline tracking.",
    }


def get_json(base_url: str, path: str, timeout_seconds: float = 30.0) -> dict[str, Any]:
    target = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    try:
        with request.urlopen(target, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exception:
        return {"error": str(exception)}


def encode_multipart(fields: dict[str, str], file_path: Path) -> tuple[bytes, str]:
    boundary = f"codex-{uuid.uuid4().hex}"
    line_break = b"\r\n"
    content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    file_bytes = file_path.read_bytes()
    body = bytearray()

    for name, value in fields.items():
        body.extend(f"--{boundary}".encode("utf-8"))
        body.extend(line_break)
        body.extend(f'Content-Disposition: form-data; name="{name}"'.encode("utf-8"))
        body.extend(line_break)
        body.extend(line_break)
        body.extend(str(value).encode("utf-8"))
        body.extend(line_break)

    body.extend(f"--{boundary}".encode("utf-8"))
    body.extend(line_break)
    body.extend(f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"'.encode("utf-8"))
    body.extend(line_break)
    body.extend(f"Content-Type: {content_type}".encode("utf-8"))
    body.extend(line_break)
    body.extend(line_break)
    body.extend(file_bytes)
    body.extend(line_break)
    body.extend(f"--{boundary}--".encode("utf-8"))
    body.extend(line_break)
    return bytes(body), boundary


def retry_after_seconds(http_error: error.HTTPError, payload: dict[str, Any] | None, default_seconds: float) -> float:
    header_value = http_error.headers.get("Retry-After")
    if header_value:
        try:
            return max(0.0, float(header_value))
        except ValueError:
            pass

    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, dict):
            candidate = detail.get("retryAfterSeconds")
            if candidate is not None:
                try:
                    return max(0.0, float(candidate))
                except (TypeError, ValueError):
                    pass

    return max(0.0, default_seconds)


def post_analyze(
    base_url: str,
    image_path: Path,
    top_tags: int,
    mode: str | None,
    ocr_policy: str | None,
    max_retries: int,
    retry_after_default: float,
) -> tuple[dict[str, Any], float]:
    fields = {"topTags": str(top_tags), "includeDebug": "true"}
    if mode:
        fields["mode"] = mode
    if ocr_policy:
        fields["ocrPolicy"] = ocr_policy

    body, boundary = encode_multipart(fields, image_path)
    target = f"{base_url.rstrip('/')}/analyze"
    started = time.perf_counter()
    http_request = request.Request(
        target,
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    for attempt in range(max_retries + 1):
        try:
            with request.urlopen(http_request, timeout=300) as response:
                payload = json.loads(response.read().decode("utf-8"))
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            return payload, elapsed_ms
        except error.HTTPError as http_error:
            body = http_error.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = {"detail": {"code": f"HTTP_{http_error.code}", "message": body}}

            detail = payload.get("detail") if isinstance(payload, dict) else None
            is_queue_full = http_error.code == 429 and isinstance(detail, dict) and detail.get("code") == "ANALYSIS_QUEUE_FULL"
            if not is_queue_full or attempt >= max_retries:
                raise error.HTTPError(
                    http_error.url,
                    http_error.code,
                    http_error.reason,
                    http_error.headers,
                    io.BytesIO(body.encode("utf-8")),
                ) from http_error

            time.sleep(retry_after_seconds(http_error, payload, retry_after_default))

    raise RuntimeError("unreachable")


def levenshtein(left: list[str], right: list[str]) -> int:
    if not left:
        return len(right)
    if not right:
        return len(left)
    previous = list(range(len(right) + 1))
    for index, left_item in enumerate(left, start=1):
        current = [index]
        for right_index, right_item in enumerate(right, start=1):
            cost = 0 if left_item == right_item else 1
            current.append(
                min(
                    previous[right_index] + 1,
                    current[right_index - 1] + 1,
                    previous[right_index - 1] + cost,
                )
            )
        previous = current
    return previous[-1]


def normalize_text(value: str | None) -> str:
    return " ".join((value or "").replace("\r", " ").replace("\n", " ").split()).strip().lower()


def cer(expected: str, predicted: str) -> float:
    expected_chars = list(expected)
    predicted_chars = list(predicted)
    return levenshtein(expected_chars, predicted_chars) / max(1, len(expected_chars))


def wer(expected: str, predicted: str) -> float:
    expected_words = expected.split()
    predicted_words = predicted.split()
    return levenshtein(expected_words, predicted_words) / max(1, len(expected_words))


def percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    index = (len(ordered) - 1) * ratio
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return float(ordered[int(index)])
    lower_value = ordered[lower]
    upper_value = ordered[upper]
    return float(lower_value + (upper_value - lower_value) * (index - lower))


def compute_quality_metrics(item_results: list[dict[str, Any]]) -> dict[str, Any]:
    labeled_items = [item for item in item_results if item.get("hasExpected")]
    ocr_items = [item for item in labeled_items if item["expectedText"]]
    cer_values = [item["cer"] for item in ocr_items]
    wer_values = [item["wer"] for item in ocr_items]
    garbage_rate = sum(1 for item in labeled_items if item["acceptedGarbage"]) / max(1, len(labeled_items))
    empty_result_rate = sum(1 for item in ocr_items if item["predictedText"] == "") / max(1, len(ocr_items))
    expected_containment_rate = sum(1 for item in ocr_items if item.get("expectedTextContained")) / max(1, len(ocr_items))
    false_text_items = [item for item in labeled_items if not item["expectedText"]]
    false_text_rate = sum(1 for item in false_text_items if item["predictedText"] != "") / max(1, len(false_text_items))
    forbidden_tag_rate = sum(1 for item in labeled_items if item["forbiddenTagHit"]) / max(1, len(labeled_items))
    empty_tag_rate = sum(1 for item in item_results if not item["predictedTags"]) / max(1, len(item_results))
    request_error_rate = sum(1 for item in item_results if item.get("errorCode")) / max(1, len(item_results))
    ocr_times = [item["ocrTimeMs"] for item in item_results]
    total_times = [item["totalTimeMs"] for item in item_results]
    avg_ocr_time = statistics.fmean(ocr_times) if ocr_times else 0.0
    median_ocr_time = statistics.median(ocr_times) if ocr_times else 0.0
    p95_ocr_time = percentile(ocr_times, 0.95)
    avg_total_time = statistics.fmean(total_times) if total_times else 0.0
    median_total_time = statistics.median(total_times) if total_times else 0.0
    p95_total_time = percentile(total_times, 0.95)

    return {
        "labeledImageCount": len(labeled_items),
        "unlabeledImageCount": len(item_results) - len(labeled_items),
        "cer": round(statistics.fmean(cer_values), 4) if cer_values else None,
        "wer": round(statistics.fmean(wer_values), 4) if wer_values else None,
        "acceptedGarbageRate": round(garbage_rate, 4),
        "emptyResultRate": round(empty_result_rate, 4),
        "expectedTextContainmentRate": round(expected_containment_rate, 4),
        "falseTextRate": round(false_text_rate, 4),
        "averageOcrTimeMs": round(avg_ocr_time, 2),
        "medianOcrTimeMs": round(median_ocr_time, 2),
        "p95OcrTimeMs": round(p95_ocr_time, 2),
        "precisionAt5": round(statistics.fmean(item["precisionAt5"] for item in item_results), 4) if item_results else 0.0,
        "recallAt5": round(statistics.fmean(item["recallAt5"] for item in item_results), 4) if item_results else 0.0,
        "forbiddenTagRate": round(forbidden_tag_rate, 4),
        "emptyTagRate": round(empty_tag_rate, 4),
        "requestErrorRate": round(request_error_rate, 4),
        "averageTotalTimeMs": round(avg_total_time, 2),
        "medianTotalTimeMs": round(median_total_time, 2),
        "p95TotalTimeMs": round(p95_total_time, 2),
        "cacheHitRate": None,
        "duplicateInferenceCount": None,
        "failedOrPartialJobs": sum(1 for item in item_results if item.get("errorCode") or item.get("pipelineStatus") not in {None, "SEARCHABLE", "COMPLETED"}),
        "peakRamMb": None,
        "cpuUtilization": None,
    }


def markdown_summary(report: dict[str, Any], comparison: dict[str, Any] | None) -> str:
    metrics = report["overall"]
    lines = [
        "# Analysis Evaluation Report",
        "",
        f"- Generated at: `{report['generatedAt']}`",
        f"- Base URL: `{report['baseUrl']}`",
        f"- Images evaluated: `{report['imageCount']}`",
        f"- Labeled images: `{metrics['labeledImageCount']}`",
        f"- Unlabeled images: `{metrics['unlabeledImageCount']}`",
        f"- Pipeline version: `{report.get('pipelineVersion')}`",
        "",
        "## Overall Metrics",
        "",
        f"- CER: `{metrics['cer']}`",
        f"- WER: `{metrics['wer']}`",
        f"- Accepted garbage rate: `{metrics['acceptedGarbageRate']}`",
        f"- Empty result rate: `{metrics['emptyResultRate']}`",
        f"- Expected text containment rate: `{metrics.get('expectedTextContainmentRate')}`",
        f"- False text rate: `{metrics['falseTextRate']}`",
        f"- Precision@5: `{metrics['precisionAt5']}`",
        f"- Recall@5: `{metrics['recallAt5']}`",
        f"- Forbidden tag rate: `{metrics['forbiddenTagRate']}`",
        f"- Empty tag rate: `{metrics['emptyTagRate']}`",
        f"- Request error rate: `{metrics['requestErrorRate']}`",
        f"- Median OCR time ms: `{metrics['medianOcrTimeMs']}`",
        f"- Average OCR time ms: `{metrics['averageOcrTimeMs']}`",
        f"- P95 OCR time ms: `{metrics['p95OcrTimeMs']}`",
        f"- Median total time ms: `{metrics['medianTotalTimeMs']}`",
        f"- Average total time ms: `{metrics['averageTotalTimeMs']}`",
        f"- P95 total time ms: `{metrics['p95TotalTimeMs']}`",
        f"- Cache hit rate: `{metrics['cacheHitRate']}`",
        f"- Duplicate inference count: `{metrics['duplicateInferenceCount']}`",
        f"- Failed/partial jobs: `{metrics['failedOrPartialJobs']}`",
        f"- Peak RAM MB: `{metrics['peakRamMb']}`",
        f"- CPU utilization: `{metrics['cpuUtilization']}`",
        "",
        "## By Category",
        "",
    ]

    for category, category_report in report["byCategory"].items():
        lines.append(f"### {category}")
        lines.append(f"- Images: `{category_report['count']}`")
        lines.append(f"- CER: `{category_report['metrics']['cer']}`")
        lines.append(f"- WER: `{category_report['metrics']['wer']}`")
        lines.append(f"- Precision@5: `{category_report['metrics']['precisionAt5']}`")
        lines.append(f"- Recall@5: `{category_report['metrics']['recallAt5']}`")
        lines.append(f"- Accepted garbage rate: `{category_report['metrics']['acceptedGarbageRate']}`")
        lines.append(f"- Expected text containment rate: `{category_report['metrics'].get('expectedTextContainmentRate')}`")
        lines.append("")

    if comparison:
        lines.extend(
            [
                "## Comparison",
                "",
                f"- Previous report: `{comparison.get('reportName', 'unknown')}`",
                f"- CER delta: `{delta(comparison.get('overall', {}).get('cer'), metrics['cer'])}`",
                f"- WER delta: `{delta(comparison.get('overall', {}).get('wer'), metrics['wer'])}`",
                f"- Precision@5 delta: `{delta(comparison.get('overall', {}).get('precisionAt5'), metrics['precisionAt5'])}`",
                f"- Recall@5 delta: `{delta(comparison.get('overall', {}).get('recallAt5'), metrics['recallAt5'])}`",
                f"- Garbage rate delta: `{delta(comparison.get('overall', {}).get('acceptedGarbageRate'), metrics['acceptedGarbageRate'])}`",
                f"- P95 total time delta: `{delta(comparison.get('overall', {}).get('p95TotalTimeMs'), metrics['p95TotalTimeMs'])}`",
                "",
            ]
        )

    return "\n".join(lines)


def delta(previous: float | None, current: float | None) -> str:
    if previous is None or current is None:
        return "n/a"
    diff = current - previous
    return f"{diff:+.4f}"


def main() -> None:
    args = parse_args()
    images_dir = Path(args.images_dir)
    expected_dir = Path(args.expected_dir)
    results_dir = Path(args.results_dir)
    reports_dir = Path(args.reports_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    images = sorted(path for path in images_dir.iterdir() if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp", ".ppm"})
    report_name = args.report_name or datetime.now(timezone.utc).strftime("baseline-%Y%m%dT%H%M%SZ")
    run_results_dir = results_dir / report_name
    run_results_dir.mkdir(parents=True, exist_ok=True)
    health_live = get_json(args.base_url, "/health/live")
    health_ready = get_json(args.base_url, "/health/ready")
    health_models = get_json(args.base_url, "/health/models", timeout_seconds=120.0)

    item_results: list[dict[str, Any]] = []
    by_category: dict[str, list[dict[str, Any]]] = {}

    for image_path in images:
        expected = read_expected(image_path, expected_dir, args.allow_missing_expected)
        error_code = None
        error_message = None
        try:
            payload, wall_time_ms = post_analyze(
                args.base_url,
                image_path,
                args.top_tags,
                args.mode,
                args.ocr_policy,
                args.max_retries,
                args.retry_after_default,
            )
        except error.HTTPError as http_error:
            wall_time_ms = 0.0
            body = http_error.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = {"detail": {"code": f"HTTP_{http_error.code}", "message": body}}
            detail = payload.get("detail") if isinstance(payload, dict) else None
            if isinstance(detail, dict):
                error_code = str(detail.get("code") or f"HTTP_{http_error.code}")
                error_message = str(detail.get("message") or body)
            else:
                error_code = f"HTTP_{http_error.code}"
                error_message = body
        except Exception as exception:
            payload = {"detail": {"code": "REQUEST_FAILED", "message": str(exception)}}
            wall_time_ms = 0.0
            error_code = "REQUEST_FAILED"
            error_message = str(exception)
        predicted_text = normalize_text(payload.get("recognizedText") or payload.get("ocr", {}).get("displayText"))
        expected_text = normalize_text(expected.get("expectedText"))
        tags = [str(tag.get("value", "")).strip().lower() for tag in payload.get("tags", []) if str(tag.get("value", "")).strip()]
        top_tags = tags[:5]
        has_expected = bool(expected.get("hasExpected"))
        positive_tags = {tag.lower() for tag in expected.get("requiredTags", []) + expected.get("allowedTags", [])}
        required_tags = {tag.lower() for tag in expected.get("requiredTags", [])}
        forbidden_tags = {tag.lower() for tag in expected.get("forbiddenTags", [])}

        matches = sum(1 for tag in top_tags if tag in positive_tags)
        recall_hits = sum(1 for tag in required_tags if tag in top_tags)
        cer_value = cer(expected_text, predicted_text) if expected_text else 0.0
        wer_value = wer(expected_text, predicted_text) if expected_text else 0.0
        expected_contained = bool(expected_text) and expected_text in predicted_text
        garbage = has_expected and bool(predicted_text) and (not expected_text or (cer_value > 0.6 and not expected_contained))
        ocr_time_ms = float(payload.get("debug", {}).get("timingsMs", {}).get("ocr", wall_time_ms))
        total_time_ms = float(payload.get("debug", {}).get("timingsMs", {}).get("total", wall_time_ms))
        raw_result_path = run_results_dir / f"{image_path.stem}.result.json"
        try:
            display_result_path = str(raw_result_path.resolve().relative_to(ROOT.resolve()))
        except ValueError:
            display_result_path = str(raw_result_path)

        item = {
            "image": image_path.name,
            "hasExpected": has_expected,
            "imageKind": expected.get("imageKind") or expected.get("expectedKind") or "unlabeled",
            "expectedText": expected_text,
            "predictedText": predicted_text,
            "predictedTags": top_tags,
            "finalTags": tags,
            "precisionAt5": matches / max(1, min(5, len(top_tags))) if has_expected and top_tags else 0.0,
            "recallAt5": recall_hits / max(1, len(required_tags)) if has_expected and required_tags else (1.0 if has_expected else 0.0),
            "forbiddenTagHit": any(tag in forbidden_tags for tag in top_tags),
            "acceptedGarbage": garbage,
            "expectedTextContained": expected_contained,
            "cer": round(cer_value, 4),
            "wer": round(wer_value, 4),
            "ocrTimeMs": round(ocr_time_ms, 2),
            "totalTimeMs": round(total_time_ms, 2),
            "httpWallTimeMs": round(wall_time_ms, 2),
            "pipelineStatus": payload.get("pipelineStatus") or payload.get("debug", {}).get("pipelineStatus"),
            "ocrQuality": payload.get("ocr", {}).get("quality") if isinstance(payload.get("ocr"), dict) else None,
            "ocrCandidateCount": len(payload.get("debug", {}).get("ocrCandidates", [])) if isinstance(payload.get("debug"), dict) else 0,
            "yoloDetectionCount": len(payload.get("debug", {}).get("rawYoloLabels", [])) if isinstance(payload.get("debug"), dict) else 0,
            "clipCandidateCount": len(payload.get("debug", {}).get("clipScores", [])) if isinstance(payload.get("debug"), dict) else 0,
            "rawResultPath": display_result_path,
            "errorCode": error_code,
            "errorMessage": error_message,
        }
        item_results.append(item)
        by_category.setdefault(item["imageKind"], []).append(item)
        raw_result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    report = {
        "reportName": report_name,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "baseUrl": args.base_url,
        "imagesDir": str(images_dir),
        "expectedDir": str(expected_dir),
        "resultsDir": str(run_results_dir),
        "pipelineVersion": health_live.get("version"),
        "service": {
            "healthLive": health_live,
            "healthReady": health_ready,
            "healthModels": health_models,
        },
        "modelVersions": [
            {"name": model.get("name"), "version": model.get("version"), "ready": model.get("ready")}
            for model in health_models.get("models", [])
            if isinstance(model, dict)
        ],
        "imageCount": len(item_results),
        "overall": compute_quality_metrics(item_results),
        "byCategory": {
            category: {
                "count": len(items),
                "metrics": compute_quality_metrics(items),
            }
            for category, items in sorted(by_category.items())
        },
        "items": item_results,
    }

    comparison = None
    if args.comparison_json:
        comparison = json.loads(Path(args.comparison_json).read_text(encoding="utf-8"))
        report["comparisonTo"] = args.comparison_json

    json_path = reports_dir / f"{report_name}.json"
    md_path = reports_dir / f"{report_name}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(markdown_summary(report, comparison), encoding="utf-8")
    print(json_path)
    print(md_path)


if __name__ == "__main__":
    main()
