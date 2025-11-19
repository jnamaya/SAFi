// This file focuses on element initialization, visibility control,
// toasts, and other low-level UI helpers.
import * as uiSettingsModals from './ui-settings-modals.js'; 

export let elements = {};
let currentLoadingInterval = null; 
let activeToast = null;
let openDropdown = null;

// --- Touch Swipe State for Sidebar ---
let touchStartX = 0;
let touchStartY = 0;
let isSwiping = false;
export let isSidebarOpen = false; // Exported for potential use in other modules
const swipeThreshold = 50; // Minimum horizontal distance to count as a swipe

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
    // --- NEW ---
    cpNavMyProfile: document.getElementById('cp-nav-my-profile'),
    // --- END NEW ---
    cpTabProfile: document.getElementById('cp-tab-profile'),
    cpTabModels: document.getElementById('cp-tab-models'),
    cpTabDashboard: document.getElementById('cp-tab-dashboard'),
    cpTabAppSettings: document.getElementById('cp-tab-app-settings'),
    // --- NEW ---
    cpTabMyProfile: document.getElementById('cp-tab-my-profile'),
    // --- END NEW ---

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
    cancelDeleteConvoBtn: document.getElementById('cancel-delete-convo-btn'),
    
    activeProfileChip: document.getElementById('active-profile-chip'),
    activeProfileChipMobile: document.getElementById('active-profile-chip-mobile'),
    
    profileModal: document.getElementById('profile-details-modal'),
    profileModalContent: document.getElementById('profile-details-content'),
    
    sidebarElement: null, // Initialized later in open/close functions
    sidebarOverlay: null, // Initialized later
    menuToggleButton: document.getElementById('menu-toggle'), // New element reference
  };
}

// Helper to lazily initialize elements (called by every public function)
export function _ensureElements() {
  if (!elements.loginView) {
    _initElements();
  }
}

// --- VISIBILITY & NAVIGATION HELPERS ---

// Manages the state of the currently open conversation dropdown menu
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

// Timeout holder for hiding the sidebar after transition
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
    
    // 2. Apply positioning classes
    elements.sidebarElement.classList.remove('-translate-x-full');
    elements.sidebarElement.classList.remove('w-72'); 
    elements.sidebarElement.classList.add('w-full');
    elements.sidebarOverlay.classList.remove('hidden');
    isSidebarOpen = true;
    
    // 3. Hide the mobile menu toggle button
    if (elements.menuToggleButton) {
        elements.menuToggleButton.classList.add('hidden');
    }
  } else {
    // 1. Apply off-screen translation
    elements.sidebarElement.classList.add('-translate-x-full');
    elements.sidebarElement.classList.remove('w-full');
    elements.sidebarElement.classList.add('w-72');
    elements.sidebarOverlay.classList.add('hidden');
    isSidebarOpen = false;

    // 2. Hide the element completely after the transition (300ms duration in CSS)
    hideSidebarTimeout = setTimeout(() => {
        // Only hide if the sidebar is still marked as closed
        if (!isSidebarOpen) { 
            elements.sidebarElement.classList.add('hidden');
        }
    }, 350); // 50ms buffer after the 300ms CSS transition

    // 3. Show the mobile menu toggle button
    if (elements.menuToggleButton && window.innerWidth < 768) {
        elements.menuToggleButton.classList.remove('hidden');
    }
  }
}

export function openSidebar() {
  updateSidebarState(true);
}

export function closeSidebar() {
  updateSidebarState(false);
}


// --- MOBILE SWIPE GESTURE HANDLERS (for Sidebar) ---

function handleTouchStart(e) {
  // Only track touches on mobile
  if (window.innerWidth >= 768) return;
    
  touchStartX = e.touches[0].clientX;
  touchStartY = e.touches[0].clientY;
  isSwiping = false;
  // If the swipe starts outside the left edge (only for opening)
  // Check if it starts within 10% of the screen width from the left edge
  if (!isSidebarOpen && touchStartX > window.innerWidth * 0.1) {
    return; // Don't track swipe unless near the edge
  }
  
  // CRITICAL: Must remove the 'hidden' class here if it was applied on close
  const sidebar = document.getElementById('sidebar');
  if (sidebar) {
      sidebar.classList.remove('hidden');
      if (hideSidebarTimeout) {
        clearTimeout(hideSidebarTimeout);
        hideSidebarTimeout = null;
      }
  }
  
  // Prevent scrolling to allow the sidebar movement to be tracked precisely
  document.body.style.overflow = 'hidden'; 
}

