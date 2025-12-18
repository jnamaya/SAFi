// This file focuses on element initialization, visibility control,
// toasts, and other low-level UI helpers.
import * as uiSettingsModals from './ui-settings-modals.js';

export let elements = {};
let currentLoadingInterval = null;
let activeToast = null;
let openDropdown = null;

// --- Sidebar State ---
export let isSidebarOpen = false; // Exported for use by toggle buttons

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
    cpNavMyProfile: document.getElementById('cp-nav-my-profile'),
    cpNavGovernance: document.getElementById('cp-nav-governance'),
    cpNavOrganization: document.getElementById('cp-nav-organization'), // NEW

    cpTabProfile: document.getElementById('cp-tab-profile'),
    cpTabModels: document.getElementById('cp-tab-models'),
    cpTabDashboard: document.getElementById('cp-tab-dashboard'),
    cpTabAppSettings: document.getElementById('cp-tab-app-settings'),
    cpTabMyProfile: document.getElementById('cp-tab-my-profile'),
    cpTabGovernance: document.getElementById('cp-tab-governance'),
    cpTabOrganization: document.getElementById('cp-tab-organization'), // NEW

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
    
    agentSelectorBtn: document.getElementById('agent-selector-btn'),
    agentSelectorDropdown: document.getElementById('agent-selector-dropdown'),
    agentSelectorContainer: document.getElementById('agent-selector-container'),

    renameModal: document.getElementById('rename-modal'),
    renameInput: document.getElementById('rename-input'),
    confirmRenameBtn: document.getElementById('confirm-rename-btn'),
    cancelRenameBtn: document.getElementById('cancel-rename-btn'),

    deleteConvoModal: document.getElementById('delete-convo-modal'),
    confirmDeleteConvoBtn: document.getElementById('confirm-delete-convo-btn'),
    cancelDeleteConvoBtn: document.getElementById('cancel-delete-convo-btn'),

    activeProfileChip: document.getElementById('active-profile-chip'),
    activeProfileChipMobile: document.getElementById('active-profile-chip-mobile'),

    profileModal: document.getElementById('profile-details-modal'),
    profileModalContent: document.getElementById('profile-details-content'),

    sidebarElement: null, // Initialized later in open/close functions
    sidebarOverlay: null, // Initialized later
    // Note: We keep the reference but stop toggling its visibility class
    menuToggleButton: document.getElementById('menu-toggle'),
  };
}

// Helper to lazily initialize elements (called by every public function)
export function _ensureElements() {
  if (!elements.loginView) {
    _initElements();
  }
}

// --- VISIBILITY & NAVIGATION HELPERS ---

export function setOpenDropdown(menuElement) {
  _ensureElements();
  closeAllConvoMenus(); // Close any existing one first
  openDropdown = menuElement;
  document.body.appendChild(openDropdown);
}

export function closeAllConvoMenus() {
  if (openDropdown) {
    openDropdown.remove();
    openDropdown = null;
  }
}

let hideSidebarTimeout = null;

function updateSidebarState(open) {
  _ensureElements();
  elements.sidebarElement = document.getElementById('sidebar');
  elements.sidebarOverlay = document.getElementById('sidebar-overlay');

  if (!elements.sidebarElement || !elements.sidebarOverlay) return;

  // Clear any pending hide timeout
  if (hideSidebarTimeout) {
    clearTimeout(hideSidebarTimeout);
    hideSidebarTimeout = null;
  }

  // Reset inline transform property for CSS classes to take over transitions
  elements.sidebarElement.style.transform = '';

  if (open) {
    // 1. Make it visible immediately so the slide-in transition can occur
    elements.sidebarElement.classList.remove('hidden');

    // FIX: Force flex display so flex-col and flex-1 work on mobile, pushing footer down
    elements.sidebarElement.classList.add('flex');

    // 2. Apply positioning classes
    elements.sidebarElement.classList.remove('-translate-x-full');
    elements.sidebarElement.classList.remove('w-72');
    elements.sidebarElement.classList.add('w-full');
    elements.sidebarOverlay.classList.remove('hidden');

    // Fade in overlay
    setTimeout(() => {
      elements.sidebarOverlay.classList.remove('opacity-0');
    }, 10);

    isSidebarOpen = true;

  } else {
    // 1. Apply off-screen translation
    elements.sidebarElement.classList.add('-translate-x-full');

    // FIX: Do NOT remove w-full immediately. Let it transition out at full width.
    // elements.sidebarElement.classList.remove('w-full');
    // elements.sidebarElement.classList.add('w-72');

    // Fade out overlay
    elements.sidebarOverlay.classList.add('opacity-0');

    // Hide overlay completely after fade
    setTimeout(() => {
      if (!isSidebarOpen) {
        elements.sidebarOverlay.classList.add('hidden');
      }
    }, 300);

    isSidebarOpen = false;

    // 2. Hide the element completely after the transition (300ms duration in CSS)
    hideSidebarTimeout = setTimeout(() => {
      if (!isSidebarOpen) {
        elements.sidebarElement.classList.add('hidden');

        // FIX: Remove flex so it returns to default hidden state safely
        elements.sidebarElement.classList.remove('flex');

        // FIX: Reset width ONLY after it is hidden to prepare for next open/desktop
        elements.sidebarElement.classList.remove('w-full');
        elements.sidebarElement.classList.add('w-72');
      }
    }, 350);
  }
}

export function openSidebar() {
  updateSidebarState(true);
}

export function closeSidebar() {
  updateSidebarState(false);
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
  const chatWindow = elements.chatWindow;

  if (chatWindow) {
    requestAnimationFrame(() => {
      const behavior = window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth';
      chatWindow.scrollTo({
        top: chatWindow.scrollHeight,
        behavior: behavior
      });
      setTimeout(() => {
        chatWindow.scrollTo({ top: chatWindow.scrollHeight, behavior: 'auto' });
      }, 150);
    });
  }
}

// --- MODAL / TOAST ---

const Cap = typeof window !== "undefined" ? window.Capacitor : null;
const isNative = !!(Cap && Cap.isNativePlatform && Cap.isNativePlatform());
const Toast = Cap?.Plugins?.Toast;

export async function showToast(message, type = 'info', duration = 3000) {
  _ensureElements();

  try {
    if (isNative && Toast && typeof Toast.show === 'function') {
      let capDuration = duration <= 2000 ? 'short' : 'long';
      await Toast.show({ text: message, duration: capDuration });
      return;
    }
  } catch (e) {
    console.warn('Native Toast failed:', e);
  }

  if (activeToast) activeToast.remove();
  const toast = document.createElement('div');
  const colors = { info: 'bg-blue-500', success: 'bg-green-600', error: 'bg-red-600' };
  toast.className = `toast text-white px-4 py-2 rounded-lg shadow-lg ${colors[type]} cursor-default`;
  toast.textContent = message;
  elements.toastContainer.appendChild(toast);
  activeToast = toast;

  setTimeout(() => toast.classList.add('show'), 10);

  setTimeout(() => {
    toast.classList.remove('show');
    toast.addEventListener('transitionend', function handler() {
      toast.removeEventListener('transitionend', handler);
      toast.remove();
    });
    if (activeToast === toast) activeToast = null;
  }, duration);
}


export function showModal(kind, data) {
  _ensureElements();
  if (kind === 'conscience') {
    uiSettingsModals.setupConscienceModalContent(data);
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
  else if (kind === 'profile') {
    elements.profileModal.classList.remove('hidden');
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

  if (elements.profileModal) {
    elements.profileModal.classList.add('hidden');
  }
}

_ensureElements();