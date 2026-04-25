/**
 * detail.js - 终极修复完整版 (V7)
 * 包含：多选关联、AJAX 上传(无刷新)、Masonry 布局兼容、视频/图片分栏显示、图片防重叠
 */

let currentIndex = 0;
let imageModal = null; 
// 独立存储详情页模态框中的文件
let modalGenFiles = [];
let modalRefFiles = [];
let detailLayoutFrameId = null;
let detailLayoutRestoreFrameId = null;
let detailGridTransitionTimeoutId = null;
let detailRatioGroupsPromise = null;
let detailRatioGroupsLoaded = false;
let detailConversationState = {
    conversationId: null,
    conversation: null,
    isSending: false,
};

// === 多选关联状态 ===
let selectedLinkIds = new Set();

function getCurrentGroupId() {
    const match = location.pathname.match(/\/(?:detail|image)\/(\d+)/);
    return match ? parseInt(match[1], 10) : null;
}

function getDetailPageConfig() {
    const fallback = {
        groupId: null,
        rawPromptContent: 'image',
        sortMode: 'similar',
        ratioFilter: 'all',
        ratioGroupsUrl: null,
    };

    const configEl = document.getElementById('detail-config-data');
    if (!configEl) {
        return fallback;
    }

    try {
        return { ...fallback, ...JSON.parse(configEl.textContent) };
    } catch (error) {
        console.error('Failed to parse detail config:', error);
        return fallback;
    }
}

