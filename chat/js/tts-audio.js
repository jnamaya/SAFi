// tts-audio.js

import * as ui from './ui.js'; // For access to showToast
import * as api from './api.js'; // Import API for TTS call
import { iconPlay, iconPause, iconLoading } from './ui-render-constants.js'; // Assuming icons are moved to a constants file

// --- GLOBAL STATE FOR AUDIO ---
let audio = null;
let currentPlaybackElement = null; // Stores the button element currently playing

// --- TTS HELPER FUNCTION ---
/**
 * Fetches and plays TTS audio for the given text, managing the playback button state.
 * @param {string} text - The text to speak.
 * @param {HTMLElement} buttonElement - The button element triggering playback.
 */
export async function playSpeech(text, buttonElement) {
    // Case A: A different message's audio is currently active (playing or paused). Stop and reset it.
    if (currentPlaybackElement && currentPlaybackElement !== buttonElement) {
        resetAudioState();
    }
    
    // Set the button element for the current interaction
    currentPlaybackElement = buttonElement;

    // Case 1: Audio exists AND is playing -> PAUSE
    if (audio && !audio.paused) {
        audio.pause();
        buttonElement.innerHTML = iconPlay; // Change icon to Play (Ready to Resume)
        buttonElement.classList.remove('text-green-500', 'animate-pulse');
        return;
    }
    
    // Case 2: Audio exists AND is paused -> RESUME
    if (audio && audio.paused) {
        audio.play().catch(e => {
            console.error("Audio playback failed (resume):", e);
            ui.showToast('Audio playback blocked by browser.', 'error');
            resetAudioState();
        });
        buttonElement.innerHTML = iconPause; // Change icon to Pause (Currently Playing)
        buttonElement.classList.add('text-green-500');
        return;
    }

    // Case 3: No audio loaded yet -> FETCH AND PLAY
    
    // Set loading state
    buttonElement.innerHTML = iconLoading;
    buttonElement.classList.add('text-green-500', 'animate-pulse');

    try {
        ui.showToast('Generating audio...', 'info', 1500);
        const audioBlob = await api.fetchTTSAudio(text);
        
        // Clear any old audio object reference
        if (audio) {
             URL.revokeObjectURL(audio.src);
        }
        
        const audioUrl = URL.createObjectURL(audioBlob);
        audio = new Audio(audioUrl);
        
        audio.oncanplaythrough = () => {
            // Start playback
            audio.play().catch(e => {
                console.error("Audio playback failed (initial):", e);
                ui.showToast('Audio playback blocked by browser.', 'error');
                resetAudioState();
            });
            // Update button to Pause icon
            currentPlaybackElement.innerHTML = iconPause; 
            currentPlaybackElement.classList.remove('animate-pulse');
            currentPlaybackElement.classList.add('text-green-500');
        };

        audio.onended = () => {
            // Audio finished playing
            resetAudioState();
        };

        audio.onerror = (e) => {
            console.error("Audio error:", e);
            ui.showToast('Error playing audio.', 'error');
            resetAudioState();
        };

    } catch (error) {
        console.error('TTS generation failed:', error);
        ui.showToast('TTS service unavailable.', 'error');
        resetAudioState();
    }
}

/**
 * Stops current audio playback and resets the global state and button UI.
 */
export function resetAudioState() {
    if (audio) {
        audio.pause();
        // Clean up the object URL to free memory
        URL.revokeObjectURL(audio.src); 
        audio = null;
    }
    if (currentPlaybackElement) {
        // Reset the button to 'Play' icon
        currentPlaybackElement.innerHTML = iconPlay;
        currentPlaybackElement.classList.remove('text-green-500', 'animate-pulse');
        currentPlaybackElement = null;
    }
}