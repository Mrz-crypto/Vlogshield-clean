from datetime import datetime, timezone
import logging
import os
from pathlib import Path

from flask import Flask, jsonify, render_template, request
from PIL import Image, UnidentifiedImageError
from PIL.ExifTags import GPSTAGS, TAGS

# Configure logging for production monitoring
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
UPLOAD_DIR = Path(__file__).resolve().parent / "uploads"
ALLOWED = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".heic", ".webp"}
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", "16")) * 1024 * 1024
STARTED_AT = datetime.now(timezone.utc)

app = Flask(
    __name__,
    template_folder=str(ROOT / "templates"),
    static_folder=str(ROOT / "static"),
)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
app.config["JSON_SORT_KEYS"] = False
UPLOAD_DIR.mkdir(exist_ok=True)
SKIP = {"MakerNote", "PrintImageMatching"}
SEVERITY = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}

# Request counter for analytics
request_count = {"total": 0, "successful": 0, "failed": 0}


def normalize_metadata_value(value):
    """Convert EXIF values into JSON-safe primitives."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, dict):
        return {
            _normalize_metadata_key(key): normalize_metadata_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [normalize_metadata_value(item) for item in value]
    if hasattr(value, "numerator") and hasattr(value, "denominator"):
        try:
            return float(value)
        except (TypeError, ZeroDivisionError):
            return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _normalize_metadata_key(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _json_error(message, status_code):
    request_count["failed"] += 1
    return jsonify({"error": message}), status_code


def _uptime_seconds():
    return round((datetime.now(timezone.utc) - STARTED_AT).total_seconds(), 2)


def validate_image(path):
    try:
        with Image.open(path) as image:
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValueError("Uploaded file is not a readable image.") from exc


def extract_exif(path):
    try:
        with Image.open(path) as image:
            raw = image._getexif() or {}
    except Exception as e:
        logger.warning(f"EXIF extraction failed for {path}: {e}")
        return {}

    out = {}
    for tag_id, value in raw.items():
        name = TAGS.get(tag_id, str(tag_id))
        if name == "GPSInfo":
            out["GPS"] = {
                GPSTAGS.get(k, str(k)): normalize_metadata_value(v)
                for k, v in value.items()
            }
        else:
            out[name] = normalize_metadata_value(value)
    return out


@app.before_request
def count_request():
    if request.endpoint != "static":
        request_count["total"] += 1


@app.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint for monitoring."""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uptime_seconds": _uptime_seconds(),
        "max_upload_mb": round(MAX_UPLOAD_BYTES / (1024 * 1024)),
    }), 200

@app.route("/stats", methods=["GET"])
def get_stats():
    """Return application statistics."""
    logger.info(f"Stats requested - Total: {request_count['total']}, Success: {request_count['successful']}, Failed: {request_count['failed']}")
    return jsonify({
        **request_count,
        "uptime_seconds": _uptime_seconds(),
        "max_upload_mb": round(MAX_UPLOAD_BYTES / (1024 * 1024)),
        "success_rate": round(request_count["successful"] / max(request_count["total"], 1), 3),
    }), 200


@app.errorhandler(413)
def too_large(_error):
    return _json_error("File too large", 413)


@app.errorhandler(404)
def not_found(_error):
    return _json_error("Endpoint not found", 404)


def register_routes():
    try:
        from . import scorer
    except ImportError:
        import scorer


register_routes()


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