function handleTouchMove(e) {
  if (!touchStartX || window.innerWidth >= 768) return;

  const currentX = e.touches[0].clientX;
  const currentY = e.touches[0].clientY;
  const diffX = currentX - touchStartX;
  const diffY = currentY - touchStartY;
  
  // Determine if horizontal movement is dominant
  if (Math.abs(diffX) > 10 && Math.abs(diffX) > Math.abs(diffY)) {
      isSwiping = true;
      e.preventDefault(); // Prevent vertical scrolling if horizontal swipe is detected

      const sidebar = document.getElementById('sidebar');
      if (sidebar) {
          let newTranslateX;
          const sidebarWidth = window.innerWidth; 
          
          if (isSidebarOpen) {
              // Closing: Dragging right to left (diffX < 0)
              // Sidebar is open (transform: translateX(0)). New position = drag amount.
              newTranslateX = Math.max(-sidebarWidth, diffX); 
          } else {
              // Opening: Dragging left to right (diffX > 0)
              // Sidebar is closed (transform: translateX(-sidebarWidth)). New position = closed_pos + drag amount.
              newTranslateX = Math.min(0, -sidebarWidth + diffX);
          }
          
          // Disable transition during drag for smoothness
          sidebar.style.transition = 'none';
          sidebar.style.transform = `translateX(${newTranslateX}px)`;
          
          // Update overlay opacity based on progress (0 to 1)
          const progress = Math.abs(newTranslateX) / sidebarWidth;
          const overlay = document.getElementById('sidebar-overlay');
          if (overlay) {
             // Opacity should be 0.75 when open (progress=0), and 0 when closed (progress=1)
             overlay.style.opacity = Math.min(0.75, Math.max(0, 0.75 * (1 - progress))); 
          }
      }
  }
}

function handleTouchEnd(e) {
  if (window.innerWidth >= 768) return;
    
  document.body.style.overflow = ''; // Restore scrolling
  const sidebar = document.getElementById('sidebar');
  if (!sidebar) return;
  
  // Restore CSS transition
  sidebar.style.transition = 'transform 0.3s ease-in-out';
  const overlay = document.getElementById('sidebar-overlay');
  if (overlay) {
    overlay.style.transition = 'opacity 0.3s ease-in-out';
    // Let the CSS class handle opacity for fully open/closed states
    overlay.style.opacity = ''; 
  }
  
  if (!isSwiping) {
    touchStartX = 0;
    return; 
  }

  const endX = e.changedTouches[0].clientX;
  const diffX = endX - touchStartX;
  
  // Get the current translated position
  const currentTranslateXMatch = sidebar.style.transform.match(/translateX\(([-.\d]+)px\)/);
  const currentTranslateX = currentTranslateXMatch ? parseFloat(currentTranslateXMatch[1]) : 0;
  
  const midPoint = -window.innerWidth / 2;

  if (isSidebarOpen) {
    // Closing: If dragged left past the threshold (or dragged past midpoint)
    if (diffX < -swipeThreshold || currentTranslateX < midPoint) {
      closeSidebar();
    } else {
      // Snap open
      openSidebar();
    }
  } else {
    // Opening: If dragged right past the threshold (or dragged past midpoint)
    if (diffX > swipeThreshold || currentTranslateX > midPoint) {
      openSidebar();
    } else {
      // Snap closed (needs to be explicitly set back to -100% via the class)
      closeSidebar();
    }
  }

  touchStartX = 0;
  isSwiping = false;
}

document.addEventListener('DOMContentLoaded', () => {
    // Attach swipe handlers for sidebar on mobile viewport
    if (window.innerWidth < 768) {
        document.addEventListener('touchstart', handleTouchStart, { passive: false });
        document.addEventListener('touchmove', handleTouchMove, { passive: false });
        document.addEventListener('touchend', handleTouchEnd);
        document.addEventListener('touchcancel', handleTouchEnd);
    }
});
// --- END: MOBILE SWIPE GESTURE HANDLERS ---


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

// CRITICAL CHANGE: Scroll the chat window element, not the window
export function scrollToBottom() {
  _ensureElements();
  const chatWindow = elements.chatWindow;
  if (chatWindow) {
      // Scroll the container directly
      chatWindow.scrollTo({ top: chatWindow.scrollHeight, behavior: 'smooth' });
  }
}

// --- MODAL / TOAST ---

// Capacitor Toast logic is handled here for native fallbacks
const Cap = typeof window !== "undefined" ? window.Capacitor : null;
const isNative = !!(Cap && Cap.isNativePlatform && Cap.isNativePlatform());
const Toast = Cap?.Plugins?.Toast;

export async function showToast(message, type = 'info', duration = 3000) {
  _ensureElements();
  
  // Try native Capacitor Toast first
  try {
    if (isNative && Toast && typeof Toast.show === 'function') {
        let capDuration = duration <= 2000 ? 'short' : 'long';
        await Toast.show({ text: message, duration: capDuration });
        return;
    }
  } catch (e) {
    console.warn('Native Toast failed:', e);
  }

  // Fallback DOM toast (FIX: Ensure content and better cleanup)
  if (activeToast) activeToast.remove();
  const toast = document.createElement('div');
  const colors = { info: 'bg-blue-500', success: 'bg-green-600', error: 'bg-red-600' };
  toast.className = `toast text-white px-4 py-2 rounded-lg shadow-lg ${colors[type]} cursor-default`;
  toast.textContent = message; // Set message content
  elements.toastContainer.appendChild(toast);
  activeToast = toast;
  
  // Show the toast immediately after it's added to the DOM
  setTimeout(() => toast.classList.add('show'), 10);
  
  // Hide the toast after duration
  setTimeout(() => {
    toast.classList.remove('show');
    // Ensure the toast is fully removed after transition
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

// Export initial element fetch for use by other modules
_ensureElements();