function escapeDetailConversationHtml(value) {
    return String(value || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function getDetailConversationPanel() {
    return document.getElementById('detail-gpt-conversation-panel');
}

function getDetailConversationRecentPanel() {
    return document.getElementById('detail-gpt-conversation-recent');
}

function getDetailConversationRecentList() {
    return document.getElementById('detail-gpt-conversation-recent-list');
}

function buildDetailPromptMediationRuleBadges(rules) {
    if (!Array.isArray(rules) || !rules.length) {
        return '<span class="small text-muted">未触发专门规则</span>';
    }

    return rules.map((rule) => (
        `<span class="badge rounded-pill text-bg-light border text-secondary">${escapeDetailConversationHtml(rule)}</span>`
    )).join('');
}

function buildDetailPromptMediationRewriteDetails(details) {
    if (!Array.isArray(details) || !details.length) {
        return '<div class="small text-muted">没有发生逐条改写。</div>';
    }

    return details.map((detail) => `
        <div class="border rounded-3 bg-light p-2">
            <div class="small text-muted mb-1 d-flex align-items-center gap-2 flex-wrap"><span class="badge rounded-pill text-bg-light border text-secondary">${escapeDetailConversationHtml(detail.reason_tag || '表达优化')}</span><span>${escapeDetailConversationHtml(detail.reason || '表达优化')}</span></div>
            <div class="small"><span class="text-danger">原文</span> ${escapeDetailConversationHtml(detail.before || '')}</div>
            <div class="small mt-1"><span class="text-success">改写后</span> ${escapeDetailConversationHtml(detail.after || '')}</div>
        </div>
    `).join('');
}

function buildDetailPromptMediationOutline(outline) {
    if (!Array.isArray(outline) || !outline.length) {
        return '<span class="small text-muted">暂无结构提取结果</span>';
    }

    return outline.map((block) => (
        `<span class="badge rounded-pill text-bg-light border text-secondary">${escapeDetailConversationHtml(block.label || block.category)}: ${escapeDetailConversationHtml((block.items || []).join(' / '))}</span>`
    )).join('');
}

function renderDetailConversationPromptMediation(mediation) {
    const panel = document.getElementById('detail-gpt-conversation-mediation-panel');
    const badge = document.getElementById('detail-gpt-conversation-mediation-badge');
    const summary = document.getElementById('detail-gpt-conversation-mediation-summary');
    const details = document.getElementById('detail-gpt-conversation-mediation-details');
    const outline = document.getElementById('detail-gpt-conversation-mediation-outline');
    const optimized = document.getElementById('detail-gpt-conversation-mediation-optimized');
    const rules = document.getElementById('detail-gpt-conversation-mediation-rules');
    if (!panel || !badge || !summary || !details || !outline || !optimized || !rules) return;

    if (!mediation || !mediation.optimized_prompt) {
        panel.style.display = 'none';
        return;
    }

    panel.style.display = 'block';
    badge.textContent = mediation.changed ? '已改写' : '原样透传';
    summary.textContent = mediation.changed ? '这次请求已先经过 GPT Image 2 专用 Prompt 优化层。' : '这次请求未触发额外改写，按原意直接发送。';
    details.innerHTML = buildDetailPromptMediationRewriteDetails(mediation.rewrite_details || []);
    outline.innerHTML = buildDetailPromptMediationOutline(mediation.structured_outline || []);
    optimized.textContent = mediation.optimized_prompt || '';
    rules.innerHTML = buildDetailPromptMediationRuleBadges(mediation.applied_rules || []);
}

function hideDetailConversationPromptMediation() {
    const panel = document.getElementById('detail-gpt-conversation-mediation-panel');
    if (panel) {
        panel.style.display = 'none';
    }
}

function getLatestDetailConversationPromptMediation(conversation) {
    const turns = conversation?.turns || [];
    const latestTurn = turns[turns.length - 1];
    return latestTurn?.response_payload?.prompt_mediation || null;
}

function getDetailConversationParams() {
    return {
        quality: document.getElementById('detail-gpt-conversation-quality')?.value || 'medium',
        image_size_mode: document.getElementById('detail-gpt-conversation-size-mode')?.value || 'custom',
        resolution: document.getElementById('detail-gpt-conversation-resolution')?.value || '2K',
        aspect_ratio: document.getElementById('detail-gpt-conversation-aspect-ratio')?.value || '9:16',
        prompt_optimization_level: document.getElementById('detail-gpt-conversation-optimization-level')?.value || 'balanced',
    };
}

function normalizeDetailConversationOptimizationLevel(value) {
    if (value === 'conservative' || value === 'faithful') return 'balanced';
    if (value === 'visual_rewrite') return 'enhanced';
    return value || 'balanced';
}

function getDetailPromptOptimizationLevelLabel(value) {
    switch (normalizeDetailConversationOptimizationLevel(value)) {
        case 'off':
            return '关闭优化';
        case 'balanced':
            return '保真';
        case 'enhanced':
            return '增强';
        default:
            return '当前等级';
    }
}

async function confirmDetailPromptOptimizationEscalation(data) {
    const attemptedLabel = getDetailPromptOptimizationLevelLabel(data.attempted_optimization_level);
    const nextLabel = getDetailPromptOptimizationLevelLabel(data.next_optimization_level);
    const canRetry = Boolean(data.can_retry_higher && data.next_optimization_level);

    const result = await Swal.fire({
        title: '本轮调图触发审核拦截',
        html: canRetry
            ? `当前尝试等级：<b>${attemptedLabel}</b><br>是否继续升级到 <b>${nextLabel}</b> 再试一次？<br><span class="text-muted small">当前已尝试的优化结果已展示在下方卡片中。</span>`
            : `当前尝试等级：<b>${attemptedLabel}</b><br>已没有更高的优化等级可继续尝试。<br><span class="text-muted small">当前已尝试的优化结果已展示在下方卡片中。</span>`,
        icon: 'warning',
        showCancelButton: canRetry,
        confirmButtonText: canRetry ? `继续升级到${nextLabel}` : '知道了',
        cancelButtonText: '停止本轮',
        confirmButtonColor: '#8a2be2',
    });

    return canRetry && result.isConfirmed;
}

function applyDetailConversationParams(params = {}) {
    const qualityEl = document.getElementById('detail-gpt-conversation-quality');
    const sizeModeEl = document.getElementById('detail-gpt-conversation-size-mode');
    const resolutionEl = document.getElementById('detail-gpt-conversation-resolution');
    const aspectRatioEl = document.getElementById('detail-gpt-conversation-aspect-ratio');
    const optimizationLevelEl = document.getElementById('detail-gpt-conversation-optimization-level');

    if (qualityEl && params.quality) qualityEl.value = params.quality;
    if (sizeModeEl && params.image_size_mode) sizeModeEl.value = params.image_size_mode;
    if (resolutionEl && params.resolution) resolutionEl.value = params.resolution;
    if (aspectRatioEl && params.aspect_ratio) aspectRatioEl.value = params.aspect_ratio;
    if (optimizationLevelEl && params.prompt_optimization_level) optimizationLevelEl.value = normalizeDetailConversationOptimizationLevel(params.prompt_optimization_level);
}

function resolveDetailConversationModelKey() {
    const panel = getDetailConversationPanel();
    if (!panel) return null;

    const modelInfo = String(panel.dataset.modelInfo || '').trim().toLowerCase();
    const provider = String(panel.dataset.provider || '').trim().toLowerCase();
    if (modelInfo !== 'gpt image 2') {
        return null;
    }
    if (provider === 'openai' || provider === 'chatgpt') {
        return 'gpt-image-2-openai';
    }
    if (provider === 'fal_ai') {
        return 'gpt-image-2-edit-fal';
    }
    return null;
}

function getCurrentDetailConversationImage() {
    if (!Array.isArray(window.galleryImages) || window.galleryImages.length === 0) {
        return null;
    }

    const activeItem = window.galleryImages[currentIndex];
    if (activeItem && !activeItem.isVideo) {
        return activeItem;
    }

    return window.galleryImages.find((item) => !item.isVideo) || null;
}

function setDetailConversationStatus(message) {
    const statusEl = document.getElementById('detail-gpt-conversation-status');
    if (statusEl) {
        statusEl.innerText = message;
    }
}

function renderDetailConversationHistory() {
    const historyEl = document.getElementById('detail-gpt-conversation-history');
    if (!historyEl) return;

    const turns = detailConversationState.conversation?.turns || [];
    const activePath = detailConversationState.conversation?.active_image_path || '';
    if (!turns.length) {
        historyEl.innerHTML = '<div class="text-muted small">还没有对话记录。</div>';
        return;
    }

    historyEl.innerHTML = turns.map((turn) => {
        const previewUrl = turn.response_payload?.image_urls?.[0] || '';
        return `
            <div class="border rounded-4 bg-white p-3 mb-2 ${turn.output_image_path === activePath ? 'border-primary' : ''}">
                <div class="d-flex justify-content-between align-items-center mb-2">
                    <span class="badge bg-primary-subtle text-primary border">第 ${turn.turn_index} 轮</span>
                    <span class="text-muted small">${new Date(turn.created_at).toLocaleString()}</span>
                </div>
                <div class="fw-semibold mb-2">${escapeDetailConversationHtml(turn.instruction)}</div>
                ${previewUrl ? `<img src="${previewUrl}" class="img-fluid rounded-3 border mb-2" style="max-height: 160px; object-fit: contain;">` : ''}
                <div class="small text-muted mb-2">${escapeDetailConversationHtml(turn.output_image_path || '本轮输出尚未落地记录')}</div>
                <div class="d-flex flex-wrap gap-2">
                    <button type="button" class="btn btn-sm ${turn.output_image_path === activePath ? 'btn-primary' : 'btn-outline-primary'} rounded-pill" data-turn-id="${turn.id}" data-output-path="${escapeDetailConversationHtml(turn.output_image_path || '')}" onclick="activateDetailConversationTurn(this)">
                        <i class="bi bi-arrow-repeat me-1"></i>${turn.output_image_path === activePath ? '当前基底' : '切换为当前基底'}
                    </button>
                    ${turn.output_image_path ? `<button type="button" class="btn btn-sm btn-outline-success rounded-pill" data-output-path="${escapeDetailConversationHtml(turn.output_image_path)}" onclick="appendDetailConversationTurnToGroup(this)"><i class="bi bi-plus-circle me-1"></i>追加到当前作品</button>` : ''}
                </div>
            </div>
        `;
    }).join('');
}

function renderDetailConversationRecentList(conversations) {
    const recentPanel = getDetailConversationRecentPanel();
    const recentList = getDetailConversationRecentList();
    if (!recentPanel || !recentList) return;

    if (!conversations || conversations.length === 0) {
        recentPanel.style.display = 'none';
        recentList.innerHTML = '';
        return;
    }

    recentPanel.style.display = 'block';
    recentList.innerHTML = conversations.map((conversation) => `
        <button type="button" class="btn btn-sm btn-outline-secondary text-start rounded-4 px-3 py-2" data-conversation-id="${conversation.conversation_id}" onclick="restoreDetailConversation(this)">
            <div class="fw-semibold text-truncate">${escapeDetailConversationHtml(conversation.last_instruction || conversation.initial_prompt || '未命名会话')}</div>
            <div class="small text-muted d-flex justify-content-between gap-2">
                <span>${escapeDetailConversationHtml(conversation.model_label || 'GPT Image 2')} · ${conversation.turn_count} 轮</span>
                <span>${new Date(conversation.updated_at).toLocaleString()}</span>
            </div>
        </button>
    `).join('');
}

async function loadRecentDetailConversations() {
    const detailConfig = window.detailConfig || getDetailPageConfig();
    if (!detailConfig.groupId) {
        return;
    }

    try {
        const response = await fetch(`/api/gpt-image-conversations/recent/?source_page=detail&source_prompt_group_id=${detailConfig.groupId}&limit=6`);
        const data = await response.json();
        if (data.status === 'success') {
            renderDetailConversationRecentList(data.conversations || []);
        }
    } catch (error) {
        console.error(error);
    }
}

function updateDetailConversationPanelVisibility() {
    const panel = getDetailConversationPanel();
    if (!panel) return;

    const modelKey = resolveDetailConversationModelKey();
    panel.style.display = modelKey ? 'block' : 'none';
    if (!modelKey) {
        hideDetailConversationPromptMediation();
    }
    const recentPanel = getDetailConversationRecentPanel();
    if (recentPanel && !modelKey) {
        recentPanel.style.display = 'none';
    }
    if (!modelKey) return;

    const currentImage = getCurrentDetailConversationImage();
    if (!detailConversationState.conversationId) {
        setDetailConversationStatus(currentImage ? `将基于当前图片 #${currentImage.id} 发起对话调整。` : '当前作品没有可用于调图的图片。');
        return;
    }

    setDetailConversationStatus('会话已创建，后续每轮将基于当前会话的激活结果继续调整。');
}

function resetDetailConversationState() {
    detailConversationState.conversationId = null;
    detailConversationState.conversation = null;
    detailConversationState.isSending = false;
    hideDetailConversationPromptMediation();
    renderDetailConversationHistory();
    updateDetailConversationPanelVisibility();
}

async function restoreDetailConversation(buttonEl) {
    const conversationId = buttonEl?.dataset?.conversationId;
    if (!conversationId) return;

    try {
        const response = await fetch(`/api/gpt-image-conversations/${conversationId}/`);
        const data = await response.json();
        if (data.status !== 'success') {
            throw new Error(data.message || '恢复会话失败');
        }

        detailConversationState.conversationId = data.conversation.conversation_id;
        detailConversationState.conversation = data.conversation;
        applyDetailConversationParams(data.conversation.latest_params || {});
        renderDetailConversationPromptMediation(getLatestDetailConversationPromptMediation(data.conversation));
        renderDetailConversationHistory();

        const activeImageId = data.conversation.active_image_id;
        if (activeImageId && Array.isArray(window.galleryImages)) {
            const index = window.galleryImages.findIndex((item) => item.id === activeImageId);
            if (index !== -1) {
                currentIndex = index;
            }
        }

        updateDetailConversationPanelVisibility();
        Swal.fire({ toast: true, position: 'top', icon: 'success', title: '已恢复最近会话', showConfirmButton: false, timer: 1800 });
    } catch (error) {
        Swal.fire('恢复失败', error.message || '未知错误', 'error');
    }
}

async function syncDetailConversationActiveImage(imageId, imageUrl = '') {
    if (!detailConversationState.conversationId || !imageId) return;

    const formData = new FormData();
    formData.append('image_id', imageId);
    if (imageUrl) {
        formData.append('image_path', imageUrl);
    }

    try {
        const response = await fetch(`/api/gpt-image-conversations/${detailConversationState.conversationId}/active-result/`, {
            method: 'POST',
            body: formData,
        });
        const data = await response.json();
        if (data.status === 'success') {
            detailConversationState.conversation = {
                ...(detailConversationState.conversation || {}),
                ...data.conversation,
            };
            renderDetailConversationHistory();
            updateDetailConversationPanelVisibility();
        }
    } catch (error) {
        console.error(error);
    }
}

async function activateDetailConversationTurn(buttonEl) {
    const turnId = buttonEl?.dataset?.turnId;
    const outputPath = buttonEl?.dataset?.outputPath || '';
    if (!detailConversationState.conversationId || !turnId) return;

    const formData = new FormData();
    formData.append('turn_id', turnId);
    if (outputPath) {
        formData.append('image_path', outputPath);
    }

    try {
        const response = await fetch(`/api/gpt-image-conversations/${detailConversationState.conversationId}/active-result/`, {
            method: 'POST',
            body: formData,
        });
        const data = await response.json();
        if (data.status !== 'success') {
            throw new Error(data.message || '切换当前基底失败');
        }

        detailConversationState.conversation = {
            ...(detailConversationState.conversation || {}),
            ...data.conversation,
        };
        renderDetailConversationHistory();
        updateDetailConversationPanelVisibility();
    } catch (error) {
        Swal.fire('切换失败', error.message || '未知错误', 'error');
    }
}

async function appendDetailConversationTurnToGroup(buttonEl) {
    const outputPath = buttonEl?.dataset?.outputPath || '';
    const detailConfig = window.detailConfig || getDetailPageConfig();
    const groupId = detailConfig.groupId || getCurrentGroupId();
    if (!outputPath || !groupId) {
        Swal.fire('追加失败', '缺少当前作品或输出图片路径', 'error');
        return;
    }

    buttonEl.disabled = true;
    const originalHtml = buttonEl.innerHTML;
    buttonEl.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>追加中';

    try {
        const formData = new FormData();
        formData.append('group_id', groupId);
        formData.append('saved_paths', outputPath);

        const response = await fetch('/api/append-to-existing-group/', {
            method: 'POST',
            body: formData,
        });
        const data = await response.json();
        if (data.status !== 'success') {
            throw new Error(data.message || '追加失败');
        }

        applyDetailNewImagesResponse(data);
        Swal.fire({ toast: true, position: 'top', icon: 'success', title: '已追加到当前作品', showConfirmButton: false, timer: 1600 });
        buttonEl.disabled = false;
        buttonEl.innerHTML = '<i class="bi bi-check2 me-1"></i>已追加';
    } catch (error) {
        Swal.fire('追加失败', error.message || '未知错误', 'error');
        buttonEl.disabled = false;
        buttonEl.innerHTML = originalHtml;
    }
}

async function ensureDetailConversation() {
    if (detailConversationState.conversationId) {
        return detailConversationState.conversation;
    }

    const modelKey = resolveDetailConversationModelKey();
    if (!modelKey) {
        throw new Error('当前作品不是可对话调图的 GPT Image 2 作品');
    }

    const currentImage = getCurrentDetailConversationImage();
    if (!currentImage || !currentImage.id) {
        throw new Error('当前没有可作为基底图的图片');
    }

    const detailConfig = window.detailConfig || getDetailPageConfig();
    const formData = new FormData();
    formData.append('source_page', 'detail');
    formData.append('model_choice', modelKey);
    formData.append('source_prompt_group_id', detailConfig.groupId || getCurrentGroupId());
    formData.append('source_image_id', currentImage.id);
    formData.append('active_image_id', currentImage.id);
    formData.append('prompt', detailConfig.rawPromptContent || '');
    formData.append('latest_params', JSON.stringify(getDetailConversationParams()));

    const response = await fetch('/api/gpt-image-conversations/', {
        method: 'POST',
        body: formData,
    });
    const data = await response.json();
    if (data.status !== 'success') {
        throw new Error(data.message || '创建详情页调图会话失败');
    }

    detailConversationState.conversationId = data.conversation.conversation_id;
    detailConversationState.conversation = data.conversation;
    renderDetailConversationHistory();
    updateDetailConversationPanelVisibility();
    loadRecentDetailConversations();
    return data.conversation;
}

async function sendDetailConversationMessage() {
    const inputEl = document.getElementById('detail-gpt-conversation-input');
    const sendBtn = document.getElementById('detail-gpt-conversation-send');
    if (!inputEl || !sendBtn || detailConversationState.isSending) return;

    const instruction = inputEl.value.trim();
    if (!instruction) {
        Swal.fire('提示', '请输入本轮调图指令', 'warning');
        return;
    }

    detailConversationState.isSending = true;
    sendBtn.disabled = true;
    sendBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>发送中';

    try {
        await ensureDetailConversation();
        let nextOptimizationLevel = '';

        while (true) {
            const formData = new FormData();
            formData.append('instruction', instruction);
            formData.append('adaptive_prompt_optimization', 'true');
            Object.entries(getDetailConversationParams()).forEach(([key, value]) => formData.append(key, value));
            if (nextOptimizationLevel) {
                formData.append('next_optimization_level', nextOptimizationLevel);
            }

            const response = await fetch(`/api/gpt-image-conversations/${detailConversationState.conversationId}/turns/`, {
                method: 'POST',
                body: formData,
            });
            const data = await response.json();
            if (data.status === 'success') {
                detailConversationState.conversation = data.conversation;
                renderDetailConversationPromptMediation(data.prompt_mediation || getLatestDetailConversationPromptMediation(data.conversation));
                renderDetailConversationHistory();
                inputEl.value = '';
                loadRecentDetailConversations();
                Swal.fire({ toast: true, position: 'top', icon: 'success', title: '已追加一轮对话调图', showConfirmButton: false, timer: 2200 });
                break;
            }

            if (data.prompt_mediation) {
                renderDetailConversationPromptMediation(data.prompt_mediation);
            }
            if (data.status === 'moderation_failed') {
                const shouldRetry = await confirmDetailPromptOptimizationEscalation(data);
                if (shouldRetry) {
                    nextOptimizationLevel = data.next_optimization_level || '';
                    continue;
                }
                setDetailConversationStatus('本轮触发审核拦截，已保留当前尝试的优化结果。');
                break;
            }

            throw new Error(data.message || '详情页对话调图失败');
        }
    } catch (error) {
        Swal.fire('对话调图失败', error.message || '未知错误', 'error');
    } finally {
        detailConversationState.isSending = false;
        sendBtn.disabled = false;
        sendBtn.innerHTML = '<i class="bi bi-send me-1"></i>发送';
        updateDetailConversationPanelVisibility();
    }
}

function applyDetailRatioGroups(ratioGroups) {
    Object.entries(ratioGroups || {}).forEach(([imageId, ratioGroup]) => {
        const card = document.querySelector(`#detail-masonry-grid-images .grid-item[data-img-id="${imageId}"]`);
        if (card && ratioGroup) {
            card.dataset.ratioGroup = ratioGroup;
        }
    });
}

function ensureDetailRatioGroupsLoaded() {
    if (detailRatioGroupsLoaded) {
        return Promise.resolve();
    }

    if (detailRatioGroupsPromise) {
        return detailRatioGroupsPromise;
    }

    const detailConfig = window.detailConfig || getDetailPageConfig();
    if (!detailConfig.ratioGroupsUrl) {
        return Promise.resolve();
    }

    detailRatioGroupsPromise = fetch(detailConfig.ratioGroupsUrl, {
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
    })
        .then((response) => {
            if (!response.ok) {
                throw new Error(`Failed to load detail ratio groups: ${response.status}`);
            }
            return response.json();
        })
        .then((payload) => {
            if (payload.status === 'success') {
                applyDetailRatioGroups(payload.ratio_groups);
                detailRatioGroupsLoaded = true;
            }
        })
        .catch((error) => {
            console.error(error);
        })
        .finally(() => {
            if (!detailRatioGroupsLoaded) {
                detailRatioGroupsPromise = null;
            }
        });

    return detailRatioGroupsPromise;
}

function warmDetailRatioGroupsInBackground() {
    const startWarmup = () => {
        ensureDetailRatioGroupsLoaded().then(() => {
            if ((window.currentDetailRatioFilter || 'all') !== 'all') {
                applyDetailRatioFilter(window.currentDetailRatioFilter || 'all', { syncUrl: false, animate: false });
            }
        });
    };

    if (typeof window.requestIdleCallback === 'function') {
        window.requestIdleCallback(startWarmup, { timeout: 1200 });
    } else {
        window.setTimeout(startWarmup, 180);
    }
}

function syncDetailQueryParam(paramName, value, defaultValue, reloadPage = false) {
    const url = new URL(window.location.href);

    if (!value || value === defaultValue) {
        url.searchParams.delete(paramName);
    } else {
        url.searchParams.set(paramName, value);
    }

    const queryString = url.searchParams.toString();
    const nextUrl = `${url.pathname}${queryString ? `?${queryString}` : ''}${url.hash}`;

    if (reloadPage) {
        window.location.href = nextUrl;
        return;
    }

    window.history.replaceState({}, '', nextUrl);
}

function setActiveDetailSortMode(sortMode) {
    document.querySelectorAll('#detail-sort-filter [data-sort-value]').forEach((button) => {
        button.classList.toggle('active', button.dataset.sortValue === sortMode);
    });
}

function syncGalleryImagesFromCurrentLayout() {
    if (!Array.isArray(window.galleryImages)) {
        return;
    }

    const mediaById = new Map(window.galleryImages.map((item) => [String(item.id), item]));
    const orderedImageItems = Array.from(
        document.querySelectorAll('#detail-masonry-grid-images .grid-item[data-media-type="image"]')
    )
        .map((card) => mediaById.get(card.dataset.imgId))
        .filter(Boolean);

    const videoItems = window.galleryImages.filter((item) => item.isVideo);
    window.galleryImages = [...orderedImageItems, ...videoItems];
}

function getDetailCardSortOrder(card, sortMode) {
    if (!card) {
        return 0;
    }

    const datasetKey = sortMode === 'latest' ? 'sortLatest' : 'sortSimilar';
    return parseInt(card.dataset[datasetKey] || '0', 10);
}

function syncMasonryOrderWithCards(sortMode) {
    if (!window.msnryImages || !Array.isArray(window.msnryImages.items)) {
        return;
    }

    window.msnryImages.items.sort((leftItem, rightItem) => {
        return getDetailCardSortOrder(leftItem.element, sortMode) - getDetailCardSortOrder(rightItem.element, sortMode);
    });
}

function sortDetailImageCards(sortMode, options = {}) {
    const { syncUrl = true, animate = false } = options;
    const grid = document.getElementById('detail-masonry-grid-images');
    if (!grid) {
        return;
    }

    const cards = Array.from(grid.querySelectorAll('.grid-item[data-media-type="image"]'));
    if (!cards.length) {
        return;
    }

    const normalizedSortMode = sortMode === 'latest' ? 'latest' : 'similar';
    cards.sort((leftCard, rightCard) => {
        return getDetailCardSortOrder(leftCard, normalizedSortMode) - getDetailCardSortOrder(rightCard, normalizedSortMode);
    });

    const fragment = document.createDocumentFragment();
    cards.forEach((card) => fragment.appendChild(card));
    grid.appendChild(fragment);
    syncMasonryOrderWithCards(normalizedSortMode);

    window.detailConfig = { ...(window.detailConfig || {}), sortMode: normalizedSortMode };
    setActiveDetailSortMode(normalizedSortMode);

    syncGalleryImagesFromCurrentLayout();
    relayoutDetailImages({ animate });

    if (syncUrl) {
        syncDetailQueryParam('sort', normalizedSortMode, 'similar');
    }
}

function relayoutDetailImages(options = {}) {
    const { animate = false } = options;
    if (window.msnryImages) {
        const grid = document.getElementById('detail-masonry-grid-images');
        const gridItems = document.querySelectorAll('#detail-masonry-grid-images .grid-item[data-media-type="image"]');
        const previousTransitionDuration = window.msnryImages.options.transitionDuration;

        if (grid) {
            grid.style.minHeight = `${Math.ceil(grid.getBoundingClientRect().height)}px`;
            if (animate) {
                grid.classList.add('detail-grid-transitioning');
            }
        }

        gridItems.forEach((card) => {
            const isHidden = card.classList.contains('ratio-filter-hidden');

            if (isHidden) {
                if (typeof window.msnryImages.ignore === 'function') {
                    window.msnryImages.ignore(card);
                }
                card.style.left = '';
                card.style.top = '';
            } else if (typeof window.msnryImages.unignore === 'function') {
                window.msnryImages.unignore(card);
            }
        });

        if (detailLayoutFrameId) {
            cancelAnimationFrame(detailLayoutFrameId);
        }
        if (detailLayoutRestoreFrameId) {
            cancelAnimationFrame(detailLayoutRestoreFrameId);
        }
        if (detailGridTransitionTimeoutId) {
            clearTimeout(detailGridTransitionTimeoutId);
        }

        window.msnryImages.options.transitionDuration = 0;

        detailLayoutFrameId = requestAnimationFrame(() => {
            window.msnryImages.layout();

            detailLayoutRestoreFrameId = requestAnimationFrame(() => {
                window.msnryImages.layout();

                window.msnryImages.options.transitionDuration = previousTransitionDuration;
                if (grid) {
                    grid.style.minHeight = '';
                    if (animate) {
                        detailGridTransitionTimeoutId = setTimeout(() => {
                            grid.classList.remove('detail-grid-transitioning');
                            detailGridTransitionTimeoutId = null;
                        }, 120);
                    } else {
                        grid.classList.remove('detail-grid-transitioning');
                    }
                }

                detailLayoutFrameId = null;
                detailLayoutRestoreFrameId = null;
            });
        });
    }
}

function updateDetailImageCountBadge(visibleCount) {
    const badge = document.getElementById('image-count-badge');
    if (!badge) {
        return;
    }

    const totalCount = parseInt(badge.dataset.totalCount || '0', 10);
    const ratioFilter = window.currentDetailRatioFilter || 'all';
    badge.textContent = ratioFilter === 'all' ? `${totalCount}` : `${visibleCount} / ${totalCount}`;
}

function setActiveDetailRatioFilter(filterValue) {
    document.querySelectorAll('#detail-ratio-filter [data-ratio-value]').forEach((button) => {
        button.classList.toggle('active', button.dataset.ratioValue === filterValue);
    });
}

function classifyDetailImageCard(card) {
    if (!card || card.dataset.mediaType !== 'image') {
        return null;
    }

    const existingRatioGroup = card.dataset.ratioGroup;
    if (existingRatioGroup && existingRatioGroup !== 'pending' && existingRatioGroup !== 'unknown') {
        return existingRatioGroup;
    }

    const image = card.querySelector('img.thumb-img');
    if (!image || !image.complete || image.naturalWidth <= 0 || image.naturalHeight <= 0) {
        return null;
    }

    const aspectRatio = image.naturalWidth / image.naturalHeight;
    let ratioGroup = 'square';

    if (aspectRatio > 1.05) {
        ratioGroup = 'landscape';
    } else if (aspectRatio < 0.95) {
        ratioGroup = 'portrait';
    }

    card.dataset.ratioGroup = ratioGroup;
    return ratioGroup;
}

function applyDetailRatioFilter(filterValue, options = {}) {
    const { syncUrl = true, animate = false } = options;
    const cards = document.querySelectorAll('#detail-masonry-grid-images .grid-item[data-media-type="image"]');

    window.currentDetailRatioFilter = filterValue;
    setActiveDetailRatioFilter(filterValue);

    let visibleCount = 0;
    cards.forEach((card) => {
        const ratioGroup = classifyDetailImageCard(card) || card.dataset.ratioGroup || 'unknown';
        const isVisible = filterValue === 'all' || ratioGroup === filterValue;
        card.classList.toggle('ratio-filter-hidden', !isVisible);
        if (isVisible) {
            visibleCount += 1;
        }
    });

    updateDetailImageCountBadge(visibleCount);
    relayoutDetailImages({ animate });

    if (syncUrl) {
        syncDetailQueryParam('ratio', filterValue, 'all');
    }
}

function initializeDetailOrganizer() {
    const sortButtons = document.querySelectorAll('#detail-sort-filter [data-sort-value]');
    const ratioButtons = document.querySelectorAll('#detail-ratio-filter [data-ratio-value]');
    const imageCards = document.querySelectorAll('#detail-masonry-grid-images .grid-item[data-media-type="image"]');

    if (!sortButtons.length && !ratioButtons.length) {
        return;
    }

    const detailConfig = window.detailConfig || getDetailPageConfig();
    const initialRatioFilter = detailConfig.ratioFilter || 'all';
    const initialSortMode = detailConfig.sortMode || 'similar';

    sortButtons.forEach((button) => {
        button.addEventListener('click', () => {
            const nextSortMode = button.dataset.sortValue || 'similar';
            sortDetailImageCards(nextSortMode, { animate: true });
        });
    });

    ratioButtons.forEach((button) => {
        button.addEventListener('click', () => {
            const nextRatioFilter = button.dataset.ratioValue || 'all';
            if (nextRatioFilter === 'all') {
                applyDetailRatioFilter(nextRatioFilter, { animate: true });
                return;
            }

            ensureDetailRatioGroupsLoaded().finally(() => {
                applyDetailRatioFilter(nextRatioFilter, { animate: true });
            });
        });
    });

    imageCards.forEach((card) => {
        const image = card.querySelector('img.thumb-img');
        if (!image) {
            return;
        }

        if (image.complete && image.naturalWidth > 0 && image.naturalHeight > 0) {
            classifyDetailImageCard(card);
            return;
        }

        image.addEventListener('load', () => {
            classifyDetailImageCard(card);
            applyDetailRatioFilter(window.currentDetailRatioFilter || 'all', { syncUrl: false, animate: false });
        }, { once: true });
    });

    setActiveDetailSortMode(initialSortMode);
    sortDetailImageCards(initialSortMode, { syncUrl: false, animate: false });

    if (initialRatioFilter === 'all') {
        applyDetailRatioFilter(initialRatioFilter, { syncUrl: false, animate: false });
        warmDetailRatioGroupsInBackground();
    } else {
        ensureDetailRatioGroupsLoaded().finally(() => {
            applyDetailRatioFilter(initialRatioFilter, { syncUrl: false, animate: false });
        });
    }
}

// === 新增：视频布局自适应函数 ===
function adjustVideoLayout(video) {
    if (video.videoWidth > 0 && video.videoHeight > 0) {
        // 1. 计算视频实际宽高比
        const ratioPercent = (video.videoHeight / video.videoWidth) * 100;
        const isVertical = video.videoHeight > video.videoWidth;
        
        const card = video.closest('.grid-item');
        const ratioContainer = video.closest('.ratio'); // 获取视频外层的容器

        // 2. 调整容器比例，消除黑边
        if (ratioContainer) {
            // 将容器的比例设置为视频的真实比例
            ratioContainer.style.setProperty('--bs-aspect-ratio', `${ratioPercent}%`);
        }

        // 3. 调整卡片宽度 (横屏全宽，竖屏窄卡片)
        if (card) {
            if (isVertical) {
                // 竖屏：窄卡片 (1/3 或 1/4 宽)
                card.classList.remove('video-wide-item', 'col-12');
                card.classList.add('col-6', 'col-md-4', 'col-lg-3');
            } else {
                // 横屏：全宽 (100% 宽)
                card.classList.add('video-wide-item', 'col-12');
                card.classList.remove('col-6', 'col-md-4', 'col-lg-3');
            }
        }
        
        // 4. 通知 Masonry 重新布局 (防止卡片重叠)
        if (window.msnryImages) {
            window.msnryImages.layout();
        }
    }
}

// === 初始化逻辑 ===
document.addEventListener('DOMContentLoaded', function() {
    // 1. 读取相册数据
    const dataElement = document.getElementById('gallery-data');
    if (dataElement) {
        window.galleryImages = JSON.parse(dataElement.textContent);
    }

    window.detailConfig = { ...getDetailPageConfig(), ...(window.detailConfig || {}) };

    // 2. 初始化大图模态框
    const modalEl = document.getElementById('imageModal');
    if (modalEl) {
        imageModal = new bootstrap.Modal(modalEl);
        
        // 【新增】监听模态框关闭事件，关闭时自动暂停视频
        modalEl.addEventListener('hidden.bs.modal', function () {
            const vid = document.getElementById('previewVideo');
            if (vid) vid.pause();
        });
    }
    
    // 3. 初始化 Masonry (针对图片栏)
    // 注意：HTML中ID已改为 detail-masonry-grid-images
    const imgGrid = document.querySelector('#detail-masonry-grid-images');
    if (imgGrid && typeof Masonry !== 'undefined') {
        window.msnryImages = new Masonry(imgGrid, {
            itemSelector: '.grid-item', // 确保 HTML item 有此类名
            percentPosition: true
        });

        if (typeof imagesLoaded !== 'undefined') {
            imagesLoaded(imgGrid).on('progress', function() {
                window.msnryImages.layout();
            });
        }
    }

    initializeDetailOrganizer();

    //  视频布局自动调整 (针对页面加载时已存在的视频)
    const videos = document.querySelectorAll('#detail-masonry-grid-videos video');
    videos.forEach(vid => {
        if (vid.readyState >= 1) {
            adjustVideoLayout(vid);
        } else {
            vid.addEventListener('loadedmetadata', () => adjustVideoLayout(vid));
        }
    });

    // 4. 键盘事件
    document.addEventListener('keydown', function(event) {
        if (modalEl && modalEl.classList.contains('show')) {
            if (event.key === 'ArrowLeft') changeImage(-1);
            if (event.key === 'ArrowRight') changeImage(1);
            if (event.key === 'Escape') imageModal.hide();
        }
    });

    // 5. 点击外部关闭标签输入
    document.addEventListener('click', function(event) {
        const container = document.getElementById('tagInputContainer');
        const addBtn = document.getElementById('btnAddTag');
        if (container && container.classList.contains('show')) {
            if (!container.contains(event.target) && !addBtn.contains(event.target)) {
                if (!document.getElementById('newTagInput').value.trim()) {
                    resetTagInput();
                }
            }
        }
    });

    // 6. 初始化拖拽上传
    setupInlineDragDrop('inline-trigger-gen', 'addImagesModal', 'gen');
    setupInlineDragDrop('inline-trigger-ref', 'addReferenceModal', 'ref');
    setupDetailDragDrop('zone-modal-gen', 'input-modal-gen', 'preview-modal-gen', 'gen');
    setupDetailDragDrop('zone-modal-ref', 'input-modal-ref', 'preview-modal-ref', 'ref');

    // 8. 【新增】进入详情页时，如果有 source_img_id，则直接定位到该图片
    const urlParams = new URLSearchParams(window.location.search);
    const sourceId = urlParams.get('source_img_id');
    
    if (sourceId) {
        // 尝试找到目标元素的锚点 (ID 为 img-anchor-数字)
        const targetEl = document.getElementById(`img-anchor-${sourceId}`);
        if (targetEl) {
            // 使用 setTimeout 确保页面DOM已渲染
            setTimeout(() => {
                // 【核心】behavior: 'auto' 确保是瞬间跳转 (无滚动动画)
                // block: 'center' 确保目标位于屏幕中间
                targetEl.scrollIntoView({ behavior: 'auto', block: 'center' });
                
                // 【可选】添加高亮闪烁效果，方便用户在杂乱的图中一眼看到 (利用 style.css 已有的动画类)
                const card = targetEl.querySelector('.detail-img-card');
                if (card) {
                    card.classList.add('highlight-pulse');
                    setTimeout(() => card.classList.remove('highlight-pulse'), 2000);
                }
            }, 100); 
        }
    }

});

// ================= 图片模态框逻辑 (大图预览) =================

function openModal(el, index) {
    
    
    // 兼容：如果传入的是 DOM 元素，尝试获取 ID
    // 如果传入的是 index (旧逻辑)，则直接使用
    if (typeof el === 'object') {
        // 这里只是为了阻止视频点击，实际打开逻辑复用 showModal 或直接往下走
        // 假设 showModal(id) 是主入口
    }
    
    // 如果直接传了 index
    if (typeof index === 'number') {
        currentIndex = index;
        updateModalImage();
        imageModal.show();
    }
}

function showModal(id) {
    if (window.galleryImages) {
        const index = window.galleryImages.findIndex(img => img.id === id);
        if (index !== -1) {
            currentIndex = index;
            updateModalImage();
            imageModal.show();
            const currentItem = window.galleryImages[index];
            if (currentItem && !currentItem.isVideo) {
                syncDetailConversationActiveImage(currentItem.id, currentItem.url);
            }
        } else {
            console.error("Image ID not found:", id);
        }
    }
}

function changeImage(direction) {
    if (!window.galleryImages) return;
    currentIndex += direction;
    if (currentIndex >= galleryImages.length) { currentIndex = 0; } 
    else if (currentIndex < 0) { currentIndex = galleryImages.length - 1; }
    updateModalImage();
}

function updateModalImage() {
    const imgElement = document.getElementById('previewImage');
    const vidElement = document.getElementById('previewVideo'); // 必须能在 HTML 中找到这个 ID
    const downloadBtn = document.getElementById('modalDownloadBtn');
    const deleteForm = document.getElementById('modalDeleteForm');
    const counterElement = document.getElementById('imageCounter');
    const likeBtn = document.getElementById('modalLikeBtn');

    if (!galleryImages || galleryImages.length === 0) return;

    const currentImgData = galleryImages[currentIndex];

    // === 核心修改：区分视频和图片 ===
    if (currentImgData.isVideo) {
        // 1. 如果是视频
        if (imgElement) {
            imgElement.style.display = 'none';
            imgElement.src = ""; // 停止加载图片
        }
        
        if (vidElement) {
            vidElement.style.display = 'block';
            vidElement.src = currentImgData.url;
            vidElement.load(); // 【关键】强制重载视频，防止一直转圈
            
            // 尝试自动播放
            const playPromise = vidElement.play();
            if (playPromise !== undefined) {
                playPromise.catch(error => {
                    console.log("自动播放被拦截:", error);
                });
            }
        }
    } else {
        // 2. 如果是图片
        if (vidElement) {
            vidElement.style.display = 'none';
            vidElement.pause();
            vidElement.removeAttribute('src'); // 清除视频源
            vidElement.load(); // 停止视频缓冲
        }
        
        if (imgElement) {
            imgElement.style.display = 'block';
            imgElement.style.opacity = '0.5';
            imgElement.src = currentImgData.url;
            imgElement.onload = function() { imgElement.style.opacity = '1'; };
        }
    }

    // 更新按钮链接和状态
    if (downloadBtn) downloadBtn.href = currentImgData.url;
    if (deleteForm) deleteForm.action = `/delete-image/${currentImgData.id}/`;
    if (counterElement) counterElement.innerText = `${currentIndex + 1} / ${galleryImages.length}`;
    
    if (likeBtn) {
        if (currentImgData.isLiked) {
            likeBtn.classList.add('active');
            likeBtn.innerHTML = '<i class="bi bi-heart-fill"></i> 已喜欢';
        } else {
            likeBtn.classList.remove('active');
            likeBtn.innerHTML = '<i class="bi bi-heart"></i> 喜欢';
        }
    }
}

function toggleModalLike() {
    const currentImgData = galleryImages[currentIndex];
    const csrftoken = getCookie('csrftoken');
    
    fetch(`/toggle-like-image/${currentImgData.id}/`, {
        method: 'POST',
        headers: { 'X-CSRFToken': csrftoken, 'Content-Type': 'application/json' }
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            currentImgData.isLiked = data.is_liked;
            updateModalImage(); 
            const listBtn = document.getElementById(`like-btn-${currentImgData.id}`);
            if (listBtn) {
                const icon = listBtn.querySelector('i');
                if (data.is_liked) {
                    listBtn.classList.add('active');
                    icon.classList.remove('bi-heart'); icon.classList.add('bi-heart-fill');
                } else {
                    listBtn.classList.remove('active');
                    icon.classList.remove('bi-heart-fill'); icon.classList.add('bi-heart');
                }
            }
        }
    });
}

function toggleImageLike(event, pk) {
    event.stopPropagation(); 
    const btn = event.currentTarget;
    const csrftoken = getCookie('csrftoken');
    const icon = btn.querySelector('i');
    
    fetch(`/toggle-like-image/${pk}/`, {
        method: 'POST',
        headers: { 'X-CSRFToken': csrftoken, 'Content-Type': 'application/json' }
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            if (data.is_liked) {
                btn.classList.add('active');
                icon.classList.remove('bi-heart'); icon.classList.add('bi-heart-fill');
            } else {
                btn.classList.remove('active');
                icon.classList.remove('bi-heart-fill'); icon.classList.add('bi-heart');
            }
            if (window.galleryImages) {
                const imgData = galleryImages.find(img => img.id === pk);
                if (imgData) { imgData.isLiked = data.is_liked; }
            }
        }
    });
}

