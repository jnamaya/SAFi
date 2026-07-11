// Conversation Management Logic:chat.js

import * as api from './api.js';
import * as ui from '../ui/ui.js';
import * as uiAuthSidebar from '../ui/ui-auth-sidebar.js';
import * as uiMessages from '../ui/ui-messages.js';
import * as cache from './cache.js'; // Use cache for optimistic updates
// CHANGE: Import the utility function
import { formatRelativeTime } from './utils.js';


// --- CONVERSATION STATE ---
export let currentConversationId = null;
let convoToRename = { id: null, oldTitle: null };
let convoToDelete = null;

// --- PROJECT (WORKSPACE) STATE ---
// `projects` holds the user's project list; `currentProjectId` is the project a
// newly-created chat will be filed under (null = loose / no project).
let projects = [];
let currentProjectId = null;
const EXPANDED_PROJECTS_KEY = 'safi_expanded_projects';

function getExpandedProjects() {
    try {
        return new Set(JSON.parse(localStorage.getItem(EXPANDED_PROJECTS_KEY) || '[]'));
    } catch {
        return new Set();
    }
}

function setProjectExpanded(projectId, expanded) {
    const set = getExpandedProjects();
    if (expanded) set.add(projectId); else set.delete(projectId);
    try { localStorage.setItem(EXPANDED_PROJECTS_KEY, JSON.stringify([...set])); } catch { /* ignore */ }
}

// --- FILE UPLOAD STATE ---
let pendingFiles = [];   // array — supports multiple attachments

/**
 * Initializes the file upload button and hidden input.
 * Each pick appends to pendingFiles so users can add files from multiple dialogs.
 */
export function initFileUpload() {
    const fileInput = document.getElementById('file-upload-input');
    if (!fileInput) return;

    fileInput.addEventListener('change', (e) => {
        const picked = Array.from(e.target.files);
        if (picked.length) {
            pendingFiles.push(...picked);
            _renderFileChips();
        }
        fileInput.value = '';
    });
}

export function triggerFilePicker() {
    document.getElementById('file-upload-input')?.click();
}

/** Returns type-specific colour tokens for the file card. */
function _getFileTypeConfig(filename) {
    const ext = (filename.split('.').pop() || '').toLowerCase();
    const configs = {
        pdf:  { label: 'PDF', bg: 'bg-red-50 dark:bg-red-900/20',       border: 'border-red-200 dark:border-red-800',       text: 'text-red-500' },
        docx: { label: 'DOC', bg: 'bg-blue-50 dark:bg-blue-900/20',      border: 'border-blue-200 dark:border-blue-800',      text: 'text-blue-500' },
        doc:  { label: 'DOC', bg: 'bg-blue-50 dark:bg-blue-900/20',      border: 'border-blue-200 dark:border-blue-800',      text: 'text-blue-500' },
        xlsx: { label: 'XLS', bg: 'bg-green-50 dark:bg-green-900/20',     border: 'border-green-200 dark:border-green-800',     text: 'text-green-600' },
        xls:  { label: 'XLS', bg: 'bg-green-50 dark:bg-green-900/20',     border: 'border-green-200 dark:border-green-800',     text: 'text-green-600' },
        csv:  { label: 'CSV', bg: 'bg-emerald-50 dark:bg-emerald-900/20', border: 'border-emerald-200 dark:border-emerald-800', text: 'text-emerald-500' },
        txt:  { label: 'TXT', bg: 'bg-neutral-100 dark:bg-neutral-700',  border: 'border-neutral-200 dark:border-neutral-600', text: 'text-neutral-500' },
        md:   { label: 'MD',  bg: 'bg-violet-50 dark:bg-violet-900/20',  border: 'border-violet-200 dark:border-violet-800',  text: 'text-violet-500' },
    };
    return configs[ext] || {
        label: ext.toUpperCase() || 'FILE',
        bg: 'bg-neutral-100 dark:bg-neutral-700',
        border: 'border-neutral-200 dark:border-neutral-600',
        text: 'text-neutral-500'
    };
}

function _fmtSize(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Re-renders all pending file chips. Called after any add/remove. */
function _renderFileChips() {
    const chipArea = document.getElementById('file-chip-area');
    if (!chipArea) return;

    if (pendingFiles.length === 0) {
        chipArea.innerHTML = '';
        chipArea.classList.add('hidden');
        if (ui.elements.sendButton && ui.elements.messageInput) {
            ui.elements.sendButton.disabled = ui.elements.messageInput.value.trim().length === 0;
        }
        return;
    }

    const cards = pendingFiles.map((file, i) => {
        const cfg = _getFileTypeConfig(file.name);
        const sizeStr = _fmtSize(file.size);
        return `
        <div class="inline-flex items-center gap-3 pl-2 pr-3 py-2 bg-white dark:bg-neutral-800 rounded-xl border border-neutral-200 dark:border-neutral-700 shadow-sm max-w-[260px] animate-fade-in">
            <div class="flex flex-col items-center justify-center w-9 h-11 rounded-lg shrink-0 border ${cfg.bg} ${cfg.border}">
                <svg class="w-4 h-4 ${cfg.text}" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                          d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
                </svg>
                <span class="text-[9px] font-bold leading-none mt-0.5 ${cfg.text}">${cfg.label}</span>
            </div>
            <div class="flex flex-col min-w-0 flex-1">
                <span class="text-sm font-medium text-neutral-800 dark:text-neutral-100 truncate leading-snug">${file.name}</span>
                <span class="text-xs text-neutral-400 dark:text-neutral-500 mt-0.5">${sizeStr}</span>
            </div>
            <button type="button" class="remove-file-btn shrink-0 p-1 rounded-lg text-neutral-300 dark:text-neutral-600 hover:text-red-500 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
                    data-index="${i}" title="Remove file">
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M6 18L18 6M6 6l12 12"/>
                </svg>
            </button>
        </div>`;
    });

    chipArea.innerHTML = `<div class="flex flex-wrap gap-2">${cards.join('')}</div>`;
    chipArea.classList.remove('hidden');

    chipArea.querySelectorAll('.remove-file-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const idx = parseInt(btn.dataset.index, 10);
            pendingFiles.splice(idx, 1);
            _renderFileChips();
        });
    });

    if (ui.elements.sendButton) ui.elements.sendButton.disabled = false;
}

function _clearAllPendingFiles() {
    pendingFiles = [];
    _renderFileChips();
}

// --- CORE EXPORTED HANDLERS (Fixing ReferenceError) ---
// Moved declarations of handlers here to ensure they are defined before renderConvoList uses them.
export function handleRename(id, oldTitle) {
    convoToRename = { id, oldTitle };
    ui.showModal('rename', { oldTitle });
}

export function handleDelete(id) {
    convoToDelete = id;
    ui.showModal('delete-convo');
}

