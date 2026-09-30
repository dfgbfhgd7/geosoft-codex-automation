#!/usr/bin/env python3
"""Reusable, dependency-free review of candidate aeromagnetic survey lines."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
from typing import Any, Iterable


COLUMN_ALIASES = {
    "line_id": ("line_id", "自动测线号", "line", "line_number", "测线号"),
    "source": ("source_flight", "来源架次", "source", "file", "filename"),
    "line_type": ("line_type", "自动类型", "type"),
    "length_m": ("length_m", "长度_m", "length", "长度"),
    "heading_deg": (
        "median_azimuth_deg", "方向_deg", "heading_deg", "azimuth_deg",
        "heading", "azimuth", "方向",
    ),
}

DEFAULT_TIE_KEYWORDS = ("tie", "control", "cross", "十字", "切割线", "控制线")
DEFAULT_CALIBRATION_KEYWORDS = (
    "calibration", "compensation", "attitude", "姿态", "校准", "补偿",
)
DECISIONS = {"测线", "控制线", "删除", "待审核"}
MODES = {"strict", "assisted", "unattended"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_csv(path: Path) -> tuple[list[dict[str, str]], list[str], str]:
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            with path.open("r", encoding=encoding, newline="") as stream:
                sample = stream.read(8192)
                stream.seek(0)
                try:
                    dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
                except csv.Error:
                    dialect = csv.excel
                reader = csv.DictReader(stream, dialect=dialect)
                if not reader.fieldnames:
                    raise ValueError("candidate table has no header")
                return list(reader), list(reader.fieldnames), encoding
        except (UnicodeDecodeError, csv.Error, ValueError) as exc:
            last_error = exc
    raise ValueError(f"cannot read candidate table: {last_error}")


def _resolve_columns(fieldnames: Iterable[str],
                     column_map: dict[str, str] | None = None) -> dict[str, str | None]:
    names = list(fieldnames)
    lowered = {name.strip().lower(): name for name in names}
    resolved: dict[str, str | None] = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        explicit = (column_map or {}).get(canonical)
        if explicit:
            if explicit not in names:
                raise ValueError(f"mapped column does not exist: {canonical}={explicit}")
            resolved[canonical] = explicit
            continue
        resolved[canonical] = next(
            (lowered[alias.lower()] for alias in aliases if alias.lower() in lowered),
            None,
        )
    missing = [name for name in ("line_id", "length_m", "heading_deg") if not resolved[name]]
    if missing:
        raise ValueError(
            "candidate table requires unambiguous columns for: " + ", ".join(missing)
        )
    return resolved


def _number(value: Any) -> float:
    try:
        result = float(str(value).strip())
    except (TypeError, ValueError):
        return math.nan
    return result if math.isfinite(result) else math.nan


def _fold_heading(value: float) -> float:
    return value % 180.0


def _angular_distance(left: float, right: float) -> float:
    return abs((left - right + 90.0) % 180.0 - 90.0)


def _dominant_heading(
    rows: list[dict[str, str]],
    columns: dict[str, str | None],
    cluster_tolerance_deg: float,
) -> float:
    samples: list[tuple[float, float]] = []
    for row in rows:
        heading = _number(row[columns["heading_deg"]])  # type: ignore[index]
        length = _number(row[columns["length_m"]])  # type: ignore[index]
        if not math.isfinite(heading) or not math.isfinite(length) or length <= 0:
            continue
        samples.append((_fold_heading(heading), length))
    if not samples:
        raise ValueError("no valid heading and length pairs")
    centre = max(
        (angle for angle, _ in samples),
        key=lambda candidate: sum(
            weight
            for angle, weight in samples
            if _angular_distance(angle, candidate) <= cluster_tolerance_deg
        ),
    )
    cluster = [
        (angle, weight)
        for angle, weight in samples
        if _angular_distance(angle, centre) <= cluster_tolerance_deg
    ]
    sine = sum(weight * math.sin(math.radians(2.0 * angle)) for angle, weight in cluster)
    cosine = sum(weight * math.cos(math.radians(2.0 * angle)) for angle, weight in cluster)
    return (math.degrees(math.atan2(sine, cosine)) / 2.0) % 180.0


def _contains(text: str, keywords: Iterable[str]) -> bool:
    lowered = text.casefold()
    for keyword in keywords:
        normalized = keyword.casefold().strip()
        if not normalized:
            continue
        if normalized.isascii() and normalized.replace("_", "").isalnum():
            if re.search(
                rf"(?<![a-z0-9_]){re.escape(normalized)}(?![a-z0-9_])",
                lowered,
            ):
                return True
        elif normalized in lowered:
            return True
    return False


def _normalized_type(value: str) -> str | None:
    key = value.strip().casefold()
    if key in {"traverse", "survey", "line", "测线"}:
        return "测线"
    if key in {"tie", "control", "cross", "控制线"}:
        return "控制线"
    if key in {"deleted", "delete", "删除"}:
        return "删除"
    return None


def review_rows(
    rows: list[dict[str, str]],
    fieldnames: list[str],
    *,
    mode: str = "assisted",
    heading_tolerance_deg: float = 12.0,
    confidence_threshold: float = 0.85,
    minimum_length_m: float | None = None,
    tie_keywords: Iterable[str] = DEFAULT_TIE_KEYWORDS,
    calibration_keywords: Iterable[str] = DEFAULT_CALIBRATION_KEYWORDS,
    column_map: dict[str, str] | None = None,
    intersection_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if mode not in MODES:
        raise ValueError(f"mode must be one of: {', '.join(sorted(MODES))}")
    if not 0 < heading_tolerance_deg < 45:
        raise ValueError("heading_tolerance_deg must be between 0 and 45")
    if not 0 <= confidence_threshold <= 1:
        raise ValueError("confidence_threshold must be between 0 and 1")
    if not rows:
        raise ValueError("candidate table has no rows")

    columns = _resolve_columns(fieldnames, column_map)
    dominant = _dominant_heading(rows, columns, heading_tolerance_deg)
    tie_heading = (dominant + 90.0) % 180.0
    positive_lengths = [
        value for row in rows
        if math.isfinite(value := _number(row[columns["length_m"]])) and value > 0  # type: ignore[index]
    ]
    median_length = statistics.median(positive_lengths)
    inferred_minimum = max(1.0, median_length * 0.35)
    minimum = inferred_minimum if minimum_length_m is None else float(minimum_length_m)
    if minimum <= 0 or not math.isfinite(minimum):
        raise ValueError("minimum_length_m must be positive")

    reviewed: list[dict[str, Any]] = []
    decision_counts = {decision: 0 for decision in sorted(DECISIONS)}
    suggestion_counts = {decision: 0 for decision in sorted(DECISIONS)}
    for original in rows:
        row: dict[str, Any] = dict(original)
        line_id = str(original.get(columns["line_id"] or "", "")).strip()
        source = str(original.get(columns["source"] or "", "")).strip()
        supplied_type = _normalized_type(
            str(original.get(columns["line_type"] or "", ""))
        )
        length = _number(original.get(columns["length_m"] or ""))
        heading = _number(original.get(columns["heading_deg"] or ""))
        reasons: list[str] = []
        exceptions: list[str] = []
        suggestion = "待审核"
        confidence = 0.0

        if not line_id:
            exceptions.append("缺少测线编号")
        if not math.isfinite(length) or length <= 0:
            exceptions.append("长度无效")
        if not math.isfinite(heading):
            exceptions.append("方向无效")

        semantic_text = f"{source} {line_id}"
        source_name = re.split(r"[\\/]", source)[-1]
        name_text = f"{source_name} {line_id}"
        tie_hint = _contains(semantic_text, tie_keywords)
        calibration_hint = (
            _contains(name_text, calibration_keywords)
            or (
                _contains(semantic_text, calibration_keywords)
                and not tie_hint
            )
        )
        if calibration_hint:
            suggestion, confidence = "删除", 0.99
            reasons.append("来源名称包含校准/姿态语义")
        elif not exceptions:
            folded = _fold_heading(heading)
            traverse_distance = _angular_distance(folded, dominant)
            tie_distance = _angular_distance(folded, tie_heading)
            if traverse_distance <= heading_tolerance_deg:
                geometry = "测线"
                geometry_confidence = max(
                    0.55, 0.96 - 0.30 * traverse_distance / heading_tolerance_deg
                )
            elif tie_distance <= heading_tolerance_deg:
                geometry = "控制线"
                geometry_confidence = max(
                    0.55, 0.94 - 0.30 * tie_distance / heading_tolerance_deg
                )
            else:
                geometry = None
                geometry_confidence = 0.25
                exceptions.append("方向既不接近主测线也不接近正交控制线")

            semantic_type = supplied_type or ("控制线" if tie_hint else None)
            suggestion = semantic_type or geometry or "待审核"
            confidence = geometry_confidence
            if geometry:
                reasons.append(
                    f"方向{folded:.2f}°；主测线{dominant:.2f}°；控制线{tie_heading:.2f}°"
                )
            if semantic_type:
                reasons.append(f"类型或来源语义提示为{semantic_type}")
            if semantic_type and geometry and semantic_type != geometry:
                confidence = min(confidence, 0.49)
                exceptions.append(f"语义类型{semantic_type}与几何类型{geometry}冲突")
            elif semantic_type and geometry == semantic_type:
                confidence = min(0.99, confidence + 0.03)

        if math.isfinite(length) and length < minimum:
            confidence = min(confidence, 0.45)
            exceptions.append(f"长度{length:.1f}m低于本批阈值{minimum:.1f}m")
        if intersection_ids is not None and suggestion == "控制线" and line_id not in intersection_ids:
            confidence = min(confidence, 0.40)
            exceptions.append("控制线未出现在交点表")

        if mode == "strict":
            decision = "待审核"
        elif mode == "assisted":
            decision = (
                suggestion
                if suggestion != "待审核"
                and confidence >= confidence_threshold
                and not exceptions
                else "待审核"
            )
        else:
            decision = suggestion

        status = "自动通过" if decision != "待审核" else "需要复核"
        row.update({
            "建议决定": suggestion,
            "审核决定": decision,
            "自动审核置信度": f"{confidence:.3f}",
            "自动审核状态": status,
            "自动审核理由": "；".join(reasons),
            "自动审核异常": "；".join(exceptions),
        })
        reviewed.append(row)
        decision_counts[decision] += 1
        suggestion_counts[suggestion] += 1

    summary = {
        "mode": mode,
        "candidate_rows": len(reviewed),
        "dominant_traverse_heading_deg": dominant,
        "inferred_tie_heading_deg": tie_heading,
        "median_candidate_length_m": median_length,
        "minimum_length_m": minimum,
        "heading_tolerance_deg": heading_tolerance_deg,
        "confidence_threshold": confidence_threshold,
        "decision_counts": {key: value for key, value in decision_counts.items() if value},
        "suggestion_counts": {key: value for key, value in suggestion_counts.items() if value},
        "requires_review": decision_counts["待审核"],
        "reusable_policy": True,
    }
    return reviewed, summary


def _intersection_ids(path: Path | None) -> set[str] | None:
    if path is None:
        return None
    rows, fieldnames, _ = _read_csv(path)
    aliases = ("traverse_id", "tie_id", "line_id", "测线号", "控制线号")
    selected = [name for name in fieldnames if name.casefold() in {a.casefold() for a in aliases}]
    if not selected:
        raise ValueError("intersection table has no recognized line-id columns")
    return {
        str(row.get(column, "")).strip()
        for row in rows for column in selected if str(row.get(column, "")).strip()
    }


def auto_review_survey_lines(
    candidate_table: str,
    output_dir: str | None = None,
    mode: str = "assisted",
    intersection_table: str | None = None,
    heading_tolerance_deg: float = 12.0,
    confidence_threshold: float = 0.85,
    minimum_length_m: float | None = None,
    tie_keywords: list[str] | None = None,
    calibration_keywords: list[str] | None = None,
    column_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    source = Path(candidate_table).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"candidate_table does not exist: {source}")
    intersection = (
        Path(intersection_table).expanduser().resolve() if intersection_table else None
    )
    if intersection is not None and not intersection.is_file():
        raise FileNotFoundError(f"intersection_table does not exist: {intersection}")

    rows, fieldnames, encoding = _read_csv(source)
    reviewed, summary = review_rows(
        rows,
        fieldnames,
        mode=mode,
        heading_tolerance_deg=heading_tolerance_deg,
        confidence_threshold=confidence_threshold,
        minimum_length_m=minimum_length_m,
        tie_keywords=tie_keywords or DEFAULT_TIE_KEYWORDS,
        calibration_keywords=calibration_keywords or DEFAULT_CALIBRATION_KEYWORDS,
        column_map=column_map,
        intersection_ids=_intersection_ids(intersection),
    )
    result: dict[str, Any] = {
        **summary,
        "candidate_table": str(source),
        "candidate_sha256": _sha256(source),
        "input_encoding": encoding,
        "intersection_table": str(intersection) if intersection else None,
        "preview": reviewed[:10],
    }
    if output_dir is None:
        result["written"] = False
        return result

    output = Path(output_dir).expanduser().resolve()
    if output.exists():
        raise FileExistsError("output_dir must not already exist")
    output.mkdir(parents=True, exist_ok=False)
    output_columns = list(fieldnames)
    for name in (
        "建议决定", "审核决定", "自动审核置信度",
        "自动审核状态", "自动审核理由", "自动审核异常",
    ):
        if name not in output_columns:
            output_columns.append(name)
    review_path = output / "自动测线审核.csv"
    with review_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=output_columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(reviewed)
    result.update({
        "written": True,
        "output_dir": str(output),
        "review_path": str(review_path),
        "review_sha256": _sha256(review_path),
    })
    summary_path = output / "自动审核摘要.json"
    result["summary_path"] = str(summary_path)
    summary_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def self_test() -> dict[str, Any]:
    rows = [
        {"id": "L1", "source": "flight-a", "length": "8100", "heading": "89"},
        {"id": "L2", "source": "flight-b", "length": "8050", "heading": "91"},
        {"id": "T1", "source": "control-a", "length": "10000", "heading": "179"},
        {"id": "C1", "source": "attitude calibration", "length": "7000", "heading": "90"},
    ]
    reviewed, summary = review_rows(
        rows,
        ["id", "source", "length", "heading"],
        mode="assisted",
        column_map={
            "line_id": "id",
            "source": "source",
            "length_m": "length",
            "heading_deg": "heading",
        },
        intersection_ids={"T1"},
    )
    decisions = {row["id"]: row["审核决定"] for row in reviewed}
    checks = {
        "infers_new_dataset_heading": abs(summary["dominant_traverse_heading_deg"] - 89.0) <= 2,
        "accepts_parallel_traverses": decisions["L1"] == decisions["L2"] == "测线",
        "accepts_connected_control": decisions["T1"] == "控制线",
        "deletes_calibration_semantics": decisions["C1"] == "删除",
    }
    return {"checks": checks, "ok": all(checks.values())}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate_table", nargs="?")
    parser.add_argument("--output-dir")
    parser.add_argument("--mode", choices=sorted(MODES), default="assisted")
    parser.add_argument("--intersection-table")
    parser.add_argument("--heading-tolerance-deg", type=float, default=12.0)
    parser.add_argument("--confidence-threshold", type=float, default=0.85)
    parser.add_argument("--minimum-length-m", type=float)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        result = self_test()
    else:
        if not args.candidate_table:
            parser.error("candidate_table is required unless --self-test is used")
        result = auto_review_survey_lines(
            args.candidate_table,
            output_dir=args.output_dir,
            mode=args.mode,
            intersection_table=args.intersection_table,
            heading_tolerance_deg=args.heading_tolerance_deg,
            confidence_threshold=args.confidence_threshold,
            minimum_length_m=args.minimum_length_m,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