// === 标题双击编辑功能 ===
function enableTitleEdit(element, pk) {
    const originalText = element.innerText;
    
    element.contentEditable = "true";
    element.focus();
    element.style.outline = "2px solid #0d6efd"; 
    element.style.borderRadius = "4px";
    element.style.padding = "0 5px";

    const range = document.createRange();
    range.selectNodeContents(element);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);

    const save = () => {
        element.onkeydown = null;
        element.onblur = null;
        
        element.contentEditable = "false";
        element.style.outline = "";
        element.style.borderRadius = "";
        element.style.padding = "";

        const newText = element.innerText.trim();

        if (newText === originalText || newText === "") {
            element.innerText = originalText;
            if (newText === "") Swal.fire('提示', '标题不能为空', 'warning');
            return;
        }

        const csrftoken = getCookie('csrftoken');
        fetch(`/update-prompts/${pk}/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrftoken },
            body: JSON.stringify({ title: newText })
        })
        .then(res => res.json())
        .then(data => {
            if (data.status === 'success') {
                Swal.fire({
                    icon: 'success', title: '标题已更新', toast: true, position: 'top-end', showConfirmButton: false, timer: 1500
                });
            } else {
                element.innerText = originalText;
                Swal.fire('更新失败', data.message || '未知错误', 'error');
            }
        })
        .catch(err => {
            element.innerText = originalText;
            console.error(err);
            Swal.fire('错误', '网络请求失败', 'error');
        });
    };

    element.onkeydown = (e) => {
        if (e.key === 'Enter') { e.preventDefault(); element.blur(); }
        else if (e.key === 'Escape') { element.innerText = originalText; element.blur(); }
    };
    element.onblur = save;
}

// === AJAX 删除逻辑 (兼容分栏) ===
function confirmDelete(event) {
    event.preventDefault(); 
    const btn = event.currentTarget;
    const form = btn.closest('form');
    const url = form.action;
    
    const isModal = btn.closest('#imageModal') !== null;
    // 关键判断：当前点击的是否为参考图区域
    const isReference = btn.closest('#reference-grid') !== null;

    Swal.fire({
        title: '确定要删除吗？',
        text: "此操作无法撤销！文件将被永久删除。",
        icon: 'warning', 
        showCancelButton: true, 
        confirmButtonColor: '#dc3545', 
        cancelButtonColor: '#6c757d', 
        confirmButtonText: '是的，彻底删除', 
        cancelButtonText: '取消',
        background: 'rgba(255, 255, 255, 0.95)', 
        customClass: { popup: 'rounded-4 shadow-lg border-0' }
    }).then((result) => { 
        if (result.isConfirmed) {
            const csrftoken = getCookie('csrftoken');
            const originalHtml = btn.innerHTML;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
            btn.disabled = true;

            fetch(url, {
                method: 'POST',
                headers: { 'X-CSRFToken': csrftoken, 'X-Requested-With': 'XMLHttpRequest' }
            })
            .then(response => response.json())
            .then(data => {
                if (data.status === 'success') {
                    // 处理整组删除
                    if (data.type === 'group') {
                        // 1. 读取当前详情页 URL 上附带的所有查询参数 (例如: ?page=3&q=猫咪&from=liked)
                        const currentParams = window.location.search;
                        const urlParams = new URLSearchParams(currentParams);
                        
                        // 2. 智能判断要退回的基础路径（是从首页进来的，还是从“喜欢”列表进来的）
                        let redirectPath = '/';
                        if (urlParams.get('from') === 'liked') {
                            redirectPath = '/liked-images/';
                        }
                        
                        // 3. 将原有的分页、搜索条件拼接到重定向 URL 中
                        window.location.href = redirectPath + currentParams; 
                        return;
                    }
                    
                    const deletedId = parseInt(data.pk);

                    // ===========================================
                    // 1. 处理参考图删除 (您丢失的逻辑补回来了)
                    // ===========================================
                    if (isReference) {
                        const col = btn.closest('.col');
                        if (col) {
                            col.style.transition = 'all 0.3s ease';
                            col.style.transform = 'scale(0)';
                            setTimeout(() => col.remove(), 300);
                        }
                    }
                    // ===========================================
                    // 2. 处理生成图/视频删除 (包含之前的强制修复)
                    // ===========================================
                    else {
                        if (window.galleryImages) {
                            const idx = window.galleryImages.findIndex(img => img.id === deletedId);
                            if (idx !== -1) window.galleryImages.splice(idx, 1);
                        }

                        // 查找元素
                        let gridItem = document.getElementById(`img-anchor-${deletedId}`);
                        if (!gridItem) gridItem = document.getElementById(`card-img-${deletedId}`);

                        if (gridItem) {
                            // 更新数量角标
                            const isVideoContainer = gridItem.closest('#detail-masonry-grid-videos');
                            const badgeId = isVideoContainer ? 'video-count-badge' : 'image-count-badge';
                            const badge = document.getElementById(badgeId);

                            if (badge) {
                                let currentCount = parseInt(badge.innerText) || 0;
                                if (currentCount > 0) {
                                    badge.innerText = currentCount - 1;
                                    badge.classList.add('text-danger'); 
                                    setTimeout(() => badge.classList.remove('text-danger'), 2000);
                                }
                            }

                            // 强制删除逻辑
                            if (!isVideoContainer && window.msnryImages) {
                                try { window.msnryImages.remove(gridItem); } catch (e) {}
                            }
                            
                            // 无论如何强制从 DOM 移除
                            gridItem.remove();

                            if (!isVideoContainer && window.msnryImages) {
                                window.msnryImages.layout();
                            }
                        }

                        if (isModal) {
                            if (!window.galleryImages || window.galleryImages.length === 0) {
                                const modalInstance = bootstrap.Modal.getInstance(document.getElementById('imageModal'));
                                if (modalInstance) modalInstance.hide();
                            } else {
                                if (currentIndex >= window.galleryImages.length) {
                                    currentIndex = window.galleryImages.length - 1;
                                }
                                updateModalImage();
                            }
                        }
                    }

                    Swal.fire({
                        icon: 'success', title: '已删除', toast: true, position: 'top-end', showConfirmButton: false, timer: 1500
                    });

                } else {
                    btn.innerHTML = originalHtml;
                    btn.disabled = false;
                    Swal.fire('删除失败', data.message || '未知错误', 'error');
                }
            })
            .catch(error => {
                console.error(error);
                btn.innerHTML = originalHtml;
                btn.disabled = false;
                Swal.fire('错误', '网络请求失败', 'error');
            });
        }
    });
}

// ================= 统一提示词编辑逻辑 =================

const promptEditorState = {
    items: [],
    draftItems: [],
    isEditing: false,
};

document.addEventListener('DOMContentLoaded', () => {
    initPromptListEditor();
});

function initPromptListEditor() {
    const dataEl = document.getElementById('prompt-list-data');
    const container = document.getElementById('promptListContainer');
    if (!dataEl || !container) return;

    try {
        const parsed = JSON.parse(dataEl.textContent || '[]');
        promptEditorState.items = normalizePromptEditorItems(parsed);
    } catch (error) {
        console.error('初始化提示词列表失败', error);
        promptEditorState.items = [];
    }

    renderPromptList(promptEditorState.items, false);
}

function normalizePromptEditorItems(items) {
    const normalized = [];

    (items || []).forEach((item) => {
        const text = typeof item === 'object'
            ? String(item.text || '').trim()
            : String(item || '').trim();

        if (!text) return;

        normalized.push({
            id: typeof item === 'object' && item.id ? item.id : `prompt_${normalized.length + 1}`,
            label: `提示词${normalized.length + 1}`,
            text,
        });
    });

    return normalized;
}

function escapePromptHtml(text) {
    const div = document.createElement('div');
    div.textContent = text || '';
    return div.innerHTML;
}

function renderPromptList(items, isEditing) {
    const container = document.getElementById('promptListContainer');
    if (!container) return;

    const displayItems = items.length > 0
        ? items
        : (isEditing ? [{ id: 'prompt_1', label: '提示词1', text: '' }] : []);

    if (displayItems.length === 0) {
        container.innerHTML = '<div class="text-muted small py-2">暂无提示词，点击“编辑”后可新增。</div>';
        togglePromptEditorControls(isEditing);
        return;
    }

    container.innerHTML = displayItems.map((item, index) => {
        const safeText = escapePromptHtml(item.text);
        return `
            <div class="border rounded-4 bg-white shadow-sm p-3">
                <div class="d-flex justify-content-between align-items-center mb-2 flex-wrap gap-2">
                    <span class="badge bg-light text-primary border rounded-pill px-3 py-2">提示词${index + 1}</span>
                    <div class="d-flex align-items-center gap-2">
                        <button type="button" class="btn btn-sm btn-outline-primary rounded-pill px-3" onclick="copyPromptItem(${index}, this)" ${item.text.trim() ? '' : 'disabled'}>
                            <i class="bi bi-clipboard me-1"></i>复制
                        </button>
                        <button type="button" class="btn btn-sm btn-outline-danger rounded-pill px-3" onclick="removePromptItem(${index})" style="${isEditing ? '' : 'display:none;'}">
                            <i class="bi bi-trash3 me-1"></i>删除
                        </button>
                    </div>
                </div>
                ${isEditing
                    ? `<textarea class="form-control prompt-list-input" rows="4" data-index="${index}" placeholder="请输入提示词${index + 1}...">${safeText}</textarea>`
                    : `<div class="prompt-box mb-0">${item.text.trim() ? safeText.replace(/\n/g, '<br>') : '<span class="empty-text">未填写</span>'}</div>`}
            </div>
        `;
    }).join('');

    togglePromptEditorControls(isEditing);
}

function togglePromptEditorControls(isEditing) {
    const editBtn = document.getElementById('btnEditPromptList');
    const addBtn = document.getElementById('btnAddPromptItem');
    const actions = document.getElementById('promptListActions');
    if (editBtn) editBtn.style.display = isEditing ? 'none' : 'inline-flex';
    if (addBtn) addBtn.style.display = isEditing ? 'inline-flex' : 'none';
    if (actions) actions.style.display = isEditing ? 'block' : 'none';
}

function collectPromptDraftItems() {
    const inputs = document.querySelectorAll('#promptListContainer .prompt-list-input');
    return normalizePromptEditorItems(Array.from(inputs).map((input) => ({ text: input.value })));
}

function buildDuplicatePromptEntries(items) {
    const seen = new Map();
    const duplicates = [];

    (items || []).forEach((item, index) => {
        const originalText = String(item?.text || '').trim();
        if (!originalText) return;

        const normalizedText = originalText.replace(/\s+/g, ' ').trim().toLowerCase();
        if (!normalizedText) return;

        if (seen.has(normalizedText)) {
            const firstMatch = seen.get(normalizedText);
            let entry = duplicates.find((dup) => dup.normalizedText === normalizedText);
            if (!entry) {
                entry = {
                    normalizedText,
                    text: firstMatch.text,
                    indexes: [firstMatch.index + 1],
                };
                duplicates.push(entry);
            }
            if (!entry.indexes.includes(index + 1)) {
                entry.indexes.push(index + 1);
            }
            return;
        }

        seen.set(normalizedText, { text: originalText, index });
    });

    return duplicates;
}

function clearDuplicatePromptHighlights() {
    document.querySelectorAll('#promptListContainer .prompt-list-input-duplicate').forEach((input) => {
        input.classList.remove('prompt-list-input-duplicate');
    });
}

function highlightDuplicatePromptInputs(duplicateEntries) {
    clearDuplicatePromptHighlights();

    (duplicateEntries || []).forEach((entry) => {
        entry.indexes.forEach((displayIndex) => {
            const input = document.querySelector(`#promptListContainer .prompt-list-input[data-index="${displayIndex - 1}"]`);
            if (input) {
                input.classList.add('prompt-list-input-duplicate');
            }
        });
    });
}