export async function handleTogglePin(id, isPinned, activeProfileData, user) {
    ui.closeAllConvoMenus();
    const newPinState = !isPinned;
    const oldPinState = isPinned; // Store old state for rollback

    try {
        // 1. Optimistic UI Update (Update local cache instantly)
        // This is done BEFORE the network call to make the change feel instant
        await cache.updateConvoInList(id, { is_pinned: newPinState });

        // 2. Refresh list only to update sidebar order/title without scrolling chat
        await refreshConvoListOnly(activeProfileData, user, ui.showModal);

        // 3. API Call (Sync to server)
        const response = await api.togglePinConversation(id, newPinState);

        if (response === 'QUEUED') {
            ui.showToast(newPinState ? 'Pin queued.' : 'Unpin queued.', 'info');
        } else {
            ui.showToast(newPinState ? 'Conversation pinned.' : 'Conversation unpinned.', 'success');
        }

        // 4. Reload list again to ensure server-side update is reflected
        await refreshConvoListOnly(activeProfileData, user, ui.showModal);

    } catch (error) {
        console.error('Failed to toggle pin status:', error);
        ui.showToast('Could not save pin status.', 'error');

        // 5. Rollback on failure 
        await cache.updateConvoInList(id, { is_pinned: oldPinState });
        await refreshConvoListOnly(activeProfileData, user, ui.showModal);
    }
}


// --- PROJECT (WORKSPACE) HANDLERS ---

// Styled project modals (create/rename name prompt + delete confirm). Listeners
// are attached once, lazily; each open swaps in a fresh pending callback.
let _projectModalsWired = false;
let _pendingProjectNameSubmit = null;
let _pendingProjectDelete = null;

function wireProjectModals() {
    if (_projectModalsWired) return;
    _projectModalsWired = true;

    const input = document.getElementById('project-name-input');
    const submitName = () => {
        const val = (input?.value || '').trim();
        const cb = _pendingProjectNameSubmit;
        _pendingProjectNameSubmit = null;
        ui.closeModal();
        if (val && cb) cb(val);
    };
    document.getElementById('confirm-project-name-btn')?.addEventListener('click', submitName);
    document.getElementById('cancel-project-name-btn')?.addEventListener('click', () => {
        _pendingProjectNameSubmit = null;
        ui.closeModal();
    });
    input?.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); submitName(); }
    });

    document.getElementById('confirm-delete-project-btn')?.addEventListener('click', () => {
        const cb = _pendingProjectDelete;
        _pendingProjectDelete = null;
        ui.closeModal();
        if (cb) cb();
    });
    document.getElementById('cancel-delete-project-btn')?.addEventListener('click', () => {
        _pendingProjectDelete = null;
        ui.closeModal();
    });
}

function openProjectNameModal({ title, value = '', onSubmit }) {
    wireProjectModals();
    if (ui.elements.projectNameModalTitle) ui.elements.projectNameModalTitle.textContent = title;
    if (ui.elements.projectNameInput) ui.elements.projectNameInput.value = value;
    _pendingProjectNameSubmit = onSubmit;
    ui.showModal('project-name');
}

function openDeleteProjectModal({ name, onConfirm }) {
    wireProjectModals();
    if (ui.elements.deleteProjectName) ui.elements.deleteProjectName.textContent = `"${name || 'Untitled'}"`;
    _pendingProjectDelete = onConfirm;
    ui.showModal('delete-project');
}

export function handleCreateProject(activeProfileData, user) {
    openProjectNameModal({
        title: 'New Folder',
        onSubmit: async (name) => {
            try {
                const created = await api.createProject(name);
                if (created === 'QUEUED') {
                    ui.showToast('Offline: cannot create a folder now.', 'error');
                    return;
                }
                if (created && created.id) setProjectExpanded(created.id, true);
                await refreshConvoListOnly(activeProfileData, user, ui.showModal);
                ui.showToast('Folder created.', 'success');
            } catch (e) {
                console.error('Failed to create project:', e);
                ui.showToast('Could not create folder.', 'error');
            }
        },
    });
}

function handleRenameProject(projectId, oldName, activeProfileData, user) {
    ui.closeAllConvoMenus();
    openProjectNameModal({
        title: 'Rename Folder',
        value: oldName || '',
        onSubmit: async (name) => {
            if (name === oldName) return;
            try {
                await api.renameProject(projectId, name);
                await refreshConvoListOnly(activeProfileData, user, ui.showModal);
            } catch (e) {
                console.error('Failed to rename project:', e);
                ui.showToast('Could not rename folder.', 'error');
            }
        },
    });
}

function handleDeleteProject(projectId, name, activeProfileData, user) {
    ui.closeAllConvoMenus();
    // Deleting a project keeps its chats — they fall back to History.
    openDeleteProjectModal({
        name,
        onConfirm: async () => {
            try {
                await api.deleteProject(projectId);
                if (currentProjectId === projectId) currentProjectId = null;
                await refreshConvoListOnly(activeProfileData, user, ui.showModal);
                ui.showToast('Folder deleted.', 'success');
            } catch (e) {
                console.error('Failed to delete project:', e);
                ui.showToast('Could not delete folder.', 'error');
            }
        },
    });
}

function handleToggleProject(projectId, activeProfileData, user) {
    const expanded = getExpandedProjects().has(projectId);
    setProjectExpanded(projectId, !expanded);
    refreshConvoListOnly(activeProfileData, user, ui.showModal);
}

function handleNewChatInProject(projectId, activeProfileData, user) {
    setProjectExpanded(projectId, true);
    startNewConversation(false, activeProfileData, user, createDefaultPromptHandler(activeProfileData, user), projectId);
    if (window.innerWidth < 768) ui.closeSidebar();
}

async function handleMoveConversation(convoId, projectId, activeProfileData, user) {
    ui.closeAllConvoMenus();
    try {
        await cache.updateConvoInList(convoId, { project_id: projectId });
        if (projectId) setProjectExpanded(projectId, true);
        const res = await api.moveConversationToProject(convoId, projectId);
        if (res === 'QUEUED') {
            ui.showToast('Move queued.', 'info');
        }
        await refreshConvoListOnly(activeProfileData, user, ui.showModal);
    } catch (e) {
        console.error('Failed to move conversation:', e);
        ui.showToast('Could not move conversation.', 'error');
    }
}

// --- HELPER: Create Prompt Handler ---
// This ensures that "New Chat" buttons always have a working prompt click handler
function createDefaultPromptHandler(activeProfileData, user) {
    return (promptText) => {
        if (!ui.elements.messageInput) return;
        ui.elements.messageInput.value = promptText;
        autoSize();
        ui.elements.sendButton.disabled = false;
        sendMessage(activeProfileData, user);
    };
}

// --- CORE CONVERSATION MANAGEMENT ---

/**
 * Loads conversation list from server/cache, re-renders sidebar, 
 * and optionally switches to the active chat and scrolls to the bottom.
 * @param {object} activeProfileData 
 * @param {object} user 
 * @param {function} promptClickHandler 
 * @param {function} showModal 
 * @param {boolean} [shouldSwitchChat=true] - NEW: If false, only the list is refreshed, preserving current chat view.
 */
