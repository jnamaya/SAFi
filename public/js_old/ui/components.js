// js/ui/components.js
// Manages self-contained UI components like modals and toasts.

import { elements } from './dom.js';

let activeToast = null;

export function showToast(message, type = 'info', duration = 3000) {
  const toastContainer = elements.toastContainer();
  if (!toastContainer) return;
  if (activeToast) activeToast.remove();

  const toast = document.createElement('div');
  const colors = { info: 'bg-blue-500', success: 'bg-green-600', error: 'bg-red-600' };
  toast.className = `toast text-white px-4 py-2 rounded-lg shadow-lg ${colors[type]}`;
  toast.textContent = message;
  toastContainer.appendChild(toast);
  activeToast = toast;

  setTimeout(() => toast.classList.add('show'), 10);
  setTimeout(() => {
    toast.classList.remove('show');
    toast.addEventListener('transitionend', () => toast.remove());
    if (activeToast === toast) activeToast = null;
  }, duration);
}

function renderConscienceHeader(container, payload) {
  const name = payload.profile || 'Current value set';
  const chips = (payload.values || []).map(v => `<span class="px-2 py-1 rounded-full border text-sm">${v.value} <span class="text-neutral-500">(${Math.round((v.weight || 0) * 100)}%)</span></span>`).join(' ');
  let scoreHtml = '';
  if (payload.spirit_score !== null && payload.spirit_score !== undefined) {
    const score = Math.max(1, Math.min(10, payload.spirit_score));
    const scorePercentage = (score - 1) / 9 * 100;
    scoreHtml = `<div class="rounded-lg border p-3 my-4">
        <div class="flex items-center justify-between mb-1"><div class="text-sm font-semibold">Alignment Score</div><div class="text-lg font-bold">${score}/10</div></div>
        <div class="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-2.5"><div class="bg-emerald-500 h-2.5 rounded-full" style="width: ${scorePercentage}%"></div></div>
      </div>`;
  }
  container.innerHTML = `<div class="mb-4"><div class="text-xs uppercase">Value Set:</div><div class="text-base font-semibold">${name}</div><div class="mt-2 flex flex-wrap gap-2">${chips || '—'}</div></div>${scoreHtml}`;
}

function renderConscienceLedger(container, ledger) {
  const html = (ledger || []).map(row => {
    const s = Number(row.score ?? 0);
    const bucket = s > 0 ? 'uphold' : s < 0 ? 'conflict' : 'neutral';
    const tone = {
      uphold: { icon: '▲', pill: 'text-green-700 bg-green-50', title: 'text-green-700', label: 'Upholds' },
      conflict: { icon: '▼', pill: 'text-red-700 bg-red-50', title: 'text-red-700', label: 'Conflicts with' },
      neutral: { icon: '•', pill: 'text-neutral-600 bg-neutral-100', title: 'text-neutral-800', label: 'Neutral on' }
    }[bucket];
    return `<div class="rounded-lg border p-3 mb-3">
        <div class="flex items-center gap-2 mb-1"><span class="inline-flex items-center justify-center w-5 h-5 rounded-full ${tone.pill} text-xs">${tone.icon}</span><div class="font-semibold ${tone.title}">${tone.label} ${row.value}</div></div>
        <div class="text-sm">${DOMPurify.sanitize(String(row.reason || ''))}</div>
      </div>`;
  }).join('');
  container.insertAdjacentHTML('beforeend', html || '<div class="text-sm">No ledger available.</div>');
}


export function showModal(kind, data) {
    const backdrop = elements.modalBackdrop();
    if (!backdrop) return;
    
    if (kind === 'conscience') {
        const payload = data || { ledger: [], profile: null, values: [], spirit_score: null };
        const box = elements.conscienceDetails();
        if (!box) return;

        box.innerHTML = '';
        renderConscienceHeader(box, payload);
        renderConscienceLedger(box, payload.ledger);
        elements.conscienceModal()?.classList.remove('hidden');
    } else if (kind === 'delete') {
        elements.deleteAccountModal()?.classList.remove('hidden');
    }
    backdrop.classList.remove('hidden');
}

export function closeModal() {
  elements.modalBackdrop()?.classList.add('hidden');
  elements.conscienceModal()?.classList.add('hidden');
  elements.deleteAccountModal()?.classList.add('hidden');
}
