"""
Mixin for Text-to-Speech (TTS) functionality.
"""
from __future__ import annotations
from typing import Optional
from pathlib import Path
import hashlib
import asyncio
import logging
import time

class TtsMixin:
    """Mixin for Text-to-Speech functionality."""

    def _sweep_tts_cache(self, cache_dir, ttl_days: int):
        """Deletes cached MP3s older than the TTL (data-at-rest hygiene:
        the audio is derived from AI responses). Runs opportunistically on
        cache access — the directory stays small, so a listing is cheap.
        Failures are logged and ignored; the sweep must never break TTS."""
        if ttl_days <= 0:
            return
        cutoff = time.time() - ttl_days * 86400
        try:
            for f in Path(cache_dir).glob("*.mp3"):
                if f.stat().st_mtime < cutoff:
                    f.unlink(missing_ok=True)
        except OSError as e:
            self.log.warning(f"TTS cache sweep failed: {e}")

    def generate_speech_audio(self, text: str) -> Optional[bytes]:
        """
        Generates MP3 audio using Sync clients (safe for background threads).
        """
        tts_model = getattr(self.config, "TTS_MODEL", "edge-tts")
        cache_dir = getattr(self.config, "TTS_CACHE_DIR", "tts_cache")
        log = self.log

        # 1. Determine Provider
        if tts_model == "edge-tts":
            provider = "edge"
        elif tts_model.startswith("gpt-"):
            provider = "openai"
        elif tts_model.startswith("gemini-"):
            provider = "gemini"
        else:
            log.error(f"Unsupported TTS_MODEL: {tts_model}")
            return None

        tts_voice = getattr(self.config, "TTS_VOICE", "en-US-AriaNeural")
        if provider == "gemini":
            tts_voice = getattr(self.config, "GEMINI_TTS_VOICE", "Puck")

        # 2. Check Cache (TTL-bounded; 0 = no disk caching at all)
        ttl_days = getattr(self.config, "TTS_CACHE_TTL_DAYS", 7)
        if Path(cache_dir).is_dir():
            self._sweep_tts_cache(cache_dir, ttl_days)
        cache_hash = hashlib.sha256(f"{text}|{tts_model}|{tts_voice}".encode('utf-8')).hexdigest()
        cache_path = Path(cache_dir) / f"{cache_hash}.mp3"

        if ttl_days > 0 and cache_path.exists():
            try:
                with open(cache_path, "rb") as f: return f.read()
            except IOError: pass

        # 3. Generate
        try:
            Path(cache_dir).mkdir(parents=True, exist_ok=True)
            audio_content = None

            if provider == "edge":
                import edge_tts
                async def _synthesize():
                    communicate = edge_tts.Communicate(text, tts_voice)
                    chunks = []
                    async for chunk in communicate.stream():
                        if chunk["type"] == "audio":
                            chunks.append(chunk["data"])
                    return b"".join(chunks)
                audio_content = asyncio.run(_synthesize())

            elif provider == "openai":
                if not getattr(self, 'openai_client_sync', None):
                    log.error("OpenAI Sync client not available.")
                    return None
                response = self.openai_client_sync.audio.speech.create(
                    model=tts_model, voice=tts_voice, input=text, response_format="mp3"
                )
                audio_content = response.content

            elif provider == "gemini":
                if not getattr(self, 'gemini_client', None):
                    log.error("Gemini client not available.")
                    return None
                from google.generativeai import types as genai_types
                from google.generativeai import SpeechConfig, VoiceConfig, PrebuiltVoiceConfig

                resp = self.gemini_client(model_name=tts_model).generate_content(
                   contents=f"Speak: {text}",
                   generation_config=genai_types.GenerationConfig(
                      response_modalities=["AUDIO"],
                      speech_config=SpeechConfig(voice_config=VoiceConfig(prebuilt_voice_config=PrebuiltVoiceConfig(voice_name=tts_voice)))
                   )
                )
                audio_content = resp.candidates[0].content.parts[0].inline_data.data

            if audio_content:
                if ttl_days > 0:
                    with open(cache_path, "wb") as f: f.write(audio_content)
                return audio_content

        except Exception as e:
            log.error(f"TTS failed: {e}")
            return None