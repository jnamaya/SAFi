import os
import subprocess
import tempfile
import logging

from ...config import Config

log = logging.getLogger(__name__)


class TranscriptionError(Exception):
    pass


def is_available() -> bool:
    return (
        Config.VOICE_INPUT_ENABLED
        and os.path.isfile(Config.WHISPER_CLI_PATH)
        and os.path.isfile(Config.WHISPER_MODEL_PATH)
    )


def transcribe(audio_bytes: bytes, filename: str) -> str:
    if not Config.VOICE_INPUT_ENABLED:
        raise TranscriptionError("Voice input is disabled on this deployment.")
    if not os.path.isfile(Config.WHISPER_CLI_PATH):
        raise TranscriptionError("The speech-to-text engine is not installed on this deployment.")
    if not os.path.isfile(Config.WHISPER_MODEL_PATH):
        raise TranscriptionError("The speech-to-text model is not installed on this deployment.")

    timeout = Config.WHISPER_TIMEOUT_SECONDS

    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "input")
        wav = os.path.join(d, "audio.wav")
        prefix = os.path.join(d, "out")

        with open(src, "wb") as f:
            f.write(audio_bytes)

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
