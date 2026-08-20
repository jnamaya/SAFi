/**
 * Voice input (backlog 74). Governed by transcribe-then-govern: we record audio,
 * send it to /api/audio/transcribe, and drop the returned TEXT into the composer.
 * The user reviews it and sends it like any typed prompt, so the transcript is
 * what the pipeline governs and audits. Raw audio never reaches a model.
 *
 * The mic button stays hidden unless /api/app-config reports voice_input_enabled,
 * so a deployment with the feature off (the default) shows nothing.
 */
import * as api from '../core/api.js';
import * as ui from './ui.js';

let _mediaRecorder = null;
let _chunks = [];
let _recording = false;
let _stream = null;

function _micBtn() {
    return document.getElementById('composer-mic-btn');
}

function _setState(state) {
    // state: 'idle' | 'recording' | 'working'
    const btn = _micBtn();
    if (!btn) return;
    btn.classList.remove('text-red-500', 'animate-pulse', 'opacity-60', 'cursor-not-allowed');
    btn.disabled = false;
    if (state === 'recording') {
        btn.classList.add('text-red-500', 'animate-pulse');
        btn.title = 'Stop recording';
        btn.setAttribute('aria-label', 'Stop recording');
    } else if (state === 'working') {
        btn.classList.add('opacity-60', 'cursor-not-allowed');
        btn.disabled = true;
        btn.title = 'Transcribing...';
    } else {
        btn.title = 'Record voice input';
        btn.setAttribute('aria-label', 'Record voice input');
    }
}

function _insertText(text) {
    const input = document.getElementById('message-input');
    if (!input || !text) return;
    const existing = input.value.trim();
    input.value = existing ? `${existing} ${text}` : text;
    // Let the composer's own handlers run: autosize the textarea and enable send.
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.focus();
}

async function _start() {
    if (!navigator.mediaDevices?.getUserMedia) {
        ui.showToast('This browser cannot record audio.', 'error');
        return;
    }
    try {
        _stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
        ui.showToast('Microphone access was denied.', 'error');
        return;
    }
    _chunks = [];
    // Let the browser pick a container it supports (webm/opus on Chrome/Firefox,
    // mp4 on Safari); ffmpeg on the server normalizes whatever arrives.
    try {
        _mediaRecorder = new MediaRecorder(_stream);
    } catch (e) {
        _mediaRecorder = null;
    }
    if (!_mediaRecorder) {
        _stopStream();
        ui.showToast('This browser cannot record audio.', 'error');
        return;
    }
    _mediaRecorder.ondataavailable = (ev) => { if (ev.data && ev.data.size) _chunks.push(ev.data); };
    _mediaRecorder.onstop = _onStop;
    _mediaRecorder.start();
    _recording = true;
    _setState('recording');
}

function _stopStream() {
    if (_stream) {
        _stream.getTracks().forEach(t => t.stop());
        _stream = null;
    }
}

async function _onStop() {
    _recording = false;
    _stopStream();
    const blob = new Blob(_chunks, { type: _chunks[0]?.type || 'audio/webm' });
    _chunks = [];
    if (!blob.size) { _setState('idle'); return; }
    _setState('working');
    try {
        const res = await api.transcribeAudio(blob);
        if (res && res.text) {
            _insertText(res.text);
        } else {
            ui.showToast('No speech was detected.', 'warning');
        }
    } catch (e) {
        ui.showToast(e.message || 'Transcription failed.', 'error');
    } finally {
        _setState('idle');
    }
}

function _toggle() {
    if (_recording && _mediaRecorder) {
        _mediaRecorder.stop();   // triggers _onStop
    } else if (!_recording) {
        _start();
    }
}

/** Called once at startup. Shows and wires the mic button only if the deployment
 * has voice input enabled. Safe to call when logged out; it just stays hidden. */
export async function initVoiceInput() {
    const btn = _micBtn();
    if (!btn) return;
    let cfg = {};
    try { cfg = await api.getAppConfig(); } catch (e) { cfg = {}; }
    if (!cfg.voice_input_enabled) return;   // feature off: button stays hidden

    btn.classList.remove('hidden');
    btn.classList.add('flex');
    _setState('idle');
    btn.addEventListener('click', (e) => { e.preventDefault(); _toggle(); });
}
