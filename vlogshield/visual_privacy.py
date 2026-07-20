from __future__ import annotations

from base64 import b64encode
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps


@dataclass(frozen=True)
class VisualFinding:
    name: str
    severity: str
    points: int
    confidence: float
    box: dict[str, int]
    advice: str
    # Findings blur in the redacted copy by default. Set False for anything that
    # should be reported for review but not blurred automatically.
    auto_redact: bool = True

    def as_risk(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": f"{round(self.confidence * 100)}% confidence",
            "severity": self.severity,
            "advice": self.advice,
            "source": "visual",
            "box": self.box,
            "auto_redact": self.auto_redact,
        }


def analyze_visual_privacy(path: str) -> dict[str, Any]:
    if os.getenv("VISUAL_AUTO_REDACTION", "1") == "0":
        return {"risks": [], "score": 0, "redacted_image": None, "available": False}

    try:
        import cv2
        import numpy as np
    except ImportError:
        return {"risks": [], "score": 0, "redacted_image": None, "available": False}

    image = _read_image(cv2, np, path)
    if image is None:
        return {
            "risks": [],
            "score": 0,
            "preview_image": None,
            "redacted_im age": None,
            "available": True,
        }

    findings: list[VisualFinding] = []
    findings.extend(_detect_faces(cv2, image))
    # Report a plate when either detector fires, boosting confidence when both
    # agree. Requiring both to agree meant real plates were silently dropped
    # whenever only one detector happened to fire -- the common case -- so
    # plates never appeared in the risk list.
    findings.extend(
        _merge_plate_detections(
            _detect_number_plates(cv2, image),
            _detect_plate_candidates(cv2, np, image) + _detect_red_plates(cv2, np, image),
        )
    )
    if os.getenv("VISUAL_BODY_HEURISTIC", "1") != "0":
        findings.extend(_detect_skin_regions(cv2, np, image))
    findings = _merge_overlapping_findings(findings)
    preview_image = _encode_image(cv2, image)

    if not findings:
        return {
            "risks": [],
            "score": 0,
            "preview_image": preview_image,
            "redacted_image": None,
            "available": True,
        }

    redacted = _blur_findings(
        cv2, image.copy(), [finding for finding in findings if finding.auto_redact]
    )
    redacted_image = _encode_image(cv2, redacted)

    return {
        "risks": [finding.as_risk() for finding in findings],
        "score": min(sum(finding.points for finding in findings), 45),
        "preview_image": preview_image,
        "redacted_image": redacted_image,
        "available": True,
    }


def _read_image(cv2, np, path: str):
    with Image.open(path) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        rgb = np.array(image)
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def _encode_image(cv2, image) -> str | None:
    ok, encoded = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
    if not ok:
        return None
    return "data:image/jpeg;base64," + b64encode(encoded.tobytes()).decode("ascii")


# Upright frontal cascades miss faces that are tilted or resting on a hand.
# Running detection on a few rotated copies of the image recovers them.
_FACE_ROTATIONS = (-30, -20, -12, 0, 12, 20, 30)


