import logging
from pathlib import Path
from datetime import datetime

from flask import Flask, jsonify, render_template, request
from PIL import Image
from PIL.ExifTags import GPSTAGS, TAGS

# Configure logging for production monitoring
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
UPLOAD_DIR = Path(__file__).resolve().parent / "uploads"
ALLOWED = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".heic", ".webp"}

app = Flask(
    __name__,
    template_folder=str(ROOT / "templates"),
    static_folder=str(ROOT / "static"),
)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
app.config["JSON_SORT_KEYS"] = False
UPLOAD_DIR.mkdir(exist_ok=True)
SKIP = {"MakerNote", "PrintImageMatching"}
SEVERITY = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}

# Request counter for analytics
request_count = {"total": 0, "successful": 0, "failed": 0}


def _decode_bytes(value):
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value


def extract_exif(path):
    try:
        raw = Image.open(path)._getexif() or {}
    except Exception:
        return {}

    out = {}
    for tag_id, value in raw.items():
        name = TAGS.get(tag_id, str(tag_id))
        if name == "GPSInfo":
            out["GPS"] = {GPSTAGS.get(k, str(k)): v for k, v in value.items()}
        else:
            out[name] = _decode_bytes(value)
    return out


@app.before_request
def count_request():
    if request.endpoint != "static":
        request_count["total"] += 1


@app.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint for monitoring."""
    return jsonify({"status": "healthy", "timestamp": datetime.utcnow().isoformat()}), 200

@app.route("/stats", methods=["GET"])
def get_stats():
    """Return application statistics."""
    logger.info(f"Stats requested - Total: {request_count['total']}, Success: {request_count['successful']}, Failed: {request_count['failed']}")
    return jsonify(request_count), 200


def register_routes():
    try:
        from . import scorer
    except ImportError:
        import scorer


register_routes()


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