function buildDuplicatePromptAlertHtml(duplicateEntries) {
    const rows = (duplicateEntries || []).map((entry, index) => {
        const indexes = entry.indexes.map((item) => `提示词${item}`).join('、');
        return `
            <div class="duplicate-prompt-row">
                <div class="duplicate-prompt-row-top">
                    <span class="duplicate-prompt-badge">重复项 ${index + 1}</span>
                    <span class="duplicate-prompt-meta">出现在 ${indexes}</span>
                </div>
                <div class="duplicate-prompt-text">${escapePromptHtml(entry.text)}</div>
            </div>
        `;
    }).join('');

    return `
        <div class="duplicate-prompt-alert">
            <div class="duplicate-prompt-summary">
                <span class="duplicate-prompt-icon"><i class="bi bi-exclamation-triangle-fill"></i></span>
                <div>
                    <div class="fw-bold mb-1">提示词组里有重复内容</div>
                    <div class="small">已为你高亮重复输入框，请先删除或改写后再保存。</div>
                </div>
            </div>
            <div class="duplicate-prompt-list">${rows}</div>
        </div>
    `;
}

function enablePromptListEdit() {
    promptEditorState.draftItems = promptEditorState.items.map((item) => ({ ...item }));
    promptEditorState.isEditing = true;
    renderPromptList(promptEditorState.draftItems, true);
}

function cancelPromptListEdit() {
    promptEditorState.isEditing = false;
    promptEditorState.draftItems = [];
    clearDuplicatePromptHighlights();
    renderPromptList(promptEditorState.items, false);
}

function addPromptItem() {
    if (!promptEditorState.isEditing) return;

    promptEditorState.draftItems = collectPromptDraftItems();
    promptEditorState.draftItems.push({
        id: `prompt_${promptEditorState.draftItems.length + 1}`,
        label: `提示词${promptEditorState.draftItems.length + 1}`,
        text: '',
    });
    renderPromptList(promptEditorState.draftItems, true);

    const inputs = document.querySelectorAll('#promptListContainer .prompt-list-input');
    const lastInput = inputs[inputs.length - 1];
    if (lastInput) lastInput.focus();
}

function removePromptItem(index) {
    if (!promptEditorState.isEditing) return;

    promptEditorState.draftItems = collectPromptDraftItems();
    promptEditorState.draftItems.splice(index, 1);
    renderPromptList(promptEditorState.draftItems, true);
}

function savePromptList(pk) {
    const csrftoken = getCookie('csrftoken');
    const prompts = collectPromptDraftItems();
    const duplicatePrompts = buildDuplicatePromptEntries(prompts);

    if (duplicatePrompts.length > 0) {
        highlightDuplicatePromptInputs(duplicatePrompts);
        Swal.fire({
            icon: 'warning',
            title: '检测到重复提示词',
            html: buildDuplicatePromptAlertHtml(duplicatePrompts),
            confirmButtonText: '返回修改',
            width: 640,
        });
        return;
    }

    clearDuplicatePromptHighlights();

    fetch(`/update-prompts/${pk}/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrftoken },
        body: JSON.stringify({ prompts })
    })
    .then(response => response.json())
    .then(res => {
        if (res.status === 'success') {
            promptEditorState.items = prompts;
            promptEditorState.draftItems = [];
            promptEditorState.isEditing = false;
            clearDuplicatePromptHighlights();
            renderPromptList(promptEditorState.items, false);
            Swal.fire({ icon: 'success', title: '保存成功', toast: true, position: 'top-end', showConfirmButton: false, timer: 1500 });
        } else {
            Swal.fire({ icon: 'error', title: '保存失败', text: res.message || '未知错误' });
        }
    })
    .catch(err => {
        console.error(err);
        Swal.fire({ icon: 'error', title: '错误', text: '网络错误' });
    });
}

function copyPromptItem(index, btnElement) {
    const sourceItems = promptEditorState.isEditing ? collectPromptDraftItems() : promptEditorState.items;
    const text = sourceItems[index] ? sourceItems[index].text.trim() : '';
    if (!text) return;

    copyToClipboard(text);
    const originalHTML = btnElement.innerHTML;
    btnElement.innerHTML = '<i class="bi bi-check-lg me-1"></i>已复制';
    btnElement.classList.remove('btn-outline-primary');
    btnElement.classList.add('btn-success', 'text-white');
    setTimeout(() => {
        btnElement.innerHTML = originalHTML;
        btnElement.classList.remove('btn-success', 'text-white');
        btnElement.classList.add('btn-outline-primary');
    }, 2000);
}

// ================= 标签交互逻辑 =================
function showTagInput() {
    document.getElementById('btnAddTag').style.display = 'none';
    const container = document.getElementById('tagInputContainer');
    container.classList.add('show');
    setTimeout(() => document.getElementById('newTagInput').focus(), 100);
}

function handleTagKey(event, groupPk) {
    if (event.key === 'Enter') { event.preventDefault(); addTag(groupPk); }
    else if (event.key === 'Escape') { resetTagInput(); }
}

function resetTagInput() {
    const container = document.getElementById('tagInputContainer');
    if(container) {
        container.classList.remove('show');
        document.getElementById('newTagInput').value = '';
        setTimeout(() => {
            const btn = document.getElementById('btnAddTag');
            if(btn) btn.style.display = 'inline-flex';
        }, 300);
    }
}

function addTag(groupPk) {
    const input = document.getElementById('newTagInput');
    const tagName = input.value.trim();
    if (!tagName) { input.focus(); return; }

    const csrftoken = getCookie('csrftoken');
    fetch(`/add-tag/${groupPk}/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrftoken },
        body: JSON.stringify({ tag_name: tagName })
    })
    .then(res => res.json())
    .then(data => {
        if (data.status === 'success') {
            // 智能分流：根据后端返回的 tag_type 决定插入哪个容器，并附带正确的删除参数
            if (data.tag_type === 'character') {
                const wrapper = document.getElementById('characters-wrapper');
                if (wrapper) {
                    const html = `
                        <span class="tag-interactive tag-char" id="char-pill-${data.tag_id}">
                            <i class="bi bi-person-fill me-1"></i>
                            <a href="/?q=${encodeURIComponent(data.tag_name)}">${data.tag_name}</a>
                            <span class="tag-remove-btn" onclick="removeTag(${groupPk}, ${data.tag_id}, 'character')" title="移除人物">
                                <i class="bi bi-x-circle-fill"></i>
                            </span>
                        </span>`;
                    wrapper.insertAdjacentHTML('beforeend', html);
                }
            } else {
                const wrapper = document.getElementById('normal-tags-wrapper');
                if (wrapper) {
                    const html = `
                        <span class="tag-interactive" id="tag-pill-${data.tag_id}">
                            <a href="/?q=${encodeURIComponent(data.tag_name)}">${data.tag_name}</a>
                            <span class="tag-remove-btn" onclick="removeTag(${groupPk}, ${data.tag_id}, 'tag')" title="移除标签">
                                <i class="bi bi-x-circle-fill"></i>
                            </span>
                        </span>`;
                    wrapper.insertAdjacentHTML('beforeend', html);
                }
            }
            
            // 恢复输入框状态
            input.value = '';
            input.focus();
        } else {
            Swal.fire({ icon: 'error', title: '添加失败', text: data.message });
        }
    })
    .catch(err => {
        console.error(err);
        Swal.fire('错误', '网络请求失败', 'error');
    });
}

