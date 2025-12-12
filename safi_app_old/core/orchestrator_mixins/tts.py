"""
Mixin for Text-to-Speech (TTS) functionality.
"""
from __future__ import annotations
from typing import Optional
from pathlib import Path
import hashlib
import logging

class TtsMixin:
    """Mixin for Text-to-Speech functionality."""

    def generate_speech_audio(self, text: str) -> Optional[bytes]:
        """
        Generates MP3 audio using Sync clients (safe for background threads).
        """
        tts_model = getattr(self.config, "TTS_MODEL", "gpt-4o-mini-tts")
        cache_dir = getattr(self.config, "TTS_CACHE_DIR", "tts_cache")
        log = self.log 
        
        # 1. Determine Provider
        provider = "openai" if tts_model.startswith("gpt-") else "gemini" if tts_model.startswith("gemini-") else None
        if not provider:
            log.error(f"Unsupported TTS_MODEL: {tts_model}")
            return None

        tts_voice = getattr(self.config, "TTS_VOICE", "alloy") if provider == "openai" else getattr(self.config, "GEMINI_TTS_VOICE", "Puck")

        # 2. Check Cache
        cache_hash = hashlib.sha256(f"{text}|{tts_model}|{tts_voice}".encode('utf-8')).hexdigest()
        cache_path = Path(cache_dir) / f"{cache_hash}.mp3"
        
        if cache_path.exists():
            try:
                with open(cache_path, "rb") as f: return f.read()
            except IOError: pass

        # 3. Generate
        try:
            Path(cache_dir).mkdir(parents=True, exist_ok=True)
            audio_content = None

            if provider == "openai":
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
                with open(cache_path, "wb") as f: f.write(audio_content)
                return audio_content

        except Exception as e:
            log.error(f"TTS failed: {e}")
            return None