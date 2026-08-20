"""
Governed speech-to-text.

Transcribe-then-govern, the same pattern document_processor uses for images
(OCR). Audio is converted to text HERE by a local whisper.cpp binary, and only
the TEXT travels onward: the API layer hands it back to the composer, and the
user sends it through the normal /evaluate pipeline, so Phase Zero scans the
transcript and it lands in the audit record like any typed prompt.

Raw audio is NEVER sent to a reasoning model, and it is not stored. The governed
artifact is the transcript, which means transcription fidelity is a real seam:
what whisper heard, not what was said, is what gets governed. That is the same
trade OCR makes, and it is why the transcript, not the audio, is the record.

Everything here runs locally and shells out to whisper.cpp; nothing leaves the
host. The feature is off unless SAFI_VOICE_INPUT is set AND the binary and model
exist, so a stock deployment (e.g. a Docker image without whisper installed)
simply reports the feature unavailable rather than failing obscurely.
"""
import os
import subprocess
import tempfile
import logging

from ...config import Config

log = logging.getLogger(__name__)


class TranscriptionError(Exception):
    """A clean, user-facing failure. The API layer returns its message as a 400."""
    pass


def is_available() -> bool:
    """True only if the feature is enabled and the whisper.cpp binary and model
    are actually present. The API and the app-config flag can use this to avoid
    offering voice input where it cannot work."""
    return (
        Config.VOICE_INPUT_ENABLED
        and os.path.isfile(Config.WHISPER_CLI_PATH)
        and os.path.isfile(Config.WHISPER_MODEL_PATH)
    )


def transcribe(audio_bytes: bytes, filename: str) -> str:
    """Transcribe an uploaded audio blob to text with whisper.cpp.

    Steps: normalize whatever the browser recorded (webm/opus, mp4, wav, ...) to
    16kHz mono WAV with ffmpeg, then run whisper.cpp against the configured model.
    Both steps are bounded by a subprocess timeout so a pathological or oversized
    clip cannot tie up a worker, the same reliability rule the model calls follow.
    """
    if not Config.VOICE_INPUT_ENABLED:
        raise TranscriptionError("Voice input is disabled on this deployment.")
    if not os.path.isfile(Config.WHISPER_CLI_PATH):
        raise TranscriptionError("The speech-to-text engine is not installed on this deployment.")
    if not os.path.isfile(Config.WHISPER_MODEL_PATH):
        raise TranscriptionError("The speech-to-text model is not installed on this deployment.")

    timeout = Config.WHISPER_TIMEOUT_SECONDS

    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "input")   # extension-agnostic; ffmpeg sniffs the format
        wav = os.path.join(d, "audio.wav")
        prefix = os.path.join(d, "out")

        with open(src, "wb") as f:
            f.write(audio_bytes)

        # 1) Normalize to the 16kHz mono WAV whisper.cpp expects.
        try:
            subprocess.run(
                ["ffmpeg", "-nostdin", "-y", "-i", src, "-ar", "16000", "-ac", "1", "-f", "wav", wav],
                check=True, capture_output=True, timeout=timeout,
            )
        except FileNotFoundError:
            raise TranscriptionError("Audio conversion is unavailable (ffmpeg is not installed).")
        except subprocess.TimeoutExpired:
            raise TranscriptionError("Audio conversion timed out. Try a shorter clip.")
        except subprocess.CalledProcessError as e:
            log.error("ffmpeg failed: %s", (e.stderr or b"").decode("utf-8", "ignore")[:500])
            raise TranscriptionError("Could not read the audio. Please try recording again.")

        # 2) Transcribe. -nt drops timestamps; -otxt writes <prefix>.txt.
        try:
            subprocess.run(
                [Config.WHISPER_CLI_PATH, "-m", Config.WHISPER_MODEL_PATH,
                 "-f", wav, "-l", "en", "-nt", "-otxt", "-of", prefix, "-t", "2"],
                check=True, capture_output=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            raise TranscriptionError("Transcription timed out. Try a shorter clip.")
        except subprocess.CalledProcessError as e:
            log.error("whisper-cli failed: %s", (e.stderr or b"").decode("utf-8", "ignore")[:500])
            raise TranscriptionError("Transcription failed.")

        txt_path = prefix + ".txt"
        if not os.path.isfile(txt_path):
            raise TranscriptionError("Transcription produced no output.")
        with open(txt_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read().strip()

    return text