function removeTag(groupPk, tagId, tagType = 'tag') {
    Swal.fire({
        title: '确定要移除吗？',
        icon: 'warning',
        showCancelButton: true, 
        confirmButtonColor: '#ff4757', 
        confirmButtonText: '移除', 
        cancelButtonText: '取消'
    }).then((result) => {
        if (result.isConfirmed) {
            const csrftoken = getCookie('csrftoken');
            fetch(`/remove-tag/${groupPk}/`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrftoken },
                // 必须将 tagType 传给后端，后端才知道要去查 Character 表还是 Tag 表
                body: JSON.stringify({ tag_id: tagId, tag_type: tagType })
            })
            .then(res => res.json())
            .then(data => {
                if (data.status === 'success') {
                    // 精准找到页面上的节点并移除
                    const elId = tagType === 'character' ? `char-pill-${tagId}` : `tag-pill-${tagId}`;
                    const el = document.getElementById(elId);
                    if (el) { 
                        el.style.transform = 'scale(0.8)'; 
                        el.style.opacity = '0'; 
                        setTimeout(() => el.remove(), 300); 
                    }
                } else { 
                    Swal.fire({ icon: 'error', title: '移除失败', text: data.message }); 
                }
            })
            .catch(err => {
                console.error(err);
                Swal.fire('错误', '网络请求失败', 'error');
            });
        }
    });
}

// ================= 【核心修改】上传处理 (支持无刷新 + 分栏) =================

function handleImageUpload(event) {
    event.preventDefault(); 
    const form = event.target;
    const formData = new FormData(form);
    const submitBtn = form.querySelector('button[type="submit"]');
    const originalBtnContent = submitBtn.innerHTML;
    
    submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>上传处理中...';
    submitBtn.disabled = true;

    fetch(form.action, {
        method: 'POST',
        body: formData,
        headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': getCookie('csrftoken') }
    })
    .then(response => response.json())
    .then(data => {
        submitBtn.innerHTML = originalBtnContent;
        submitBtn.disabled = false;

        if (data.status === 'success' || data.status === 'warning') {
            const modalId = (data.type === 'ref') ? 'addReferenceModal' : 'addImagesModal';
            const modalEl = document.getElementById(modalId);
            if (modalEl) bootstrap.Modal.getInstance(modalEl).hide();

            // === 生成内容处理 (图片/视频) ===
            if (data.type === 'gen') {
                
                // 1. 更新数量统计
                let addedImages = 0;
                let addedVideos = 0;
                
                if (data.new_images_data && window.galleryImages) {
                    // 【修复】将新数据正确合并到全局数据源，防止大图预览报错
                    // 使用 reverse() 确保插入顺序正确（因为 unshift 是插入头部）
                    [...data.new_images_data].reverse().forEach(img => {
                        // 确保字段兼容性
                        img.isVideo = img.is_video || img.isVideo || false;
                        window.galleryImages.unshift(img);
                        
                        if (img.isVideo) addedVideos++; else addedImages++;
                    });
                }

                // 2. 更新徽章数字
                const imgBadge = document.getElementById('image-count-badge');
                if (imgBadge && addedImages > 0) {
                    imgBadge.innerText = (parseInt(imgBadge.innerText) || 0) + addedImages;
                    imgBadge.classList.add('text-primary'); setTimeout(() => imgBadge.classList.remove('text-primary'), 2000);
                }
                const vidBadge = document.getElementById('video-count-badge');
                if (vidBadge && addedVideos > 0) {
                    vidBadge.innerText = (parseInt(vidBadge.innerText) || 0) + addedVideos;
                    vidBadge.classList.add('text-primary'); setTimeout(() => vidBadge.classList.remove('text-primary'), 2000);
                }

                // 3. 插入 HTML 卡片
                if (data.new_images_html && data.new_images_html.length > 0) {
                    const imgContainer = document.getElementById('detail-masonry-grid-images');
                    const vidContainer = document.getElementById('detail-masonry-grid-videos');

                    const tempDiv = document.createElement('div');
                    const newImagesNodes = [];
                    
                    data.new_images_html.forEach((html, index) => {
                        const meta = data.new_images_data ? data.new_images_data[index] : null;
                        const isVideo = meta ? (meta.is_video || meta.isVideo) : false;
                        const targetContainer = isVideo ? vidContainer : imgContainer;
                        
                        if (targetContainer) {
                            const emptyPlaceholder = targetContainer.querySelector('.alert');
                            if (emptyPlaceholder) emptyPlaceholder.parentNode.remove();

                            tempDiv.innerHTML = html;
                            const node = tempDiv.firstElementChild;
                            
                            // 【核心修复】只设置 eager 加载，绝对不要隐藏图片！
                            const img = node.querySelector('img');
                            if (img) {
                                img.setAttribute('loading', 'eager');
                                // img.onerror = ... <--- 删除了这行会导致白图的罪魁祸首
                                
                                // 可选：如果加载失败，尝试重新加载一次原图 (增强稳定性)
                                img.onerror = function() {
                                    if (!this.dataset.retried) {
                                        this.dataset.retried = true;
                                        this.src = meta.url; // 尝试加载原图
                                    }
                                };
                            }
                            
                            targetContainer.prepend(node);
                            
                            if (isVideo) {
                                const newVid = node.querySelector('video');
                                if (newVid) newVid.addEventListener('loadedmetadata', () => adjustVideoLayout(newVid));
                            } else {
                                newImagesNodes.push(node);
                            }
                        }
                    });

                    // 4. 刷新 Masonry (仅针对图片栏)
                    if (window.msnryImages && newImagesNodes.length > 0) {
                        window.msnryImages.prepended(newImagesNodes);
                        
                        const onLayout = () => { window.msnryImages.layout(); };
                        if (typeof imagesLoaded !== 'undefined') {
                            imagesLoaded(newImagesNodes).on('progress', onLayout);
                        }
                        
                        // 多重延时布局，防止图片加载慢导致重叠
                        onLayout();
                        setTimeout(onLayout, 300);
                        setTimeout(onLayout, 1000);
                    }
                    
                    modalGenFiles = [];
                    document.getElementById('preview-modal-gen').innerHTML = '';
                }
            } 
            // === 参考图处理 ===
            else if (data.type === 'ref') {
                 if (data.new_references_html && data.new_references_html.length > 0) {
                    const refGrid = document.getElementById('reference-grid');
                    if (refGrid) {
                        data.new_references_html.forEach(html => refGrid.insertAdjacentHTML('beforeend', html));
                    }
                    modalRefFiles = [];
                    document.getElementById('preview-modal-ref').innerHTML = '';
                }
            }

            if (data.status === 'warning') {
                let listItems = data.duplicates.map(dup => `
                    <div class="duplicate-item">
                        <img src="${dup.existing_url||''}" class="duplicate-alert-img">
                        <div class="duplicate-text-content">
                            <div class="duplicate-filename">${dup.name}</div>
                            <div class="duplicate-badge">已拦截</div>
                        </div>
                    </div>`).join('');
                Swal.fire({
                    title: '重复拦截报告',
                    html: `<div class="duplicate-scroll-container">${listItems}</div>
                           <div class="mt-2 text-end">成功: <b class="text-success">${data.uploaded_count}</b> / 拦截: <b class="text-danger">${data.duplicates.length}</b></div>`,
                    width: '600px'
                });
            } else {
                Swal.fire({ icon: 'success', title: data.message || `已添加 ${data.uploaded_count} 个文件`, toast: true, position: 'top-end', showConfirmButton: false, timer: 2000 });
            }
            form.reset();
        } else {
            Swal.fire({ icon: 'error', title: '操作失败', text: 'Server error' });
        }
    })
    .catch(error => {
        submitBtn.innerHTML = originalBtnContent;
        submitBtn.disabled = false;
        console.error(error);
        Swal.fire({ icon: 'error', title: '上传错误', text: error.message });
    });
}

function applyDetailNewImagesResponse(data) {
    if (!data || data.type !== 'gen') {
        return;
    }

    let addedImages = 0;
    let addedVideos = 0;

    if (data.new_images_data && window.galleryImages) {
        [...data.new_images_data].reverse().forEach(img => {
            img.isVideo = img.is_video || img.isVideo || false;
            window.galleryImages.unshift(img);
            if (img.isVideo) {
                addedVideos++;
            } else {
                addedImages++;
            }
        });
    }

    const imgBadge = document.getElementById('image-count-badge');
    if (imgBadge && addedImages > 0) {
        imgBadge.innerText = (parseInt(imgBadge.innerText, 10) || 0) + addedImages;
        imgBadge.classList.add('text-primary');
        setTimeout(() => imgBadge.classList.remove('text-primary'), 2000);
    }

    const vidBadge = document.getElementById('video-count-badge');
    if (vidBadge && addedVideos > 0) {
        vidBadge.innerText = (parseInt(vidBadge.innerText, 10) || 0) + addedVideos;
        vidBadge.classList.add('text-primary');
        setTimeout(() => vidBadge.classList.remove('text-primary'), 2000);
    }

    if (data.new_images_html && data.new_images_html.length > 0) {
        const imgContainer = document.getElementById('detail-masonry-grid-images');
        const vidContainer = document.getElementById('detail-masonry-grid-videos');

        const tempDiv = document.createElement('div');
        const newImagesNodes = [];

        data.new_images_html.forEach((html, index) => {
            const meta = data.new_images_data ? data.new_images_data[index] : null;
            const isVideo = meta ? (meta.is_video || meta.isVideo) : false;
            const targetContainer = isVideo ? vidContainer : imgContainer;
            if (!targetContainer) {
                return;
            }

            const emptyPlaceholder = targetContainer.querySelector('.alert');
            if (emptyPlaceholder) {
                emptyPlaceholder.parentNode.remove();
            }

            tempDiv.innerHTML = html;
            const node = tempDiv.firstElementChild;
            if (!node) {
                return;
            }

            const img = node.querySelector('img');
            if (img && meta?.url) {
                img.setAttribute('loading', 'eager');
                img.onerror = function () {
                    if (!this.dataset.retried) {
                        this.dataset.retried = true;
                        this.src = meta.url;
                    }
                };
            }

            targetContainer.prepend(node);

            if (isVideo) {
                const newVid = node.querySelector('video');
                if (newVid) {
                    newVid.addEventListener('loadedmetadata', () => adjustVideoLayout(newVid));
                }
            } else {
                newImagesNodes.push(node);
            }
        });

        if (window.msnryImages && newImagesNodes.length > 0) {
            newImagesNodes.forEach(node => window.msnryImages.prepended(node));
            window.msnryImages.layout();
        }
    }
}

// ================= 拖拽上传辅助函数 (修复 Video 预览) =================

function setupInlineDragDrop(triggerId, modalId, type) {
    const trigger = document.getElementById(triggerId); if (!trigger) return;
    let dragCounter = 0;
    trigger.addEventListener('click', () => {
        const modalEl = document.getElementById(modalId);
        if (modalEl) bootstrap.Modal.getOrCreateInstance(modalEl).show();
    });
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        trigger.addEventListener(eventName, (e) => { e.preventDefault(); e.stopPropagation(); }, false);
    });
    trigger.addEventListener('dragenter', () => { dragCounter++; trigger.classList.add('drag-over'); });
    trigger.addEventListener('dragleave', () => { dragCounter--; if (dragCounter === 0) trigger.classList.remove('drag-over'); });
    trigger.addEventListener('drop', (e) => {
        dragCounter = 0; trigger.classList.remove('drag-over');
        const files = e.dataTransfer.files;
        if (files && files.length > 0) {
            const modalEl = document.getElementById(modalId);
            if (modalEl) {
                bootstrap.Modal.getOrCreateInstance(modalEl).show();
                const input = document.getElementById(`input-modal-${type}`);
                const previewContainer = document.getElementById(`preview-modal-${type}`);
                if (input && previewContainer) handleModalFiles(files, type, input, previewContainer);
            }
        }
    });
}

function setupDetailDragDrop(zoneId, inputId, previewId, type) {
    const zone = document.getElementById(zoneId); if (!zone) return; 
    const input = document.getElementById(inputId);
    const previewContainer = document.getElementById(previewId);
    let dragCounter = 0;
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        zone.addEventListener(eventName, (e) => { e.preventDefault(); e.stopPropagation(); }, false);
    });
    zone.addEventListener('dragenter', () => { dragCounter++; zone.classList.add('drag-over'); });
    zone.addEventListener('dragleave', () => { dragCounter--; if (dragCounter === 0) zone.classList.remove('drag-over'); });
    zone.addEventListener('drop', (e) => {
        dragCounter = 0; zone.classList.remove('drag-over');
        handleModalFiles(e.dataTransfer.files, type, input, previewContainer);
    });
    input.addEventListener('change', () => {
        if (input.files.length > 0) handleModalFiles(input.files, type, input, previewContainer);
    });
}

function handleModalFiles(newFiles, type, input, previewContainer) {
    const fileArray = (type === 'gen') ? modalGenFiles : modalRefFiles;
    Array.from(newFiles).forEach(file => {
        const exists = fileArray.some(f => f.name === file.name && f.size === file.size);
        if (!exists) {
            fileArray.push(file);
            addModalPreviewItem(file, type, previewContainer, input);
        }
    });
    updateModalInputFiles(type, input);
}

function updateModalInputFiles(type, input) {
    const fileArray = (type === 'gen') ? modalGenFiles : modalRefFiles;
    const dataTransfer = new DataTransfer();
    fileArray.forEach(file => dataTransfer.items.add(file));
    input.files = dataTransfer.files;
}