export async function loadConversations(activeProfileData, user, promptClickHandler, showModal, shouldSwitchChat = true) {
    // --- ADDED --- (Feature 1)
    // Check for the flag set during profile change
    const forceNewChat = sessionStorage.getItem('forceNewChat') === 'true';
    if (forceNewChat) {
        // Clear the flag so it doesn't persist on future reloads
        sessionStorage.removeItem('forceNewChat');
    }
    // --- END ADDED ---

    // 1. Load from local cache for immediate display
    const cachedConvos = await cache.loadConvoList();
    if (cachedConvos.length > 0) {
        renderConvoList(cachedConvos, activeProfileData, user, showModal);
    }

    try {
        // 2. Fetch fresh data (uses offlineManager/cache)
        const [response, projectResponse] = await Promise.all([
            api.fetchConversations(),
            api.fetchProjects().catch(() => []),
        ]);

        const conversations = Array.isArray(response) ? response
            : (response && Array.isArray(response.conversations)) ? response.conversations
                : [];

        projects = Array.isArray(projectResponse) ? projectResponse : [];

        // 3. Save new list and render if different
        await cache.saveConvoList(conversations);
        renderConvoList(conversations, activeProfileData, user, showModal);

        if (shouldSwitchChat) {
            // --- MODIFIED BLOCK --- (Feature 1)
            if (forceNewChat) {
                // If the flag is set, always start a new conversation
                await startNewConversation(false, activeProfileData, user, promptClickHandler);
            } else if (conversations?.length > 0) {
                // Original logic: load the last active or most recent convo
                const targetConvoId = (currentConversationId && conversations.some(c => c.id === currentConversationId))
                    ? currentConversationId
                    : conversations[0].id;

                await switchConversation(targetConvoId, activeProfileData, user, showModal, true); // Scroll to bottom on full load
            } else {
                // Original logic: no convos exist, so start a new one
                await startNewConversation(false, activeProfileData, user, promptClickHandler);
            }
            // --- END MODIFIED BLOCK ---
        }
    } catch (error) {
        console.error('Failed to load conversations:', error);
        if (cachedConvos.length === 0) {
            ui.showToast('Failed to load conversations. Check connectivity.', 'error');
        }
    }
}

/**
 * NEW: Loads conversation list from server/cache and re-renders sidebar ONLY.
 * This is used for actions like Pin/Delete/Rename where we don't want to force
 * the main chat window to reload or scroll.
 */
export async function refreshConvoListOnly(activeProfileData, user, showModal) {
    // This calls loadConversations but explicitly sets shouldSwitchChat to false.
    return loadConversations(activeProfileData, user, () => { }, showModal, false);
}


function renderConvoList(conversations, activeProfileData, user, showModal) {
    const convoList = document.getElementById('convo-list');
    if (!convoList) return;

    // ADDED SAFETY CHECK: Ensure user object exists before proceeding
    if (!user) {
        console.warn('Cannot render conversation list: User data is missing.');
        return;
    }

    convoList.innerHTML = '';

    // Pinned first, then most-recently-updated.
    const sortConvos = (list) => list.sort((a, b) => {
        if (a.is_pinned !== b.is_pinned) return a.is_pinned ? -1 : 1;
        const dateA = a.last_updated ? new Date(a.last_updated) : new Date(0);
        const dateB = b.last_updated ? new Date(b.last_updated) : new Date(0);
        return dateB - dateA;
    });
    sortConvos(conversations);

    const handlers = {
        switchHandler: (id) => switchConversation(id, activeProfileData, user, showModal, true), // Click always switches/scrolls
        // NOTE: handleRename, handleDelete, handleTogglePin are now defined at the module top level.
        renameHandler: handleRename,
        deleteHandler: handleDelete,
        pinHandler: (id, isPinned) => handleTogglePin(id, isPinned, activeProfileData, user), // Pass all args
        moveHandler: (id, projectId) => handleMoveConversation(id, projectId, activeProfileData, user),
        projects: projects,
    };

    // --- PROJECTS SECTION (workspaces that group conversations) ---
    const projectIds = new Set(projects.map(p => p.id));
    const convosByProject = {};
    projects.forEach(p => { convosByProject[p.id] = []; });
    conversations.forEach(c => {
        if (c.project_id && projectIds.has(c.project_id)) {
            convosByProject[c.project_id].push(c);
        }
    });

    const projHeader = document.createElement('div');
    projHeader.className = 'px-3 mt-2 mb-1 flex items-center justify-between';
    const projTitle = document.createElement('h3');
    projTitle.className = 'text-[11px] font-semibold text-neutral-500 uppercase tracking-wider';
    projTitle.textContent = 'Folders';
    const newProjBtn = document.createElement('button');
    newProjBtn.type = 'button';
    newProjBtn.title = 'New folder';
    newProjBtn.className = 'flex items-center gap-1 text-[11px] font-semibold text-neutral-500 hover:text-green-600 dark:hover:text-green-400 transition-colors uppercase tracking-wider';
    newProjBtn.innerHTML = `<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"></path></svg><span>New</span>`;
    newProjBtn.addEventListener('click', (e) => { e.stopPropagation(); handleCreateProject(activeProfileData, user); });
    projHeader.appendChild(projTitle);
    projHeader.appendChild(newProjBtn);
    convoList.appendChild(projHeader);

    const expanded = getExpandedProjects();
    const projectHandlers = {
        toggleHandler: (pid) => handleToggleProject(pid, activeProfileData, user),
        newChatHandler: (pid) => handleNewChatInProject(pid, activeProfileData, user),
        renameHandler: (pid, name) => handleRenameProject(pid, name, activeProfileData, user),
        deleteHandler: (pid, name) => handleDeleteProject(pid, name, activeProfileData, user),
    };

    projects.forEach(project => {
        const projConvos = sortConvos(convosByProject[project.id] || []);
        const folder = uiAuthSidebar.renderProjectFolder(
            project, projConvos, expanded.has(project.id), projectHandlers, handlers
        );
        convoList.appendChild(folder);
    });

    // Loose conversations (no project) keep the original Pinned / History layout.
    const looseConversations = conversations.filter(c => !c.project_id || !projectIds.has(c.project_id));
    const pinnedConversations = looseConversations.filter(c => c.is_pinned);
    const unpinnedConversations = looseConversations.filter(c => !c.is_pinned);

    if (pinnedConversations.length > 0) {
        const pinnedHeader = document.createElement('h3');
        pinnedHeader.className = 'px-3 mt-2 mb-1 text-[11px] font-semibold text-neutral-500 uppercase tracking-wider';
        pinnedHeader.textContent = 'Pinned';
        convoList.appendChild(pinnedHeader);

        pinnedConversations.forEach(convo => {
            const link = uiAuthSidebar.renderConversationLink(convo, handlers);
            convoList.appendChild(link);
        });
    }

    if (unpinnedConversations.length > 0) {
        const headerContainer = document.createElement('div');
        headerContainer.className = 'px-3 mt-4 mb-2 flex items-center justify-between';

        const allHeader = document.createElement('h3');
        allHeader.className = 'text-[11px] font-semibold text-neutral-500 uppercase tracking-wider';
        allHeader.textContent = 'History';

        const clearBtn = document.createElement('button');
        clearBtn.id = 'clear-all-convos-button';
        clearBtn.type = 'button';
        clearBtn.title = 'Clear History';
        clearBtn.className = 'p-1 rounded hover:bg-neutral-100 dark:hover:bg-neutral-800 text-neutral-400 hover:text-red-500 dark:hover:text-red-400 transition-colors';
        clearBtn.innerHTML = `<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>`;

        headerContainer.appendChild(allHeader);
        headerContainer.appendChild(clearBtn);
        convoList.appendChild(headerContainer);

        unpinnedConversations.forEach(convo => {
            const link = uiAuthSidebar.renderConversationLink(convo, handlers);
            convoList.appendChild(link);
        });
    } else {
        // Fallback: List is empty (or all pinned). Show Header anyway.
        const headerContainer = document.createElement('div');
        const mt = pinnedConversations.length > 0 ? 'mt-4 border-t border-gray-100 dark:border-gray-800 pt-4' : 'mt-2';
        headerContainer.className = `px-3 mb-2 ${mt} flex items-center justify-between`;

        const allHeader = document.createElement('h3');
        allHeader.className = 'text-[11px] font-semibold text-neutral-500 uppercase tracking-wider';
        allHeader.textContent = 'History';

        const clearBtn = document.createElement('button');
        clearBtn.id = 'clear-all-convos-button';
        clearBtn.type = 'button';
        clearBtn.title = 'Clear History';
        clearBtn.className = 'p-1 rounded hover:bg-neutral-100 dark:hover:bg-neutral-800 text-neutral-400 hover:text-red-500 dark:hover:text-red-400 transition-colors';
        clearBtn.innerHTML = `<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>`;

        headerContainer.appendChild(allHeader);
        headerContainer.appendChild(clearBtn);
        convoList.appendChild(headerContainer);
    }
    // --- END NEW: Sorting Logic ---

    // Ensure the currently active link is highlighted after rendering
    if (currentConversationId) {
        uiAuthSidebar.setActiveConvoLink(currentConversationId);
    }
}


