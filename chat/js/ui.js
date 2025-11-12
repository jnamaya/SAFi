// This file focuses on element initialization, visibility control,
// toasts, and other low-level UI helpers.
import * as uiRender from './ui-render.js'; // <-- FIX: Import uiRender here

export let elements = {};
let currentLoadingInterval = null; 
let activeToast = null;
let openDropdown = null;

// Initialization function to run after DOM is loaded
export function _initElements() {
  elements = {
    loginView: document.getElementById('login-view'),
    chatView: document.getElementById('chat-view'),
    controlPanelView: document.getElementById('control-panel-view'),
    controlPanelBackButton: document.getElementById('control-panel-back-btn'),
    cpNavProfile: document.getElementById('cp-nav-profile'),
    cpNavModels: document.getElementById('cp-nav-models'),
    cpNavDashboard: document.getElementById('cp-nav-dashboard'),
    cpNavAppSettings: document.getElementById('cp-nav-app-settings'),
    cpTabProfile: document.getElementById('cp-tab-profile'),
    cpTabModels: document.getElementById('cp-tab-models'),
    cpTabDashboard: document.getElementById('cp-tab-dashboard'),
    cpTabAppSettings: document.getElementById('cp-tab-app-settings'),

    loginButton: document.getElementById('login-button'),
    sidebarContainer: document.getElementById('sidebar-container'),
    chatWindow: document.getElementById('chat-window'),
    messageInput: document.getElementById('message-input'),
    sendButton: document.getElementById('send-button'),
    toastContainer: document.getElementById('toast-container'),
    modalBackdrop: document.getElementById('modal-backdrop'),
    conscienceModal: document.getElementById('conscience-modal'),
    deleteAccountModal: document.getElementById('delete-account-modal'),
    composerFooter: document.getElementById('composer-footer'),
    conscienceDetails: document.getElementById('conscience-details'),
    closeConscienceModalBtn: document.getElementById('close-conscience-modal'),
    
    renameModal: document.getElementById('rename-modal'),
    renameInput: document.getElementById('rename-input'),
    confirmRenameBtn: document.getElementById('confirm-rename-btn'),
    cancelRenameBtn: document.getElementById('cancel-rename-btn'),

    deleteConvoModal: document.getElementById('delete-convo-modal'),
    confirmDeleteConvoBtn: document.getElementById('confirm-delete-convo-btn'),
    cancelDeleteConvoBtn: document.getElementById('cancel-delete-convo-btn'), // <-- This was the typo
    
    activeProfileChip: document.getElementById('active-profile-chip'),
    activeProfileChipMobile: document.getElementById('active-profile-chip-mobile'),
  };
}

// Helper to lazily initialize elements (called by every public function)
export function _ensureElements() {
  if (!elements.loginView) {
    _initElements();
  }
}

// --- VISIBILITY & NAVIGATION HELPERS ---

// --- NEW FUNCTION ---
// Manages the state of the currently open conversation dropdown menu
export function setOpenDropdown(menuElement) {
  _ensureElements();
  closeAllConvoMenus(); // Close any existing one first
  openDropdown = menuElement;
  document.body.appendChild(openDropdown);
}
// --- END NEW FUNCTION ---

export function closeAllConvoMenus() {
  if (openDropdown) {
    openDropdown.remove();
    openDropdown = null;
  }
}

export function openSidebar() {
  _ensureElements();
  document.getElementById('sidebar')?.classList.remove('-translate-x-full');
  document.getElementById('sidebar-overlay')?.classList.remove('hidden');
}

export function closeSidebar() {
  _ensureElements();
  document.getElementById('sidebar')?.classList.add('-translate-x-full');
  document.getElementById('sidebar-overlay')?.classList.add('hidden');
}

// --- LOADING / SCROLLING ---

export function clearLoadingInterval() {
  if (currentLoadingInterval) {
    clearInterval(currentLoadingInterval);
    currentLoadingInterval = null;
  }
}

export function setLoadingInterval(interval) {
    currentLoadingInterval = interval;
}

export function scrollToBottom() {
  _ensureElements();
  window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
}

// --- MODAL / TOAST ---

export function showToast(message, type = 'info', duration = 3000) {
  _ensureElements();
  if (activeToast) activeToast.remove();
  const toast = document.createElement('div');
  const colors = { info: 'bg-blue-500', success: 'bg-green-600', error: 'bg-red-600' };
  toast.className = `toast text-white px-4 py-2 rounded-lg shadow-lg ${colors[type]}`;
  toast.textContent = message;
  elements.toastContainer.appendChild(toast);
  activeToast = toast;
  setTimeout(() => toast.classList.add('show'), 10);
  setTimeout(() => {
    toast.classList.remove('show');
    toast.addEventListener('transitionend', () => toast.remove());
    if (activeToast === toast) activeToast = null;
  }, duration);
}

// This function now relies on ui-render.js to build the content
export function showModal(kind, data) {
  _ensureElements();
  if (kind === 'conscience') {
    // Pass to ui-render to generate content before showing
    uiRender.setupConscienceModalContent(data);
    elements.conscienceModal.classList.remove('hidden');
  } else if (kind === 'delete') {
    elements.deleteAccountModal.classList.remove('hidden');
  } 
  else if (kind === 'rename') {
    if (elements.renameInput) {
        elements.renameInput.value = data.oldTitle;
    }
    elements.renameModal.classList.remove('hidden');
    if (elements.renameInput) {
        elements.renameInput.focus();
        elements.renameInput.select();
    }
  } else if (kind === 'delete-convo') {
    elements.deleteConvoModal.classList.remove('hidden');
  }
  
  elements.modalBackdrop.classList.remove('hidden');
}

export function closeModal() {
  _ensureElements();
  elements.modalBackdrop.classList.add('hidden');
  elements.conscienceModal.classList.add('hidden');
  elements.deleteAccountModal.classList.add('hidden');
  elements.renameModal.classList.add('hidden');
  elements.deleteConvoModal.classList.add('hidden');
}

// Export initial element fetch for use by other modules
_ensureElements();