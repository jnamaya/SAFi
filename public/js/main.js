import * as api from './api.js';
import * as ui from './ui.js';
import * as utils from './utils.js';

let currentConversationId = null;
const msgCountByConvo = {};

function getMsgCount(id) { return msgCountByConvo[id] ?? 0; }
function bumpMsgCount(id) { msgCountByConvo[id] = getMsgCount(id) + 1; }

async function checkLoginStatus() {
    const me = await api.getMe();
    const user = (me?.ok && me.user) ? me.user : (me?.user || me);
    
    ui.updateUIForAuthState(user, handleLogout);
    
    if (user) {
        await loadConversations();
    }
    
    const isOnline = await api.checkConnection();
    ui.updateConnectionStatus(isOnline);
}

async function loadConversations() {
    try {
        const conversations = await api.fetchConversations();
        ui.elements.convoList.innerHTML = '';
        if (conversations?.length > 0) {
            conversations.forEach(convo => ui.renderConversationLink(convo, switchConversation, showOptionsMenu));
            await switchConversation(conversations[0].id);
        } else {
            await startNewConversation();
        }
        ui.updateConnectionStatus(true);
    } catch (error) {
        console.error('Failed to load conversations:', error);
        ui.showToast('Failed to load conversations.', 'error');
        ui.updateConnectionStatus(false);
    }
}

async function startNewConversation() {
    try {
        await api.createNewConversation();
        await loadConversations();
    } catch (error) {
        console.error('Failed to create new conversation:', error);
        ui.showToast('Could not start a new chat.', 'error');
    }
}

async function switchConversation(id) {
    currentConversationId = id;
    ui.setActiveConvoLink(id);
    ui.resetChatView();

    try {
        const history = await api.fetchHistory(id);
        
        if (history?.length > 0) {
            history.forEach((turn, i) => {
                const date = turn.timestamp ? new Date(turn.timestamp) : utils.getOrInitTimestamp(id, i, turn.role, turn.content);
                ui.displayMessage(turn.role, turn.content, date, null, (ledger) => ui.showModal('conscience', ledger));
            });
        } else {
            // In a real app, you would fetch this from your API.
            const mockActiveProfile = {
                name: 'Default Ethical Framework',
                values: ['Beneficence', 'Non-maleficence', 'Autonomy', 'Justice']
            };
            ui.displayEmptyState(mockActiveProfile);
        }
        
        msgCountByConvo[id] = history?.length || 0;
        ui.scrollToBottom();
    } catch (error) {
        console.error('Failed to switch conversation:', error);
        ui.showToast('Could not load chat history.', 'error');
        ui.displayEmptyState();
    }
}

async function sendMessage() {
    const userMessage = ui.elements.messageInput.value.trim();
    if (!userMessage || !currentConversationId) return;
    
    const now = new Date();
    ui.displayMessage('user', userMessage, now);
    utils.setTimestamp(currentConversationId, getMsgCount(currentConversationId), 'user', userMessage, now);
    bumpMsgCount(currentConversationId);

    const originalMessage = ui.elements.messageInput.value;
    ui.elements.messageInput.value = '';
    autoSize();
    ui.elements.sendButton.disabled = true;
    const loadingIndicator = ui.showLoadingIndicator();

    try {
        const aiResponse = await api.processUserMessage(userMessage, currentConversationId);
        loadingIndicator.remove();
        
        const aiNow = new Date();
        const consciencePayload = {
          ledger: aiResponse.conscienceLedger || [],
          profile: aiResponse.activeProfile || null,
          values: aiResponse.activeValues || []
        };

        ui.displayMessage(
          'ai',
          aiResponse.finalOutput,
          aiNow,
          consciencePayload,
          (payload) => ui.showModal('conscience', payload)
        );

        utils.setTimestamp(currentConversationId, getMsgCount(currentConversationId), 'ai', aiResponse.finalOutput, aiNow);
        bumpMsgCount(currentConversationId);

        if (aiResponse.newTitle) {
            const link = document.querySelector(`#convo-list div[data-id="${currentConversationId}"] button`);
            if (link) link.textContent = aiResponse.newTitle;
        }
        ui.updateConnectionStatus(true);
    } catch (error) {
        loadingIndicator.remove();
        ui.displayMessage('ai', 'Sorry, an error occurred.', new Date());
        ui.elements.messageInput.value = originalMessage;
        autoSize();
        ui.showToast(error.message || 'An unknown error occurred.', 'error');
        ui.updateConnectionStatus(false);
    } finally {
        ui.elements.sendButton.disabled = false;
        ui.elements.messageInput.focus();
    }
}