export async function startNewConversation(isInitialLoad = false, activeProfileData, user, promptClickHandler, projectId = null) {
    if (ui.elements.controlPanelView) ui.elements.controlPanelView.classList.add('hidden');
    if (ui.elements.chatView) ui.elements.chatView.classList.remove('hidden');

    // The next created chat lands in this project (null = loose). The global
    // "New Chat" button passes no projectId, so it always clears the context.
    currentProjectId = projectId;

    if (!isInitialLoad) {
        currentConversationId = null;
        uiAuthSidebar.setActiveConvoLink(null);
        uiMessages.resetChatView();
        uiAuthSidebar.updateChatTitle('New Chat');

        uiAuthSidebar.updateActiveProfileChip(activeProfileData.name || 'Default');

        const firstName = user && user.name ? user.name.split(' ')[0] : '';
        uiMessages.displayEmptyState(activeProfileData, promptClickHandler, firstName);
    }
    // We rely on sendMessage to create the conversation when the user types the first message.
}

/**
 * Switches the main chat view to the specified conversation ID.
 * @param {string} id - The conversation ID.
 * @param {object} activeProfileData 
 * @param {object} user 
 * @param {function} showModal 
 * @param {boolean} [shouldScroll=false] - NEW: If true, scrolls to the bottom after rendering history.
 */
export async function switchConversation(id, activeProfileData, user, showModal, shouldScroll = false) {
    if (ui.elements.controlPanelView) ui.elements.controlPanelView.classList.add('hidden');
    if (ui.elements.chatView) ui.elements.chatView.classList.remove('hidden');

    currentConversationId = id;
    uiAuthSidebar.setActiveConvoLink(id);
    uiMessages.resetChatView();
    uiAuthSidebar.updateActiveProfileChip(activeProfileData.name || 'Default');

    // Set title optimistically
    try {
        const activeLink = document.querySelector(`a[data-id="${id}"]`);
        const title = activeLink ? activeLink.querySelector('.convo-title').textContent : 'SAFi';
        uiAuthSidebar.updateChatTitle(title);
    } catch (e) {
        uiAuthSidebar.updateChatTitle('SAFi');
    }

    // 1. Load from local UI state cache first
    const cachedHistory = await cache.loadConvoHistory(id);
    if (cachedHistory.length > 0) {
        // Updated to pass activeProfileData for retry logic
        renderHistory(cachedHistory, user, showModal, activeProfileData);
        if (shouldScroll) ui.scrollToBottom(); // Scroll only if requested
    } else {
        const firstName = user && user.name ? user.name.split(' ')[0] : '';
        uiMessages.displayEmptyState(activeProfileData, createDefaultPromptHandler(activeProfileData, user), firstName);
    }

    try {
        // 2. Then fetch from network (or network's API cache via offlineManager)
        const historyResponse = await api.fetchHistory(id);
        const history = Array.isArray(historyResponse) ? historyResponse
            : (historyResponse && Array.isArray(historyResponse.history)) ? historyResponse.history
                : [];

        // 3. Save to local UI state cache, re-render, and scroll
        await cache.saveConvoHistory(id, history);

        // Only re-render if the newly fetched history is different from the cache we rendered,
        // or if we initially rendered the empty state (cachedHistory.length === 0).
        if (cachedHistory.length === 0 || JSON.stringify(cachedHistory) !== JSON.stringify(history)) {
            uiMessages.resetChatView();
            // Updated to pass activeProfileData for retry logic
            renderHistory(history, user, showModal, activeProfileData);
            if (shouldScroll) ui.scrollToBottom(); // Scroll only if requested
        }
    } catch (error) {
        console.error('Failed to fetch conversation history:', error);
        // If fetch failed but we rendered cache, just warn.
        if (cachedHistory.length === 0) {
            ui.showToast('Could not load chat history.', 'error');
        }
    }
}

/**
 * Strips injected document context blocks from a user message before display.
 * The backend appends [UPLOADED DOCUMENT: ...]...[END DOCUMENT] to the stored
 * turn content; we never want to render that wall of text in the chat bubble.
 */
