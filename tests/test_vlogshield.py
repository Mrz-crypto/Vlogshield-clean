import io
from pathlib import Path
import tempfile
from unittest.mock import patch
import unittest

from PIL import Image

import vlogshield.auth as auth
from vlogshield.app import app, extract_exif, normalize_metadata_value, scan_store
from vlogshield.auth import configure_user_store
from vlogshield.scorer import build_action_items, format_metadata_display, grade_scan
from vlogshield.visual_privacy import VisualFinding, _blur_findings


def make_png_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), color=(30, 80, 120)).save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


class VlogShieldApiTests(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        self.auth_tmp = tempfile.TemporaryDirectory()
        configure_user_store(Path(self.auth_tmp.name) / "users.sqlite3")
        self.client = app.test_client()
        scan_store.clear()
        self.register_and_login()

    def tearDown(self):
        self.auth_tmp.cleanup()

    def register_and_login(self):
        response = self.client.post(
            "/register",
            data={
                "username": "owner",
                "email": "owner@example.com",
                "password": "password123",
                "confirm": "password123",
            },
        )
        self.assertEqual(response.status_code, 302)

    def test_unauthenticated_scan_requires_login(self):
        guest = app.test_client()

        response = guest.post(
            "/scan",
            data={"file": (make_png_bytes(), "clean.png")},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["error"], "Authentication required")

    def test_first_registered_user_can_open_admin_dashboard(self):
        response = self.client.get("/admin")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"owner@example.com", response.data)

    def test_admin_can_delete_user(self):
        guest = app.test_client()
        guest.post(
            "/register",
            data={
                "username": "remove-me",
                "email": "remove-me@example.com",
                "password": "password123",
                "confirm": "password123",
            },
        )

        target = auth.user_store.find_by_identity("remove-me")
        self.assertIsNotNone(target)

        response = self.client.post(
            f"/admin/users/{target['id']}/delete",
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Deleted user remove-me.", response.data)
        self.assertIsNone(auth.user_store.find_by_identity("remove-me"))

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
        self.assertIn("actions", payload)
        self.assertIn("risk_breakdown", payload)
        self.assertIn("privacy_guards", payload)
        self.assertGreaterEqual(len(payload["actions"]), 1)
        self.assertIn("Temporary upload is deleted after scanning.", payload["privacy_guards"])
        self.assertEqual(payload["risk_breakdown"]["metadata"], 0)
        self.assertEqual(payload["risk_breakdown"]["visual"], 0)
        self.assertEqual(payload["visual_scan"]["risk_count"], 0)

    def test_image_validation_accepts_registered_heic(self):
        from pillow_heif import HeifImagePlugin  # noqa: F401

        buffer = io.BytesIO()
        Image.new("RGB", (4, 4), color=(30, 80, 120)).save(buffer, format="HEIF")
        buffer.seek(0)

        response = self.client.post(
            "/scan",
            data={"file": (buffer, "clean.heic")},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 200)

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

    def test_extract_exif_reads_nested_gps_ifd_and_formats_coordinates(self):
        class FakeExif(dict):
            def get_ifd(self, tag):
                self.requested_tag = tag
                return {
                    1: "N",
                    2: (27.0, 42.0, 0.0),
                    3: "E",
                    4: (85.0, 19.0, 30.0),
                }

        class FakeImage:
            def __init__(self):
                self.exif = FakeExif({34853: 12})

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def getexif(self):
                return self.exif

        with patch("vlogshield.app.Image.open", return_value=FakeImage()):
            metadata = extract_exif("location.heic")

        self.assertEqual(metadata["GPS"]["Coordinates"], "27.700000, 85.325000")
        self.assertEqual(metadata["GPS"]["GPSLatitudeRef"], "N")

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

    def test_timestamp_action_is_included_for_timestamp_risk(self):
        actions = build_action_items(
            [{"name": "Original Timestamp", "severity": "LOW", "source": "metadata"}],
            [],
        )

        self.assertIn("Check timestamps if the capture time should stay private.", actions)

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

    def test_review_only_body_finding_is_not_blurred(self):
        import cv2
        import numpy as np

        image = np.full((40, 40, 3), 120, dtype=np.uint8)
        body_warning = VisualFinding(
            name="Possible sensitive body content",
            severity="MEDIUM",
            points=20,
            confidence=0.7,
            box={"x": 5, "y": 5, "width": 30, "height": 30},
            advice="Review-only warning.",
            auto_redact=False,
        )

        output = _blur_findings(
            cv2, image.copy(), [finding for finding in [body_warning] if finding.auto_redact]
        )

        self.assertTrue(np.array_equal(output, image))
        self.assertFalse(body_warning.as_risk()["auto_redact"])


if __name__ == "__main__":
    unittest.main()
