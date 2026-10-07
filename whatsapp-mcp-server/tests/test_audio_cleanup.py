import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests
import whatsapp


class AudioCleanupTests(unittest.TestCase):
    def test_converted_file_is_cleaned_after_success_and_failure(self):
        for response in [Mock(status_code=200, json=lambda: {"success": True}),
                         Mock(status_code=500, text="failed"),
                         requests.ConnectionError("offline")]:
            with self.subTest(response=response), tempfile.TemporaryDirectory() as directory:
                source = Path(directory) / "original.wav"
                converted = Path(directory) / "converted.ogg"
                source.write_bytes(b"original")
                converted.write_bytes(b"converted")

                def post(*args, **kwargs):
                    self.assertTrue(converted.exists())
                    self.assertEqual(kwargs["json"]["media_path"], str(converted))
                    if isinstance(response, Exception):
                        raise response
                    return response

                with patch.object(whatsapp.audio, "convert_to_opus_ogg_temp", return_value=str(converted)), patch.object(whatsapp.requests, "post", side_effect=post):
                    whatsapp.send_audio_message("123", str(source))
                self.assertFalse(converted.exists())
                self.assertEqual(source.read_bytes(), b"original")

    def test_original_ogg_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "original.ogg"
            source.write_bytes(b"original")
            with patch.object(whatsapp.requests, "post", side_effect=requests.ConnectionError("offline")):
                whatsapp.send_audio_message("123", str(source))
            self.assertEqual(source.read_bytes(), b"original")
