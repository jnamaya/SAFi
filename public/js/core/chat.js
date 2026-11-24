import * as api from './api.js';
import * as ui from '../ui/ui.js';
import * as uiAuthSidebar from '../ui/ui-auth-sidebar.js';
import * as uiMessages from '../ui/ui-messages.js';
import { openConversationShareDialog, openProjectShareDialog } from '../ui/ui-share-dialog.js';
import * as cache from './cache.js';
export let currentConversationId = null;
let convoToRename = { id: null, oldTitle: null };
let convoToDelete = null;

let projects = [];
let currentProjectId = null;
let sharedConversations = [];
let sharedProjects = [];
let mySharedConvoIds = new Set();
let mySharedProjectIds = new Set();
const EXPANDED_PROJECTS_KEY = 'safi_expanded_projects';
const SHARED_SECTION_KEY = '__shared_with_me__';

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
    try { localStorage.setItem(EXPANDED_PROJECTS_KEY, JSON.stringify([...set])); } catch {   }
}

let pendingFiles = [];

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

function _getFileTypeConfig(filename) {
    const ext = (filename.split('.').pop() || '').toLowerCase();
    const configs = {
        pdf:  { label: 'PDF', bg: 'bg-red-50 dark:bg-red-900/20',       border: 'border-red-200 dark:border-red-800',       text: 'text-red-500' },
        docx: { label: 'DOC', bg: 'bg-green-50 dark:bg-green-900/20',      border: 'border-green-200 dark:border-green-800',      text: 'text-green-500' },
        doc:  { label: 'DOC', bg: 'bg-green-50 dark:bg-green-900/20',      border: 'border-green-200 dark:border-green-800',      text: 'text-green-500' },
        xlsx: { label: 'XLS', bg: 'bg-green-50 dark:bg-green-900/20',     border: 'border-green-200 dark:border-green-800',     text: 'text-green-600' },
        xls:  { label: 'XLS', bg: 'bg-green-50 dark:bg-green-900/20',     border: 'border-green-200 dark:border-green-800',     text: 'text-green-600' },
        csv:  { label: 'CSV', bg: 'bg-green-50 dark:bg-green-900/20', border: 'border-green-200 dark:border-green-800', text: 'text-green-500' },
        txt:  { label: 'TXT', bg: 'bg-neutral-100 dark:bg-neutral-700',  border: 'border-neutral-200 dark:border-neutral-600', text: 'text-neutral-500' },
        md:   { label: 'MD',  bg: 'bg-green-50 dark:bg-green-900/20',  border: 'border-green-200 dark:border-green-800',  text: 'text-green-500' },
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

export function getProjects() {
    return projects;
}

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
    const oldPinState = isPinned;

    try {
        await cache.updateConvoInList(id, { is_pinned: newPinState });

        await refreshConvoListOnly(activeProfileData, user, ui.showModal);

        const response = await api.togglePinConversation(id, newPinState);

        if (response === 'QUEUED') {
            ui.showToast(newPinState ? 'Pin queued.' : 'Unpin queued.', 'info');
        } else {
            ui.showToast(newPinState ? 'Conversation pinned.' : 'Conversation unpinned.', 'success');
        }

        await refreshConvoListOnly(activeProfileData, user, ui.showModal);

    } catch (error) {
        console.error('Failed to toggle pin status:', error);
        ui.showToast('Could not save pin status.', 'error');

        await cache.updateConvoInList(id, { is_pinned: oldPinState });
        await refreshConvoListOnly(activeProfileData, user, ui.showModal);
    }
}


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
                console.error('Failed to create folder:', e);
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
                console.error('Failed to rename folder:', e);
                ui.showToast('Could not rename folder.', 'error');
            }
        },
    });
}