function addModalPreviewItem(file, type, container, input) {
    const div = document.createElement('div');
    div.className = 'preview-item-modal';
    
    // 1. 创建删除按钮 (先不添加到 DOM，等内容添加完再放最后，确保在最上层)
    const delBtn = document.createElement('div');
    delBtn.className = 'btn-remove-preview-modal';
    delBtn.innerHTML = '<i class="bi bi-x-lg"></i>';
    delBtn.style.zIndex = '10'; 
    delBtn.onclick = (e) => {
        e.stopPropagation();
        const fileArray = (type === 'gen') ? modalGenFiles : modalRefFiles;
        const index = fileArray.indexOf(file);
        if (index > -1) {
            fileArray.splice(index, 1);
            div.remove();
            updateModalInputFiles(type, input);
        }
    };

    container.appendChild(div);

    // 2. 根据类型添加内容
    if (file.type.startsWith('video/') || file.name.match(/\.(mp4|mov|avi|webm|mkv)$/i)) {
        const video = document.createElement('video');
        video.src = URL.createObjectURL(file);
        video.muted = true;
        video.className = 'w-100 h-100 object-fit-cover';
        video.preload = 'metadata';
        
        const icon = document.createElement('div');
        icon.className = 'position-absolute top-50 start-50 translate-middle text-white';
        icon.innerHTML = '<i class="bi bi-camera-video-fill fs-4" style="text-shadow:0 0 5px rgba(0,0,0,0.5)"></i>';
        icon.style.zIndex = '5';
        
        div.appendChild(icon);
        div.appendChild(video);
        // 【关键修复】视频最后添加按钮，确保按钮在视频图层之上
        div.appendChild(delBtn); 
    } else {
        // 图片逻辑
        // 【关键修复】不要使用 innerHTML +=，这会销毁 delBtn 的事件绑定
        const spinner = document.createElement('div');
        spinner.className = 'spinner-border text-secondary spinner-border-sm position-absolute top-50 start-50';
        div.appendChild(spinner);
        
        // 先把按钮加上去 (确保 loading 时也能删除)
        div.appendChild(delBtn); 

        createModalThumbnail(file).then(url => {
            spinner.remove();
            if (url) {
                const img = document.createElement('img');
                img.src = url;
                img.className = 'w-100 h-100 object-fit-cover';
                // 使用 insertBefore 将图片插在按钮之前，保证按钮依旧在最上面
                div.insertBefore(img, delBtn);
            } else {
                const err = document.createElement('span');
                err.className = 'small text-danger position-absolute top-50 start-50 translate-middle';
                err.innerText = 'Error';
                div.insertBefore(err, delBtn);
            }
        });
    }
}

function createModalThumbnail(file) {
    return new Promise((resolve) => {
        if (!file.type.startsWith('image/')) { resolve(null); return; }
        const reader = new FileReader();
        reader.onload = (e) => {
            const img = new Image();
            img.onload = () => {
                const canvas = document.createElement('canvas');
                const ctx = canvas.getContext('2d');
                const maxSize = 200;
                let w = img.width, h = img.height;
                if (w > h) { if (w > maxSize) { h *= maxSize/w; w = maxSize; } }
                else { if (h > maxSize) { w *= maxSize/h; h = maxSize; } }
                canvas.width = w; canvas.height = h;
                ctx.drawImage(img, 0, 0, w, h);
                resolve(canvas.toDataURL('image/jpeg', 0.8));
            };
            img.src = e.target.result;
        };
        reader.readAsDataURL(file);
    });
}

document.addEventListener('DOMContentLoaded', function() {
    if (!document.body.classList.contains('detail-page')) return;
    const navbar = document.querySelector('.navbar-glass');
    const update = () => {
        const sl = document.querySelector('.detail-scroll-left')?.scrollTop || 0;
        const sr = document.querySelector('.detail-scroll-right')?.scrollTop || 0;
        if(sl>10 || sr>10) navbar.classList.remove('navbar-transparent'); else navbar.classList.add('navbar-transparent');
    };
    update();
    document.querySelector('.detail-scroll-left')?.addEventListener('scroll', update);
    document.querySelector('.detail-scroll-right')?.addEventListener('scroll', update);
});

// ================= 版本合并管理 (手动选择合并 - 增强兼容版) =================

// 1. 使用全局事件委托监听复选框，彻底解决监听不到的问题
document.addEventListener('change', function(e) {
    // 只要触发变化的元素是带有 variant-merge-checkbox 类的复选框
    if (e.target && e.target.classList.contains('variant-merge-checkbox')) {
        
        const checkedCount = document.querySelectorAll('.variant-merge-checkbox:checked').length;
        const mergeBtn = document.getElementById('btn-merge-selected');
        const mergeCountSpan = document.getElementById('merge-count');

        if (!mergeBtn) {
            console.error('⚠️ 找不到合并按钮，请检查 detail.html 中是否正确添加了 id="btn-merge-selected" 的代码！');
            return;
        }

        if (checkedCount > 0) {
            // 使用 important 强行覆盖隐藏样式
            mergeBtn.style.setProperty('display', 'inline-block', 'important'); 
            if (mergeCountSpan) mergeCountSpan.innerText = checkedCount;
        } else {
            mergeBtn.style.setProperty('display', 'none', 'important');
        }
    }
});

// 2. 使用全局事件委托监听合并按钮点击
document.addEventListener('click', function(e) {
    // 判断点击的是不是合并按钮 (或者按钮里的图标/文字)
    const mergeBtn = e.target.closest('#btn-merge-selected');
    if (!mergeBtn) return;

    e.preventDefault();
    
    const selectedIds = Array.from(document.querySelectorAll('.variant-merge-checkbox:checked')).map(cb => cb.value);
    const mainGroupId = getCurrentGroupId(); 

    if (!mainGroupId) {
        Swal.fire('错误', '无法获取当前作品ID', 'error');
        return;
    }

    Swal.fire({
        title: `确认合并这 ${selectedIds.length} 个版本？`,
        text: "被合并版本内的所有图片将转移至当前组，并且原来的空壳版本将被永久删除！此操作不可恢复。",
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: '#ffc107',
        cancelButtonColor: '#6c757d',
        confirmButtonText: '确认合并',
        cancelButtonText: '取消'
    }).then((result) => {
        if (result.isConfirmed) {
            
            Swal.fire({
                title: '正在合并...',
                allowOutsideClick: false,
                didOpen: () => { Swal.showLoading(); }
            });

            fetch('/api/merge-variants/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCookie('csrftoken') 
                },
                body: JSON.stringify({
                    main_group_id: mainGroupId,
                    merge_ids: selectedIds
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.status === 'success') {
                    Swal.fire({
                        icon: 'success', 
                        title: '合并完成', 
                        text: data.message,
                        timer: 1500,
                        showConfirmButton: false
                    }).then(() => {
                        window.location.reload(); 
                    });
                } else {
                    Swal.fire('合并失败', data.message, 'error');
                }
            })
            .catch(error => {
                console.error('Error:', error);
                Swal.fire('网络错误', '请求未能成功，请检查网络或控制台', 'error');
            });
        }
    });
});

// 3. 【新增】全选/取消全选 (针对侧边栏其他版本)
document.addEventListener('DOMContentLoaded', function() {
    const selectAllBtn = document.getElementById('selectAllVariants');
    
    if (selectAllBtn) {
        // 点击“全选”时，勾选所有子项
        selectAllBtn.addEventListener('change', function() {
            const isChecked = this.checked;
            const variantCheckboxes = document.querySelectorAll('.variant-merge-checkbox');
            
            variantCheckboxes.forEach(cb => {
                cb.checked = isChecked;
            });
            
            // 手动派发一个 change 事件，让第1步写的代码能捕捉到，从而显示“合并(N)”按钮
            if (variantCheckboxes.length > 0) {
                variantCheckboxes[0].dispatchEvent(new Event('change', { bubbles: true }));
            }
        });
    }
});

// 4. 【新增】当手动勾选/取消某个子项时，反向更新全选按钮的状态（全选/半选）
document.addEventListener('change', function(e) {
    if (e.target && e.target.classList.contains('variant-merge-checkbox')) {
        const checkboxes = document.querySelectorAll('.variant-merge-checkbox');
        const selectAllBtn = document.getElementById('selectAllVariants');
        
        if (selectAllBtn && checkboxes.length > 0) {
            const allChecked = Array.from(checkboxes).every(c => c.checked);
            const someChecked = Array.from(checkboxes).some(c => c.checked);
            
            selectAllBtn.checked = allChecked;
            // 如果只选了一部分，给全选框加个横线的“半选”状态
            selectAllBtn.indeterminate = someChecked && !allChecked;
        }
    }
});

// ================= 版本关联管理 (支持多选 & 自动推荐) =================

function unlinkSibling(e, id) { 
    e.preventDefault(); e.stopPropagation(); 
    Swal.fire({title:'解除关联?',showCancelButton:true,confirmButtonText:'确定'}).then(r=>{
        if(r.isConfirmed){
            fetch(`/api/unlink-group/${id}/`,{method:'POST',headers:{'X-CSRFToken':getCookie('csrftoken')}})
            .then(res=>res.json()).then(d=>{if(d.status==='success')location.reload();});
        }
    });
} 

let linkModal;

function openLinkModal() { 
    if(!linkModal) linkModal=new bootstrap.Modal(document.getElementById('linkVersionModal')); 
    
    const input = document.getElementById('linkSearchInput');
    input.value = '';
    
    selectedLinkIds.clear();
    updateLinkSelectionUI();
    
    // 【新增】打开时自动加载推荐
    loadSimilarRecommendations();
    
    linkModal.show(); 
    
    // 聚焦输入框
    setTimeout(() => input.focus(), 500);
}

// 【新增】加载相似推荐函数
function loadSimilarRecommendations() {
    const container = document.getElementById('linkSearchResults');
    // 显示加载状态
    container.innerHTML = '<div class="text-center text-muted p-4"><div class="spinner-border spinner-border-sm text-primary me-2"></div>正在寻找相似提示词...</div>';
    
    const currentPk = getCurrentGroupId();
    if (!currentPk) return;

    fetch(`/api/similar-groups/${currentPk}/`)
        .then(res => res.json())
        .then(data => {
            if (data.status === 'success' && data.results.length > 0) {
                // 添加推荐标题头
                container.innerHTML = `<div class="px-3 py-2 mb-2 small fw-bold text-primary bg-primary bg-opacity-10 border-bottom d-flex align-items-center justify-content-between">
                    <span><i class="bi bi-stars me-1"></i>智能推荐 (按提示词相似度)</span>
                    <span class="badge bg-white text-primary border">${data.results.length}</span>
                </div>`;
                renderLinkResults(data.results, true); // true 表示追加到 container
            } else {
                // 无推荐时的默认提示
                container.innerHTML = '<div class="text-center text-muted p-5"><i class="bi bi-search fs-1 opacity-25 d-block mb-2"></i>请输入关键词搜索关联版本</div>';
            }
        })
        .catch(err => {
            console.error(err);
            container.innerHTML = '<div class="text-center text-muted p-3">推荐加载失败，请尝试手动搜索</div>';
        });
}

function updateLinkSelectionUI() {
    document.getElementById('linkSelectedCount').textContent = selectedLinkIds.size;
    // 更新列表中已选中项的样式
    document.querySelectorAll('.search-result-item').forEach(el => {
        const id = parseInt(el.dataset.id);
        const icon = el.querySelector('.select-icon');
        if (selectedLinkIds.has(id)) {
            el.classList.add('bg-primary', 'bg-opacity-10', 'border-primary'); 
            icon.classList.replace('bi-circle', 'bi-check-circle-fill');
            icon.classList.add('text-primary');
        } else {
            el.classList.remove('bg-primary', 'bg-opacity-10', 'border-primary');
            icon.classList.replace('bi-check-circle-fill', 'bi-circle');
            icon.classList.remove('text-primary');
        }
    });
}

function toggleLinkSelection(id) {
    if (selectedLinkIds.has(id)) { selectedLinkIds.delete(id); } else { selectedLinkIds.add(id); }
    updateLinkSelectionUI();
}

function clearLinkSelection() {
    selectedLinkIds.clear(); updateLinkSelectionUI();
}

let st; 
function debounceSearchLink() { 
    const val = document.getElementById('linkSearchInput').value.trim();
    clearTimeout(st); 
    
    // 【修改】如果清空了输入框，重新显示推荐
    if (!val) {
        loadSimilarRecommendations();
        return;
    }
    
    st=setTimeout(()=>{performLinkSearch(val)},500); 
}

function performLinkSearch(q) {
    if(!q) return;
    const container = document.getElementById('linkSearchResults');
    container.innerHTML = '<div class="text-center text-muted p-3"><span class="spinner-border spinner-border-sm"></span> 搜索中...</div>';
    
    fetch(`/api/groups/?q=${encodeURIComponent(q)}`).then(r=>r.json()).then(d=>{
        container.innerHTML = ''; // 清空 loading
        if(!d.results.length) { 
            container.innerHTML='<div class="text-center text-muted p-5">未找到匹配结果</div>'; 
            return; 
        }
        renderLinkResults(d.results, true);
    });
}

// 【新增】提取渲染逻辑，供搜索和推荐共用
function renderLinkResults(results, append = false) {
    const container = document.getElementById('linkSearchResults');
    const currentPk = getCurrentGroupId();
    
    if (!append) container.innerHTML = '';

    results.forEach(i => {
        if (i.id === currentPk) return; 

        const isSelected = selectedLinkIds.has(i.id);
        const bgClass = isSelected ? 'bg-primary bg-opacity-10 border-primary' : '';
        const iconClass = isSelected ? 'bi-check-circle-fill text-primary' : 'bi-circle text-muted';
        
        // 如果有相似度字段，显示相似度徽章
        const similarityBadge = i.similarity ? 
            `<span class="badge bg-success bg-opacity-10 text-success border border-success border-opacity-25 ms-2" style="font-weight:normal; font-size:0.7rem;">相似度 ${i.similarity}</span>` : '';

        const html = `
            <div class="d-flex align-items-center p-2 border-bottom search-result-item ${bgClass}" 
                 data-id="${i.id}" 
                 onclick="toggleLinkSelection(${i.id})" 
                 style="cursor:pointer; transition: all 0.2s;">
                <div class="me-3"><i class="bi ${iconClass} select-icon fs-5"></i></div>
                <div class="rounded overflow-hidden bg-light me-3 border" style="width: 48px; height: 48px; flex-shrink: 0;">
                    ${i.cover_url ? `<img src="${i.cover_url}" class="w-100 h-100 object-fit-cover">` : '<div class="w-100 h-100 d-flex align-items-center justify-content-center text-muted"><i class="bi bi-image"></i></div>'}
                </div>
                <div class="flex-grow-1 overflow-hidden">
                    <div class="d-flex align-items-center mb-1">
                        <div class="fw-bold text-truncate text-dark" style="font-size: 0.9rem; max-width: 200px;">${i.title}</div>
                        ${similarityBadge}
                    </div>
                    <div class="text-muted text-truncate small" style="font-size: 0.75rem;">${i.prompt_text ? i.prompt_text.substring(0,60) : '无提示词'}...</div>
                </div>
            </div>`;
        container.insertAdjacentHTML('beforeend', html);
    });
}

function submitLinkSelection() {
    if (selectedLinkIds.size === 0) { Swal.fire('提示', '请至少选择一个版本', 'warning'); return; }
    const currentPk = getCurrentGroupId();
    
    Swal.fire({
        title: `确认关联 ${selectedLinkIds.size} 个版本?`, 
        text: '这些版本将归入同一系列，共享展示位置。',
        icon: 'question', 
        showCancelButton: true, 
        confirmButtonText: '确认关联',
        confirmButtonColor: '#0d6efd'
    }).then((result) => {
        if (result.isConfirmed) {
            fetch(`/api/link-group/${currentPk}/`, {
                method: 'POST',
                body: JSON.stringify({ target_ids: Array.from(selectedLinkIds) }),
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') }
            })
            .then(res => res.json())
            .then(data => {
                if (data.status === 'success') {
                    Swal.fire({
                        icon: 'success', 
                        title: '关联成功', 
                        toast: true, 
                        position: 'top-end', 
                        showConfirmButton: false, 
                        timer: 1500
                    }).then(() => location.reload());
                } else { Swal.fire('失败', data.message, 'error'); }
            });
        }
    });
}
// === 主版本设置逻辑 ===