def _detect_faces(cv2, image) -> list[VisualFinding]:
    height, width = image.shape[:2]
    if height <= 0 or width <= 0:
        return []

    # Work on a normalised resolution. Haar cascades are slow and noisy on
    # multi-megapixel photos: they miss the obvious large face while emitting
    # tiny false positives on wheels and bodywork. Scaling the long side to
    # ~1024px fixes both problems.
    scale = min(1.0, 1024.0 / max(height, width))
    work = cv2.resize(image, (int(width * scale), int(height * scale))) if scale < 1.0 else image
    gray = cv2.equalizeHist(cv2.cvtColor(work, cv2.COLOR_BGR2GRAY))
    work_h, work_w = gray.shape[:2]

    haar = Path(cv2.data.haarcascades)
    cascades = []
    for name in ("haarcascade_frontalface_alt2.xml", "haarcascade_frontalface_default.xml"):
        clf = cv2.CascadeClassifier(str(haar / name))
        if not clf.empty():
            cascades.append(clf)
    if not cascades:
        return []
    eye_cascade = cv2.CascadeClassifier(str(haar / "haarcascade_eye.xml"))

    centre = (work_w / 2.0, work_h / 2.0)
    min_side = max(28, int(min(work_h, work_w) * 0.05))
    raw: list[dict[str, int]] = []
    for angle in _FACE_ROTATIONS:
        if angle:
            rot_m = cv2.getRotationMatrix2D(centre, angle, 1.0)
            inv_m = cv2.getRotationMatrix2D(centre, -angle, 1.0)
            frame = cv2.warpAffine(gray, rot_m, (work_w, work_h))
        else:
            inv_m = None
            frame = gray
        for clf in cascades:
            for x, y, w, h in clf.detectMultiScale(frame, 1.1, 5, minSize=(min_side, min_side)):
                cx, cy = x + w / 2.0, y + h / 2.0
                if inv_m is not None:
                    cx, cy = (
                        inv_m[0, 0] * cx + inv_m[0, 1] * cy + inv_m[0, 2],
                        inv_m[1, 0] * cx + inv_m[1, 1] * cy + inv_m[1, 2],
                    )
                raw.append(
                    _box_dict(
                        int((cx - w / 2.0) / scale),
                        int((cy - h / 2.0) / scale),
                        int(w / scale),
                        int(h / scale),
                    )
                )

    # Cluster the raw hits. A face found from several angles is trustworthy; a
    # lone hit must additionally show eye structure to be kept, which removes
    # the small false positives on background texture.
    clusters: list[dict[str, Any]] = []
    for box in raw:
        for cluster in clusters:
            if _same_target(box, cluster["box"]):
                cluster["votes"] += 1
                break
        else:
            clusters.append({"box": box, "votes": 1})

    gray_full = None
    findings: list[VisualFinding] = []
    for cluster in clusters:
        box = cluster["box"]
        votes = cluster["votes"]
        # Rotation can occasionally return a box covering most of the frame.
        if box["width"] > width * 0.8 or box["height"] > height * 0.8:
            continue

        eyes = 0
        if votes < 2:
            if gray_full is None:
                gray_full = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            x1 = max(0, box["x"])
            y1 = max(0, box["y"])
            x2 = min(width, x1 + box["width"])
            y2 = min(height, y1 + box["height"])
            roi = gray_full[y1:y2, x1:x2]
            if roi.size and not eye_cascade.empty():
                eyes = len(
                    eye_cascade.detectMultiScale(
                        roi[: max(1, (y2 - y1) // 2), :],
                        scaleFactor=1.1,
                        minNeighbors=5,
                        minSize=(12, 12),
                    )
                )
            if eyes == 0:
                continue

        findings.append(
            VisualFinding(
                name="Face or person identity",
                severity="MEDIUM",
                points=15,
                confidence=min(0.92, 0.6 + 0.1 * votes),
                box=box,
                advice="Face-like visible content was detected and blurred in the redacted copy.",
            )
        )

    return findings


def _detect_number_plates(cv2, image) -> list[VisualFinding]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    cascade_names = [
        "haarcascade_russian_plate_number.xml",
        "haarcascade_license_plate_rus_16stages.xml",
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

    # Haar plate cascades can emit several overlapping proposals around the
    # same vehicle. Keep only the strongest, distinct candidates so a photo is
    # never covered by a collection of near-duplicate blur boxes.
    kept: list[VisualFinding] = []
    for finding in sorted(
        findings,
        key=lambda item: item.box["width"] * item.box["height"],
        reverse=True,
    ):
        if any(_same_target(finding.box, existing.box) for existing in kept):
            continue
        kept.append(finding)
        if len(kept) == 3:
            break
    return kept


def _detect_plate_candidates(cv2, np, image) -> list[VisualFinding]:
    height, width = image.shape[:2]
    if height <= 0 or width <= 0:
        return []

    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    bright = cv2.inRange(hsv, np.array([0, 0, 135]), np.array([180, 95, 255]))
    yellow = cv2.inRange(hsv, np.array([15, 55, 80]), np.array([42, 255, 255]))
    red_low = cv2.inRange(hsv, np.array([0, 55, 70]), np.array([10, 255, 255]))
    red_high = cv2.inRange(hsv, np.array([170, 55, 70]), np.array([180, 255, 255]))
    plate_color = cv2.bitwise_or(yellow, cv2.bitwise_or(red_low, red_high))
    mask = cv2.bitwise_or(bright, plate_color)
    mask[: int(height * 0.42), :] = 0
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    findings: list[VisualFinding] = []
    image_area = width * height
    candidates = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < image_area * 0.00008 or area > image_area * 0.025:
            continue

        x, y, w, h = cv2.boundingRect(contour)
        if w < 35 or h < 10:
            continue
        if h > height * 0.055 or y + h > height * 0.97:
            continue
        if x < width * 0.03 or x + w > width * 0.97:
            continue

        aspect = w / max(h, 1)
        extent = area / max(w * h, 1)
        if not (1.5 <= aspect <= 6.5 and extent >= 0.35):
            continue

        color_roi = plate_color[y : y + h, x : x + w]
        plate_color_ratio = cv2.countNonZero(color_roi) / max(w * h, 1)
        if plate_color_ratio < 0.08:
            continue

        # The candidate contour has already passed tight geometry and colour
        # checks. Large refinement searches were swallowing monitors and other
        # nearby objects, resulting in giant redaction boxes.
        box = _pad_box(x, y, w, h, width, height)
        box_area = box["width"] * box["height"]
        score = box_area * (1 + (box["y"] / max(height, 1)))
        candidates.append(
            (
                score,
                VisualFinding(
                    name="Possible vehicle number plate",
                    severity="MEDIUM",
                    points=20,
                    confidence=0.64,
                    box=box,
                    advice="A plate-like visible region was detected. Review or adjust the blur before sharing.",
                ),
            )
        )

    return [finding for _score, finding in sorted(candidates, key=lambda item: item[0], reverse=True)[:3]]


def _detect_red_plates(cv2, np, image) -> list[VisualFinding]:
    """Locate red-background number plates (common on motorbikes/scooters).

    A saturated-red mask closed with a wide kernel captures the whole plate as
    one blob, so the blur covers the full number instead of a stray fragment.
    """
    height, width = image.shape[:2]
    if height <= 0 or width <= 0:
        return []

    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    red = cv2.bitwise_or(
        cv2.inRange(hsv, np.array([0, 90, 70]), np.array([12, 255, 255])),
        cv2.inRange(hsv, np.array([165, 90, 70]), np.array([180, 255, 255])),
    )
    # Plates sit on vehicle bodies, not in the sky/upper background.
    red[: int(height * 0.30), :] = 0
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 9))
    red = cv2.morphologyEx(red, cv2.MORPH_CLOSE, kernel, iterations=2)
    contours, _ = cv2.findContours(red, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    image_area = width * height
    scored = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < image_area * 0.0005 or area > image_area * 0.05:
            continue
        x, y, w, h = cv2.boundingRect(contour)
        if w < 50 or h < 15:
            continue
        aspect = w / max(h, 1)
        extent = area / max(w * h, 1)
        # Plates are wide rectangles; a near-square red blob is usually a
        # tail-light or fabric, so keep the aspect floor above 1.3.
        if not (1.3 <= aspect <= 8.0 and extent >= 0.32):
            continue
        box = _pad_box(x, y, w, h, width, height)
        scored.append(
            (
                area,
                VisualFinding(
                    name="Possible vehicle number plate",
                    severity="MEDIUM",
                    points=20,
                    confidence=0.8,
                    box=box,
                    advice="A number-plate-coloured region was detected and blurred in the redacted copy.",
                ),
            )
        )

    return [finding for _area, finding in sorted(scored, key=lambda item: item[0], reverse=True)[:3]]


def _merge_plate_detections(
    cascade_findings: list[VisualFinding], candidate_findings: list[VisualFinding]
) -> list[VisualFinding]:
    """Report plates from either detector; agreement raises confidence.

    Colour/shape candidates give tighter, colour-verified boxes, so they are
    preferred when they exist. Cascade-only hits are still reported (at lower
    confidence) so a plate is never silently missed. The user can remove a wrong
    box in the editor before downloading.
    """
    findings: list[VisualFinding] = []
    used_cascade: set[int] = set()

    for candidate in candidate_findings:
        matched = None
        for index, cascade in enumerate(cascade_findings):
            if index in used_cascade:
                continue
            if _same_target(candidate.box, cascade.box):
                matched = index
                break
        if matched is not None:
            used_cascade.add(matched)
            confidence = 0.82
            advice = "A plate-like region was confirmed and blurred in the redacted copy."
        else:
            confidence = 0.6
            advice = "A plate-like visible region was detected and blurred. Review the box before sharing."
        findings.append(
            VisualFinding(
                name="Possible vehicle number plate",
                severity="MEDIUM",
                points=20,
                confidence=confidence,
                box=candidate.box,
                advice=advice,
            )
        )

    for index, cascade in enumerate(cascade_findings):
        if index in used_cascade:
            continue
        findings.append(
            VisualFinding(
                name="Possible vehicle number plate",
                severity="MEDIUM",
                points=20,
                confidence=0.6,
                box=cascade.box,
                advice="A plate-like rectangle was detected and blurred. Review the box before sharing.",
            )
        )

    kept: list[VisualFinding] = []
    for finding in sorted(findings, key=lambda item: item.confidence, reverse=True):
        if any(_same_target(finding.box, existing.box) for existing in kept):
            continue
        kept.append(finding)
        if len(kept) == 3:
            break
    return kept


def _detect_skin_regions(cv2, np, image) -> list[VisualFinding]:
    height, width = image.shape[:2]
    image_area = height * width
    if image_area <= 0:
        return []

    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    lower_skin = np.array([0, 35, 55], dtype=np.uint8)
    upper_skin = np.array([25, 170, 255], dtype=np.uint8)
    lower_skin_alt = np.array([160, 35, 55], dtype=np.uint8)
    upper_skin_alt = np.array([180, 170, 255], dtype=np.uint8)
    mask = cv2.bitwise_or(
        cv2.inRange(hsv, lower_skin, upper_skin),
        cv2.inRange(hsv, lower_skin_alt, upper_skin_alt),
    )
    mask = cv2.medianBlur(mask, 7)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    findings: list[VisualFinding] = []
    for contour in contours:
        area = cv2.contourArea(contour)
        area_ratio = area / image_area
        if area_ratio < 0.07:
            continue

        x, y, w, h = cv2.boundingRect(contour)
        if w < 80 or h < 80:
            continue

        aspect = w / max(h, 1)
        if not (0.35 <= aspect <= 3.5):
            continue

        findings.append(
            VisualFinding(
                name="Possible sensitive body content",
                severity="MEDIUM",
                points=20,
                confidence=min(0.88, 0.5 + area_ratio),
                box=_box_dict(x, y, w, h),
                advice=(
                    "A large skin-tone region was detected and blurred in the "
                    "redacted copy. Remove the box if it covers clothing or "
                    "background rather than skin."
                ),
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
        blurred = cv2.GaussianBlur(roi, (kernel, kernel), 0)
        blurred = cv2.GaussianBlur(blurred, (kernel, kernel), 0)
        image[y1:y2, x1:x2] = blurred
        cv2.rectangle(image, (x1, y1), (x2, y2), (37, 199, 183), 2)
    return image


def _merge_overlapping_findings(findings: list[VisualFinding]) -> list[VisualFinding]:
    # Only collapse duplicates of the *same* kind. A face sitting inside a large
    # skin region must still be reported as a face -- otherwise a big body box
    # would silently swallow the face finding and its blur.
    kept: list[VisualFinding] = []
    for finding in sorted(findings, key=lambda item: item.points, reverse=True):
        if any(
            finding.name == other.name and _same_target(finding.box, other.box)
            for other in kept
        ):
            continue
        kept.append(finding)
    return kept[:12]


def _same_target(a: dict[str, int], b: dict[str, int]) -> bool:
    if _overlap_ratio(a, b) > 0.2:
        return True

    ax = a["x"] + a["width"] / 2
    ay = a["y"] + a["height"] / 2
    bx = b["x"] + b["width"] / 2
    by = b["y"] + b["height"] / 2
    center_dx = abs(ax - bx)
    center_dy = abs(ay - by)
    max_width = max(a["width"], b["width"])
    max_height = max(a["height"], b["height"])
    return center_dx <= max_width * 0.6 and center_dy <= max_height * 0.6


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


def _pad_box(x, y, width, height, image_width, image_height) -> dict[str, int]:
    pad_x = max(18, int(width * 0.32))
    pad_y = max(16, int(height * 0.9))
    x1 = max(0, int(x) - pad_x)
    y1 = max(0, int(y) - pad_y)
    x2 = min(int(image_width), int(x + width) + pad_x)
    y2 = min(int(image_height), int(y + height) + pad_y)
    return _box_dict(x1, y1, x2 - x1, y2 - y1)


def _refine_plate_box(cv2, plate_color, x, y, width, height, image_width, image_height) -> dict[str, int]:
    fallback = _pad_box(x, y, width, height, image_width, image_height)
    expand_x = max(40, int(width * 0.7))
    expand_y = max(30, int(height * 0.9))
    search_x1 = max(0, x - expand_x)
    search_y1 = max(0, y - expand_y)
    search_x2 = min(int(image_width), x + width + expand_x)
    search_y2 = min(int(image_height), y + height + expand_y)
    roi = plate_color[search_y1:search_y2, search_x1:search_x2]

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (17, 7))
    roi = cv2.morphologyEx(roi, cv2.MORPH_CLOSE, kernel, iterations=2)
    contours, _ = cv2.findContours(roi, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    center_x = x + width / 2
    center_y = y + height / 2
    useful = []
    for contour in contours:
        if cv2.contourArea(contour) < 40:
            continue
        cx, cy, cw, ch = cv2.boundingRect(contour)
        absolute_cx = search_x1 + cx + cw / 2
        absolute_cy = search_y1 + cy + ch / 2
        if abs(absolute_cx - center_x) > max(90, width * 0.9):
            continue
        if abs(absolute_cy - center_y) > max(70, height * 1.1):
            continue
        useful.append(contour)
    if not useful:
        return fallback

    points = cv2.vconcat(useful)
    rx, ry, rw, rh = cv2.boundingRect(points)
    refined_x = search_x1 + rx
    refined_y = search_y1 + ry
    pad_x = max(28, int(rw * 0.45))
    pad_y = max(18, int(rh * 0.8))
    x1 = max(0, refined_x - pad_x)
    y1 = max(0, refined_y - pad_y)
    x2 = min(int(image_width), refined_x + rw + pad_x)
    y2 = min(int(image_height), refined_y + rh + pad_y)
    refined = _box_dict(x1, y1, x2 - x1, y2 - y1)
    if refined["width"] > max(width * 3.0, 520) or refined["height"] > max(height * 3.2, 420):
        return fallback
    return refined
