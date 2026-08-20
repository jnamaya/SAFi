"""
Voice input wiring (backlog 74).

The contract pinned here:

- The feature is OFF by default. /api/audio/transcribe returns 404 unless
  SAFI_VOICE_INPUT is enabled, so a stock deployment offers nothing.
- The endpoint requires authentication.
- When enabled, it runs the local transcription service and returns its text.
  The transcription itself (whisper.cpp + ffmpeg) is mocked here: the wiring is
  what this test owns, not the binary.
- The transcription service reports itself unavailable when the binary or model
  is missing, so the feature cannot be turned on where it cannot work.
- /api/app-config advertises the flag so the frontend can show or hide the mic.

Needs the disposable stack:
    docker compose -f docker-compose.test.yml run --rm tests -k voice_input
"""
import io
import sys
import uuid
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app import create_app
from safi_app.config import Config
from safi_app.core.services import transcription

from support import login_as, new_user


class VoiceInputWiring(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()

    def setUp(self):
        self.client = self.app.test_client()
        self.uid = f"voice-user-{uuid.uuid4().hex[:8]}"
        new_user(user_id=self.uid, role="member")

    def _post_audio(self):
        return self.client.post(
            "/api/audio/transcribe",
            data={"file": (io.BytesIO(b"fake-audio-bytes"), "rec.webm")},
            content_type="multipart/form-data",
        )

    def test_requires_authentication(self):
        # No session at all.
        r = self.client.post("/api/audio/transcribe",
                             data={"file": (io.BytesIO(b"x"), "r.webm")},
                             content_type="multipart/form-data")
        self.assertEqual(r.status_code, 401)

    def test_disabled_by_default_returns_404(self):
        login_as(self.client, self.uid, "member")
        with mock.patch.object(Config, "VOICE_INPUT_ENABLED", False):
            r = self._post_audio()
        self.assertEqual(r.status_code, 404)

    def test_enabled_returns_transcript(self):
        login_as(self.client, self.uid, "member")
        with mock.patch.object(Config, "VOICE_INPUT_ENABLED", True), \
             mock.patch("safi_app.core.services.transcription.transcribe",
                        return_value="hello from the microphone"):
            r = self._post_audio()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["text"], "hello from the microphone")

    def test_enabled_surfaces_transcription_error_cleanly(self):
        login_as(self.client, self.uid, "member")
        err = transcription.TranscriptionError("Transcription timed out. Try a shorter clip.")
        with mock.patch.object(Config, "VOICE_INPUT_ENABLED", True), \
             mock.patch("safi_app.core.services.transcription.transcribe", side_effect=err):
            r = self._post_audio()
        self.assertEqual(r.status_code, 400)
        self.assertIn("shorter clip", r.get_json()["error"])

    def test_oversize_audio_rejected(self):
        login_as(self.client, self.uid, "member")
        big = io.BytesIO(b"0" * (Config.MAX_AUDIO_SIZE_MB * 1024 * 1024 + 1024))
        with mock.patch.object(Config, "VOICE_INPUT_ENABLED", True):
            r = self.client.post("/api/audio/transcribe",
                                 data={"file": (big, "big.webm")},
                                 content_type="multipart/form-data")
        self.assertEqual(r.status_code, 400)
        self.assertIn("too large", r.get_json()["error"].lower())

    def test_service_unavailable_without_binary(self):
        # Enabled, but the whisper binary/model paths do not exist.
        with mock.patch.object(Config, "VOICE_INPUT_ENABLED", True), \
             mock.patch.object(Config, "WHISPER_CLI_PATH", "/nonexistent/whisper-cli"), \
             mock.patch.object(Config, "WHISPER_MODEL_PATH", "/nonexistent/model.bin"):
            self.assertFalse(transcription.is_available())
            with self.assertRaises(transcription.TranscriptionError):
                transcription.transcribe(b"data", "rec.webm")

    def test_app_config_exposes_voice_flag(self):
        r = self.client.get("/api/app-config")
        self.assertEqual(r.status_code, 200)
        self.assertIn("voice_input_enabled", r.get_json())


if __name__ == "__main__":
    unittest.main()