function _stripDocumentContext(content) {
    if (typeof content !== 'string') return content;
    return content.replace(/\n\n\[UPLOADED DOCUMENT:[\s\S]*?\[END DOCUMENT\]/g, '').trim();
}

// Updated signature to accept activeProfileData
function renderHistory(history, user, showModal, activeProfileData) {
    if (!history || history.length === 0) return;

    history.forEach((turn, i) => {
        if (turn.audit_status === 'cancelled') return;

        const date = turn.timestamp ? new Date(turn.timestamp) : new Date();
        const ledger = typeof turn.conscience_ledger === 'string' ? JSON.parse(turn.conscience_ledger) : turn.conscience_ledger;
        const values = typeof turn.profile_values === 'string' ? JSON.parse(turn.profile_values) : turn.profile_values;

        // --- THIS IS THE FIX ---
        // Parse `suggested_prompts` from a string to an array, just like we do for the ledger.
        let parsedSuggestions = [];
        if (turn.suggested_prompts) {
            if (typeof turn.suggested_prompts === 'string') {
                try { parsedSuggestions = JSON.parse(turn.suggested_prompts); } catch (e) { parsedSuggestions = []; }
            } else if (Array.isArray(turn.suggested_prompts)) {
                parsedSuggestions = turn.suggested_prompts;
            }
        }
        // --- END FIX ---

        // --- THIS IS THE FIX ---
        // Filter out null/undefined scores *before* passing to the trend line.
        const scoresHistory = history.slice(0, i + 1)
            .map(t => t.spirit_score)
            .filter(s => s !== null && s !== undefined);
        // --- END FIX ---

        const payload = {
            ledger: ledger || [],
            profile: (activeProfileData && activeProfileData.key === turn.profile_name)
                ? activeProfileData.name
                : turn.profile_name,
            values: values || [],
            spirit_score: turn.spirit_score,
            spirit_scores_history: scoresHistory,
            // --- MODIFIED: Use the parsed array ---
            suggested_prompts: parsedSuggestions,
            message_id: turn.message_id // Ensure message_id is in payload
        };

        const options = {};
        if (turn.role === 'user' && user) {
            options.avatarUrl = user.picture || user.avatar || `https://placehold.co/40x40/7e22ce/FFFFFF?text=${user.name ? user.name.charAt(0) : 'U'}`;

            // --- NEW: Retry Handler ---
            // If activeProfileData is available, allow retry
            if (activeProfileData) {
                options.onRetry = (text) => {
                    ui.elements.messageInput.value = text;
                    autoSize();
                    ui.elements.sendButton.disabled = false;
                    ui.elements.messageInput.focus();
                    sendMessage(activeProfileData, user);
                };
            }
        }
        // --- MODIFIED: Use the parsed array ---
        options.suggestedPrompts = parsedSuggestions;

        // Strip injected document context from user messages before rendering
        const displayContent = turn.role === 'user'
            ? _stripDocumentContext(turn.content)
            : turn.content;

        uiMessages.displayMessage(
            turn.role,
            displayContent,
            date,
            turn.message_id,
            payload,
            async (p) => {
                // --- FIX: Fetch fresh history on click ---
                const freshHistory = await cache.loadConvoHistory(currentConversationId);
                const msgIndex = freshHistory.findIndex(m => m.message_id === p.message_id);

                let freshScores = [];
                if (msgIndex > -1) {
                    freshScores = freshHistory.slice(0, msgIndex + 1)
                        .map(t => t.spirit_score)
                        .filter(s => s !== null && s !== undefined);
                }

                ui.showModal('conscience', { ...p, spirit_scores_history: freshScores });
            },
            options
        );

        // For historical messages that pre-date inline audit data, do a single fetch.
        if (turn.role === 'ai' && turn.message_id && turn.audit_status === 'pending') {
            fetchAndApplyAuditResult(turn.message_id);
        }
    });
}


// --- MESSAGE FLOW ---

// --- ABORT CONTROLLER STATE ---
let currentAbortController = null;
let currentAiMessageId = null;

function generateUUID() {
    if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID();
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
        const r = (Math.random() * 16) | 0, v = c === 'x' ? r : (r & 0x3) | 0x8;
        return v.toString(16);
    });
}

