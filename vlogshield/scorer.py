from pathlib import Path
import logging
import unicodedata

from flask import jsonify, render_template, request
from werkzeug.utils import secure_filename

try:
    from .app import app, UPLOAD_DIR, ALLOWED, extract_exif, SKIP, SEVERITY, request_count, MAX_UPLOAD_BYTES, validate_image, scan_store, scan_rate_limit
    from .visual_privacy import analyze_visual_privacy
except ImportError:
    try:
        from __main__ import app, UPLOAD_DIR, ALLOWED, extract_exif, SKIP, SEVERITY, request_count, MAX_UPLOAD_BYTES, validate_image, scan_store, scan_rate_limit
        from visual_privacy import analyze_visual_privacy
    except ImportError:
        from app import app, UPLOAD_DIR, ALLOWED, extract_exif, SKIP, SEVERITY, request_count, MAX_UPLOAD_BYTES, validate_image, scan_store, scan_rate_limit
        from visual_privacy import analyze_visual_privacy

logger = logging.getLogger(__name__)

# tag -> (name, points, severity, advice)
RISKS = {
    "GPS": ("GPS Coordinates", 45, "CRITICAL", "Exact location is embedded in this image."),
    "Make": ("Camera/Phone Brand", 10, "LOW", "Shows which device brand took the photo."),
    "Model": ("Camera/Phone Model", 15, "MEDIUM", "Shows your exact device model."),
    "Software": ("Software Used", 10, "LOW", "Shows which app or OS processed the image."),
    "DateTime": ("Original Timestamp", 10, "LOW", "Shows when the photo was taken."),
    "DateTimeOriginal": ("Shooting Timestamp", 10, "LOW", "Shows the exact capture time."),
    "Artist": ("Artist / Author Name", 25, "HIGH", "Your real name may be stored in the file."),
    "Copyright": ("Copyright String", 15, "MEDIUM", "May contain your name or handle."),
    "ImageDescription": ("Image Description", 10, "LOW", "Custom description text in the file."),
    "UserComment": ("User Comment", 20, "HIGH", "Comment field may hold personal info."),
    "SerialNumber": ("Device Serial Number", 30, "CRITICAL", "Unique hardware ID in metadata."),
    "LensSerialNumber": ("Lens Serial Number", 20, "HIGH", "Lens ID can link photos to you."),
    "BodySerialNumber": ("Body Serial Number", 30, "CRITICAL", "Camera body serial in metadata."),
    "CameraOwnerName": ("Camera Owner Name", 25, "HIGH", "Owner name registered on the camera."),
    "OwnerName": ("Owner Name", 25, "HIGH", "Owner name field has identifying info."),
    "XPAuthor": ("Windows Author Tag", 20, "HIGH", "Windows author metadata found."),
    "XPComment": ("Windows Comment Tag", 15, "MEDIUM", "Windows comment metadata found."),
    "XPSubject": ("Windows Subject Tag", 10, "LOW", "Windows subject metadata found."),
}

RECOMMENDATIONS = {
    "CRITICAL": "Strip metadata and use the redacted copy before sharing.",
    "HIGH": "Remove identifying fields or visible private details before publishing this image.",
    "MEDIUM": "Review this finding and use the redacted copy when posting publicly.",
    "LOW": "This field is usually low impact, but removing it is still safer.",
}


def format_metadata_display(value):
    text = str(value)
    cleaned = "".join(
        char
        for char in text
        if char in {"\n", "\r", "\t"} or not unicodedata.category(char).startswith("C")
    ).strip()

    if not cleaned or cleaned.count("\ufffd") >= 3:
        return "Unreadable embedded text"
    return cleaned