function setMainVariant(pk) {
    const btn = event.currentTarget;
    // 简单的防止重复点击
    if(btn.style.opacity === '0.5') return;
    
    const csrfToken = getCookie('csrftoken');
    
    // 乐观UI更新 (先变色，失败再变回来)
    const originalStyle = btn.getAttribute('style');
    btn.style.opacity = '0.5';

    fetch(`/api/set-main/${pk}/`, {
        method: 'POST',
        headers: { 'X-CSRFToken': csrfToken }
    })
    .then(res => res.json())
    .then(data => {
        if (data.status === 'success') {
            Swal.fire({
                icon: 'success',
                title: '已设为首页展示版本',
                toast: true,
                position: 'top',
                showConfirmButton: false,
                timer: 1500
            }).then(() => location.reload()); // 刷新页面以更新所有状态
        } else {
            btn.setAttribute('style', originalStyle);
            Swal.fire('设置失败', '未知错误', 'error');
        }
    })
    .catch(err => {
        btn.setAttribute('style', originalStyle);
        console.error(err);
    });
}

function setMainVariantSibling(e, pk) {
    e.preventDefault(); e.stopPropagation();
    setMainVariant(pk); // 复用上面的逻辑
}

window.enableParamEdit = function(field, currentValue, pk) {
    const displaySpan = document.getElementById(`display-${field}`);
    if (!displaySpan || displaySpan.querySelector('input')) return; 

    // 1. 获取原有的 datalist 数据，并转化为 JS 数组
    const listId = field === 'model_info' ? 'model-list' : 'provider-list';
    const datalist = document.getElementById(listId);
    const options = Array.from(datalist.options).map(opt => ({
        value: opt.value,
        text: opt.text || opt.value // 获取显示的文本（如：fal_ai (Fal AI)）
    }));

    displaySpan.dataset.originalHtml = displaySpan.innerHTML;

    // 2. 注入带有高级 CSS 类的全新结构，去掉原生 list 属性
    displaySpan.innerHTML = `
        <div class="custom-param-container">
            <input type="text" 
                   id="input-${field}" 
                   class="custom-param-input" 
                   value="${currentValue}" 
                   autocomplete="off"
                   placeholder="输入或选择...">
            <div id="dropdown-${field}" class="custom-param-dropdown"></div>
        </div>
    `;
    
    const inputEl = document.getElementById(`input-${field}`);
    const dropdownEl = document.getElementById(`dropdown-${field}`);
    let currentFocus = -1; // 键盘上下键的索引

    // 3. 渲染优雅的下拉菜单内容
    const renderDropdown = (filterText = '') => {
        const lowerFilter = filterText.toLowerCase();
        // 模糊搜索
        const filtered = options.filter(o => o.value.toLowerCase().includes(lowerFilter) || o.text.toLowerCase().includes(lowerFilter));

        if (filtered.length === 0) {
            dropdownEl.innerHTML = '<div class="p-2 text-muted small text-center"><i class="bi bi-magic me-1"></i>按回车创建新标签</div>';
        } else {
            dropdownEl.innerHTML = filtered.map(o => `
                <div class="custom-param-item" data-value="${o.value}">
                    <i class="bi bi-chevron-right text-indigo-300 opacity-50 me-2" style="font-size:0.7rem;"></i>${o.text}
                </div>
            `).join('');
        }

        // 为每一个选项绑定点击事件 (使用 mousedown 是为了在 input 的 blur 触发前执行)
        dropdownEl.querySelectorAll('.custom-param-item').forEach((item, index) => {
            item.addEventListener('mousedown', (e) => {
                e.preventDefault(); 
                inputEl.value = item.dataset.value;
                dropdownEl.classList.remove('show');
                inputEl.blur(); // 赋值后手动触发失去焦点，执行保存
            });
        });
        currentFocus = -1;
    };

    // 4. 强行延迟 50 毫秒（等待浏览器渲染完毕），然后直接展开下拉框并全选文字
    setTimeout(() => {
        renderDropdown('');               // 渲染所有选项
        dropdownEl.classList.add('show'); // 强制显示下拉框
        inputEl.focus();                  // 强制聚焦
        inputEl.select();                 // 全选已有文字
    }, 50);

    inputEl.addEventListener('input', () => {
        renderDropdown(inputEl.value);
        dropdownEl.classList.add('show');
    });

    inputEl.addEventListener('blur', () => {
        // 延迟移除，让动画有时间播放完成，并执行保存逻辑
        dropdownEl.classList.remove('show');
        saveParamEdit(field, pk, inputEl.value.trim(), currentValue, displaySpan);
    });

    // 5. 键盘导航逻辑 (完美支持上下箭头与回车)
    inputEl.addEventListener('keydown', function(e) {
        let items = dropdownEl.querySelectorAll('.custom-param-item');
        
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            currentFocus++;
            addActive(items);
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            currentFocus--;
            addActive(items);
        } else if (e.key === 'Enter') {
            e.preventDefault();
            if (currentFocus > -1 && items.length > 0) {
                // 如果用键盘选定了某一项，直接模拟点击
                items[currentFocus].dispatchEvent(new Event('mousedown'));
            } else {
                // 如果没选，直接保存框里的内容
                dropdownEl.classList.remove('show');
                inputEl.blur();
            }
        } else if (e.key === 'Escape') {
            dropdownEl.classList.remove('show');
            displaySpan.innerHTML = displaySpan.dataset.originalHtml;
        }
    });

    // 辅助函数：处理键盘上下高亮状态
    function addActive(items) {
        if (!items || items.length === 0) return;
        removeActive(items);
        if (currentFocus >= items.length) currentFocus = 0;
        if (currentFocus < 0) currentFocus = items.length - 1;
        
        items[currentFocus].classList.add('active');
        // 自动滚动到可视区域
        items[currentFocus].scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }

    function removeActive(items) {
        items.forEach(item => item.classList.remove('active'));
    }
};

function saveParamEdit(field, pk, newValue, oldValue, displaySpan) {
    // 如果没有实质性修改，恢复原状并退出
    if (newValue === oldValue) {
        displaySpan.innerHTML = displaySpan.dataset.originalHtml;
        return;
    }
    
    const payload = {};
    payload[field] = newValue;
    
    fetch(`/update-prompts/${pk}/`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken') 
        },
        body: JSON.stringify(payload)
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            // 保存成功后刷新页面 (确保根据新的 provider 渲染出对应的颜色和图标)
            window.location.reload();
        } else {
            alert('修改失败: ' + data.message);
            displaySpan.innerHTML = displaySpan.dataset.originalHtml;
        }
    })
    .catch(error => {
        console.error('保存参数时发生错误:', error);
        alert('网络错误，修改失败');
        displaySpan.innerHTML = displaySpan.dataset.originalHtml;
    });
}

// ================= 大图预览：基于 Transform 的完美放大与拖拽 =================

document.addEventListener('DOMContentLoaded', function() {
    const previewImg = document.getElementById('previewImage');
    const modalBody = previewImg ? previewImg.closest('.modal-body') : null;
    
    if (!previewImg || !modalBody) return;

    // 核心矩阵变量
    let scale = 1;
    let translateX = 0;
    let translateY = 0;

    // 拖拽状态管理
    let isDragging = false;
    let dragMoved = false; // 用于严格区分“纯点击”还是“拖拽”
    let startX, startY;
    let lastTranslateX = 0;
    let lastTranslateY = 0;

    // 1. 鼠标按下：准备拖拽
    previewImg.addEventListener('mousedown', function(e) {
        if (scale === 1) return; // 没放大时不许拖动
        e.preventDefault(); // 防止触发浏览器默认的图片拖拽(禁止图标)
        
        // 拖拽时【必须】关闭 CSS 动画过渡，保证图片 100% 贴紧鼠标无延迟
        previewImg.style.transition = 'none';

        isDragging = true;
        dragMoved = false;
        startX = e.clientX;
        startY = e.clientY;
        lastTranslateX = translateX;
        lastTranslateY = translateY;
    });

    // 2. 全局鼠标移动：执行平移计算
    document.addEventListener('mousemove', function(e) {
        if (!isDragging) return;

        const dx = e.clientX - startX;
        const dy = e.clientY - startY;

        // 移动距离超过 5px 判定为真实的拖拽 (防止帕金森手抖导致的点击失效)
        if (Math.abs(dx) > 5 || Math.abs(dy) > 5) {
            dragMoved = true;
        }

        if (dragMoved) {
            // 实时更新偏移量并渲染
            translateX = lastTranslateX + dx;
            translateY = lastTranslateY + dy;
            updateTransform();
        }
    });

    // 3. 全局鼠标松开：结束拖拽
    document.addEventListener('mouseup', function() {
        if (isDragging) {
            isDragging = false;
            // 延迟一点重置 dragMoved，让下方的 click 事件有足够的时间去读取它并进行拦截
            setTimeout(() => {
                dragMoved = false;
            }, 50);
        }
    });

    // 4. 核心：点击放大 / 缩小
    previewImg.addEventListener('click', function(e) {
        // 【最关键的拦截】：如果刚刚发生了真实的拖拽移动，这次松开绝对不能触发缩小！
        if (dragMoved) return;

        if (scale === 1) {
            // --- 进入放大模式 ---
            scale = 2.5; // 放大倍数，默认 2.5 倍
            
            // 数学计算：获取点击位置相对于图片中心点的偏移量，实现“指哪放哪”
            const rect = previewImg.getBoundingClientRect();
            const offsetX = e.clientX - rect.left - rect.width / 2;
            const offsetY = e.clientY - rect.top - rect.height / 2;
            
            // 计算为了让点击点居中，需要反向移动的距离
            translateX = -offsetX * (scale - 1);
            translateY = -offsetY * (scale - 1);

            // 开启过渡动画，让放大过程充满丝滑感
            previewImg.style.transition = 'transform 0.3s cubic-bezier(0.25, 1, 0.5, 1)';
            previewImg.classList.add('zoomed-in');
            modalBody.classList.add('modal-zoomed-mode');
            
        } else {
            // --- 退出放大模式 ---
            resetZoomState();
        }
        updateTransform();
    });

    // 统一更新 DOM 的 transform 属性
    function updateTransform() {
        previewImg.style.transform = `translate(${translateX}px, ${translateY}px) scale(${scale})`;
    }

    // 全局重置状态函数
    function resetZoomState() {
        if (scale === 1) return;
        scale = 1;
        translateX = 0;
        translateY = 0;
        
        // 开启过渡动画，让缩小回原位的过程同样丝滑
        previewImg.style.transition = 'transform 0.3s cubic-bezier(0.25, 1, 0.5, 1)';
        previewImg.classList.remove('zoomed-in');
        modalBody.classList.remove('modal-zoomed-mode');
        
        updateTransform();
    }

    // 5. 状态清理：监听图片切换或模态框关闭，强制退出放大模式
    const observer = new MutationObserver(function(mutations) {
        mutations.forEach(function(mutation) {
            if (mutation.attributeName === "src") {
                // 用户点击“下一张”时，瞬间重置回原位，不需要过渡动画
                previewImg.style.transition = 'none';
                resetZoomState();
            }
        });
    });
    observer.observe(previewImg, { attributes: true });
    
    // 模态框关闭时清理
    const modalEl = document.getElementById('imageModal');
    if (modalEl) {
        modalEl.addEventListener('hide.bs.modal', function () {
            previewImg.style.transition = 'none';
            resetZoomState();
        });
    }
});
// ===== 详情页扩展交互逻辑 (从 HTML 中提取) =====