export async function sendMessage(activeProfileData, user) {
    // 1. Check if we are currently sending (and thus can cancel)
    if (currentAbortController) {
        console.log('Cancelling request...');
        currentAbortController.abort();
        currentAbortController = null;

        // Tell the backend to stop the pipeline
        if (currentAiMessageId) {
            api.cancelMessage(currentAiMessageId).catch(() => {});
            currentAiMessageId = null;
        }

        ui.showToast('Request cancelled.', 'info');

        // Reset button immediately
        const buttonIcon = document.getElementById('button-icon');
        const buttonLoader = document.getElementById('button-loader');
        buttonIcon.classList.remove('hidden');
        buttonIcon.innerHTML = `
           <svg class="w-5 h-5" viewBox="0 0 20 20" fill="currentColor">
              <path fill-rule="evenodd"
                d="M3.293 9.707a1 1 0 010-1.414l6-6a1 1 0 011.414 0l6 6a1 1 0 01-1.414 1.414L11 5.414V17a1 1 0 11-2 0V5.414L4.707 9.707a1 1 0 01-1.414 0z"
                clip-rule="evenodd" />
            </svg>`;
        buttonLoader.classList.add('hidden');

        ui.elements.sendButton.classList.remove('canceling');
        // Re-evaluate disabled state based on input text (likely empty if just sent)
        // But the input was cleared! So we should keep it focused.
        ui.elements.sendButton.disabled = ui.elements.messageInput.value.trim().length === 0;

        ui.clearLoadingInterval();
        const loadingIndicator = document.querySelector('.loading-indicator'); // Or robust find
        if (loadingIndicator) loadingIndicator.remove();
        return;
    }

    const userMessage = ui.elements.messageInput.value.trim();
    if (!userMessage && pendingFiles.length === 0) return;

    let isNewConversation = false;

    if (!currentConversationId) {
        isNewConversation = true;
        try {
            // currentProjectId files the chat under a project when one is active.
            const newConvo = await api.createNewConversation(currentProjectId);

            if (newConvo === 'QUEUED') {
                ui.showToast('Offline: Cannot start new chat now.', 'error');
                return;
            }

            currentConversationId = newConvo.id;
            // The API response now includes is_pinned: false
            const newConvoMeta = {
                id: newConvo.id,
                title: 'Untitled',
                last_updated: new Date().toISOString(),
                is_pinned: newConvo.is_pinned === true,
                project_id: newConvo.project_id || currentProjectId || null
            };
            await cache.updateConvoInList(newConvo.id, newConvoMeta);

            if (newConvoMeta.project_id) {
                // A project chat must land inside its folder, not the loose list —
                // a full list re-render groups it correctly.
                setProjectExpanded(newConvoMeta.project_id, true);
                await refreshConvoListOnly(activeProfileData, user, ui.showModal);
                uiAuthSidebar.setActiveConvoLink(currentConversationId);
            } else {
                const handlers = {
                    switchHandler: (id) => switchConversation(id, activeProfileData, user, ui.showModal, true),
                    renameHandler: handleRename,
                    deleteHandler: handleDelete,
                    pinHandler: (id, isPinned) => handleTogglePin(id, isPinned, activeProfileData, user),
                    moveHandler: (id, projectId) => handleMoveConversation(id, projectId, activeProfileData, user),
                    projects: projects,
                };
                uiAuthSidebar.prependConversationLink(newConvoMeta, handlers);
                uiAuthSidebar.setActiveConvoLink(currentConversationId);
            }

        } catch (error) {
            console.error('Failed to create new conversation on send:', error);
            ui.showToast('Could not start a new chat.', 'error');
            return;
        }
    }

    const buttonIcon = document.getElementById('button-icon');
    const buttonLoader = document.getElementById('button-loader');

    // UI: Show Stop Button instead of Spinner/Arrow
    // Ideally we want a nice transition. For now, swap icon to "Stop"
    buttonIcon.classList.remove('hidden'); // Keep icon visible
    buttonIcon.innerHTML = `
        <svg class="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
          <rect x="5" y="5" width="10" height="10" rx="1"></rect>
        </svg>`;

    // We do NOT use the spinner anymore, or we use it as a border? 
    // The user asked for "cancel option to the spinning button". 
    // Let's keep the spinner but put the stop icon INSIDE it?
    // Current CSS structure: button-icon OR button-loader. Loader replaces icon.
    // Let's show loader AND stop icon.
    buttonLoader.classList.remove('hidden'); // Spinner rotating
    // Remove the icon? No, we want the stop icon visible. 
    // The loader is likely a div that spins. If we put text inside it spins.
    // Let's look at index.html: loader is empty div.
    // Solution: Keep loader spinning (if it's absolute/overlay) or just show Stop icon.
    // "cancel option to the spinning button" -> implied Stop Button.
    // Standard UI: Spinner ring around a square stop button.
    // Simpler UI: Just a stop button. 

    // Let's do: Stop Icon only. No spinner, or spinner around it? 
    // Given the request, "spinning button" usually means "button is loading". 
    // I will replace the spinner with an actionable Stop Icon.
    buttonLoader.classList.add('hidden'); // Hide simple spinner
    // Stop icon is already set above.
    ui.elements.sendButton.disabled = false; // ENABLED so we can click to cancel!

    // Turn button red while the request is in flight
    ui.elements.sendButton.classList.add('canceling');

    // Init AbortController
    currentAbortController = new AbortController();

    const now = new Date();
    // ADDED NULL CHECK: Safely get user info
    const pic = user && (user.picture || user.avatar) || `https://placehold.co/40x40/7e22ce/FFFFFF?text=${user && user.name ? user.name.charAt(0) : 'U'}`;
    const userMessageId = crypto.randomUUID();

    // --- NEW: Retry Handler for optimistic message ---
    const retryHandler = (text) => {
        ui.elements.messageInput.value = text;
        autoSize();
        ui.elements.sendButton.disabled = false;
        ui.elements.messageInput.focus();
        sendMessage(activeProfileData, user);
    };

    // Capture pending file infos before extraction (for display in chat bubble)
    const pendingFileInfos = pendingFiles.map(f => ({ name: f.name, size: f.size }));

    uiMessages.displayMessage('user', userMessage, now, userMessageId, null, null, {
        avatarUrl: pic,
        onRetry: retryHandler,
        attachedFiles: pendingFileInfos
    });

    const userMessageObject = {
        role: 'user',
        content: userMessage,
        timestamp: now.toISOString(),
        message_id: userMessageId,
        audit_status: 'n/a' // User messages don't need audit
    };
    await cache.addMessageToHistory(currentConversationId, userMessageObject);

    const originalMessage = ui.elements.messageInput.value;
    ui.elements.messageInput.value = '';
    autoSize(); // resets disabled=true (empty input) — re-enable immediately for cancel
    ui.elements.sendButton.disabled = false;

    const loadingIndicator = uiMessages.showLoadingIndicator(activeProfileData.name);

    const aiMessageId = generateUUID();
    currentAiMessageId = aiMessageId;
    // Poll for live reasoning status only while the API call is in flight.
    // Stops automatically in the finally block. Audit data comes from the response itself.
    let statusPollInterval = setInterval(async () => {
        try {
            const result = await api.fetchAuditResult(aiMessageId);
            if (result && result.reasoning_log) {
                let log = result.reasoning_log;
                if (typeof log === 'string') log = JSON.parse(log);
                if (Array.isArray(log) && log.length > 0) {
                    uiMessages.updatePipelineTrace(log);
                }
            }
        } catch (e) { /* message may not exist yet — ignore */ }
    }, 1500);

    // --- DOCUMENT UPLOAD: Extract text from all pending files ---
    let documentContext = '';
    if (pendingFiles.length > 0) {
        const filesToProcess = [...pendingFiles];
        _clearAllPendingFiles();
        for (const file of filesToProcess) {
            try {
                const extracted = await api.extractDocumentText(file);
                documentContext += `\n\n[UPLOADED DOCUMENT: ${extracted.filename}]\n[INSTRUCTION: Before analyzing this document, first assess whether its content falls within your defined role and expertise. If the document is outside your domain, politely decline to analyze it in depth, explain why it falls outside your scope, and suggest what type of professional or agent would be more appropriate. Do not force a connection between the document and your role if none exists.]\n${extracted.text}\n[END DOCUMENT]`;
                if (extracted.was_truncated) {
                    ui.showToast(`${file.name} truncated to fit context window.`, 'info');
                }
            } catch (error) {
                ui.showToast(error.message || `Failed to process ${file.name}.`, 'error');
                _clearAllPendingFiles();
                if (loadingIndicator && loadingIndicator.parentNode) loadingIndicator.remove();
                ui.clearLoadingInterval();
                // Reset button
                buttonIcon.classList.remove('hidden');
                buttonIcon.innerHTML = `
                   <svg class="w-5 h-5" viewBox="0 0 20 20" fill="currentColor">
                      <path fill-rule="evenodd"
                        d="M3.293 9.707a1 1 0 010-1.414l6-6a1 1 0 011.414 0l6 6a1 1 0 01-1.414 1.414L11 5.414V17a1 1 0 11-2 0V5.414L4.707 9.707a1 1 0 01-1.414 0z"
                        clip-rule="evenodd" />
                    </svg>`;
                buttonLoader.classList.add('hidden');
                ui.elements.sendButton.classList.remove('canceling');
                currentAbortController = null;
                ui.elements.messageInput.value = originalMessage;
                autoSize();
                return;
            }
        }
    }
    // --- END DOCUMENT UPLOAD ---

    // Build the full message: user text + document context (if any)
    const fullMessage = documentContext ? (userMessage || 'Please analyze the attached document.') + documentContext : userMessage;

    try {
        // PASS SIGNAL AND MESSAGE_ID HERE
        const initialResponse = await api.processUserMessage(fullMessage, currentConversationId, currentAbortController.signal, aiMessageId);

        ui.clearLoadingInterval();
        if (loadingIndicator && loadingIndicator.parentNode) loadingIndicator.remove();

        if (initialResponse === 'QUEUED') {
            ui.showToast('Message queued, will send when online.', 'info');
            // Remove user message from display/cache as it will be resent on flush.
            const userMsgElement = document.querySelector(`[data-message-id="${userMessageId}"]`);
            if (userMsgElement) userMsgElement.remove();
            return;
        }

        // --- START BUG FIX: Handle empty/missing data from API ---
        const mainAnswer = initialResponse.finalOutput ?? '[Sorry, the model returned an empty response.]';
        const ledger = typeof initialResponse.conscienceLedger === 'string' ? JSON.parse(initialResponse.conscienceLedger) : (initialResponse.conscienceLedger || []);
        const values = typeof initialResponse.profileValues === 'string' ? JSON.parse(initialResponse.profileValues) : (initialResponse.profileValues || []);
        const suggestions = initialResponse.suggestedPrompts || [];
        const messageId = initialResponse.messageId || aiMessageId;
        // Resolve human-readable profile name
        let profileName = initialResponse.activeProfile;
        // If the returned profile matches the current active profile key, use the readable name
        if (activeProfileData && activeProfileData.key === profileName) {
            profileName = activeProfileData.name;
        }
        // Fallback if initialResponse.activeProfile was null
        if (!profileName && activeProfileData) {
            profileName = activeProfileData.name;
        }
        const spiritScore = initialResponse.spirit_score;
        const isBlocked = mainAnswer.includes("🛑 **The answer was blocked**");
        // --- END BUG FIX ---

        // Fetch full history *including* the user message we just added
        const historyForPayload = await cache.loadConvoHistory(currentConversationId);

        // Filter out null/undefined scores *before* passing to the trend line.
        const scoresHistoryForPayload = historyForPayload
            .map(t => t.spirit_score)
            .filter(s => s !== null && s !== undefined);
        // Add the new score (if it exists) to the history for the trend line
        if (spiritScore !== null && spiritScore !== undefined) {
            scoresHistoryForPayload.push(spiritScore);
        }

        const aiMessageObject = {
            role: 'ai',
            content: mainAnswer,
            timestamp: new Date().toISOString(),
            message_id: messageId,
            conscience_ledger: ledger,
            profile_name: profileName,
            profile_values: values,
            spirit_score: spiritScore,
            suggested_prompts: suggestions,
            audit_status: 'complete'
        };

        await cache.addMessageToHistory(currentConversationId, aiMessageObject);

        const initialPayload = {
            ledger: ledger,
            profile: profileName,
            values: values,
            spirit_score: spiritScore,
            spirit_scores_history: scoresHistoryForPayload,
            message_id: messageId
        };

        uiMessages.displayMessage(
            'ai',
            mainAnswer,
            new Date(),
            messageId,
            initialPayload,
            async (p) => {
                const freshHistory = await cache.loadConvoHistory(currentConversationId);
                const msgIndex = freshHistory.findIndex(m => m.message_id === p.message_id);

                let freshScores = [];
                if (msgIndex > -1) {
                    freshScores = freshHistory.slice(0, msgIndex + 1)
                        .map(t => t.spirit_score)
                        .filter(s => s !== null && s !== undefined);
                }

                ui.showModal('conscience', { ...p, spirit_scores_history: freshScores });
            },
            { suggestedPrompts: suggestions, animate: true }
        );

        // Follow-up suggestions are generated off the request path on the
        // backend; poll the audit endpoint and inject them once ready.
        if (messageId && (!suggestions || suggestions.length === 0)) {
            _pollForSuggestions(messageId);
        }

        const updateMeta = { last_updated: new Date().toISOString() };
        if (initialResponse.newTitle && isNewConversation) {
            updateMeta.title = initialResponse.newTitle;
        }

        if (updateMeta.title || isNewConversation) {
            const link = document.querySelector(`a[data-id="${currentConversationId}"]`);
            if (link) {
                const titleEl = link.querySelector('.convo-title');
                const timeEl = link.querySelector('.convo-timestamp');
                if (updateMeta.title) titleEl.textContent = updateMeta.title;
                if (timeEl) timeEl.textContent = formatRelativeTime(new Date());
                uiAuthSidebar.updateChatTitle(updateMeta.title || 'Untitled');
            }
        }
        await cache.updateConvoInList(currentConversationId, updateMeta);

    } catch (error) {
        if (error.name === 'AbortError') {
            return;
        }

        // FIX: Ensure loading indicator is removed on error
        if (loadingIndicator && loadingIndicator.parentNode) loadingIndicator.remove();
        ui.clearLoadingInterval();

        // Check for 429 status OR error message
        if (error.status === 429 || (error.message && error.message.includes('DEMO_LIMIT_REACHED'))) {
            ui.showModal('demo_limit');
            const failedMsg = document.querySelector(`[data-message-id="${userMessageId}"]`);
            if (failedMsg) failedMsg.remove();
        } else {
            console.error("Message send failed:", error); // Keep log
            uiMessages.displayMessage('ai', 'Sorry, an error occurred.', new Date(), null, null, null);
            ui.showToast(error.message || 'An unknown error occurred.', 'error');
        }

        ui.elements.messageInput.value = originalMessage;
        autoSize();
    } finally {
        // Double check loading indicator removal in case of other exit paths (though catch covers errors)
        if (loadingIndicator && loadingIndicator.parentNode) loadingIndicator.remove();
        // Reset Button Style
        buttonIcon.classList.remove('hidden');
        buttonIcon.innerHTML = `
           <svg class="w-5 h-5" viewBox="0 0 20 20" fill="currentColor">
               <path fill-rule="evenodd"
                 d="M3.293 9.707a1 1 0 010-1.414l6-6a1 1 0 011.414 0l6 6a1 1 0 01-1.414 1.414L11 5.414V17a1 1 0 11-2 0V5.414L4.707 9.707a1 1 0 01-1.414 0z"
                 clip-rule="evenodd" />
             </svg>`;

        clearInterval(statusPollInterval);

        buttonLoader.classList.add('hidden');

        ui.elements.sendButton.classList.remove('canceling'); // Revert to green

        ui.elements.sendButton.disabled = false;

        currentAbortController = null;
        currentAiMessageId = null;

        // Re-focus and check input state
        ui.elements.messageInput.focus();
        // Since input is empty after send, disable it again if needed
        ui.elements.sendButton.disabled = ui.elements.messageInput.value.trim().length === 0;
    }
}

