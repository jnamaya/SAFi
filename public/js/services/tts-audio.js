// tts-audio.js

import * as api from '../core/api.js';
import { iconPlay, iconLoading } from '../ui/ui-render-constants.js';
import * as ui from '../ui/ui.js';

const MSE_SUPPORTED = (() => {
    try { return typeof MediaSource !== 'undefined' && MediaSource.isTypeSupported('audio/mpeg'); }
    catch { return false; }
})();

const CIRCUMFERENCE = 439.8; // 2π × 70

// --- DOM refs (lazy) ---
let _player, _loading, _controls, _playpause, _playIcon, _pauseIcon;
let _ring, _current, _duration, _closeBtn, _closeLoadingBtn;

function els() {
    if (_player) return;
    _player          = document.getElementById('audio-player');
    _loading         = document.getElementById('audio-player-loading');
    _controls        = document.getElementById('audio-player-controls');
    _playpause       = document.getElementById('audio-player-playpause');
    _playIcon        = document.getElementById('audio-pp-play-icon');
    _pauseIcon       = document.getElementById('audio-pp-pause-icon');
    _ring            = document.getElementById('audio-player-ring');
    _current         = document.getElementById('audio-player-current');
    _duration        = document.getElementById('audio-player-duration');
    _closeBtn        = document.getElementById('audio-player-close');
    _closeLoadingBtn = document.getElementById('audio-player-close-loading');

    _playpause.addEventListener('click', togglePlayPause);
    _closeBtn.addEventListener('click', closePlayer);
    _closeLoadingBtn.addEventListener('click', closePlayer);
}

// --- State ---
let audio = null;
let mediaSource = null;
let currentTriggerBtn = null;
let rafId = null;

// --- Visibility (scale/fade pop) ---
function showPlayer(loadingState) {
    els();
    _loading.classList.toggle('hidden', !loadingState);
    _controls.classList.toggle('hidden', loadingState);
    _player.classList.remove('scale-75', 'opacity-0', 'pointer-events-none');
    _player.classList.add('scale-100', 'opacity-100', 'pointer-events-auto');
}

function hidePlayer() {
    els();
    _player.classList.remove('scale-100', 'opacity-100', 'pointer-events-auto');
    _player.classList.add('scale-75', 'opacity-0', 'pointer-events-none');
}

// --- Time formatting ---
function fmt(s) {
    if (!isFinite(s) || isNaN(s)) return '--:--';
    const m = Math.floor(s / 60);
    return `${m}:${Math.floor(s % 60).toString().padStart(2, '0')}`;
}

// --- Progress ring ---
function startProgressLoop() {
    cancelAnimationFrame(rafId);
    function tick() {
        if (!audio) return;
        updateProgress();
        if (!audio.paused) rafId = requestAnimationFrame(tick);
    }
    rafId = requestAnimationFrame(tick);
}

function updateProgress() {
    if (!audio) return;
    const cur = audio.currentTime;
    const dur = audio.duration;
    const known = isFinite(dur) && dur > 0;
    const pct   = known ? cur / dur : 0;
    _ring.style.strokeDashoffset = CIRCUMFERENCE * (1 - pct);
    _current.textContent  = fmt(cur);
    _duration.textContent = known ? fmt(dur) : '--:--';
}

// --- Controls ---
function togglePlayPause() {
    if (!audio) return;
    if (audio.paused) { audio.play(); setPauseIcon(); startProgressLoop(); }
    else              { audio.pause(); setPlayIcon(); }
}

function setPlayIcon()  { _playIcon.classList.remove('hidden'); _pauseIcon.classList.add('hidden'); }
function setPauseIcon() { _playIcon.classList.add('hidden');    _pauseIcon.classList.remove('hidden'); }

function closePlayer() { resetAudioState(); hidePlayer(); }

function resetTriggerBtn() {
    if (currentTriggerBtn) {
        currentTriggerBtn.innerHTML = iconPlay;
        currentTriggerBtn.classList.remove('text-green-500', 'animate-pulse');
        currentTriggerBtn = null;
    }
}

function startPlayback() {
    showPlayer(false);
    setPauseIcon();
    updateProgress();
    audio.play().catch(() => { ui.showToast('Audio playback blocked by browser.', 'error'); closePlayer(); });
    startProgressLoop();
    resetTriggerBtn();
}

function onEnded() {
    cancelAnimationFrame(rafId);
    setPlayIcon();
    updateProgress();
    resetTriggerBtn();
}

function onAudioError() {
    ui.showToast('Error playing audio.', 'error');
    closePlayer();
}

// --- MSE streaming ---
async function loadStreaming(text) {
    mediaSource = new MediaSource();
    audio = new Audio(URL.createObjectURL(mediaSource));
    audio.addEventListener('ended',          onEnded);
    audio.addEventListener('error',          onAudioError);
    audio.addEventListener('durationchange', updateProgress);

    await new Promise(r => mediaSource.addEventListener('sourceopen', r, { once: true }));

    const sb        = mediaSource.addSourceBuffer('audio/mpeg');
    const waitUpdate = () => new Promise(r => sb.addEventListener('updateend', r, { once: true }));
    const response  = await api.fetchTTSStream(text);
    const reader    = response.body.getReader();
    let started = false;

    while (true) {
        const { done, value } = await reader.read();
        if (done) {
            if (mediaSource && mediaSource.readyState === 'open') mediaSource.endOfStream();
            break;
        }
        if (sb.updating) await waitUpdate();
        sb.appendBuffer(value);
        await waitUpdate();
        if (!started) { started = true; startPlayback(); }
    }
}

// --- Blob fallback ---
async function loadBlob(text) {
    const blob = await api.fetchTTSAudio(text);
    if (audio) URL.revokeObjectURL(audio.src);
    audio = new Audio(URL.createObjectURL(blob));
    audio.addEventListener('ended',          onEnded);
    audio.addEventListener('error',          onAudioError);
    audio.addEventListener('canplaythrough', startPlayback, { once: true });
}

// --- Public ---
export async function playSpeech(text, buttonElement) {
    els();

    if (currentTriggerBtn === buttonElement && audio) { togglePlayPause(); return; }

    resetAudioState();
    currentTriggerBtn = buttonElement;
    buttonElement.innerHTML = iconLoading;
    buttonElement.classList.add('text-green-500', 'animate-pulse');
    showPlayer(true);

    try {
        if (MSE_SUPPORTED) await loadStreaming(text);
        else               await loadBlob(text);
    } catch (err) {
        console.error('TTS failed:', err);
        ui.showToast('TTS service unavailable.', 'error');
        closePlayer();
        resetTriggerBtn();
    }
}

export function resetAudioState() {
    cancelAnimationFrame(rafId);
    if (audio) {
        audio.pause();
        try { URL.revokeObjectURL(audio.src); } catch {}
        audio = null;
    }
    if (mediaSource) {
        try { if (mediaSource.readyState === 'open') mediaSource.endOfStream(); } catch {}
        mediaSource = null;
    }
    resetTriggerBtn();
    if (_ring)     _ring.style.strokeDashoffset = CIRCUMFERENCE;
    if (_current)  _current.textContent  = '0:00';
    if (_duration) _duration.textContent = '--:--';
    if (_playIcon) setPlayIcon();
}
