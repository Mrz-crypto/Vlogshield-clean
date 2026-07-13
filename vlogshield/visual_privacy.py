from __future__ import annotations

from base64 import b64encode
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class VisualFinding:
    name: str
    severity: str
    points: int
    confidence: float
    box: dict[str, int]
    advice: str

    def as_risk(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": f"{round(self.confidence * 100)}% confidence",
            "severity": self.severity,
            "advice": self.advice,
            "source": "visual",
            "box": self.box,
        }


def analyze_visual_privacy(path: str) -> dict[str, Any]:
    if os.getenv("VISUAL_AUTO_REDACTION", "1") == "0":
        return {"risks": [], "score": 0, "redacted_image": None, "available": False}

    try:
        import cv2
        import numpy as np
    except ImportError:
        return {"risks": [], "score": 0, "redacted_image": None, "available": False}

    image_path = Path(path)
    image = cv2.imread(str(image_path))
    if image is None:
        return {"risks": [], "score": 0, "redacted_image": None, "available": True}

    findings: list[VisualFinding] = []
    findings.extend(_detect_faces(cv2, image))
    findings.extend(_detect_number_plates(cv2, image))
    if os.getenv("VISUAL_BODY_HEURISTIC", "0") == "1":
        findings.extend(_detect_skin_regions(cv2, np, image))
    findings = _merge_overlapping_findings(findings)

    if not findings:
        return {"risks": [], "score": 0, "redacted_image": None, "available": True}

    redacted = _blur_findings(cv2, image.copy(), findings)
    ok, encoded = cv2.imencode(".jpg", redacted, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
    redacted_image = None
    if ok:
        redacted_image = "data:image/jpeg;base64," + b64encode(encoded.tobytes()).decode("ascii")

    return {
        "risks": [finding.as_risk() for finding in findings],
        "score": min(sum(finding.points for finding in findings), 45),
        "redacted_image": redacted_image,
        "available": True,
    }


def _detect_faces(cv2, image) -> list[VisualFinding]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    cascade_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
    eye_cascade_path = Path(cv2.data.haarcascades) / "haarcascade_eye.xml"
    cascade = cv2.CascadeClassifier(str(cascade_path))
    eye_cascade = cv2.CascadeClassifier(str(eye_cascade_path))
    if cascade.empty() or eye_cascade.empty():
        return []

    boxes = cascade.detectMultiScale(gray, scaleFactor=1.05, minNeighbors=8, minSize=(56, 56))
    findings: list[VisualFinding] = []
    for x, y, w, h in boxes:
        roi = gray[y : y + h, x : x + w]
        upper_face = roi[: max(1, h // 2), :]
        eyes = eye_cascade.detectMultiScale(
            upper_face,
            scaleFactor=1.08,
            minNeighbors=5,
            minSize=(10, 10),
        )

        if len(eyes) == 0:
            continue

        findings.append(
            VisualFinding(
                name="Face or person identity",
                severity="MEDIUM",
                points=15,
                confidence=0.8 if len(eyes) >= 2 else 0.68,
                box=_box_dict(x, y, w, h),
                advice="Face-like visible content was detected and blurred in the redacted copy.",
            )
        )

    return findings


def _detect_number_plates(cv2, image) -> list[VisualFinding]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    cascade_names = [
        "haarcascade_russian_plate_number.xml",
        "haarcascade_licence_plate_rus_16stages.xml",
    ]
    findings: list[VisualFinding] = []

    for name in cascade_names:
        cascade_path = Path(cv2.data.haarcascades) / name
        if not cascade_path.exists():
            continue
        cascade = cv2.CascadeClassifier(str(cascade_path))
        if cascade.empty():
            continue
        boxes = cascade.detectMultiScale(gray, scaleFactor=1.05, minNeighbors=7, minSize=(60, 18))
        findings.extend(
            VisualFinding(
                name="Possible vehicle number plate",
                severity="MEDIUM",
                points=20,
                confidence=0.7,
                box=_box_dict(x, y, w, h),
                advice="A plate-like rectangle was detected and blurred in the redacted copy.",
            )
            for x, y, w, h in boxes
        )

    return findings


def _detect_skin_regions(cv2, np, image) -> list[VisualFinding]:
    height, width = image.shape[:2]
    image_area = height * width
    if image_area <= 0:
        return []

    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    lower = np.array([0, 30, 45], dtype=np.uint8)
    upper = np.array([25, 180, 255], dtype=np.uint8)
    mask = cv2.inRange(hsv, lower, upper)
    mask = cv2.medianBlur(mask, 7)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    findings: list[VisualFinding] = []
    for contour in contours:
        area = cv2.contourArea(contour)
        area_ratio = area / image_area
        if area_ratio < 0.025:
            continue

        x, y, w, h = cv2.boundingRect(contour)
        if w < 40 or h < 40:
            continue

        findings.append(
            VisualFinding(
                name="Possible sensitive body content",
                severity="MEDIUM",
                points=20,
                confidence=min(0.9, 0.45 + area_ratio),
                box=_box_dict(x, y, w, h),
                advice="A skin-tone region was detected. Review the redacted copy before sharing.",
            )
        )

    return findings


def _blur_findings(cv2, image, findings: list[VisualFinding]):
    height, width = image.shape[:2]
    for finding in findings:
        box = finding.box
        x1 = max(0, box["x"])
        y1 = max(0, box["y"])
        x2 = min(width, x1 + box["width"])
        y2 = min(height, y1 + box["height"])
        if x2 <= x1 or y2 <= y1:
            continue

        roi = image[y1:y2, x1:x2]
        kernel = max(25, (min(roi.shape[:2]) // 2) | 1)
        image[y1:y2, x1:x2] = cv2.GaussianBlur(roi, (kernel, kernel), 0)
        cv2.rectangle(image, (x1, y1), (x2, y2), (37, 199, 183), 2)
    return image


def _merge_overlapping_findings(findings: list[VisualFinding]) -> list[VisualFinding]:
    kept: list[VisualFinding] = []
    for finding in sorted(findings, key=lambda item: item.points, reverse=True):
        if any(_overlap_ratio(finding.box, other.box) > 0.55 for other in kept):
            continue
        kept.append(finding)
    return kept[:12]


def _overlap_ratio(a: dict[str, int], b: dict[str, int]) -> float:
    ax2 = a["x"] + a["width"]
    ay2 = a["y"] + a["height"]
    bx2 = b["x"] + b["width"]
    by2 = b["y"] + b["height"]
    ix1 = max(a["x"], b["x"])
    iy1 = max(a["y"], b["y"])
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0

    intersection = (ix2 - ix1) * (iy2 - iy1)
    smaller = min(a["width"] * a["height"], b["width"] * b["height"])
    return intersection / max(smaller, 1)


def _box_dict(x, y, width, height) -> dict[str, int]:
    return {
        "x": int(x),
        "y": int(y),
        "width": int(width),
        "height": int(height),
    }
