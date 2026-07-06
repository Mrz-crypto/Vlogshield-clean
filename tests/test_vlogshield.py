import io
import unittest

from PIL import Image

from vlogshield.app import app, normalize_metadata_value, scan_store


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


if __name__ == "__main__":
    unittest.main()