def build_summary(score, risks):
    if not risks:
        return {
            "headline": "No sensitive metadata or visual privacy risks found.",
            "next_step": "This image looks clean for sharing.",
            "top_severity": "NONE",
        }

    top = risks[0]["severity"]
    visual_count = sum(1 for risk in risks if risk.get("source") == "visual")
    metadata_count = len(risks) - visual_count
    parts = []
    if metadata_count:
        parts.append(f"{metadata_count} metadata risk{'s' if metadata_count != 1 else ''}")
    if visual_count:
        parts.append(f"{visual_count} visual risk{'s' if visual_count != 1 else ''}")

    return {
        "headline": f"{' and '.join(parts)} found.",
        "next_step": RECOMMENDATIONS.get(top, "Review the metadata before sharing."),
        "top_severity": top,
    }


def grade_scan(score, risks):
    severities = {risk["severity"] for risk in risks}
    if "CRITICAL" in severities:
        return "High risk"
    if "HIGH" in severities:
        return "High risk" if score >= 50 else "Medium risk"
    if "MEDIUM" in severities:
        return "Medium risk"
    if score > 0:
        return "Low risk"
    return "Safe"


def score_image(path):
    data = extract_exif(path)
    visual = analyze_visual_privacy(path)
    risks = []
    safe_fields = []
    total_score = 0
    visual_risks = visual["risks"] if visual["available"] else []

    for tag, value in data.items():
        if tag in SKIP:
            continue
        if tag in RISKS:
            name, points, severity, advice = RISKS[tag]
            risks.append({
                "name": name,
                "value": format_metadata_display(value),
                "severity": severity,
                "advice": advice,
                "source": "metadata",
            })
            total_score += points
        else:
            safe_fields.append({"tag": tag, "value": value})

    risks.extend(visual_risks)
    total_score += visual["score"] if visual["available"] else 0
    risks.sort(key=lambda item: SEVERITY.get(item["severity"], 99))
    score = min(total_score, 100)
    grade = grade_scan(score, risks)

    return {
        "score": score,
        "grade": grade,
        "summary": build_summary(score, risks),
        "risks": risks,
        "safe_fields": safe_fields,
        "visual_scan": {
            "available": visual["available"],
            "risk_count": len(visual_risks),
            "redacted_image": visual["redacted_image"] if visual["available"] else None,
        },
    }


def allowed(filename):
    return Path(filename).suffix.lower() in ALLOWED


def file_size(file):
    file.stream.seek(0, 2)
    size = file.stream.tell()
    file.stream.seek(0)
    return size


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/scan", methods=["POST"])
@scan_rate_limit
def scan():
    file = request.files.get("file")
    if not file or not file.filename:
        request_count["failed"] += 1
        logger.warning("Scan attempted without file")
        return jsonify({"error": "No file uploaded"}), 400
    if not allowed(file.filename):
        request_count["failed"] += 1
        logger.warning(f"Unsupported file type: {file.filename}")
        return jsonify({"error": "File type not supported"}), 400

    # File size validation (16MB limit) without buffering the whole upload.
    size = file_size(file)
    if size > MAX_UPLOAD_BYTES:
        request_count["failed"] += 1
        return jsonify({"error": "File too large"}), 413

    original_name = secure_filename(file.filename) or "upload"
    ext = Path(original_name).suffix.lower().lstrip(".")
    path = UPLOAD_DIR / f"{uuid_token()}.{ext}"

    try:
        file.save(path)
        validate_image(path)
        result = score_image(str(path))
        request_count["successful"] += 1

        file_type = Path(original_name).suffix.lower().lstrip(".") or "image"
        scan_store.add_scan(file_type, result)

        logger.info(f"Image scan completed - Score: {result['score']}")
        return jsonify(result)
    except ValueError as e:
        request_count["failed"] += 1
        logger.warning(f"Upload validation failed: {e}")
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        request_count["failed"] += 1
        logger.error(f"Processing failed: {str(e)}")
        return jsonify({"error": "Processing failed"}), 500
    finally:
        path.unlink(missing_ok=True)

@app.route("/history", methods=["GET"])
def get_history():
    """Return recent scan history."""
    return jsonify({"scans": scan_store.recent_scans(50)}), 200


def uuid_token():
    import uuid

    return uuid.uuid4().hex