document.addEventListener('DOMContentLoaded', function () {
    // 1. 获取后端传来的配置数据 (如果存在)
    let detailConfig = { ...getDetailPageConfig(), ...(window.detailConfig || {}) };
    window.detailConfig = detailConfig;

    var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    var tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });

    // === 批量管理逻辑 Start ===
    const body = document.body;
    const btnEnter = document.getElementById('btn-enter-batch');
    const btnExit = document.getElementById('btn-exit-batch');
    const batchBar = document.getElementById('batch-action-bar');
    const countSpan = document.getElementById('selected-count');
    const btnSelectAll = document.getElementById('btn-select-all');

    function toggleBatchMode(active) {
        if (active) {
            body.classList.add('batch-mode');
            batchBar.classList.add('active');
            btnEnter.classList.add('d-none');
        } else {
            body.classList.remove('batch-mode');
            batchBar.classList.remove('active');
            btnEnter.classList.remove('d-none');
            document.querySelectorAll('.item-card').forEach(c => c.classList.remove('selected'));
            updateCount();
        }
    }

    if(btnEnter) btnEnter.addEventListener('click', () => toggleBatchMode(true));
    if(btnExit) btnExit.addEventListener('click', () => toggleBatchMode(false));

    const gridContainer = document.getElementById('detail-masonry-grid-images');
    const videoGridContainer = document.getElementById('detail-masonry-grid-videos');
    let isDragSelectionOccurred = false;

    function handleCardClick(e) {
        if (!body.classList.contains('batch-mode')) return;
        if (isDragSelectionOccurred) return;
        
        const card = e.target.closest('.item-card');
        if (card) {
            e.preventDefault();
            e.stopPropagation();
            card.classList.toggle('selected');
            updateCount();
        }
    }

    if(gridContainer) gridContainer.addEventListener('click', handleCardClick);
    if(videoGridContainer) videoGridContainer.addEventListener('click', handleCardClick);

    // 框选逻辑
    const selectionBox = document.createElement('div');
    selectionBox.classList.add('selection-area-box');
    document.body.appendChild(selectionBox);

    let isDragging = false;
    let startX, startY;

    document.addEventListener('mousedown', function(e) {
        if (!body.classList.contains('batch-mode')) return;
        if (e.target.closest('.batch-bar') || 
            e.target.closest('.sticky-sidebar') || 
            e.target.closest('.modal') || 
            e.target.closest('button')) return;

        isDragging = true;
        isDragSelectionOccurred = false; 
        startX = e.clientX;
        startY = e.clientY;
        
        selectionBox.style.left = startX + 'px';
        selectionBox.style.top = startY + 'px';
        selectionBox.style.width = '0px';
        selectionBox.style.height = '0px';
        selectionBox.style.display = 'block';
    });

    document.addEventListener('mousemove', function(e) {
        if (!isDragging) return;

        const curX = e.clientX;
        const curY = e.clientY;

        if (Math.abs(curX - startX) > 5 || Math.abs(curY - startY) > 5) {
            isDragSelectionOccurred = true;
        }

        const left = Math.min(startX, curX);
        const top = Math.min(startY, curY);
        const width = Math.abs(curX - startX);
        const height = Math.abs(curY - startY);

        selectionBox.style.left = left + 'px';
        selectionBox.style.top = top + 'px';
        selectionBox.style.width = width + 'px';
        selectionBox.style.height = height + 'px';

        const cards = document.querySelectorAll('.item-card');
        cards.forEach(card => {
            const rect = card.getBoundingClientRect();
            if (left < rect.right && left + width > rect.left && top < rect.bottom && top + height > rect.top) {
                 if (!card.classList.contains('selected')) {
                     card.classList.add('selected');
                 }
            }
        });
        
        if (isDragSelectionOccurred) {
            requestAnimationFrame(updateCount);
        }
    });

    document.addEventListener('mouseup', function(e) {
        if (isDragging) {
            isDragging = false;
            selectionBox.style.display = 'none';
            selectionBox.style.width = '0';
            selectionBox.style.height = '0';
            setTimeout(() => { isDragSelectionOccurred = false; }, 100);
        }
    });

    if(btnSelectAll) {
        btnSelectAll.addEventListener('click', () => {
            const cards = document.querySelectorAll('.item-card');
            const allSelected = document.querySelectorAll('.item-card.selected').length === cards.length;
            cards.forEach(c => {
                if (allSelected) c.classList.remove('selected');
                else c.classList.add('selected');
            });
            updateCount();
        });
    }

    function updateCount() {
        const count = document.querySelectorAll('.item-card.selected').length;
        if(countSpan) countSpan.textContent = count;
    }

    function getSelectedItems() {
        const selected = [];
        document.querySelectorAll('.item-card.selected').forEach(card => {
            selected.push({
                id: card.dataset.imgId,
                url: card.dataset.imgUrl
            });
        });
        return selected;
    }

    const batchDeleteModalEl = document.getElementById('batchDeleteModal');
    let modalDelete;
    if(batchDeleteModalEl) {
        modalDelete = new bootstrap.Modal(batchDeleteModalEl);
    }
    const btnTriggerDelete = document.getElementById('btn-batch-delete-trigger');
    const btnConfirmDelete = document.getElementById('btn-confirm-batch-delete');

    if(btnTriggerDelete && modalDelete) {
        btnTriggerDelete.addEventListener('click', () => {
            const items = getSelectedItems();
            if (items.length === 0) return alert('请先选择要删除的项目');
            document.getElementById('modal-delete-count').textContent = items.length;
            modalDelete.show();
        });
    }

    if(btnConfirmDelete && modalDelete) {
        btnConfirmDelete.addEventListener('click', () => {
            const items = getSelectedItems();
            const ids = items.map(i => i.id);
            const csrfInput = document.querySelector('[name=csrfmiddlewaretoken]');
            const csrfToken = csrfInput ? csrfInput.value : '';
            
            fetch("/batch-delete-images/", { 
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify({ image_ids: ids })
            })
            .then(response => response.json())
            .then(data => {
                modalDelete.hide();
                if (data.status === 'success') {
                    document.querySelectorAll('.item-card.selected').forEach(card => {
                        const col = card.closest('.col-6') || card.closest('.col-12') || card; 
                        col.remove();
                    });
                    toggleBatchMode(false); 
                    const imgCountBadge = document.getElementById('image-count-badge');
                    if(imgCountBadge) imgCountBadge.innerText = document.querySelectorAll('#detail-masonry-grid-images .item-card').length;
                } else {
                    alert('删除失败: ' + data.message);
                }
            });
        });
    }

    const btnBatchDownload = document.getElementById('btn-batch-download');
    const modalDownloadEl = document.getElementById('batchDownloadModal');
    let modalDownload;
    if(modalDownloadEl) {
        modalDownload = new bootstrap.Modal(modalDownloadEl);
    }
    const btnConfirmDownload = document.getElementById('btn-confirm-batch-download');
    
    function sanitizeFilename(text) {
        if (!text) return 'image';
        return text.replace(/[\r\n]+/g, ' ').replace(/[<>:"/\\|?*]/g, '').trim().substring(0, 60);
    }

    if(btnBatchDownload && modalDownload) {
        btnBatchDownload.addEventListener('click', () => {
            const items = getSelectedItems();
            if (items.length === 0) return alert('请先选择要下载的项目');
            document.getElementById('modal-download-count').textContent = items.length;
            modalDownload.show();
        });
    }

    if(btnConfirmDownload && modalDownload) {
        btnConfirmDownload.addEventListener('click', () => {
            modalDownload.hide();
            const items = getSelectedItems();
            const basePromptName = sanitizeFilename(window.detailConfig.rawPromptContent) || 'image';

            const downloadNext = (index) => {
                if (index >= items.length) return;
                const item = items[index];
                const ext = item.url.split('.').pop().split('?')[0]; 
                const filename = `${basePromptName}_${item.id}.${ext}`; 
                
                fetch(item.url)
                    .then(resp => resp.blob())
                    .then(blob => {
                        const url = window.URL.createObjectURL(blob);
                        const a = document.createElement('a');
                        a.style.display = 'none';
                        a.href = url;
                        a.download = filename; 
                        document.body.appendChild(a);
                        a.click();
                        window.URL.revokeObjectURL(url);
                        document.body.removeChild(a);
                        setTimeout(() => downloadNext(index + 1), 400); 
                    })
                    .catch(err => {
                        console.error('下载失败', err);
                        setTimeout(() => downloadNext(index + 1), 400);
                    });
            };
            downloadNext(0);
        });
    }

    // 智能对比并高亮“其他版本”列表中的人物标签
    const currentCharNodes = document.querySelectorAll('#characters-wrapper .tag-char a');
    const currentCharNames = Array.from(currentCharNodes).map(a => a.textContent.trim());
    
    document.querySelectorAll('.sibling-char-badge').forEach(badge => {
        const charName = badge.getAttribute('data-char');
        if (currentCharNames.includes(charName)) {
            badge.style.backgroundColor = '#fff0f6';
            badge.style.color = '#d81b60';
            badge.style.borderColor = '#ffdeeb';
            badge.title = "人物一致";
        } else {
            badge.style.backgroundColor = '#fff3cd';
            badge.style.color = '#856404';
            badge.style.borderColor = '#ffeeba';
            badge.innerHTML = '<i class="bi bi-person-exclamation me-1"></i>' + charName;
            badge.title = "人物变更: 当前主卡片无此角色";
        }
    });

    // 底部抽屉批量管理
    const drawerGrid = document.getElementById('drawer-siblings-grid');
    const drawerCountSpan = document.getElementById('drawer-selected-count');
    
    if (drawerGrid) {
        drawerGrid.addEventListener('click', function(e) {
            if (e.target.closest('.diff-toggle-btn')) return;
            const card = e.target.closest('.item-card');
            if (card) {
                card.classList.toggle('selected');
                updateDrawerCount();
            }
        });
        
        function updateDrawerCount() {
            const count = drawerGrid.querySelectorAll('.item-card.selected').length;
            if(drawerCountSpan) {
                drawerCountSpan.textContent = count;
                drawerCountSpan.style.transform = 'scale(1.3)';
                setTimeout(() => drawerCountSpan.style.transform = 'scale(1)', 200);
            }
        }
        
        const btnSelectAllDrawer = document.getElementById('btn-drawer-select-all');
        if(btnSelectAllDrawer) {
            btnSelectAllDrawer.addEventListener('click', function() {
                const cards = drawerGrid.querySelectorAll('.item-card');
                const allSelected = drawerGrid.querySelectorAll('.item-card.selected').length === cards.length;
                cards.forEach(card => {
                    if (allSelected) card.classList.remove('selected');
                    else card.classList.add('selected');
                });
                this.textContent = allSelected ? "全选" : "取消全选";
                updateDrawerCount();
            });
        }
        
        function getSelectedSiblingIds() {
            const selected = [];
            drawerGrid.querySelectorAll('.drawer-sibling-item').forEach(item => {
                if (item.querySelector('.item-card').classList.contains('selected')) {
                    selected.push(item.getAttribute('data-id'));
                }
            });
            return selected;
        }

        const btnDrawerMerge = document.getElementById('btn-drawer-merge');
        if(btnDrawerMerge) {
            btnDrawerMerge.addEventListener('click', function() {
                const ids = getSelectedSiblingIds();
                if (ids.length === 0) return Swal.fire('提示', '请先选择要合并的版本', 'info');
                const mainGroupId = window.detailConfig.groupId;
                if (!mainGroupId) return Swal.fire('错误', '无法获取当前作品ID', 'error');

                Swal.fire({
                    title: `确认合并这 ${ids.length} 个版本？`,
                    text: "被合并版本内的所有图片将转移至当前作品中，并且原来的空壳版本将被永久删除！此操作不可恢复。",
                    icon: 'warning',
                    showCancelButton: true,
                    confirmButtonColor: '#ffc107',
                    cancelButtonColor: '#6c757d',
                    confirmButtonText: '确认合并',
                    cancelButtonText: '取消'
                }).then((result) => {
                    if (result.isConfirmed) {
                        Swal.fire({ title: '正在合并...', allowOutsideClick: false, didOpen: () => { Swal.showLoading(); } });
                        // 请确保 getCookie 存在（通常在 common.js）
                        let tk = typeof getCookie === 'function' ? getCookie('csrftoken') : document.querySelector('[name=csrfmiddlewaretoken]').value;
                        fetch('/api/merge-variants/', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                                'X-CSRFToken': tk 
                            },
                            body: JSON.stringify({ main_group_id: mainGroupId, merge_ids: ids })
                        })
                        .then(response => response.json())
                        .then(data => {
                            if (data.status === 'success') {
                                Swal.fire({ icon: 'success', title: '合并完成', timer: 1500, showConfirmButton: false }).then(() => window.location.reload());
                            } else {
                                Swal.fire('合并失败', data.message, 'error');
                            }
                        })
                        .catch(error => {
                            console.error('Error:', error);
                            Swal.fire('网络错误', '请求未能成功，请检查网络或控制台', 'error');
                        });
                    }
                });
            });
        }

        const btnDrawerUnlink = document.getElementById('btn-drawer-unlink');
        if(btnDrawerUnlink) {
            btnDrawerUnlink.addEventListener('click', function() {
                const ids = getSelectedSiblingIds();
                if (ids.length === 0) return Swal.fire('提示', '请先选择要解除关联的版本', 'info');
                
                Swal.fire({
                    title: `确认解除这 ${ids.length} 个版本的关联?`,
                    text: '这些版本将从当前系列中移出，变为独立的画廊卡片。',
                    icon: 'warning',
                    showCancelButton: true,
                    confirmButtonColor: '#dc3545',
                    confirmButtonText: '确认解除'
                }).then((result) => {
                    if (result.isConfirmed) {
                        Swal.fire({ title: '正在解除关联...', allowOutsideClick: false, didOpen: () => { Swal.showLoading(); } });
                        let tk = typeof getCookie === 'function' ? getCookie('csrftoken') : document.querySelector('[name=csrfmiddlewaretoken]').value;
                        
                        const unlinkPromises = ids.map(id => 
                            fetch(`/api/unlink-group/${id}/`, {
                                method: 'POST',
                                headers: { 'X-CSRFToken': tk }
                            }).then(res => res.json())
                        );

                        Promise.all(unlinkPromises)
                            .then(results => {
                                const allSuccess = results.every(res => res.status === 'success');
                                if (allSuccess) {
                                    Swal.fire({ icon: 'success', title: '已批量解除关联', timer: 1500, showConfirmButton: false }).then(() => window.location.reload());
                                } else {
                                    Swal.fire('部分失败', '有部分版本未能解除关联，请刷新页面查看', 'warning').then(() => window.location.reload());
                                }
                            })
                            .catch(error => {
                                console.error('Error:', error);
                                Swal.fire('网络错误', '批量请求未能完全成功', 'error');
                            });
                    }
                });
            });
        }
    }
});

// AI 工作室打开
function openAiStudioModal() {
    const modalEl = document.getElementById('aiStudioModal');
    if (modalEl) {
        new bootstrap.Modal(modalEl).show();
    }
}

// 悬浮按钮点击
function toggleGroupLike(btn, groupId) {
    const icon = btn.querySelector('i');
    const isLiked = btn.classList.contains('liked');
    btn.classList.toggle('liked');
    if (!isLiked) {
        icon.classList.remove('bi-heart');
        icon.classList.add('bi-heart-fill');
        btn.setAttribute('data-bs-original-title', '取消喜欢');
        icon.style.transform = 'scale(1.4)';
        setTimeout(() => icon.style.transform = 'scale(1)', 200);
    } else {
        icon.classList.remove('bi-heart-fill');
        icon.classList.add('bi-heart');
        btn.setAttribute('data-bs-original-title', '喜欢此作品');
    }
    const tooltip = bootstrap.Tooltip.getInstance(btn);
    if (tooltip) tooltip.hide();

    const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]').value;
    fetch(`/toggle-like-group/${groupId}/`, {
        method: 'POST',
        headers: {
            'X-CSRFToken': csrfToken,
            'X-Requested-With': 'XMLHttpRequest'
        }
    }).catch(err => console.error(err));
}

// 右键菜单逻辑
const contextMenu = document.getElementById('imgContextMenu');
let rightClickedImgId = null;

if(contextMenu) {
    document.addEventListener('contextmenu', function(e) {
        const card = e.target.closest('.item-card');
        const isInDrawer = e.target.closest('#siblingsBatchDrawer');
        if (card && !isInDrawer) {
            e.preventDefault(); 
            rightClickedImgId = card.dataset.imgId;
            contextMenu.style.display = 'block';
            contextMenu.style.left = `${e.clientX}px`;
            contextMenu.style.top = `${e.clientY}px`;
        } else {
            contextMenu.style.display = 'none';
        }
    });

    document.addEventListener('click', function() {
        contextMenu.style.display = 'none';
    });
    
    window.addEventListener('scroll', () => { contextMenu.style.display = 'none'; }, true);
}

function setAsCoverFromMenu() {
    if (!rightClickedImgId || !window.detailConfig.groupId) return;
    const groupId = window.detailConfig.groupId;
    const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]').value;

    Swal.fire({
        title: '正在设置...',
        didOpen: () => Swal.showLoading(),
        background: 'transparent',
        backdrop: 'rgba(0,0,0,0.1)',
        showConfirmButton: false
    });

    fetch(`/api/set-cover/${groupId}/${rightClickedImgId}/`, {
        method: 'POST',
        headers: {
            'X-CSRFToken': csrfToken,
            'Content-Type': 'application/json'
        }
    })
    .then(res => res.json())
    .then(data => {
        if (data.status === 'success') {
            Swal.fire({ icon: 'success', title: '封面已更新', toast: true, position: 'top', showConfirmButton: false, timer: 1000 });
            setTimeout(() => { window.location.reload(); }, 1000);
        } else {
            Swal.fire('设置失败', data.message, 'error');
        }
    })
    .catch(err => {
        console.error(err);
        Swal.fire('错误', '网络请求失败', 'error');
    });
}

function toggleDiff(event, btn) {
    event.preventDefault();
    event.stopPropagation(); 
    const container = btn.closest('.diff-container');
    const hiddenTags = container.querySelectorAll('.diff-hidden-tag');
    const isExpanded = btn.classList.contains('expanded');
    const count = btn.getAttribute('data-hidden-count');

    if (isExpanded) {
        hiddenTags.forEach(tag => tag.style.display = 'none');
        btn.classList.remove('expanded');
        btn.innerHTML = `<i class="bi bi-chevron-down"></i> 展开剩余 ${count} 项`;
        btn.style.background = '#f8fafc'; 
    } else {
        hiddenTags.forEach(tag => tag.style.display = '');
        btn.classList.add('expanded');
        btn.innerHTML = `<i class="bi bi-chevron-up"></i> 收起展开的 ${count} 项`;
        btn.style.background = '#e2e8f0'; 
    }
}

document.addEventListener('DOMContentLoaded', function () {
    const detailConversationSendBtn = document.getElementById('detail-gpt-conversation-send');
    if (detailConversationSendBtn) {
        detailConversationSendBtn.addEventListener('click', sendDetailConversationMessage);
    }

    const detailConversationResetBtn = document.getElementById('detail-gpt-conversation-reset');
    if (detailConversationResetBtn) {
        detailConversationResetBtn.addEventListener('click', resetDetailConversationState);
    }

    loadRecentDetailConversations();
    updateDetailConversationPanelVisibility();
});