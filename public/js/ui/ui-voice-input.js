import * as api from '../core/api.js';
import * as ui from './ui.js';

let _enabled = false;
let _recorder = null;
let _chunks = [];
let _recording = false;
let _working = false;
let _stream = null;
let _startedAt = 0;

const MIN_MS = 350;

const micBtn = () => document.getElementById('composer-mic-btn');
const sendBtn = () => document.getElementById('send-button');
const input = () => document.getElementById('message-input');

function _hide(el) { el.style.setProperty('display', 'none', 'important'); }
function _show(el) { el.style.setProperty('display', 'flex', 'important'); }

export function updateComposerButtons() {
    if (!_enabled || _recording || _working) return;
    const mic = micBtn();
    const send = sendBtn();
    if (!mic || !send) return;
    const hasText = (input()?.value || '').trim().length > 0;
    if (hasText) {
        _hide(mic);
        _show(send);
    } else {
        _hide(send);
        _show(mic);
    }
}

function _setMicState(state) {
    const mic = micBtn();
    if (!mic) return;
    mic.classList.remove('is-recording', 'is-working');
    if (state === 'recording') {
        mic.classList.add('is-recording');
        mic.title = 'Release to transcribe';
    } else if (state === 'working') {
        mic.classList.add('is-working');
        mic.title = 'Transcribing...';
    } else {
        mic.title = 'Hold to talk';
    }
}

function _stopStream() {
    if (_stream) {
        _stream.getTracks().forEach(t => t.stop());
        _stream = null;
    }
}

async function _press(e) {
    if (_working || _recording) return;
    if (e.button && e.button !== 0) return;
    e.preventDefault();

    if (!navigator.mediaDevices?.getUserMedia) {
        ui.showToast('This browser cannot record audio.', 'error');
        return;
    }
    try {
        _stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
        ui.showToast('Microphone access was denied.', 'error');
        return;
    }
    if (!_pressHeld) { _stopStream(); return; }

    _chunks = [];
    try {
        _recorder = new MediaRecorder(_stream);
    } catch (err) {
        _stopStream();
        ui.showToast('This browser cannot record audio.', 'error');
        return;
    }
    _recorder.ondataavailable = (ev) => { if (ev.data && ev.data.size) _chunks.push(ev.data); };
    _recorder.onstop = _onStop;
    _recorder.start();
    _recording = true;
    _startedAt = Date.now();
    _setMicState('recording');
}

function _release() {
    if (_recording && _recorder) {
        _recording = false;
        try { _recorder.stop(); } catch (e) {   }
    }
}

async function _onStop() {
    _stopStream();
    const tooShort = (Date.now() - _startedAt) < MIN_MS;
    const blob = new Blob(_chunks, { type: _chunks[0]?.type || 'audio/webm' });
    _chunks = [];
    if (tooShort || !blob.size) {
        _setMicState('idle');
        updateComposerButtons();
        return;
    }
    _working = true;
    _setMicState('working');
    try {
        const res = await api.transcribeAudio(blob);
        const text = (res && res.text || '').trim();
        if (!text) {
            ui.showToast('No speech was detected.', 'warning');
        } else {
            _fillComposer(text);
        }
    } catch (err) {
        ui.showToast(err.message || 'Transcription failed.', 'error');
    } finally {
        _working = false;
        _setMicState('idle');
        updateComposerButtons();
    }
}

function _fillComposer(text) {
    const el = input();
    if (!el) return;
    el.value = text;
    el.dispatchEvent(new Event('input', { bubbles: true }));
}

let _pressHeld = false;

export async function initVoiceInput() {
    const mic = micBtn();
    if (!mic) return;

    let cfg = {};
    try { cfg = await api.getAppConfig(); } catch (e) { cfg = {}; }
    if (!cfg.voice_input_enabled) return;

    _enabled = true;
    mic.classList.remove('hidden');

    mic.addEventListener('pointerdown', (e) => { _pressHeld = true; _press(e); });
    window.addEventListener('pointerup', () => { if (_pressHeld) { _pressHeld = false; _release(); } });
    mic.addEventListener('pointercancel', () => { _pressHeld = false; _release(); });
    mic.addEventListener('contextmenu', (e) => e.preventDefault());

    input()?.addEventListener('input', updateComposerButtons);

    updateComposerButtons();
}
