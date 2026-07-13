import io
from unittest.mock import patch
import unittest

from PIL import Image

from vlogshield.app import app, normalize_metadata_value, scan_store
from vlogshield.scorer import format_metadata_display, grade_scan


def make_png_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), color=(30, 80, 120)).save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


class VlogShieldApiTests(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()
        scan_store.clear()

    def test_health_includes_runtime_details(self):
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"], "healthy")
        self.assertIn("uptime_seconds", payload)
        self.assertIn("max_upload_mb", payload)
        self.assertIn("scan_rate_limit", payload)
        self.assertEqual(payload["storage_backend"], "memory")

    def test_responses_include_security_headers(self):
        response = self.client.get("/health")

        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(response.headers["Referrer-Policy"], "same-origin")
        self.assertEqual(
            response.headers["Permissions-Policy"],
            "geolocation=(), camera=(), microphone=()",
        )

    def test_scan_rejects_unsupported_extension(self):
        response = self.client.post(
            "/scan",
            data={"file": (io.BytesIO(b"not an image"), "notes.txt")},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "File type not supported")

    def test_scan_rejects_unreadable_image(self):
        response = self.client.post(
            "/scan",
            data={"file": (io.BytesIO(b"not an image"), "fake.jpg")},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "Uploaded file is not a readable image.")

    def test_scan_accepts_clean_png(self):
        response = self.client.post(
            "/scan",
            data={"file": (make_png_bytes(), "clean.png")},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["score"], 0)
        self.assertEqual(payload["grade"], "Safe")
        self.assertEqual(payload["summary"]["top_severity"], "NONE")
        self.assertIn("visual_scan", payload)
        self.assertEqual(payload["visual_scan"]["risk_count"], 0)

    def test_history_does_not_store_original_filename(self):
        response = self.client.post(
            "/scan",
            data={"file": (make_png_bytes(), "family-trip.png")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)

        history_response = self.client.get("/history")
        history = history_response.get_json()["scans"]

        self.assertEqual(len(history), 1)
        self.assertNotIn("filename", history[0])
        self.assertEqual(history[0]["file_type"], "png")
        self.assertIn("scan_id", history[0])

    def test_stats_include_storage_summary(self):
        self.client.post(
            "/scan",
            data={"file": (make_png_bytes(), "scan.png")},
            content_type="multipart/form-data",
        )

        payload = self.client.get("/stats").get_json()

        self.assertEqual(payload["stored_scans"], 1)
        self.assertIn("average_score", payload)
        self.assertIn("high_risk_scans", payload)
        self.assertEqual(payload["storage_backend"], "memory")

    def test_metadata_normalization_handles_nested_values(self):
        value = {
            b"author": (b"Ada", 2, None),
            "gps": {"lat": [1, 2, 3]},
        }

        self.assertEqual(
            normalize_metadata_value(value),
            {"author": ["Ada", 2, None], "gps": {"lat": [1, 2, 3]}},
        )

    def test_metadata_display_hides_control_character_noise(self):
        self.assertEqual(
            format_metadata_display("\x00\x01\x02\x03"),
            "Unreadable embedded text",
        )
        self.assertEqual(format_metadata_display("Camera note"), "Camera note")

    def test_medium_metadata_does_not_escalate_to_high_risk(self):
        risks = [
            {"severity": "MEDIUM"},
            {"severity": "LOW"},
            {"severity": "LOW"},
            {"severity": "LOW"},
        ]

        self.assertEqual(grade_scan(65, risks), "Medium risk")

    def test_critical_metadata_stays_high_risk(self):
        self.assertEqual(grade_scan(45, [{"severity": "CRITICAL"}]), "High risk")

    def test_disabled_visual_scan_does_not_return_visual_risks(self):
        fake_visual = {
            "available": False,
            "score": 30,
            "redacted_image": "data:image/jpeg;base64,abc",
            "risks": [
                {
                    "name": "Face or person identity",
                    "value": "82% confidence",
                    "severity": "MEDIUM",
                    "advice": "Review this visual finding.",
                    "source": "visual",
                }
            ],
        }

        with patch("vlogshield.scorer.analyze_visual_privacy", return_value=fake_visual):
            response = self.client.post(
                "/scan",
                data={"file": (make_png_bytes(), "clean.png")},
                content_type="multipart/form-data",
            )

        payload = response.get_json()
        self.assertEqual(payload["visual_scan"]["available"], False)
        self.assertEqual(payload["visual_scan"]["risk_count"], 0)
        self.assertFalse(any(risk.get("source") == "visual" for risk in payload["risks"]))


if __name__ == "__main__":
    unittest.main()