function autoSize() {
    ui.elements.messageInput.style.height = 'auto';
    ui.elements.messageInput.style.height = `${Math.min(ui.elements.messageInput.scrollHeight, 200)}px`;
    ui.scrollToBottom();
}

function showOptionsMenu(event, id, title) {
    event.stopPropagation();
    document.querySelector('.options-menu')?.remove();
    const menu = document.createElement('div');
    menu.className = 'options-menu absolute z-50 bg-white dark:bg-neutral-800 rounded-lg shadow-lg border border-neutral-200 dark:border-neutral-700 text-sm py-1';
    menu.style.left = `${event.clientX}px`;
    menu.style.top = `${event.clientY}px`;
    menu.innerHTML = `
        <button class="w-full text-left px-4 py-2 hover:bg-neutral-100 dark:hover:bg-neutral-600" data-action="rename">Rename</button>
        <button class="w-full text-left px-4 py-2 hover:bg-neutral-100 dark:hover:bg-neutral-600" data-action="export">Export</button>
        <button class="w-full text-left px-4 py-2 text-red-600 dark:text-red-500 hover:bg-neutral-100 dark:hover:bg-neutral-600" data-action="delete">Delete</button>`;
    document.body.appendChild(menu);
    menu.addEventListener('click', (e) => {
        const action = e.target.dataset.action;
        if (action === 'rename') handleRename(id, title);
        if (action === 'export') window.open(`${api.urls.CONVERSATIONS}/${id}/export`, '_blank');
        if (action === 'delete') handleDelete(id);
        menu.remove();
    });
    setTimeout(() => document.addEventListener('click', () => menu.remove(), { once: true }), 0);
}

async function handleRename(id, oldTitle) {
    const newTitle = prompt('Enter new name for the conversation:', oldTitle);
    if (newTitle && newTitle.trim() !== oldTitle) {
        await api.renameConversation(id, newTitle);
        await loadConversations();
        ui.showToast('Conversation renamed.', 'success');
    }
}

async function handleDelete(id) {
    if (confirm('Are you sure you want to delete this conversation?')) {
        await api.deleteConversation(id);
        await loadConversations();
        ui.showToast('Conversation deleted.', 'success');
    }
}

async function handleLogout() {
    await fetch(api.urls.LOGOUT, { credentials: 'include' });
    window.location.reload();
}

async function handleDeleteAccount() {
    try {
        await api.deleteAccount();
        ui.showToast('Account deleted successfully.', 'success');
        setTimeout(() => window.location.reload(), 1500);
    } catch (error) {
        ui.showToast(error.message, 'error');
    } finally {
        ui.closeModal();
    }
}

function initializeApp() {
    ui.updateThemeUI();
    checkLoginStatus();
    setInterval(() => api.checkConnection().then(ui.updateConnectionStatus), 60000);

    ui.elements.loginButton.addEventListener('click', () => { window.location.href = api.urls.LOGIN; });
    ui.elements.sendButton.addEventListener('click', sendMessage);
    ui.elements.messageInput.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); } });
    ui.elements.messageInput.addEventListener('input', autoSize);
    ui.elements.newChatButton.addEventListener('click', () => { startNewConversation(); if (window.innerWidth < 768) ui.closeSidebar(); });
    
    ui.elements.themeToggle.addEventListener('click', () => {
        document.documentElement.classList.toggle('dark');
        localStorage.theme = document.documentElement.classList.contains('dark') ? 'dark' : 'light';
        ui.updateThemeUI();
    });
    
    ui.elements.menuToggle.addEventListener('click', ui.openSidebar);
    ui.elements.closeSidebarButton.addEventListener('click', ui.closeSidebar);
    ui.elements.sidebarOverlay.addEventListener('click', ui.closeSidebar);
    ui.elements.closeConscienceModalBtn.addEventListener('click', ui.closeModal);
    ui.elements.cancelDeleteBtn.addEventListener('click', ui.closeModal);
    ui.elements.modalBackdrop.addEventListener('click', ui.closeModal);
    ui.elements.confirmDeleteBtn.addEventListener('click', handleDeleteAccount);
    
    document.querySelectorAll('.example-prompt-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            ui.elements.messageInput.value = btn.textContent.replace(/"/g, '');
            sendMessage();
        });
        btn.className = 'p-3 bg-neutral-100 dark:bg-neutral-800 rounded-lg text-sm text-left hover:bg-neutral-200 dark:hover:bg-neutral-700 transition';
    });
    
    new ResizeObserver(() => { ui.scrollToBottom(); }).observe(ui.elements.composerFooter);
    window.addEventListener('resize', () => { ui.scrollToBottom(); });
}

document.addEventListener('DOMContentLoaded', initializeApp);