// Poll the audit endpoint for backgrounded follow-up suggestions and inject
// them into the rendered message once they arrive.
function _pollForSuggestions(messageId, attempts = 0) {
    const MAX_ATTEMPTS = 6;
    const DELAY = 1500;
    if (attempts >= MAX_ATTEMPTS) return;

    setTimeout(async () => {
        if (!currentConversationId) return;
        let parsed = [];
        try {
            const res = await api.fetchAuditResult(messageId);
            const raw = res?.suggestedPrompts ?? res?.suggested_prompts;
            parsed = typeof raw === 'string' ? (JSON.parse(raw) || []) : (raw || []);
        } catch (e) { /* not ready yet */ }

        if (parsed.length > 0) {
            // Persist to cache so a re-render keeps them.
            try {
                const history = await cache.loadConvoHistory(currentConversationId);
                const idx = history.findIndex(m => m.message_id === messageId);
                if (idx > -1) {
                    history[idx] = { ...history[idx], suggested_prompts: parsed };
                    await cache.saveConvoHistory(currentConversationId, history);
                }
            } catch (e) { /* ignore cache errors */ }

            uiMessages.updateMessageWithAudit(
                messageId,
                { suggested_prompts: parsed, message_id: messageId },
                () => {}
            );
            return;
        }
        _pollForSuggestions(messageId, attempts + 1);
    }, DELAY);
}

