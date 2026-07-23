import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

import modelling


class FalAdapterTest(unittest.TestCase):
    def test_kling_vertical_payload_uses_single_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "start.jpg"
            Image.new("RGB", (720, 1280), "white").save(image_path)
            captured = {}
            fake_client = SimpleNamespace(
                upload_file=lambda _path: "https://example.test/start.jpg",
                submit=lambda endpoint, arguments: (
                    captured.update(endpoint=endpoint, arguments=arguments)
                    or SimpleNamespace(request_id="request-1")
                ),
            )
            params = {
                "prompt": "A subtle head turn toward camera.",
                "duration": 5,
                "aspect_ratio": "9:16",
                "sound": "off",
            }
            with patch.dict(os.environ, {"FAL_KEY": "test"}), patch.dict(
                sys.modules, {"fal_client": fake_client}
            ):
                request_id = modelling._fal_submit_video(
                    "kling3_0", params, [("image", image_path)], log=lambda _message: None
                )

        self.assertEqual(request_id, "request-1")
        self.assertEqual(captured["arguments"]["aspect_ratio"], "9:16")
        self.assertEqual(captured["arguments"]["prompt"], params["prompt"])
        self.assertNotIn("multi_prompt", captured["arguments"])

    def test_pm_rejects_fal_seedance_before_generation(self):
        with self.assertRaisesRegex(ValueError, "face-forward"):
            modelling.run_modelling(
                "245787", "E31_porto", 1, model="seedance_2_0", provider="fal"
            )


if __name__ == "__main__":
    unittest.main()