function handleDeleteProject(projectId, name, activeProfileData, user) {
    ui.closeAllConvoMenus();
    openDeleteProjectModal({
        name,
        onConfirm: async () => {
            try {
                await api.deleteProject(projectId);
                if (currentProjectId === projectId) currentProjectId = null;
                await refreshConvoListOnly(activeProfileData, user, ui.showModal);
                ui.showToast('Folder deleted.', 'success');
            } catch (e) {
                console.error('Failed to delete folder:', e);
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

function createDefaultPromptHandler(activeProfileData, user) {
    return (promptText) => {
        if (!ui.elements.messageInput) return;
        ui.elements.messageInput.value = promptText;
        autoSize();
        ui.elements.sendButton.disabled = false;
        sendMessage(activeProfileData, user);
    };
}


export async function loadConversations(activeProfileData, user, promptClickHandler, showModal, shouldSwitchChat = true) {
    const forceNewChat = sessionStorage.getItem('forceNewChat') === 'true';
    if (forceNewChat) {
        sessionStorage.removeItem('forceNewChat');
    }

    const cachedConvos = await cache.loadConvoList();
    if (cachedConvos.length > 0) {
        renderConvoList(cachedConvos, activeProfileData, user, showModal);
    }

    try {
        const [response, projectResponse, sharedConvoResponse, sharedProjectResponse, mySharesResponse] = await Promise.all([
            api.fetchConversations(),
            api.fetchProjects().catch(() => []),
            api.fetchConversationsSharedWithMe().catch(() => []),
            api.fetchProjectsSharedWithMe().catch(() => []),
            api.fetchMySharedIds().catch(() => ({})),
        ]);

        const conversations = Array.isArray(response) ? response
            : (response && Array.isArray(response.conversations)) ? response.conversations
                : [];

        projects = Array.isArray(projectResponse) ? projectResponse : [];
        sharedConversations = Array.isArray(sharedConvoResponse) ? sharedConvoResponse : [];
        sharedProjects = Array.isArray(sharedProjectResponse) ? sharedProjectResponse : [];
        mySharedConvoIds = new Set(Array.isArray(mySharesResponse?.conversations) ? mySharesResponse.conversations : []);
        mySharedProjectIds = new Set(Array.isArray(mySharesResponse?.projects) ? mySharesResponse.projects : []);

        await cache.saveConvoList(conversations);
        renderConvoList(conversations, activeProfileData, user, showModal);

        if (shouldSwitchChat) {
            if (forceNewChat) {
                await startNewConversation(false, activeProfileData, user, promptClickHandler);
            } else if (conversations?.length > 0) {
                const targetConvoId = (currentConversationId && conversations.some(c => c.id === currentConversationId))
                    ? currentConversationId
                    : conversations[0].id;

                await switchConversation(targetConvoId, activeProfileData, user, showModal, true);
            } else {
                await startNewConversation(false, activeProfileData, user, promptClickHandler);
            }
        }
    } catch (error) {
        console.error('Failed to load conversations:', error);
        if (cachedConvos.length === 0) {
            ui.showToast('Failed to load conversations. Check connectivity.', 'error');
        }
    }
}

export async function refreshConvoListOnly(activeProfileData, user, showModal) {
    return loadConversations(activeProfileData, user, () => { }, showModal, false);
}


function renderConvoList(conversations, activeProfileData, user, showModal) {
    const convoList = document.getElementById('convo-list');
    if (!convoList) return;

    if (!user) {
        console.warn('Cannot render conversation list: User data is missing.');
        return;
    }

    convoList.innerHTML = '';

    const sortConvos = (list) => list.sort((a, b) => {
        if (a.is_pinned !== b.is_pinned) return a.is_pinned ? -1 : 1;
        const dateA = a.last_updated ? new Date(a.last_updated) : new Date(0);
        const dateB = b.last_updated ? new Date(b.last_updated) : new Date(0);
        return dateB - dateA;
    });
    sortConvos(conversations);

    const handlers = {
        switchHandler: (id) => switchConversation(id, activeProfileData, user, showModal, true),
        renameHandler: handleRename,
        deleteHandler: handleDelete,
        pinHandler: (id, isPinned) => handleTogglePin(id, isPinned, activeProfileData, user),
        moveHandler: (id, projectId) => handleMoveConversation(id, projectId, activeProfileData, user),
        shareHandler: (id, title) => openConversationShareDialog(
            id, title, () => refreshConvoListOnly(activeProfileData, user, showModal)),
        sharedConvoIds: mySharedConvoIds,
        projects: projects,
    };

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
        shareHandler: (pid, name) => openProjectShareDialog(
            pid, name, () => refreshConvoListOnly(activeProfileData, user, showModal)),
    };

    if (sharedProjects.length > 0 || sharedConversations.length > 0) {
        const notOwner = (verb) => () => ui.showToast(`Only the owner can ${verb} this conversation.`, 'info');

        const removeFromShared = async (kind, id, label) => {
            if (!window.confirm(`Remove "${label}" from your shared-with-me list?`)) return;
            try {
                const res = kind === 'project'
                    ? await api.removeProjectSharedWithMe(id)
                    : await api.removeConversationSharedWithMe(id);
                if (res?.still_shared === 'group') {
                    ui.showToast('Removed your direct access, but a group you belong to is still shared this item.', 'info');
                } else if (res?.still_shared === 'project') {
                    ui.showToast('Removed your direct access, but this conversation is inside a folder shared with you.', 'info');
                } else if (res?.ok) {
                    ui.showToast('Removed from shared with me.', 'success');
                } else {
                    ui.showToast('Nothing to remove — this may not be shared with you directly.', 'info');
                }
                await refreshConvoListOnly(activeProfileData, user, showModal);
            } catch (e) {
                console.error('Failed to remove shared item:', e);
                ui.showToast('Failed to remove shared item.', 'error');
            }
        };
        const sharedConvoHandlers = {
            switchHandler: handlers.switchHandler,
            pinHandler: notOwner('pin'),
            renameHandler: notOwner('rename'),
            deleteHandler: notOwner('delete'),
            unshareHandler: (id, title) => removeFromShared('conversation', id, title || 'conversation'),
        };
        const sharedProjectHandlers = {
            toggleHandler: (pid) => handleToggleProject(pid, activeProfileData, user),
            unshareHandler: (pid, name) => removeFromShared('project', pid, name || 'folder'),
        };

        const sharedProjectIds = new Set(sharedProjects.map(p => p.id));
        const sharedConvosByProject = {};
        sharedProjects.forEach(p => { sharedConvosByProject[p.id] = []; });
        const looseSharedConversations = [];
        sharedConversations.forEach(c => {
            if (c.project_id && sharedProjectIds.has(c.project_id)) {
                sharedConvosByProject[c.project_id].push(c);
            } else {
                looseSharedConversations.push(c);
            }
        });

        const sectionCount = sharedProjects.length + looseSharedConversations.length;
        const { wrap, body } = uiAuthSidebar.renderSidebarSection(
            'Shared with me', sectionCount, expanded.has(SHARED_SECTION_KEY),
            () => handleToggleProject(SHARED_SECTION_KEY, activeProfileData, user),
            { title: 'Conversations and folders other people shared with you' }
        );
        convoList.appendChild(wrap);

        if (body) {
            sharedProjects.forEach(project => {
                const projConvos = sortConvos(sharedConvosByProject[project.id] || []);
                const folder = uiAuthSidebar.renderProjectFolder(
                    project, projConvos, expanded.has(project.id), sharedProjectHandlers, sharedConvoHandlers,
                    { readOnly: true, ownerName: project.owner_name }
                );
                body.appendChild(folder);
            });

            sortConvos(looseSharedConversations).forEach(convo => {
                const link = uiAuthSidebar.renderConversationLink(convo, sharedConvoHandlers);
                link.title = convo.owner_name ? `Shared by ${convo.owner_name}` : 'Shared with you';
                body.appendChild(link);
            });
        }
    }

    projects.forEach(project => {
        const projConvos = sortConvos(convosByProject[project.id] || []);
        const folder = uiAuthSidebar.renderProjectFolder(
            project, projConvos, expanded.has(project.id), projectHandlers, handlers,
            { shared: mySharedProjectIds.has(project.id) }
        );
        convoList.appendChild(folder);
    });

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
        const startOfToday = new Date(); startOfToday.setHours(0, 0, 0, 0);
        const DAY = 86400000;
        const groupOf = (convo) => {
            const d = new Date(convo.last_updated || convo.created_at || 0);
            if (d >= startOfToday) return 'Today';
            if (d >= new Date(startOfToday - DAY)) return 'Yesterday';
            if (d >= new Date(startOfToday - 7 * DAY)) return 'Previous 7 days';
            return 'Older';
        };
        const groups = new Map([['Today', []], ['Yesterday', []], ['Previous 7 days', []], ['Older', []]]);
        unpinnedConversations.forEach(c => groups.get(groupOf(c)).push(c));

        let firstHeader = true;
        for (const [label, convos] of groups) {
            if (!convos.length) continue;

            const headerContainer = document.createElement('div');
            headerContainer.className = firstHeader
                ? 'px-3 mt-4 mb-2 flex items-center justify-between'
                : 'px-3 mt-4 mb-2';
            const groupHeader = document.createElement('h3');
            groupHeader.className = 'text-[11px] font-semibold text-neutral-500 uppercase tracking-wider';
            groupHeader.textContent = label;
            headerContainer.appendChild(groupHeader);

            if (firstHeader) {
                const clearBtn = document.createElement('button');
                clearBtn.id = 'clear-all-convos-button';
                clearBtn.type = 'button';
                clearBtn.title = 'Clear History';
                clearBtn.className = 'p-1 rounded hover:bg-neutral-100 dark:hover:bg-neutral-800 text-neutral-400 hover:text-red-500 dark:hover:text-red-400 transition-colors';
                clearBtn.innerHTML = `<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>`;
                headerContainer.appendChild(clearBtn);
                firstHeader = false;
            }
            convoList.appendChild(headerContainer);

            convos.forEach(convo => {
                const link = uiAuthSidebar.renderConversationLink(convo, handlers);
            convoList.appendChild(link);
            });
        }
    } else {
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
    if (currentConversationId) {
        uiAuthSidebar.setActiveConvoLink(currentConversationId);
    }
}


export async function startNewConversation(isInitialLoad = false, activeProfileData, user, promptClickHandler, projectId = null) {
    if (ui.elements.controlPanelView) ui.elements.controlPanelView.classList.add('hidden');
    if (ui.elements.chatView) ui.elements.chatView.classList.remove('hidden');

    currentProjectId = projectId;

    if (!isInitialLoad) {
        currentConversationId = null;
        uiAuthSidebar.setActiveConvoLink(null);
        uiMessages.resetChatView();
        uiAuthSidebar.updateChatTitle('New Chat');

        uiAuthSidebar.updateActiveProfileChip(activeProfileData);

        const firstName = user && user.name ? user.name.split(' ')[0] : '';
        uiMessages.displayEmptyState(activeProfileData, promptClickHandler, firstName);
    }
}

export async function switchConversation(id, activeProfileData, user, showModal, shouldScroll = false) {
    if (ui.elements.controlPanelView) ui.elements.controlPanelView.classList.add('hidden');
    if (ui.elements.chatView) ui.elements.chatView.classList.remove('hidden');

    currentConversationId = id;
    uiAuthSidebar.setActiveConvoLink(id);
    uiMessages.resetChatView();
    uiAuthSidebar.updateActiveProfileChip(activeProfileData);

    try {
        const activeLink = document.querySelector(`a[data-id="${id}"]`);
        const title = activeLink ? activeLink.querySelector('.convo-title').textContent : 'SAFi';
        uiAuthSidebar.updateChatTitle(title);
    } catch (e) {
        uiAuthSidebar.updateChatTitle('SAFi');
    }

    const cachedHistory = await cache.loadConvoHistory(id);
    if (cachedHistory.length > 0) {
        renderHistory(cachedHistory, user, showModal, activeProfileData);
        if (shouldScroll) ui.scrollToBottom();
    } else {
        const firstName = user && user.name ? user.name.split(' ')[0] : '';
        uiMessages.displayEmptyState(activeProfileData, createDefaultPromptHandler(activeProfileData, user), firstName);
    }

    try {
        const historyResponse = await api.fetchHistory(id);
        const history = Array.isArray(historyResponse) ? historyResponse
            : (historyResponse && Array.isArray(historyResponse.history)) ? historyResponse.history
                : [];

        await cache.saveConvoHistory(id, history);

        if (cachedHistory.length === 0 || JSON.stringify(cachedHistory) !== JSON.stringify(history)) {
            uiMessages.resetChatView();
            renderHistory(history, user, showModal, activeProfileData);
            if (shouldScroll) ui.scrollToBottom();
        }
    } catch (error) {
        console.error('Failed to fetch conversation history:', error);
        if (cachedHistory.length === 0) {
            ui.showToast('Could not load chat history.', 'error');
        }
    }
}

function _stripDocumentContext(content) {
    if (typeof content !== 'string') return content;
    return content.replace(/\n\n\[UPLOADED DOCUMENT:[\s\S]*?\[END DOCUMENT\]/g, '').trim();
}

function renderHistory(history, user, showModal, activeProfileData) {
    if (!history || history.length === 0) return;

    let _lastReplayedUserPrompt = null;

    history.forEach((turn, i) => {
        if (turn.audit_status === 'cancelled') return;

        const date = turn.timestamp ? new Date(turn.timestamp) : new Date();
        const ledger = typeof turn.conscience_ledger === 'string' ? JSON.parse(turn.conscience_ledger) : turn.conscience_ledger;
        const values = typeof turn.profile_values === 'string' ? JSON.parse(turn.profile_values) : turn.profile_values;


        const scoresHistory = history.slice(0, i + 1)
            .map(t => t.spirit_score)
            .filter(s => s !== null && s !== undefined);

        const turnPolicyId = (turn.policy_id && turn.policy_id !== 'standalone') ? turn.policy_id : null;

        const payload = {
            ledger: ledger || [],
            profile: (activeProfileData && activeProfileData.key === turn.profile_name)
                ? activeProfileData.name
                : turn.profile_name,
            policy_id: turnPolicyId,
            policy_version: turnPolicyId ? (turn.policy_version ?? null) : null,
            policy_name: (turnPolicyId && activeProfileData && activeProfileData.policy_id === turnPolicyId)
                ? (activeProfileData.policy_name || null)
                : null,
            values: values || [],
            spirit_score: turn.spirit_score,
            spirit_scores_history: scoresHistory,
            final_output: turn.role === 'ai' ? turn.content : null,
            message_id: turn.message_id
        };

        const options = {};
        const resend = activeProfileData ? (text) => {
            ui.elements.messageInput.value = text;
            autoSize();
            ui.elements.sendButton.disabled = false;
            ui.elements.messageInput.focus();
            sendMessage(activeProfileData, user);
        } : null;

        if (turn.role === 'user' && user) {
            const init = encodeURIComponent((user.name ? user.name.charAt(0) : 'U').toUpperCase());
            options.avatarUrl = user.picture || user.avatar || `data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='40' height='40' viewBox='0 0 40 40'><rect width='40' height='40' fill='%2316a34a'/><text x='50%25' y='54%25' dominant-baseline='middle' text-anchor='middle' fill='%23FFFFFF' font-family='sans-serif' font-size='18' font-weight='600'>${init}</text></svg>`;
            if (resend) options.onRetry = resend;
        }

        const displayContent = turn.role === 'user'
            ? _stripDocumentContext(turn.content)
            : turn.content;

        if (turn.role === 'user') {
            _lastReplayedUserPrompt = displayContent;
        } else if (resend && _lastReplayedUserPrompt) {
            const promptForRedo = _lastReplayedUserPrompt;
            options.onRedo = () => resend(promptForRedo);
        }

        uiMessages.displayMessage(
            turn.role,
            displayContent,
            date,
            turn.message_id,
            payload,
            async (p) => {
                const freshHistory = await cache.loadConvoHistory(currentConversationId);
                const msgIndex = freshHistory.findIndex(m => m.message_id === p.message_id);

                let freshScores = p.spirit_scores_history || [];
                if (!freshScores.length && msgIndex > -1) {
                    freshScores = freshHistory.slice(0, msgIndex + 1)
                        .map(t => t.spirit_score)
                        .filter(s => s !== null && s !== undefined);
                }

                await showConscienceAuditModal({ ...p, spirit_scores_history: freshScores });
            },
            options
        );

        if (turn.role === 'ai' && turn.message_id && turn.audit_status === 'pending') {
            fetchAndApplyAuditResult(turn.message_id).then((outcome) => {
                if (outcome === 'pending') _pollForAudit(turn.message_id);
            });
        }
    });
}

async function showConscienceAuditModal(payload) {
    let context = {};
    if (payload.message_id && payload.will_reason == null && payload.is_redirect !== true) {
        try {
            const result = await api.fetchAuditResult(payload.message_id);
            if (result?.status === 'complete') context = result;
        } catch {   }
    }
    ui.showModal('conscience', {
        ...payload,
        will_reason: payload.will_reason ?? context.will_reason ?? null,
        is_redirect: payload.is_redirect ?? context.is_redirect ?? false,
        final_output: context.final_output ?? payload.final_output ?? null,
        conscience_model: context.conscience_model ?? payload.conscience_model ?? null,
    });
}


let currentAbortController = null;
let currentAiMessageId = null;

function generateUUID() {
    if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID();
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
        const r = (Math.random() * 16) | 0, v = c === 'x' ? r : (r & 0x3) | 0x8;
        return v.toString(16);
    });
}

async function recoverInFlightTurn(messageId, signal) {
    let consecutiveNotFound = 0;
    const deadline = Date.now() + 1_800_000;
    while (Date.now() < deadline && (!signal || !signal.aborted)) {
        await new Promise(r => setTimeout(r, 2000));
        if (signal && signal.aborted) return false;
        try {
            const result = await api.fetchAuditResult(messageId);
            consecutiveNotFound = 0;
            if (result && result.reasoning_log) {
                let log = result.reasoning_log;
                if (typeof log === 'string') log = JSON.parse(log);
                if (Array.isArray(log) && log.length > 0) {
                    uiMessages.updatePipelineTrace(log);
                }
            }
            if (result && (result.status === 'complete' || result.audit_status === 'complete')) {
                return true;
            }
        } catch (pollErr) {
            if (pollErr && pollErr.status === 404) {
                consecutiveNotFound += 1;
                if (consecutiveNotFound >= 3) return false;
            }
        }
    }
    return false;
}

export async function sendMessage(activeProfileData, user) {
    if (currentAbortController) {
        console.log('Cancelling request...');
        currentAbortController.abort();
        currentAbortController = null;

        if (currentAiMessageId) {
            api.cancelMessage(currentAiMessageId).catch(() => {});
            currentAiMessageId = null;
        }

        ui.showToast('Request cancelled.', 'info');

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
        ui.elements.sendButton.disabled = ui.elements.messageInput.value.trim().length === 0;

        ui.clearLoadingInterval();
        const loadingIndicator = document.querySelector('.loading-indicator');
        if (loadingIndicator) loadingIndicator.remove();
        return;
    }

    const userMessage = ui.elements.messageInput.value.trim();
    if (!userMessage && pendingFiles.length === 0) return;

    if (!activeProfileData || !activeProfileData.key) {
        ui.showToast('No agents currently available. Contact your administrator to grant you access to an agent.', 'warning');
        return;
    }

    let isNewConversation = false;

    if (!currentConversationId) {
        isNewConversation = true;
        try {
            const newConvo = await api.createNewConversation(currentProjectId);

            if (newConvo === 'QUEUED') {
                ui.showToast('Offline: Cannot start new chat now.', 'error');
                return;
            }

            currentConversationId = newConvo.id;
            const newConvoMeta = {
                id: newConvo.id,
                title: 'Untitled',
                last_updated: new Date().toISOString(),
                is_pinned: newConvo.is_pinned === true,
                project_id: newConvo.project_id || currentProjectId || null
            };
            await cache.updateConvoInList(newConvo.id, newConvoMeta);

            if (newConvoMeta.project_id) {
                setProjectExpanded(newConvoMeta.project_id, true);
            }
            await refreshConvoListOnly(activeProfileData, user, ui.showModal);
            uiAuthSidebar.setActiveConvoLink(currentConversationId);

        } catch (error) {
            console.error('Failed to create new conversation on send:', error);
            ui.showToast('Could not start a new chat.', 'error');
            return;
        }
    }

    const buttonIcon = document.getElementById('button-icon');
    const buttonLoader = document.getElementById('button-loader');

    buttonIcon.classList.remove('hidden');
    buttonIcon.innerHTML = `
        <svg class="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
          <rect x="5" y="5" width="10" height="10" rx="1"></rect>
        </svg>`;

    buttonLoader.classList.remove('hidden');

    buttonLoader.classList.add('hidden');
    ui.elements.sendButton.disabled = false;

    ui.elements.sendButton.classList.add('canceling');

    currentAbortController = new AbortController();

    const now = new Date();
    const init = encodeURIComponent((user && user.name ? user.name.charAt(0) : 'U').toUpperCase());
    const pic = user && (user.picture || user.avatar) || `data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='40' height='40' viewBox='0 0 40 40'><rect width='40' height='40' fill='%2316a34a'/><text x='50%25' y='54%25' dominant-baseline='middle' text-anchor='middle' fill='%23FFFFFF' font-family='sans-serif' font-size='18' font-weight='600'>${init}</text></svg>`;
    const userMessageId = generateUUID();

    const retryHandler = (text) => {
        ui.elements.messageInput.value = text;
        autoSize();
        ui.elements.sendButton.disabled = false;
        ui.elements.messageInput.focus();
        sendMessage(activeProfileData, user);
    };

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
        audit_status: 'n/a'
    };
    await cache.addMessageToHistory(currentConversationId, userMessageObject);

    const originalMessage = ui.elements.messageInput.value;
    ui.elements.messageInput.value = '';
    autoSize();
    ui.elements.sendButton.disabled = false;

    const loadingIndicator = uiMessages.showLoadingIndicator(activeProfileData?.name || 'Assistant');

    const aiMessageId = generateUUID();
    currentAiMessageId = aiMessageId;
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
        } catch (e) {   }
    }, 1500);

    let documentContext = '';
    if (pendingFiles.length > 0) {
        const filesToProcess = [...pendingFiles];
        _clearAllPendingFiles();
        for (const file of filesToProcess) {
            try {
                const extracted = await api.extractDocumentText(file);
                const provenance = [
                    `sha256 ${extracted.sha256 || 'unavailable'}`,
                    `${(extracted.total_chars || 0).toLocaleString()} characters`,
                    extracted.was_truncated
                        ? `TRUNCATED — only the first ${(extracted.chars_used || 0).toLocaleString()} were read`
                        : 'read in full',
                ].join(' | ');
                documentContext += `\n\n[UPLOADED DOCUMENT: ${extracted.filename}]\n[PROVENANCE: ${provenance}]\n[INSTRUCTION: Before analyzing this document, first assess whether its content falls within your defined role and expertise. If the document is outside your domain, politely decline to analyze it in depth, explain why it falls outside your scope, and suggest what type of professional or agent would be more appropriate. Do not force a connection between the document and your role if none exists.${extracted.was_truncated ? ' This document was truncated: say so if the user asks about anything you cannot see.' : ''}]\n${extracted.text}\n[END DOCUMENT]`;
                if (extracted.was_truncated) {
                    const kept = (extracted.chars_used || 0).toLocaleString();
                    const total = (extracted.total_chars || 0).toLocaleString();
                    ui.showToast(
                        `${file.name} is ${total} characters — only the first ${kept} were read. The rest was not seen.`,
                        'warning', 8000);
                }
            } catch (error) {
                ui.showToast(error.message || `Failed to process ${file.name}.`, 'error');
                _clearAllPendingFiles();
                if (loadingIndicator && loadingIndicator.parentNode) loadingIndicator.remove();
                ui.clearLoadingInterval();
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

    const fullMessage = documentContext ? (userMessage || 'Please analyze the attached document.') + documentContext : userMessage;

    try {
        const initialResponse = await api.processUserMessage(
            fullMessage,
            currentConversationId,
            currentAbortController.signal,
            aiMessageId,
            activeProfileData?.key || null
        );

        ui.clearLoadingInterval();
        if (loadingIndicator && loadingIndicator.parentNode) loadingIndicator.remove();

        if (initialResponse === 'QUEUED') {
            ui.showToast('Message queued, will send when online.', 'info');
            const userMsgElement = document.querySelector(`[data-message-id="${userMessageId}"]`);
            if (userMsgElement) userMsgElement.remove();
            return;
        }

        const mainAnswer = initialResponse.finalOutput ?? '[Sorry, the model returned an empty response.]';
        const ledger = typeof initialResponse.conscienceLedger === 'string' ? JSON.parse(initialResponse.conscienceLedger) : (initialResponse.conscienceLedger || []);
        const values = typeof initialResponse.profileValues === 'string' ? JSON.parse(initialResponse.profileValues) : (initialResponse.profileValues || []);
        const messageId = initialResponse.messageId || aiMessageId;
        let profileName = initialResponse.activeProfile;
        if (activeProfileData && activeProfileData.key === profileName) {
            profileName = activeProfileData.name;
        }
        if (!profileName && activeProfileData) {
            profileName = activeProfileData.name;
        }
        const respPolicyId = (initialResponse.policyId && initialResponse.policyId !== 'standalone')
            ? initialResponse.policyId : null;
        const respPolicyVersion = respPolicyId ? (initialResponse.policyVersion ?? null) : null;
        const policyName = (respPolicyId && activeProfileData && activeProfileData.policy_id === respPolicyId)
            ? (activeProfileData.policy_name || null)
            : null;
        const spiritScore = initialResponse.spirit_score;
        const isBlocked = mainAnswer.includes("🛑 **The answer was blocked**");

        const historyForPayload = await cache.loadConvoHistory(currentConversationId);

        const serverScores = Array.isArray(initialResponse.spiritScoresHistory)
            ? initialResponse.spiritScoresHistory
            : (Array.isArray(initialResponse.spirit_scores_history)
                ? initialResponse.spirit_scores_history : null);
        let scoresHistoryForPayload;
        if (serverScores && serverScores.length) {
            scoresHistoryForPayload = serverScores.slice();
        } else {
            scoresHistoryForPayload = historyForPayload
                .map(t => t.spirit_score)
                .filter(s => s !== null && s !== undefined);
            if (spiritScore !== null && spiritScore !== undefined) {
                scoresHistoryForPayload.push(spiritScore);
            }
        }

        const aiMessageObject = {
            role: 'ai',
            content: mainAnswer,
            timestamp: new Date().toISOString(),
            message_id: messageId,
            conscience_ledger: ledger,
            profile_name: profileName,
            policy_id: initialResponse.policyId || null,
            policy_version: initialResponse.policyVersion ?? null,
            profile_values: values,
            spirit_score: spiritScore,
            audit_status: 'complete'
        };

        await cache.addMessageToHistory(currentConversationId, aiMessageObject);

        const initialPayload = {
            ledger: ledger,
            profile: profileName,
            policy_id: respPolicyId,
            policy_version: respPolicyVersion,
            policy_name: policyName,
            values: values,
            spirit_score: spiritScore,
            spirit_scores_history: scoresHistoryForPayload,
            final_output: mainAnswer,
            will_reason: initialResponse.willReason || null,
            is_redirect: initialResponse.isRedirect === true,
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

                let freshScores = p.spirit_scores_history || [];
                if (!freshScores.length && msgIndex > -1) {
                    freshScores = freshHistory.slice(0, msgIndex + 1)
                        .map(t => t.spirit_score)
                        .filter(s => s !== null && s !== undefined);
                }

                await showConscienceAuditModal({ ...p, spirit_scores_history: freshScores });
            },
            { animate: true, onRedo: () => retryHandler(userMessage) }
        );

        if (messageId && auditNeedsPolling(initialResponse)) {
            _pollForAudit(messageId);
        }

        const updateMeta = { last_updated: new Date().toISOString() };
        if (initialResponse.newTitle) {
            updateMeta.title = initialResponse.newTitle;

            const convoId = currentConversationId;
            const truncated = initialResponse.newTitle;
            [2500, 7000, 15000].forEach(delay => setTimeout(async () => {
                try {
                    if (convoId !== currentConversationId) return;
                    const link = document.querySelector(`a[data-id="${convoId}"] .convo-title`);
                    if (link && link.textContent !== truncated) return;
                    const convos = await api.fetchConversations();
                    const fresh = (Array.isArray(convos) ? convos : []).find(c => c.id === convoId);
                    if (fresh && fresh.title && fresh.title !== truncated) {
                        await cache.updateConvoInList(convoId, { title: fresh.title });
                        if (link) { link.textContent = fresh.title; link.title = fresh.title; }
                        uiAuthSidebar.updateChatTitle(fresh.title);
                    }
                } catch (e) {   }
            }, delay));
        }

        if (updateMeta.title || isNewConversation) {
            const link = document.querySelector(`a[data-id="${currentConversationId}"]`);
            if (link) {
                const titleEl = link.querySelector('.convo-title');
                if (updateMeta.title) { titleEl.textContent = updateMeta.title; titleEl.title = updateMeta.title; }
                uiAuthSidebar.updateChatTitle(updateMeta.title || 'Untitled');
            }
        }
        await cache.updateConvoInList(currentConversationId, updateMeta);

    } catch (error) {
        if (error.name === 'AbortError') {
            return;
        }

        if ((!error.status || error.status === 502 || error.status === 504) && aiMessageId && currentAbortController) {
            clearInterval(statusPollInterval);
            const recovered = await recoverInFlightTurn(aiMessageId, currentAbortController.signal);
            if (recovered) {
                if (loadingIndicator && loadingIndicator.parentNode) loadingIndicator.remove();
                ui.clearLoadingInterval();
                try {
                    const convos = await api.fetchConversations();
                    const fresh = (Array.isArray(convos) ? convos : []).find(c => c.id === currentConversationId);
                    if (fresh && fresh.title) {
                        await cache.updateConvoInList(currentConversationId, { title: fresh.title });
                        const link = document.querySelector(`a[data-id="${currentConversationId}"] .convo-title`);
                        if (link) { link.textContent = fresh.title; link.title = fresh.title; }
                    }
                } catch (e) {   }
                await switchConversation(currentConversationId, activeProfileData, user, showConscienceAuditModal, true);
                return;
            }
        }

        if (loadingIndicator && loadingIndicator.parentNode) loadingIndicator.remove();
        ui.clearLoadingInterval();

        if (error.status === 429 || (error.message && error.message.includes('DEMO_LIMIT_REACHED'))) {
            ui.showModal('demo_limit');
            const failedMsg = document.querySelector(`[data-message-id="${userMessageId}"]`);
            if (failedMsg) failedMsg.remove();
        } else {
            console.error("Message send failed:", error);
            uiMessages.displayMessage('ai', 'Sorry, an error occurred.', new Date(), null, null, null);
            ui.showToast(error.message || 'An unknown error occurred.', 'error');
        }

        ui.elements.messageInput.value = originalMessage;
        autoSize();
    } finally {
        if (loadingIndicator && loadingIndicator.parentNode) loadingIndicator.remove();
        buttonIcon.classList.remove('hidden');
        buttonIcon.innerHTML = `
           <svg class="w-5 h-5" viewBox="0 0 20 20" fill="currentColor">
               <path fill-rule="evenodd"
                 d="M3.293 9.707a1 1 0 010-1.414l6-6a1 1 0 011.414 0l6 6a1 1 0 01-1.414 1.414L11 5.414V17a1 1 0 11-2 0V5.414L4.707 9.707a1 1 0 01-1.414 0z"
                 clip-rule="evenodd" />
             </svg>`;

        clearInterval(statusPollInterval);

        buttonLoader.classList.add('hidden');

        ui.elements.sendButton.classList.remove('canceling');

        ui.elements.sendButton.disabled = false;

        currentAbortController = null;
        currentAiMessageId = null;

        ui.elements.messageInput.focus();
        ui.elements.sendButton.disabled = ui.elements.messageInput.value.trim().length === 0;
    }
}

export function auditIsComplete(res) {
    return !!res && res.status === 'complete';
}

export function auditNeedsPolling(initialResponse) {
    if (!initialResponse) return false;
    if (initialResponse.audit_status && initialResponse.audit_status !== 'complete') return true;
    const s = initialResponse.spirit_score;
    return s === null || s === undefined;
}

async function fetchAndApplyAuditResult(messageId) {
    if (!currentConversationId) return 'unavailable';
    try {
        const auditResult = await api.fetchAuditResult(messageId);
        if (!auditResult || auditResult.status === 'not_found') return 'unavailable';
        if (auditResult.status === 'pending') return 'pending';
        if (!auditIsComplete(auditResult)) return 'unavailable';

        const rawLedger = auditResult.conscienceLedger || auditResult.ledger;
        const parsedLedger = typeof rawLedger === 'string' ? JSON.parse(rawLedger) : (rawLedger || []);

        const history = await cache.loadConvoHistory(currentConversationId);
        const msgIndex = history.findIndex(m => m.message_id === messageId);
        if (msgIndex > -1) {
            history[msgIndex] = {
                ...history[msgIndex],
                ...auditResult,
                content: history[msgIndex].content,
                conscience_ledger: parsedLedger,
                audit_status: 'complete'
            };
            await cache.saveConvoHistory(currentConversationId, history);
        }

        const spiritScoresHistory = Array.isArray(auditResult.spirit_scores_history)
            && auditResult.spirit_scores_history.length
            ? auditResult.spirit_scores_history.slice()
            : history.map(t => t.spirit_score).filter(s => s !== null && s !== undefined);

        const payload = {
            ...auditResult,
            ledger: parsedLedger,
            final_output: history.find(m => m.message_id === messageId)?.content || null,
            spirit_scores_history: spiritScoresHistory,
            message_id: messageId
        };

        uiMessages.updateMessageWithAudit(messageId, payload, async (p) => {
            const idx = history.findIndex(m => m.message_id === p.message_id);
            const freshScores = spiritScoresHistory.length
                ? [...spiritScoresHistory]
                : (idx > -1
                    ? history.slice(0, idx + 1).map(t => t.spirit_score).filter(s => s !== null && s !== undefined)
                    : []);
            ui.showModal('conscience', { ...p, spirit_scores_history: freshScores });
        });
        return 'complete';
    } catch (e) {
        console.warn(`Could not fetch audit result for historical message ${messageId}:`, e);
        return 'unavailable';
    }
}

function _pollForAudit(messageId, attempts = 0) {
    const MAX_ATTEMPTS = 10;
    const DELAY = 2000;
    if (attempts >= MAX_ATTEMPTS) return;

    setTimeout(async () => {
        if (!currentConversationId) return;
        const outcome = await fetchAndApplyAuditResult(messageId);
        if (outcome === 'pending') _pollForAudit(messageId, attempts + 1);
    }, DELAY);
}


export function autoSize() {
    const input = ui.elements.messageInput;
    if (!input) return;

    const sendButton = ui.elements.sendButton;

    const hasText = input.value.trim().length > 0;
    sendButton.disabled = !hasText && pendingFiles.length === 0;

    const cs = window.getComputedStyle(input);
    const lineHeight = parseFloat(cs.lineHeight) || 24;
    const padY = (parseFloat(cs.paddingTop) || 0) + (parseFloat(cs.paddingBottom) || 0);
    const MAX_LINES = 5;

    input.style.height = 'auto';
    const lines = Math.max(1, Math.min(MAX_LINES,
        Math.round((input.scrollHeight - padY) / lineHeight)));
    input.style.height = `${Math.round(lines * lineHeight + padY)}px`;

    input.style.overflowY =
        input.scrollHeight > lines * lineHeight + padY + 1 ? 'auto' : 'hidden';
}

window.addEventListener('resize', () => autoSize());


export async function handleConfirmRename(activeProfileData, user) {
    const { id, oldTitle } = convoToRename;
    const newTitle = ui.elements.renameInput.value.trim();

    if (newTitle && newTitle !== oldTitle) {
        try {
            await cache.updateConvoInList(id, { title: newTitle });

            await refreshConvoListOnly(activeProfileData, user, ui.showModal);

            const response = await api.renameConversation(id, newTitle);

            if (response === 'QUEUED') {
                ui.showToast('Rename queued.', 'info');
            } else {
                ui.showToast('Conversation renamed.', 'success');
            }

            await refreshConvoListOnly(activeProfileData, user, ui.showModal);

            if (id === currentConversationId) {
                uiAuthSidebar.updateChatTitle(newTitle);
            }
        } catch (error) {
            ui.showToast('Could not rename conversation.', 'error');
            await cache.updateConvoInList(id, { title: oldTitle });
        }
    }
    ui.closeModal();
    convoToRename = { id: null, oldTitle: null };
}

export async function handleConfirmDelete(activeProfileData, user) {
    const id = convoToDelete;
    if (!id) return;

    try {
        await cache.deleteConvo(id);

        if (id === currentConversationId) {
            currentConversationId = null;
        }

        await refreshConvoListOnly(activeProfileData, user, ui.showModal);

        if (currentConversationId === null) {

            await startNewConversation(false, activeProfileData, user, createDefaultPromptHandler(activeProfileData, user));
        }

        const response = await api.deleteConversation(id);

        if (response === 'QUEUED') {
            ui.showToast('Delete queued.', 'info');
        } else {
            ui.showToast('Conversation deleted.', 'success');
        }

        await refreshConvoListOnly(activeProfileData, user, ui.showModal);

    } catch (error) {
        ui.showToast('Could not delete conversation.', 'error');
    }

    ui.closeModal();
    convoToDelete = null;
}

export async function handleConfirmClearAll(activeProfileData, user) {
    try {
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