async function fetchAndApplyAuditResult(messageId) {
    if (!currentConversationId) return;
    try {
        const auditResult = await api.fetchAuditResult(messageId);
        if (!auditResult || auditResult.status === 'not_found') return;

        const rawLedger = auditResult.conscienceLedger || auditResult.ledger;
        const rawSuggestions = auditResult.suggestedPrompts || auditResult.suggested_prompts;

        const parsedLedger = typeof rawLedger === 'string' ? JSON.parse(rawLedger) : (rawLedger || []);
        const parsedSuggestions = typeof rawSuggestions === 'string' ? JSON.parse(rawSuggestions) : (rawSuggestions || []);

        const history = await cache.loadConvoHistory(currentConversationId);
        const msgIndex = history.findIndex(m => m.message_id === messageId);
        if (msgIndex > -1) {
            history[msgIndex] = {
                ...history[msgIndex],
                ...auditResult,
                content: history[msgIndex].content,
                conscience_ledger: parsedLedger,
                suggested_prompts: parsedSuggestions,
                audit_status: 'complete'
            };
            await cache.saveConvoHistory(currentConversationId, history);
        }

        const spiritScoresHistory = history
            .map(t => t.spirit_score)
            .filter(s => s !== null && s !== undefined);

        const payload = {
            ...auditResult,
            ledger: parsedLedger,
            suggested_prompts: parsedSuggestions,
            spirit_scores_history: spiritScoresHistory,
            message_id: messageId
        };

        uiMessages.updateMessageWithAudit(messageId, payload, async (p) => {
            const idx = history.findIndex(m => m.message_id === p.message_id);
            const freshScores = idx > -1
                ? history.slice(0, idx + 1).map(t => t.spirit_score).filter(s => s !== null && s !== undefined)
                : [...spiritScoresHistory];
            ui.showModal('conscience', { ...p, spirit_scores_history: freshScores });
        });
    } catch (e) {
        console.warn(`Could not fetch audit result for historical message ${messageId}:`, e);
    }
}


export function autoSize() {
    const input = ui.elements.messageInput;
    if (!input) return;

    const sendButton = ui.elements.sendButton;

    const hasText = input.value.trim().length > 0;
    // Enable send if there is text OR at least one pending file attachment
    sendButton.disabled = !hasText && pendingFiles.length === 0;

    if (!hasText) {
        input.style.height = '28px'; // Force reset to min-height
        return;
    }

    // Reset height to auto to shrink properly
    input.style.height = 'auto';

    // Calculate new height, capped by max-height in CSS (if set, or we can enforce here)
    // The CSS class max-h-32 (approx 128px) handles the scrolling limit.
    // We just need to set scrollHeight.
    input.style.height = `${input.scrollHeight}px`;
}

// --- CONVERSATION RENAMING/DELETING/PINNING ---

export async function handleConfirmRename(activeProfileData, user) {
    const { id, oldTitle } = convoToRename;
    const newTitle = ui.elements.renameInput.value.trim();

    if (newTitle && newTitle !== oldTitle) {
        try {
            await cache.updateConvoInList(id, { title: newTitle }); // Optimistic UI update

            // NEW: Only refresh the list, do not switch chat or scroll
            await refreshConvoListOnly(activeProfileData, user, ui.showModal);

            const response = await api.renameConversation(id, newTitle);

            if (response === 'QUEUED') {
                ui.showToast('Rename queued.', 'info');
            } else {
                ui.showToast('Conversation renamed.', 'success');
            }

            // Reload conversations again after server response
            await refreshConvoListOnly(activeProfileData, user, ui.showModal);

            if (id === currentConversationId) {
                uiAuthSidebar.updateChatTitle(newTitle);
            }
        } catch (error) {
            ui.showToast('Could not rename conversation.', 'error');
            await cache.updateConvoInList(id, { title: oldTitle }); // Rollback
        }
    }
    ui.closeModal();
    convoToRename = { id: null, oldTitle: null };
}

export async function handleConfirmDelete(activeProfileData, user) {
    const id = convoToDelete;
    if (!id) return;

    try {
        await cache.deleteConvo(id); // Optimistic UI update

        if (id === currentConversationId) {
            currentConversationId = null;
        }

        // NEW: Only refresh the list, then if the current chat was deleted, start a new one
        await refreshConvoListOnly(activeProfileData, user, ui.showModal);

        if (currentConversationId === null) {
            // If deleted chat was the active one, start a fresh view

            // --- THIS IS THE FIX ---
            // Use the shared helper
            await startNewConversation(false, activeProfileData, user, createDefaultPromptHandler(activeProfileData, user));
            // --- END FIX ---
        }

        const response = await api.deleteConversation(id);

        if (response === 'QUEUED') {
            ui.showToast('Delete queued.', 'info');
        } else {
            ui.showToast('Conversation deleted.', 'success');
        }

        // Reload to clean up the queue/ensure final state
        await refreshConvoListOnly(activeProfileData, user, ui.showModal);

    } catch (error) {
        ui.showToast('Could not delete conversation.', 'error');
        // Note: Delete rollback is complex, rely on next sync to fix list if API failed but queue is cleared.
    }

    ui.closeModal();
    convoToDelete = null;
}

export async function handleConfirmClearAll(activeProfileData, user) {
    try {
        // Optimistic UI: drop only loose (non-project) chats; project chats stay.
        const kept = (await cache.loadConvoList()).filter(c => c.project_id);
        await cache.saveConvoList(kept);
        currentConversationId = null;
        await refreshConvoListOnly(activeProfileData, user, ui.showModal);
        await startNewConversation(false, activeProfileData, user, createDefaultPromptHandler(activeProfileData, user));

        await api.clearAllConversations();
        ui.showToast('All conversations deleted.', 'success');
        await refreshConvoListOnly(activeProfileData, user, ui.showModal);
    } catch (error) {
        ui.showToast('Could not clear conversations.', 'error');
    }
    ui.closeModal();
}