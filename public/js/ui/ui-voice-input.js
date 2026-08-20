/**
 * Voice input (backlog 74), press-and-hold.
 *
 * Governed by transcribe-then-govern: we record audio, send it to
 * /api/audio/transcribe, and the returned TEXT flows through the normal pipeline
 * exactly like a typed prompt. Raw audio never reaches a model.
 *
 * UX: when voice is enabled and the composer is empty, the mic occupies the send
 * button's slot. Hold it to record, release to transcribe and auto-send. The
 * moment the user types anything, the send button takes the slot back, so typing
 * always beats voice. When the deployment has voice off, none of this runs and
 * the send button behaves exactly as before.
 */
import * as api from '../core/api.js';
import * as ui from './ui.js';

let _enabled = false;
let _recorder = null;
let _chunks = [];
let _recording = false;
let _working = false;
let _stream = null;
let _startedAt = 0;

const MIN_MS = 350;   // ignore an accidental tap that records almost nothing

const micBtn = () => document.getElementById('composer-mic-btn');
const sendBtn = () => document.getElementById('send-button');
const input = () => document.getElementById('message-input');

/** Show the mic in the send slot when the composer is empty; show send when the
 * user has typed. No-op unless voice is enabled. Left alone while recording or
 * transcribing so the button does not flip out from under the user's finger. */
// styles.css carries `#send-button { display: flex !important }`, and an
// !important author rule beats a plain inline style, so hiding the send button
// needs inline !important too. Anything less silently leaves both buttons up.
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
    // 'idle' | 'recording' | 'working'
    const mic = micBtn();
    if (!mic) return;
    // The mic sits in the send button's green circle, so state is carried by
    // background classes (styles.css), not a text colour that would be invisible.
    mic.classList.remove('is-recording', 'is-working');
    if (state === 'recording') {
        mic.classList.add('is-recording');
        mic.title = 'Release to send';
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
    // Only the primary button / a touch, and never while transcribing.
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
    // The user may have released before permission resolved.
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
        _recording = false;           // stop() is async; block re-entry now
        try { _recorder.stop(); } catch (e) { /* onstop still fires */ }
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
            _fillAndSend(text);
        }
    } catch (err) {
        ui.showToast(err.message || 'Transcription failed.', 'error');
    } finally {
        _working = false;
        _setMicState('idle');
        updateComposerButtons();
    }
}

/** Put the transcript into the composer and send it. The send button owns the
 * actual send path (agent + user context), so we surface it and click it rather
 * than duplicate that logic here. */
function _fillAndSend(text) {
    const el = input();
    if (!el) return;
    el.value = text;
    el.dispatchEvent(new Event('input', { bubbles: true }));   // enable + reveal send
    const send = sendBtn();
    const mic = micBtn();
    if (mic) _hide(mic);
    if (send) _show(send);
    send?.click();
    // After the send flow clears the input, restore the mic for the next turn.
    setTimeout(updateComposerButtons, 120);
}

// Track hold state across the async getUserMedia gap.
let _pressHeld = false;

/** Wire the mic button and the mic/send swap. Only runs where voice is enabled. */
export async function initVoiceInput() {
    const mic = micBtn();
    if (!mic) return;

    let cfg = {};
    try { cfg = await api.getAppConfig(); } catch (e) { cfg = {}; }
    if (!cfg.voice_input_enabled) return;   // feature off: mic stays hidden, send as usual

    _enabled = true;
    mic.classList.remove('hidden');   // visibility is driven by inline display now

    // Press and hold to talk. pointerdown starts; a pointerup anywhere ends it,
    // so releasing off the button still stops cleanly.
    mic.addEventListener('pointerdown', (e) => { _pressHeld = true; _press(e); });
    window.addEventListener('pointerup', () => { if (_pressHeld) { _pressHeld = false; _release(); } });
    mic.addEventListener('pointercancel', () => { _pressHeld = false; _release(); });
    mic.addEventListener('contextmenu', (e) => e.preventDefault());   // no long-press menu

    // Typing beats voice: swap to send as soon as there is text.
    input()?.addEventListener('input', updateComposerButtons);

    updateComposerButtons();   // initial: empty composer shows the mic
}
