// js/ui/dom.js
// Contains DOM element selectors and functions for direct DOM manipulation.

export const elements = {
  chatView: () => document.getElementById('chat-view'),
  sidebarContainer: () => document.getElementById('sidebar-container'),
  chatWindow: () => document.getElementById('chat-window'),
  messageInput: () => document.getElementById('message-input'),
  sendButton: () => document.getElementById('send-button'),
  chatTitle: () => document.getElementById('chat-title'),
  emptyState: () => document.getElementById('empty-state'),
  activeProfileDisplay: () => document.getElementById('active-profile-display'),
  toastContainer: () => document.getElementById('toast-container'),
  modalBackdrop: () => document.getElementById('modal-backdrop'),
  conscienceModal: () => document.getElementById('conscience-modal'),
  deleteAccountModal: () => document.getElementById('delete-account-modal'),
  composerFooterUser: () => document.getElementById('composer-footer-user'),
  composerFooterGuest: () => document.getElementById('composer-footer-guest'),
  closeConscienceModalBtn: () => document.getElementById('close-conscience-modal'),
  cancelDeleteBtn: () => document.getElementById('cancel-delete-btn'),
  confirmDeleteBtn: () => document.getElementById('confirm-delete-btn'),
  conscienceDetails: () => document.getElementById('conscience-details'),
  menuToggle: () => document.getElementById('menu-toggle'),
  convoList: () => document.getElementById('convo-list'),
  settingsMenu: () => document.getElementById('settings-menu'),
  settingsDropdown: () => document.getElementById('settings-dropdown'),
};

export function openSidebar() {
  document.getElementById('sidebar')?.classList.remove('-translate-x-full');
  document.getElementById('sidebar-overlay')?.classList.remove('hidden');
}

export function closeSidebar() {
  document.getElementById('sidebar')?.classList.add('-translate-x-full');
  document.getElementById('sidebar-overlay')?.classList.add('hidden');
}

export function resetChatView() {
  const chatWindow = elements.chatWindow();
  if (!chatWindow) return;
  
  // Clear everything except the empty state template
  Array.from(chatWindow.children).forEach(child => {
    if (child.id !== 'empty-state') child.remove();
  });
  
  const activeProfileDisplay = elements.activeProfileDisplay();
  if (activeProfileDisplay) activeProfileDisplay.innerHTML = '';
  
  const emptyState = elements.emptyState();
  if(emptyState) emptyState.classList.add('hidden');
}

export function setActiveConvoLink(id) {
  document.querySelectorAll('#convo-list > a').forEach(link => {
    const isActive = link.dataset.id === String(id);
    link.classList.toggle('bg-green-100', isActive);
    link.classList.toggle('dark:bg-green-900/50', isActive);
    link.classList.toggle('text-green-800', isActive);
    link.classList.toggle('dark:text-green-300', isActive);
    link.classList.toggle('font-medium', isActive);
  });
}

export function scrollToBottom() {
  window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
}

