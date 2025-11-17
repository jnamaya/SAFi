"""
Mixin for Text-to-Speech (TTS) functionality.
"""
from __future__ import annotations
from typing import Optional
from pathlib import Path
import hashlib
import logging

# We import these types locally within the function to avoid
# circular dependencies and keep the top-level clean.
# The main SAFi class is expected to have 'self.gemini_client', etc.


class TtsMixin:
    """Mixin for Text-to-Speech functionality."""

    def generate_speech_audio(self, text: str) -> Optional[bytes]:
        """
        Generates MP3 audio for the given text using the configured TTS provider.
        Supports OpenAI and Gemini.
        Returns the audio content as bytes, or None on failure.
        """
        
        # These attributes are expected to be on the main 'SAFi' class instance
        tts_model = self.config.TTS_MODEL
        cache_dir = self.config.TTS_CACHE_DIR
        tts_voice = ""
        log = self.log # Get logger from self
        
        # Determine provider and voice
        if tts_model.startswith("gemini-"):
            provider = "gemini"
            # This should be config.GEMINI_TTS_VOICE if it exists, or a default
            tts_voice = getattr(self.config, "GEMINI_TTS_VOICE", "Puck") 
        elif tts_model.startswith("gpt-"):
            provider = "openai"
            tts_voice = self.config.TTS_VOICE # Uses the default "alloy"
        else:
            log.error(f"Unsupported TTS_MODEL defined in config: {tts_model}")
            return None

        # 1. Create a unique cache key (hash of text + model + voice)
        cache_key_data = f"{text}|{tts_model}|{tts_voice}"
        cache_hash = hashlib.sha256(cache_key_data.encode('utf-8')).hexdigest()
        cache_path = Path(cache_dir) / f"{cache_hash}.mp3"
        
        # 2. Check Cache
        if cache_path.exists():
            try:
                with open(cache_path, "rb") as f:
                    log.info(f"TTS Cache hit for text: {text[:30]}...")
                    return f.read()
            except IOError as e:
                log.error(f"Failed to read cached MP3 file {cache_path}: {e}")
                # Continue to re-generate if reading fails

        log.info(f"TTS Cache miss for text: {text[:30]}... Calling {provider} API.")

        # 3. Generate Audio via API
        try:
            # Ensure the cache directory exists before writing
            Path(cache_dir).mkdir(parents=True, exist_ok=True)
            
            audio_content = None

            if provider == "openai":
                if not self.openai_client_sync:
                    log.error("OpenAI synchronous client not initialized. Cannot use OpenAI TTS.")
                    return None
                
                response = self.openai_client_sync.audio.speech.create(
                    model=tts_model,
                    voice=tts_voice,
                    input=text,
                    response_format="mp3"
                )
                audio_content = response.content

            elif provider == "gemini":
                if not self.gemini_client:
                    log.error("Gemini client not initialized. Cannot use Gemini TTS.")
                    return None
                
                # Import types locally
                from google.generativeai import types as genai_types
                from google.generativeai import SpeechConfig, VoiceConfig, PrebuiltVoiceConfig

                response = self.gemini_client(model_name=tts_model).generate_content(
                   contents=f"Speak the following text: {text}",
                   generation_config=genai_types.GenerationConfig(
                      response_modalities=["AUDIO"],
                      speech_config=SpeechConfig(
                         voice_config=VoiceConfig(
                            prebuilt_voice_config=PrebuiltVoiceConfig(
                               voice_name=tts_voice,
                            )
                         )
                      ),
                   )
                )
                
                # Check if audio content is present
                if not response.candidates[0].content.parts[0].inline_data.data:
                    raise Exception("Gemini API did not return audio data.")
                
                audio_content = response.candidates[0].content.parts[0].inline_data.data

            # 4. Save to Cache and return content
            if audio_content:
                with open(cache_path, "wb") as f:
                    f.write(audio_content)
                
                log.info(f"TTS audio saved to cache: {cache_path}")
                return audio_content
            else:
                raise Exception("Audio content was empty after API call.")

        except Exception as e:
            log.error(f"{provider} TTS API call failed: {e}")
            return None