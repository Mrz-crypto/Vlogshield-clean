import uuid
from pathlib import Path
from datetime import datetime, timezone
import logging

from flask import jsonify, render_template, request
from werkzeug.utils import secure_filename

try:
    from .app import app, UPLOAD_DIR, ALLOWED, extract_exif, SKIP, SEVERITY, request_count, MAX_UPLOAD_BYTES, validate_image
except ImportError:
    try:
        from __main__ import app, UPLOAD_DIR, ALLOWED, extract_exif, SKIP, SEVERITY, request_count, MAX_UPLOAD_BYTES, validate_image
    except ImportError:
        from app import app, UPLOAD_DIR, ALLOWED, extract_exif, SKIP, SEVERITY, request_count, MAX_UPLOAD_BYTES, validate_image

logger = logging.getLogger(__name__)

# Scan history for analytics (bounded to avoid unbounded memory growth)
MAX_HISTORY = 500
scan_history = []

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
    "CRITICAL": "Strip metadata before sharing and avoid posting the original file.",
    "HIGH": "Remove identifying fields before publishing this image.",
    "MEDIUM": "Review this metadata and remove it when posting publicly.",
    "LOW": "This field is usually low impact, but stripping it is still safer.",
}


def build_summary(score, risks):
    if not risks:
        return {
            "headline": "No sensitive EXIF metadata found.",
            "next_step": "This image looks clean for sharing.",
            "top_severity": "NONE",
        }

    top = risks[0]["severity"]
    return {
        "headline": f"{len(risks)} metadata risk{'s' if len(risks) != 1 else ''} found.",
        "next_step": RECOMMENDATIONS.get(top, "Review the metadata before sharing."),
        "top_severity": top,
    }


def score_image(path):
    data = extract_exif(path)
    risks = []
    safe_fields = []
    total_score = 0

    for tag, value in data.items():
        if tag in SKIP:
            continue
        if tag in RISKS:
            name, points, severity, advice = RISKS[tag]
            risks.append({
                "name": name,
                "value": str(value),
                "severity": severity,
                "advice": advice,
            })
            total_score += points
        else:
            safe_fields.append({"tag": tag, "value": value})

    risks.sort(key=lambda item: SEVERITY.get(item["severity"], 99))
    score = min(total_score, 100)
    if score >= 50:
        grade = "High risk"
    elif score >= 20:
        grade = "Medium risk"
    elif score > 0:
        grade = "Low risk"
    else:
        grade = "Safe"

    return {
        "score": score,
        "grade": grade,
        "summary": build_summary(score, risks),
        "risks": risks,
        "safe_fields": safe_fields,
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
    path = UPLOAD_DIR / f"{uuid.uuid4().hex}.{ext}"

    try:
        file.save(path)
        validate_image(path)
        result = score_image(str(path))
        request_count["successful"] += 1
        
        # Log scan to history, keeping only the most recent entries.
        scan_history.append({
            "filename": original_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "score": result["score"],
            "grade": result["grade"],
            "risk_count": len(result["risks"]),
        })
        if len(scan_history) > MAX_HISTORY:
            del scan_history[:-MAX_HISTORY]

        logger.info(f"Image scan completed: {file.filename} - Score: {result['score']}")
        return jsonify(result)
    except ValueError as e:
        request_count["failed"] += 1
        logger.warning(f"Upload validation failed for {file.filename}: {e}")
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        request_count["failed"] += 1
        logger.error(f"Processing failed for {file.filename}: {str(e)}")
        return jsonify({"error": "Processing failed"}), 500
    finally:
        path.unlink(missing_ok=True)

@app.route("/history", methods=["GET"])
def get_history():
    """Return recent scan history."""
    return jsonify({"scans": scan_history[-50:]}), 200
