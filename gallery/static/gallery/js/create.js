// 1. 获取后端传来的超级配置对象 (通过 HTML 中的 JSON script 标签)
let AI_CONFIG = {};
try {
    const configEl = document.getElementById('ai-config-data');
    if (configEl) {
        AI_CONFIG = JSON.parse(configEl.textContent);
    }
} catch (e) {
    console.error("加载 AI_CONFIG 失败", e);
}

let currentFiles = []; 
let currentExtraFiles = {};
let maxImagesAllowed = 0;
let lastSavedPaths = []; 
let initialTagsForPublish = [];
let initialCharsForPublish = [];
let allAvailableTags = [];
let allAvailableChars = [];
let currentSelectedTags = new Set(); 
let currentSelectedChars = new Set();
let currentSourceGroupId = null;
let currentPublishPromptItems = [];
let maskEditorExportCanvas = null;
let createConversationState = {
    conversationId: null,
    conversation: null,
    isSending: false,
    selectedPath: null,
};
const maskEditorState = {
    imageFile: null,
    imageName: '',
    isDrawing: false,
    lastPoint: null,
    tool: 'brush',
    brushSize: 28,
    baseCanvas: null,
    drawCanvas: null,
    displayCtx: null,
    exportCtx: null,
    baseImage: null,
};

function normalizeModelName(name) {
    return String(name || '')
        .trim()
        .toLowerCase()
        .replace(/\s*[\(（].*?[\)）]$/, '')
        .trim();
}

function escapeHtml(value) {
    return String(value || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function buildPromptMediationRuleBadges(rules) {
    if (!Array.isArray(rules) || !rules.length) {
        return '<span class="small text-muted">未触发专门规则</span>';
    }

    return rules.map((rule) => (
        `<span class="badge rounded-pill text-bg-light border text-secondary">${escapeHtml(rule)}</span>`
    )).join('');
}

function buildPromptMediationRewriteDetails(details) {
    if (!Array.isArray(details) || !details.length) {
        return '<div class="small text-muted">没有发生逐条改写。</div>';
    }

    return details.map((detail) => `
        <div class="border rounded-3 bg-white p-2">
            <div class="small text-muted mb-1 d-flex align-items-center gap-2 flex-wrap"><span class="badge rounded-pill text-bg-light border text-secondary">${escapeHtml(detail.reason_tag || '表达优化')}</span><span>${escapeHtml(detail.reason || '表达优化')}</span></div>
            <div class="small"><span class="text-danger">原文</span> ${escapeHtml(detail.before || '')}</div>
            <div class="small mt-1"><span class="text-success">改写后</span> ${escapeHtml(detail.after || '')}</div>
        </div>
    `).join('');
}

function buildPromptMediationOutline(outline) {
    if (!Array.isArray(outline) || !outline.length) {
        return '<span class="small text-muted">暂无结构提取结果</span>';
    }

    return outline.map((block) => (
        `<span class="badge rounded-pill text-bg-light border text-secondary">${escapeHtml(block.label || block.category)}: ${escapeHtml((block.items || []).join(' / '))}</span>`
    )).join('');
}

function renderCreatePromptMediationCard(config, mediation, options = {}) {
    const panel = document.getElementById(config.panelId);
    const badge = document.getElementById(config.badgeId);
    const summary = document.getElementById(config.summaryId);
    const details = document.getElementById(config.detailsId);
    const outline = document.getElementById(config.outlineId);
    const optimized = document.getElementById(config.optimizedId);
    const rules = document.getElementById(config.rulesId);
    const { hideWhenEmpty = false, emptySummary = '发送后会显示实际送入模型的 Prompt。' } = options;

    if (!panel || !badge || !summary || !details || !outline || !optimized || !rules) return;

    if (!mediation || !mediation.optimized_prompt) {
        if (hideWhenEmpty) {
            panel.style.display = 'none';
            return;
        }
        panel.style.display = 'block';
        badge.textContent = '未改写';
        summary.textContent = emptySummary;
        details.innerHTML = '<div class="small text-muted">暂无结果</div>';
        outline.innerHTML = '<span class="small text-muted">暂无结果</span>';
        optimized.textContent = '';
        rules.innerHTML = '<span class="small text-muted">暂无结果</span>';
        return;
    }

    panel.style.display = 'block';
    badge.textContent = mediation.changed ? '已改写' : '原样透传';
    summary.textContent = mediation.changed ? '这次请求已先经过 GPT Image 2 专用 Prompt 优化层。' : '这次请求未触发额外改写，按原意直接发送。';
    details.innerHTML = buildPromptMediationRewriteDetails(mediation.rewrite_details || []);
    outline.innerHTML = buildPromptMediationOutline(mediation.structured_outline || []);
    optimized.textContent = mediation.optimized_prompt || '';
    rules.innerHTML = buildPromptMediationRuleBadges(mediation.applied_rules || []);
}

function hideCreatePromptMediationCard(config) {
    const panel = document.getElementById(config.panelId);
    if (panel) {
        panel.style.display = 'none';
    }
}

function renderCreateGeneratePromptMediation(mediation) {
    renderCreatePromptMediationCard({
        panelId: 'create-gpt-prompt-mediation-panel',
        badgeId: 'create-gpt-prompt-mediation-badge',
        summaryId: 'create-gpt-prompt-mediation-summary',
        detailsId: 'create-gpt-prompt-mediation-details',
        outlineId: 'create-gpt-prompt-mediation-outline',
        optimizedId: 'create-gpt-prompt-mediation-optimized',
        rulesId: 'create-gpt-prompt-mediation-rules',
    }, mediation, {
        hideWhenEmpty: !isCreateConversationEligibleModel(document.getElementById('ai-model-select')?.value),
        emptySummary: '当前仅在 GPT Image 2 请求中生效。',
    });
}

function renderCreateConversationPromptMediation(mediation) {
    renderCreatePromptMediationCard({
        panelId: 'create-gpt-conversation-mediation-panel',
        badgeId: 'create-gpt-conversation-mediation-badge',
        summaryId: 'create-gpt-conversation-mediation-summary',
        detailsId: 'create-gpt-conversation-mediation-details',
        outlineId: 'create-gpt-conversation-mediation-outline',
        optimizedId: 'create-gpt-conversation-mediation-optimized',
        rulesId: 'create-gpt-conversation-mediation-rules',
    }, mediation, {
        hideWhenEmpty: true,
    });
}

function getPromptOptimizationLevelLabel(level) {
    switch (String(level || '').trim().toLowerCase()) {
        case 'off':
            return '关闭优化';
        case 'balanced':
        case 'conservative':
        case 'faithful':
            return '保真';
        case 'enhanced':
        case 'visual_rewrite':
            return '增强';
        default:
            return '当前等级';
    }
}

async function confirmCreatePromptOptimizationEscalation(data, roundIndex) {
    const attemptedLabel = getPromptOptimizationLevelLabel(data.attempted_optimization_level);
    const nextLabel = getPromptOptimizationLevelLabel(data.next_optimization_level);
    const canRetry = Boolean(data.can_retry_higher && data.next_optimization_level);

    const result = await Swal.fire({
        title: `第 ${roundIndex} 轮触发审核拦截`,
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

function getLatestCreateConversationPromptMediation(conversation) {
    const turns = conversation?.turns || [];
    const latestTurn = turns[turns.length - 1];
    return latestTurn?.response_payload?.prompt_mediation || null;
}

function isCreateConversationEligibleModel(modelId) {
    const modelConfig = getModelConfig(modelId);
    if (!modelConfig) return false;
    const registryName = normalizeModelName(modelConfig.registry_name || modelConfig.title);
    return registryName === 'gpt image 2';
}

function collectCurrentDynamicParams() {
    const params = {};
    document.querySelectorAll('.dynamic-param-input').forEach(input => {
        const paramId = input.getAttribute('data-param-id');
        const paramType = input.getAttribute('data-param-type');
        if (!paramId || paramId === 'prompt_aspect_ratio') return;
        params[paramId] = paramType === 'checkbox' ? input.checked : input.value;
    });
    return params;
}

function getCategoryConfig(categoryId) {
    return (AI_CONFIG.categories || []).find(c => c.id === categoryId) || {};
}

function getModelConfig(modelId) {
    return (AI_CONFIG.models || {})[modelId] || null;
}

function modelVisibleInCategory(model, categoryId) {
    if (!model) return false;
    const visibleCategories = Array.isArray(model.visible_in_categories) && model.visible_in_categories.length
        ? model.visible_in_categories
        : [model.category];
    return visibleCategories.includes(categoryId);
}

function getEffectiveUploadConfig(modelId, categoryId = null) {
    const modelConfig = getModelConfig(modelId) || {};
    const resolvedCategoryId = categoryId || modelConfig.category;
    const catConfig = getCategoryConfig(resolvedCategoryId);

    return {
        categoryId: resolvedCategoryId,
        maxImagesAllowed: modelConfig.max_base_images !== undefined ? modelConfig.max_base_images : (catConfig.img_max || 0),
        imgRequired: modelConfig.requires_base_images !== undefined ? modelConfig.requires_base_images : (catConfig.img_required !== undefined ? catConfig.img_required : (catConfig.img_max || 0) > 0),
        imgHelp: modelConfig.base_images_help || catConfig.img_help || '',
    };
}

function getModelFileParams(modelId) {
    const modelConfig = getModelConfig(modelId);
    if (!modelConfig || !Array.isArray(modelConfig.file_params)) {
        return [];
    }
    return modelConfig.file_params;
}

function modelSupportsMaskEditor(modelId) {
    return getModelFileParams(modelId).some(param => param.id === 'mask_url');
}

function clearMaskFile(options = {}) {
    const { silent = false, resetInput = true } = options;
    if (!currentExtraFiles.mask_url) return;

    delete currentExtraFiles.mask_url;
    if (resetInput) {
        const input = document.getElementById('file-param-mask_url');
        if (input) input.value = '';
    }

    renderDynamicFileParams(document.getElementById('ai-model-select').value);

    if (!silent) {
        Swal.fire({
            toast: true,
            position: 'top',
            icon: 'info',
            title: '参考图已变更，旧蒙版已自动清空',
            showConfirmButton: false,
            timer: 2200,
        });
    }
}

function clearMaskFileForReferenceChange() {
    clearMaskFile({ silent: true });
}

function loadImageFromFile(file) {
    return new Promise((resolve, reject) => {
        const image = new Image();
        const objectUrl = URL.createObjectURL(file);
        image.onload = () => {
            URL.revokeObjectURL(objectUrl);
            resolve(image);
        };
        image.onerror = (error) => {
            URL.revokeObjectURL(objectUrl);
            reject(error);
        };
        image.src = objectUrl;
    });
}

function renderExtraFilePreview(paramId) {
    const previewContainer = document.getElementById(`file-param-preview-${paramId}`);
    if (!previewContainer) return;

    previewContainer.innerHTML = '';
    const file = currentExtraFiles[paramId];
    if (!file) return;

    const wrapper = document.createElement('div');
    wrapper.className = 'preview-wrapper m-1';

    const img = document.createElement('img');
    img.className = 'preview-item shadow-sm';
    const reader = new FileReader();
    reader.onload = (e) => {
        img.src = e.target.result;
    };
    reader.readAsDataURL(file);

    const removeBtn = document.createElement('button');
    removeBtn.className = 'btn-remove-preview';
    removeBtn.innerHTML = '<i class="bi bi-x"></i>';
    removeBtn.onclick = (e) => {
        e.preventDefault();
        e.stopPropagation();
        removeExtraFile(paramId);
    };

    wrapper.appendChild(img);
    wrapper.appendChild(removeBtn);
    previewContainer.appendChild(wrapper);
}

function renderDynamicFileParams(modelId) {
    const container = document.getElementById('dynamic-file-params-container');
    if (!container) return;

    const fileParams = getModelFileParams(modelId);
    if (!fileParams.length) {
        container.innerHTML = '';
        return;
    }

    let html = `<div class="p-3 bg-light rounded-3 border"><label class="form-label fw-bold text-secondary small mb-3"><i class="bi bi-images me-1"></i>附加文件参数</label><div class="row g-3">`;
    fileParams.forEach(param => {
        const isMaskParam = param.id === 'mask_url';
        const maskEditorButton = isMaskParam
            ? `
                <div class="d-flex flex-wrap gap-2 align-items-center mt-2">
                    <button type="button" class="btn btn-sm btn-outline-danger rounded-pill" onclick="openMaskEditor()" ${currentFiles.length ? '' : 'disabled'}>
                        <i class="bi bi-pencil-square me-1"></i>${currentExtraFiles.mask_url ? '重绘蒙版' : '打开蒙版画板'}
                    </button>
                    <span class="small text-muted">${currentFiles.length ? '直接基于第 1 张参考图绘制，无需额外做一张蒙版图。' : '请先上传参考图，再打开蒙版画板。'}</span>
                </div>
            `
            : '';

        html += `
            <div class="col-12">
                <label class="form-label small text-muted mb-1">${param.label}${param.required ? ' <span class="text-danger">*</span>' : ''}</label>
                <div class="drag-drop-zone" onclick="document.getElementById('file-param-${param.id}').click()">
                    <i class="bi bi-brush mb-2 d-block"></i>
                    <span class="text-muted fw-bold">点击选择${param.label}</span>
                </div>
                <input type="file" id="file-param-${param.id}" class="d-none" accept="${param.accept || 'image/*'}" onchange="handleExtraFileChange('${param.id}', this.files)">
                ${param.help_text ? `<div class="form-text small text-muted mt-2">${param.help_text}</div>` : ''}
                ${maskEditorButton}
                <div id="file-param-preview-${param.id}" class="d-flex flex-wrap mt-2"></div>
            </div>
        `;
    });
    html += `</div></div>`;
    container.innerHTML = html;

    fileParams.forEach(param => renderExtraFilePreview(param.id));
}

function handleExtraFileChange(paramId, files) {
    if (!files || files.length === 0) return;
    currentExtraFiles[paramId] = files[0];
    renderExtraFilePreview(paramId);
    renderPreviews();
}

function removeExtraFile(paramId) {
    delete currentExtraFiles[paramId];
    const input = document.getElementById(`file-param-${paramId}`);
    if (input) input.value = '';
    renderExtraFilePreview(paramId);
    renderDynamicFileParams(document.getElementById('ai-model-select').value);
    renderPreviews();
}

function applyModelUploadConfig(modelId, categoryId = null) {
    const uploadConfig = getEffectiveUploadConfig(modelId, categoryId);
    const imgBlock = document.getElementById('ai-image-upload-block');
    const fileInput = document.getElementById('file-input-hidden');
    const imgHelp = document.getElementById('ai-img-help');

    maxImagesAllowed = uploadConfig.maxImagesAllowed;

    if (maxImagesAllowed === 0) {
        imgBlock.style.display = 'none';
        currentFiles = [];
    } else {
        imgBlock.style.display = 'block';
        imgHelp.innerHTML = uploadConfig.imgHelp;
        if (maxImagesAllowed === 1) {
            fileInput.removeAttribute('multiple');
            currentFiles = currentFiles.slice(0, 1);
        } else {
            fileInput.setAttribute('multiple', 'multiple');
            currentFiles = currentFiles.slice(0, maxImagesAllowed);
        }
    }

    renderPreviews();
    renderDynamicFileParams(modelId);
    if (!isCreateConversationEligibleModel(modelId)) {
        resetCreateConversationState();
    } else {
        updateCreateConversationPanelVisibility();
    }
}

function getMaskCanvasContexts() {
    if (!maskEditorState.baseCanvas || !maskEditorState.drawCanvas || !maskEditorExportCanvas) {
        return null;
    }

    return {
        baseCanvas: maskEditorState.baseCanvas,
        drawCanvas: maskEditorState.drawCanvas,
        displayCtx: maskEditorState.displayCtx,
        exportCanvas: maskEditorExportCanvas,
        exportCtx: maskEditorState.exportCtx,
    };
}

function resetMaskCanvasExport(width, height) {
    const contexts = getMaskCanvasContexts();
    if (!contexts) return;

    contexts.exportCanvas.width = width;
    contexts.exportCanvas.height = height;
    contexts.exportCtx = contexts.exportCanvas.getContext('2d');
    maskEditorState.exportCtx = contexts.exportCtx;
    maskEditorState.exportCtx.fillStyle = '#000000';
    maskEditorState.exportCtx.fillRect(0, 0, width, height);
}

function applyMaskStroke(fromPoint, toPoint) {
    const contexts = getMaskCanvasContexts();
    if (!contexts || !fromPoint || !toPoint) return;

    const { displayCtx, exportCtx } = contexts;
    const size = maskEditorState.brushSize;

    displayCtx.lineCap = 'round';
    displayCtx.lineJoin = 'round';
    displayCtx.lineWidth = size;
    exportCtx.lineCap = 'round';
    exportCtx.lineJoin = 'round';
    exportCtx.lineWidth = size;

    if (maskEditorState.tool === 'eraser') {
        displayCtx.save();
        displayCtx.globalCompositeOperation = 'destination-out';
        displayCtx.beginPath();
        displayCtx.moveTo(fromPoint.x, fromPoint.y);
        displayCtx.lineTo(toPoint.x, toPoint.y);
        displayCtx.stroke();
        displayCtx.restore();

        exportCtx.strokeStyle = '#000000';
    } else {
        displayCtx.strokeStyle = 'rgba(255, 88, 88, 0.58)';
        displayCtx.beginPath();
        displayCtx.moveTo(fromPoint.x, fromPoint.y);
        displayCtx.lineTo(toPoint.x, toPoint.y);
        displayCtx.stroke();

        exportCtx.strokeStyle = '#ffffff';
    }

    exportCtx.beginPath();
    exportCtx.moveTo(fromPoint.x, fromPoint.y);
    exportCtx.lineTo(toPoint.x, toPoint.y);
    exportCtx.stroke();
}

function getCanvasPoint(event) {
    const canvas = maskEditorState.drawCanvas;
    if (!canvas) return null;

    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;

    return {
        x: (event.clientX - rect.left) * scaleX,
        y: (event.clientY - rect.top) * scaleY,
    };
}

function handleMaskPointerDown(event) {
    const point = getCanvasPoint(event);
    if (!point) return;

    maskEditorState.isDrawing = true;
    maskEditorState.lastPoint = point;
    applyMaskStroke(point, point);
}

function handleMaskPointerMove(event) {
    if (!maskEditorState.isDrawing) return;

    const point = getCanvasPoint(event);
    if (!point || !maskEditorState.lastPoint) return;

    applyMaskStroke(maskEditorState.lastPoint, point);
    maskEditorState.lastPoint = point;
}

function stopMaskDrawing() {
    maskEditorState.isDrawing = false;
    maskEditorState.lastPoint = null;
}

function setMaskTool(tool) {
    maskEditorState.tool = tool;
    const brushBtn = document.getElementById('mask-tool-brush');
    const eraserBtn = document.getElementById('mask-tool-eraser');
    if (brushBtn) brushBtn.classList.toggle('active', tool === 'brush');
    if (eraserBtn) eraserBtn.classList.toggle('active', tool === 'eraser');
}

function clearMaskEditorCanvas() {
    const contexts = getMaskCanvasContexts();
    if (!contexts) return;

    contexts.displayCtx.clearRect(0, 0, contexts.drawCanvas.width, contexts.drawCanvas.height);
    resetMaskCanvasExport(contexts.drawCanvas.width, contexts.drawCanvas.height);
}

async function preloadExistingMaskIntoEditor() {
    const existingMaskFile = currentExtraFiles.mask_url;
    if (!existingMaskFile) return;

    try {
        const maskImage = await loadImageFromFile(existingMaskFile);
        const contexts = getMaskCanvasContexts();
        if (!contexts) return;

        maskEditorState.exportCtx.drawImage(maskImage, 0, 0, contexts.exportCanvas.width, contexts.exportCanvas.height);
        contexts.displayCtx.save();
        contexts.displayCtx.globalAlpha = 0.55;
        contexts.displayCtx.drawImage(maskImage, 0, 0, contexts.drawCanvas.width, contexts.drawCanvas.height);
        contexts.displayCtx.restore();
    } catch (error) {
        console.error('加载已有蒙版失败:', error);
    }
}

async function openMaskEditor() {
    const modelId = document.getElementById('ai-model-select').value;
    if (!modelSupportsMaskEditor(modelId)) {
        Swal.fire('提示', '当前模型不支持蒙版编辑。', 'info');
        return;
    }
    if (!currentFiles.length) {
        Swal.fire('提示', '请先上传至少一张参考图，再绘制蒙版。', 'warning');
        return;
    }

    const targetFile = currentFiles[0];
    const modalEl = document.getElementById('maskEditorModal');
    const canvasWrap = document.getElementById('mask-editor-canvas-wrap');
    const baseCanvas = document.getElementById('mask-base-canvas');
    const drawCanvas = document.getElementById('mask-draw-canvas');
    if (!modalEl || !canvasWrap || !baseCanvas || !drawCanvas) return;

    try {
        const image = await loadImageFromFile(targetFile);
        const maxDisplayWidth = Math.min(900, window.innerWidth - 120);
        const maxDisplayHeight = Math.min(680, window.innerHeight - 260);
        const scale = Math.min(maxDisplayWidth / image.naturalWidth, maxDisplayHeight / image.naturalHeight, 1);
        const displayWidth = Math.max(220, Math.round(image.naturalWidth * scale));
        const displayHeight = Math.max(220, Math.round(image.naturalHeight * scale));

        baseCanvas.width = image.naturalWidth;
        baseCanvas.height = image.naturalHeight;
        drawCanvas.width = image.naturalWidth;
        drawCanvas.height = image.naturalHeight;

        baseCanvas.style.width = `${displayWidth}px`;
        baseCanvas.style.height = `${displayHeight}px`;
        drawCanvas.style.width = `${displayWidth}px`;
        drawCanvas.style.height = `${displayHeight}px`;
        canvasWrap.style.width = `${displayWidth}px`;
        canvasWrap.style.height = `${displayHeight}px`;

        maskEditorState.baseCanvas = baseCanvas;
        maskEditorState.drawCanvas = drawCanvas;
        maskEditorState.displayCtx = drawCanvas.getContext('2d');
        maskEditorState.baseImage = image;
        maskEditorState.imageFile = targetFile;
        maskEditorState.imageName = targetFile.name;
        maskEditorExportCanvas = document.createElement('canvas');

        resetMaskCanvasExport(image.naturalWidth, image.naturalHeight);

        const baseCtx = baseCanvas.getContext('2d');
        baseCtx.clearRect(0, 0, baseCanvas.width, baseCanvas.height);
        baseCtx.drawImage(image, 0, 0, baseCanvas.width, baseCanvas.height);
        maskEditorState.displayCtx.clearRect(0, 0, drawCanvas.width, drawCanvas.height);

        setMaskTool(maskEditorState.tool);
        await preloadExistingMaskIntoEditor();

        const modalInstance = bootstrap.Modal.getOrCreateInstance(modalEl);
        modalInstance.show();
    } catch (error) {
        console.error('打开蒙版编辑器失败:', error);
        Swal.fire('错误', '参考图加载失败，暂时无法打开蒙版编辑器。', 'error');
    }
}

function saveMaskFromEditor() {
    if (!maskEditorExportCanvas) return;

    maskEditorExportCanvas.toBlob((blob) => {
        if (!blob) {
            Swal.fire('错误', '蒙版导出失败，请重试。', 'error');
            return;
        }

        currentExtraFiles.mask_url = new File([blob], `mask_${Date.now()}.png`, { type: 'image/png' });
        renderDynamicFileParams(document.getElementById('ai-model-select').value);
        renderPreviews();

        const modalEl = document.getElementById('maskEditorModal');
        const modalInstance = bootstrap.Modal.getInstance(modalEl);
        if (modalInstance) modalInstance.hide();

        Swal.fire({
            toast: true,
            position: 'top',
            icon: 'success',
            title: '蒙版已保存到当前模型参数',
            showConfirmButton: false,
            timer: 2200,
        });
    }, 'image/png');
}

document.addEventListener('DOMContentLoaded', () => {
    initDynamicUI();
    setupDragAndDrop();
    initPublishPromptEditor();

    const createConversationSendBtn = document.getElementById('create-gpt-conversation-send');
    if (createConversationSendBtn) {
        createConversationSendBtn.addEventListener('click', sendCreateConversationMessage);
    }
    const createConversationResetBtn = document.getElementById('create-gpt-conversation-reset');
    if (createConversationResetBtn) {
        createConversationResetBtn.addEventListener('click', () => resetCreateConversationState({ preserveSelection: true }));
    }

    maskEditorState.baseCanvas = document.getElementById('mask-base-canvas');
    maskEditorState.drawCanvas = document.getElementById('mask-draw-canvas');
    if (maskEditorState.drawCanvas) {
        maskEditorState.drawCanvas.addEventListener('pointerdown', handleMaskPointerDown);
        maskEditorState.drawCanvas.addEventListener('pointermove', handleMaskPointerMove);
        maskEditorState.drawCanvas.addEventListener('pointerup', stopMaskDrawing);
        maskEditorState.drawCanvas.addEventListener('pointerleave', stopMaskDrawing);
    }

    const brushSizeInput = document.getElementById('mask-brush-size');
    if (brushSizeInput) {
        brushSizeInput.addEventListener('input', function() {
            maskEditorState.brushSize = parseInt(this.value, 10) || 28;
        });
    }

    const brushBtn = document.getElementById('mask-tool-brush');
    if (brushBtn) brushBtn.addEventListener('click', () => setMaskTool('brush'));
    const eraserBtn = document.getElementById('mask-tool-eraser');
    if (eraserBtn) eraserBtn.addEventListener('click', () => setMaskTool('eraser'));
    const clearMaskBtn = document.getElementById('mask-clear-btn');
    if (clearMaskBtn) clearMaskBtn.addEventListener('click', clearMaskEditorCanvas);
    const saveMaskBtn = document.getElementById('mask-save-btn');
    if (saveMaskBtn) saveMaskBtn.addEventListener('click', saveMaskFromEditor);

    const maskModal = document.getElementById('maskEditorModal');
    if (maskModal) maskModal.addEventListener('hidden.bs.modal', stopMaskDrawing);

    const urlParams = new URLSearchParams(window.location.search);
    currentSourceGroupId = urlParams.get('template_id') || urlParams.get('group_id') || null;

    // 解析全库标签
    try {
        const tagsEl = document.getElementById('all-tags-data');
        if (tagsEl) allAvailableTags = JSON.parse(tagsEl.textContent);
        
        const charsEl = document.getElementById('all-chars-data');
        if (charsEl) allAvailableChars = JSON.parse(charsEl.textContent);
    } catch(e) { console.log("解析系统标签失败", e); }

    // 绑定人物自定义输入框的回车事件
    const customCharInput = document.getElementById('pub-custom-char');
    if (customCharInput) {
        customCharInput.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                const newChars = this.value.split(/[,，]/); 
                let added = false;
                newChars.forEach(char => {
                    const c = char.trim();
                    if (c && !currentSelectedChars.has(c)) {
                        currentSelectedChars.add(c);
                        if (!allAvailableChars.includes(c)) allAvailableChars.push(c);
                        added = true;
                    }
                });
                if (added) {
                    this.value = '';
                    renderPublishChars(Array.from(currentSelectedChars));
                }
            }
        });
    }
    
    // 绑定自定义标签框的回车事件
    const customTagInput = document.getElementById('pub-custom-tag');
    if (customTagInput) {
        customTagInput.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                const newTags = this.value.split(/[,，]/); 
                let added = false;
                
                newTags.forEach(tag => {
                    const t = tag.trim();
                    if (t && !currentSelectedTags.has(t)) {
                        currentSelectedTags.add(t);
                        if (!allAvailableTags.includes(t)) {
                            allAvailableTags.push(t);
                        }
                        added = true;
                    }
                });
                
                if (added) {
                    this.value = ''; 
                    renderPublishTags(Array.from(currentSelectedTags)); 
                }
            }
        });
    }

    // 接收并处理从详情页带入的预填充数据
    try {
        const initialDataEl = document.getElementById('initial-data');
        const initialDataText = initialDataEl ? initialDataEl.textContent.trim() : "";
        if (initialDataText && initialDataText !== "{}" && initialDataText !== "null") {
            const initialData = JSON.parse(initialDataText);
            if (!currentSourceGroupId && initialData.group_id) currentSourceGroupId = String(initialData.group_id);
            if (!currentSourceGroupId && initialData.id) currentSourceGroupId = String(initialData.id);

            if (initialData.prompt) {
                document.getElementById('ai-prompt').value = initialData.prompt;
            }
            if (initialData.prompts && initialData.prompts.length > 0) {
                currentPublishPromptItems = normalizePublishPromptItems(initialData.prompts);
            } else if (initialData.prompt) {
                currentPublishPromptItems = normalizePublishPromptItems([{ text: initialData.prompt }]);
            }
            
            if (initialData.tags && initialData.tags.length > 0) {
                initialTagsForPublish = initialData.tags; 
            }
            if (initialData.characters && initialData.characters.length > 0) {
                initialCharsForPublish = initialData.characters; 
            }
            let modelToastMsg = null;
            
            if (initialData.model_info && typeof initialData.model_info === 'string') {
                const rawModelName = String(initialData.model_info).trim();
                const dbModelName = normalizeModelName(initialData.model_info);
                let targetModelId = null;
                let targetCategoryId = null;

                for (const [key, model] of Object.entries(AI_CONFIG.models)) {
                    const exactTitle = String(model.title || '').trim().toLowerCase();
                    if (exactTitle && exactTitle === rawModelName.toLowerCase()) {
                        targetModelId = key;
                        targetCategoryId = model.category;
                        break;
                    }
                }

                if (!targetModelId) {
                    for (const [key, model] of Object.entries(AI_CONFIG.models)) {
                        const exactRegistryName = String(model.registry_name || '').trim().toLowerCase();
                        if (exactRegistryName && exactRegistryName === rawModelName.toLowerCase()) {
                            targetModelId = key;
                            targetCategoryId = model.category;
                            break;
                        }
                    }
                }

                if (!targetModelId) {
                    for (const [key, model] of Object.entries(AI_CONFIG.models)) {
                    const titleName = normalizeModelName(model.title);
                    const registryName = normalizeModelName(model.registry_name);
                    if (titleName === dbModelName || registryName === dbModelName) {
                        targetModelId = key;
                        targetCategoryId = model.category;
                        break;
                    }
                }
                }

                if (targetModelId) {
                    switchCategory(targetCategoryId);
                    const targetCard = document.getElementById(`card-${targetModelId}`);
                    if (targetCard) targetCard.click();
                    
                    modelToastMsg = {
                        icon: 'success',
                        title: `已为您自动匹配模型：${initialData.model_info}`
                    };
                } else {
                    modelToastMsg = {
                        icon: 'info',
                        title: `模型【${initialData.model_info}】暂不支持云端调用，已选择默认模型。`
                    };
                }
            }

            const fireModelToast = () => {
                if (modelToastMsg) {
                    setTimeout(() => {
                        Swal.fire({
                            toast: true, position: 'top', showConfirmButton: false, timer: 4500,
                            icon: modelToastMsg.icon, title: modelToastMsg.title
                        });
                    }, 600); 
                }
            };

            if (initialData.reference_urls && initialData.reference_urls.length > 0) {
                Swal.fire({
                    title: '正在导入参考图...',
                    allowOutsideClick: false,
                    didOpen: () => Swal.showLoading()
                });

                Promise.all(initialData.reference_urls.map(url => 
                    fetch(url)
                        .then(res => res.blob())
                        .then(blob => {
                            const filename = url.split('/').pop().split('?')[0] || 'reference_image.jpg';
                            return new File([blob], filename, { type: blob.type || 'image/jpeg' });
                        })
                )).then(files => {
                    clearMaskFileForReferenceChange();
                    if (maxImagesAllowed === 1) {
                        currentFiles = [files[0]]; 
                    } else if (maxImagesAllowed > 1) {
                        currentFiles = [...currentFiles, ...files].slice(0, maxImagesAllowed); 
                    }
                    renderPreviews();
                    Swal.close();
                    fireModelToast();
                }).catch(err => {
                    console.error("加载参考图失败:", err);
                    Swal.fire('导入提示', '部分参考图导入失败，请手动上传', 'warning');
                });
            } else {
                fireModelToast();
            }
        }
    } catch(e) {
        console.error("❌ 无预填充数据或解析失败，错误详情:", e);
    }

    const dynamicContainer = document.getElementById('dynamic-params-container');
    
    function handleDynamicInput(e) {
        if (e.target.classList.contains('dynamic-param-input')) {
            const modelChoice = document.getElementById('ai-model-select').value;
            if (modelChoice.toLowerCase().includes('seedream')) {
                const paramId = e.target.getAttribute('data-param-id');
                
                if (paramId === 'max_images' || paramId === 'num_images') {
                    updateSeedreamPrompt(e.target.value);
                } else if (paramId === 'prompt_aspect_ratio') {
                    updateSeedreamAspectRatio(e.target.value);
                }
            }
        }
    }

    dynamicContainer.addEventListener('input', handleDynamicInput);
    dynamicContainer.addEventListener('change', handleDynamicInput);
    loadRecentCreateConversations();
    updateCreateConversationPanelVisibility();
});

function normalizePublishPromptItems(items) {
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

function ensurePublishPromptSlots(items, minimum = 3) {
    const normalized = [...items];
    while (normalized.length < minimum) {
        normalized.push({
            id: `prompt_${normalized.length + 1}`,
            label: `提示词${normalized.length + 1}`,
            text: '',
        });
    }
    return normalized.map((item, index) => ({
        id: `prompt_${index + 1}`,
        label: `提示词${index + 1}`,
        text: item.text || '',
    }));
}

function escapePublishPromptHtml(text) {
    const div = document.createElement('div');
    div.textContent = text || '';
    return div.innerHTML;
}

function initPublishPromptEditor() {
    const addBtn = document.getElementById('btn-pub-add-prompt');
    if (!addBtn) return;

    addBtn.addEventListener('click', () => {
        syncPublishPromptItemsFromDom();
        currentPublishPromptItems.push({
            id: `prompt_${currentPublishPromptItems.length + 1}`,
            label: `提示词${currentPublishPromptItems.length + 1}`,
            text: '',
        });
        renderPublishPromptItems();

        const inputs = document.querySelectorAll('#pub-prompts-container .pub-prompt-input');
        const lastInput = inputs[inputs.length - 1];
        if (lastInput) lastInput.focus();
    });
}

function syncPublishPromptItemsFromDom() {
    const inputs = document.querySelectorAll('#pub-prompts-container .pub-prompt-input');
    if (!inputs.length) return;

    currentPublishPromptItems = Array.from(inputs).map((input, index) => ({
        id: `prompt_${index + 1}`,
        label: `提示词${index + 1}`,
        text: input.value || '',
    }));
}

function preparePublishPromptItems() {
    const activePrompt = document.getElementById('ai-prompt').value.trim();
    const existing = normalizePublishPromptItems(currentPublishPromptItems);
    const remainder = existing.filter(item => item.text.trim() && item.text.trim() !== activePrompt);
    const items = [];

    if (activePrompt) {
        items.push({ text: activePrompt });
    }

    remainder.forEach(item => items.push({ text: item.text }));
    currentPublishPromptItems = ensurePublishPromptSlots(items);
}

function renderPublishPromptItems() {
    const container = document.getElementById('pub-prompts-container');
    if (!container) return;

    currentPublishPromptItems = ensurePublishPromptSlots(currentPublishPromptItems);
    container.innerHTML = currentPublishPromptItems.map((item, index) => `
        <div class="border rounded-4 bg-light p-3">
            <div class="d-flex justify-content-between align-items-center mb-2 flex-wrap gap-2">
                <span class="badge bg-white text-primary border rounded-pill px-3 py-2">提示词${index + 1}</span>
                <button type="button" class="btn btn-sm btn-outline-danger rounded-pill px-3" onclick="removePublishPromptItem(${index})">
                    <i class="bi bi-trash3 me-1"></i>删除
                </button>
            </div>
            <textarea class="form-control pub-prompt-input" rows="3" data-index="${index}" placeholder="请输入提示词${index + 1}...">${escapePublishPromptHtml(item.text)}</textarea>
        </div>
    `).join('');
}

function removePublishPromptItem(index) {
    syncPublishPromptItemsFromDom();
    currentPublishPromptItems.splice(index, 1);
    renderPublishPromptItems();
}

// ...将原先写在 HTML 中的剩余所有 JavaScript 方法全部复制到这里（从 updateSeedreamPrompt 到 extractExistingRefToCanvas 等方法）
// 为了节省篇幅和防止你复制出错，剩余所有自定义 functions 直接无缝追加在此处即可（和原版逻辑完全一致）

function updateSeedreamPrompt(count) {
    const promptInput = document.getElementById('ai-prompt');
    let text = promptInput.value;
    const prefixRegex = /^生成\d+张图片：/;
    if (prefixRegex.test(text)) {
        promptInput.value = text.replace(prefixRegex, `生成${count}张图片：`);
    } else {
        promptInput.value = `生成${count}张图片：` + text;
    }
}

function removeSeedreamPrompt() {
    const promptInput = document.getElementById('ai-prompt');
    const prefixRegex = /^生成\d+张图片：/;
    if (prefixRegex.test(promptInput.value)) {
        promptInput.value = promptInput.value.replace(prefixRegex, '');
    }
}

function updateSeedreamAspectRatio(ratio) {
    const promptInput = document.getElementById('ai-prompt');
    let text = promptInput.value;
    const ratioRegex = /(?:，|\s)*画面比例：\d+:\d+/g;
    text = text.replace(ratioRegex, '').trim();
    if (ratio !== 'none') {
        if (text.length > 0) {
            text += `，画面比例：${ratio}`;
        } else {
            text = `画面比例：${ratio}`;
        }
    }
    promptInput.value = text;
}

function removeSeedreamAspectRatio() {
    const promptInput = document.getElementById('ai-prompt');
    const ratioRegex = /(?:，|\s)*画面比例：\d+:\d+/g;
    promptInput.value = promptInput.value.replace(ratioRegex, '').trim();
}

function initDynamicUI() {
    const tabsContainer = document.getElementById('dynamic-category-tabs');
    const cardsContainer = document.getElementById('dynamic-model-cards');
    
    if (!AI_CONFIG.categories) return;

    AI_CONFIG.categories.forEach((cat, index) => {
        const isActive = index === 0 ? 'active' : '';
        tabsContainer.innerHTML += `
            <li class="nav-item" role="presentation">
                <button class="nav-link ${isActive}" data-bs-toggle="tab" data-bs-target="#tab-${cat.id}" 
                        type="button" onclick="switchCategory('${cat.id}')">${cat.title}</button>
            </li>
        `;
        const showClass = index === 0 ? 'show active' : '';
        let cardsHtml = `<div class="tab-pane fade ${showClass}" id="tab-${cat.id}" role="tabpanel"><div class="row g-2">`;
        for (const [modelId, model] of Object.entries(AI_CONFIG.models)) {
            if (modelVisibleInCategory(model, cat.id)) {
                cardsHtml += `
                    <div class="col-6">
                        <div class="model-card" id="card-${modelId}" onclick="selectModel('${modelId}', '${cat.id}', this)">
                            <div class="model-card-title">${model.title} <i class="bi bi-check-circle-fill check-icon" style="display:none;"></i></div>
                            <p class="model-card-desc">${model.desc}</p>
                        </div>
                    </div>
                `;
            }
        }
        cardsHtml += `</div></div>`;
        cardsContainer.innerHTML += cardsHtml;
    });
    switchCategory(AI_CONFIG.categories[0].id);
}

function switchCategory(categoryId) {
    document.getElementById('ai-category-select').value = categoryId;
    currentFiles = [];
    currentExtraFiles = {};
    renderPreviews();
    renderDynamicFileParams();

    const activeTabPane = document.getElementById(`tab-${categoryId}`);
    const firstCard = activeTabPane.querySelector('.model-card');
    if (firstCard) firstCard.click();
}

function selectModel(modelId, categoryId, element) {
    document.querySelectorAll('.model-card').forEach(card => card.classList.remove('active'));
    element.classList.add('active');
    document.getElementById('ai-model-select').value = modelId;
    currentExtraFiles = {};
    renderDynamicParams(modelId);
    applyModelUploadConfig(modelId, categoryId);
}

function renderDynamicParams(modelId) {
    const container = document.getElementById('dynamic-params-container');
    container.innerHTML = ''; 
    
    const params = AI_CONFIG.models[modelId].params;
    if (!params || params.length === 0) return; 

    let html = `<div class="p-3 bg-light rounded-3 border"><label class="form-label fw-bold text-secondary small mb-3"><i class="bi bi-gear-fill me-1"></i>模型专属参数</label><div class="row g-3">`;

    params.forEach(param => {
        html += `<div class="col-12">`;
        if (param.type === 'select') {
            html += `<label class="form-label small text-muted mb-1">${param.label}</label>
                     <select class="form-select form-select-sm dynamic-param-input shadow-sm" data-param-id="${param.id}">`;
            param.options.forEach(opt => {
                html += `<option value="${opt.value}" ${opt.value === param.default ? 'selected' : ''}>${opt.text}</option>`;
            });
            html += `</select>`;
        } else if (param.type === 'range') {
            const percent = ((param.default - param.min) / (param.max - param.min)) * 100;
            html += `
                <div class="d-flex justify-content-between align-items-center mb-1">
                    <label class="form-label small text-muted mb-0">${param.label}</label>
                    <span class="badge bg-white text-primary border border-primary" id="val-${param.id}">${param.default}</span>
                </div>
                
                <input type="range" class="custom-range-slider dynamic-param-input" 
                       data-param-id="${param.id}" data-param-type="range"
                       min="${param.min}" max="${param.max}" step="${param.step}" value="${param.default}"
                       style="background-size: ${percent}% 100%;"
                       oninput="
                           document.getElementById('val-${param.id}').innerText = this.value;
                           this.style.backgroundSize = ((this.value - this.min) / (this.max - this.min)) * 100 + '% 100%';
                       ">
            `;
        }else if (param.type === 'checkbox') {
            const isChecked = param.default ? 'checked' : '';
            html += `
                <div class="form-check form-switch mt-2">
                    <input class="form-check-input dynamic-param-input" type="checkbox" role="switch" 
                           id="param-${param.id}" data-param-id="${param.id}" data-param-type="checkbox" ${isChecked}>
                    <label class="form-check-label small text-muted fw-bold" for="param-${param.id}">${param.label}</label>
                </div>`;
        }
        html += `</div>`;
    });
    html += `</div></div>`;
    container.innerHTML = html;

    if (modelId.toLowerCase().includes('seedream')) {
        const numInput = container.querySelector('.dynamic-param-input[data-param-id="max_images"], .dynamic-param-input[data-param-id="num_images"]');
        if (numInput) {
            updateSeedreamPrompt(numInput.value);
        }
        const ratioInput = container.querySelector('.dynamic-param-input[data-param-id="prompt_aspect_ratio"]');
        if (ratioInput) {
            updateSeedreamAspectRatio(ratioInput.value);
        }
    } else {
        removeSeedreamPrompt();
        removeSeedreamAspectRatio(); 
    }
}

function setupDragAndDrop() {
    const dropZone = document.getElementById('drop-zone');
    if(!dropZone) return;
    dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.classList.add('dragover'); });
    dropZone.addEventListener('dragleave', (e) => { e.preventDefault(); dropZone.classList.remove('dragover'); });
    dropZone.addEventListener('drop', (e) => { e.preventDefault(); dropZone.classList.remove('dragover'); handleFiles(e.dataTransfer.files); });
}

function renderPublishTags(preSelectedTags) {
    const container = document.getElementById('pub-tags-container');
    container.innerHTML = '';
    preSelectedTags.forEach(t => currentSelectedTags.add(t));
    const combinedTags = Array.from(new Set([...allAvailableTags, ...preSelectedTags]));
    
    if (combinedTags.length === 0) {
        container.innerHTML = '<span class="text-muted small">暂无系统标签，请在下方手动添加</span>';
        return;
    }

    combinedTags.forEach(tag => {
        const badge = document.createElement('span');
        badge.className = 'pub-tag-badge';
        if (currentSelectedTags.has(tag)) {
            badge.classList.add('active');
            badge.innerHTML = `<i class="bi bi-check2 me-1"></i>${tag}`; 
        } else {
            badge.textContent = tag;
        }
        badge.onclick = function() {
            if (currentSelectedTags.has(tag)) {
                currentSelectedTags.delete(tag);
                this.classList.remove('active');
                this.textContent = tag; 
            } else {
                currentSelectedTags.add(tag);
                this.classList.add('active');
                this.innerHTML = `<i class="bi bi-check2 me-1"></i>${tag}`;
            }
        };
        container.appendChild(badge);
    });
}

function renderPublishChars(preSelectedChars) {
    const container = document.getElementById('pub-chars-container');
    container.innerHTML = '';
    preSelectedChars.forEach(c => currentSelectedChars.add(c));
    const combinedChars = Array.from(new Set([...allAvailableChars, ...preSelectedChars]));
    
    if (combinedChars.length === 0) {
        container.innerHTML = '<span class="text-muted small">暂无记录人物，请在下方手动添加</span>';
        return;
    }

    combinedChars.forEach(char => {
        const badge = document.createElement('span');
        badge.className = 'pub-tag-badge'; 
        if (currentSelectedChars.has(char)) {
            badge.className = 'pub-tag-badge active pub-tag-char-active'; 
            badge.innerHTML = `<i class="bi bi-person-check-fill me-1"></i>${char}`;
        } else {
            badge.className = 'pub-tag-badge'; 
            badge.innerHTML = `<i class="bi bi-person me-1"></i>${char}`;
        }
        badge.onclick = function() {
            if (currentSelectedChars.has(char)) {
                currentSelectedChars.delete(char);
                this.className = 'pub-tag-badge';
                this.innerHTML = `<i class="bi bi-person me-1"></i>${char}`;
            } else {
                currentSelectedChars.add(char);
                this.className = 'pub-tag-badge active pub-tag-char-active';
                this.innerHTML = `<i class="bi bi-person-check-fill me-1"></i>${char}`;
            }
        };
        container.appendChild(badge);
    });
}

function handleFiles(files) {
    if (!files || files.length === 0 || maxImagesAllowed === 0) return;
    clearMaskFileForReferenceChange();
    if (maxImagesAllowed === 1) {
        currentFiles = [files[0]]; 
    } else {
        currentFiles = [...currentFiles, ...Array.from(files)].slice(0, maxImagesAllowed); 
    }
    renderPreviews();
}

function renderPreviews() {
    const container = document.getElementById('preview-container');
    container.innerHTML = ''; 
    currentFiles.forEach((file, index) => {
        const supportsMaskEditor = modelSupportsMaskEditor(document.getElementById('ai-model-select').value);
        const canOpenMaskEditor = index === 0 && supportsMaskEditor;
        const wrapper = document.createElement('div');
        wrapper.className = 'preview-wrapper m-1';
        const img = document.createElement('img');
        img.className = `preview-item shadow-sm ${canOpenMaskEditor ? 'preview-item-clickable' : ''}`;
        if (canOpenMaskEditor) {
            img.title = currentExtraFiles.mask_url ? '点击打开参考图并查看/继续编辑蒙版' : '点击打开参考图并开始绘制蒙版';
            img.onclick = (e) => {
                e.preventDefault();
                e.stopPropagation();
                openMaskEditor();
            };
        }
        const reader = new FileReader();
        reader.onload = (e) => { img.src = e.target.result; }
        reader.readAsDataURL(file);
        
        const removeBtn = document.createElement('button');
        removeBtn.className = 'btn-remove-preview';
        removeBtn.innerHTML = '<i class="bi bi-x"></i>';
        removeBtn.onclick = (e) => {
            e.preventDefault();
            e.stopPropagation(); 
            removeFile(index);
        };

        if (canOpenMaskEditor) {
            if (currentExtraFiles.mask_url) {
                const badge = document.createElement('div');
                badge.className = 'preview-badge';
                badge.textContent = '已挂载蒙版';
                wrapper.appendChild(badge);
            }

            const hint = document.createElement('div');
            hint.className = 'preview-click-hint';
            hint.innerHTML = '<i class="bi bi-arrows-angle-expand me-1"></i>点击参考图查看蒙版';
            wrapper.appendChild(hint);

            const actions = document.createElement('div');
            actions.className = 'preview-actions';

            const maskBtn = document.createElement('button');
            maskBtn.type = 'button';
            maskBtn.className = 'btn-preview-action';
            maskBtn.innerHTML = currentExtraFiles.mask_url ? '<i class="bi bi-brush me-1"></i>重绘蒙版' : '<i class="bi bi-brush me-1"></i>编辑蒙版';
            maskBtn.onclick = (e) => {
                e.preventDefault();
                e.stopPropagation();
                openMaskEditor();
            };

            actions.appendChild(maskBtn);
            wrapper.appendChild(actions);
        }

        wrapper.appendChild(img);
        wrapper.appendChild(removeBtn);
        container.appendChild(wrapper);
    });

    const activeModelId = document.getElementById('ai-model-select')?.value;
    if (activeModelId) {
        renderDynamicFileParams(activeModelId);
    }
}

function removeFile(index) {
    clearMaskFileForReferenceChange();
    currentFiles.splice(index, 1);
    renderPreviews();
}

function toggleGenResultSelect(element) {
    element.classList.toggle('selected');
    if (element.classList.contains('selected')) {
        createConversationState.selectedPath = element.getAttribute('data-path');
        syncCreateConversationActiveResult(createConversationState.selectedPath);
    } else if (createConversationState.selectedPath === element.getAttribute('data-path')) {
        createConversationState.selectedPath = getCreateConversationSelectedPath();
    }
    updateCreateConversationPanelVisibility();
}

function getSelectedSavedPaths() {
    const selectedCards = document.querySelectorAll('.gen-result-card.selected');
    const paths = [];
    selectedCards.forEach(card => {
        paths.push(card.getAttribute('data-path'));
    });
    return paths;
}

function getCreateConversationPanel() {
    return document.getElementById('create-gpt-conversation-panel');
}

function getCreateConversationRecentPanel() {
    return document.getElementById('create-gpt-conversation-recent');
}

function getCreateConversationRecentList() {
    return document.getElementById('create-gpt-conversation-recent-list');
}

function getCreateConversationParamOverrides() {
    return {
        quality: document.getElementById('create-gpt-conversation-quality')?.value || 'medium',
        image_size_mode: document.getElementById('create-gpt-conversation-size-mode')?.value || 'custom',
        resolution: document.getElementById('create-gpt-conversation-resolution')?.value || '2K',
        aspect_ratio: document.getElementById('create-gpt-conversation-aspect-ratio')?.value || '9:16',
        prompt_optimization_level: document.getElementById('create-gpt-conversation-optimization-level')?.value || 'balanced',
    };
}

function normalizeCreateConversationOptimizationLevel(value) {
    if (value === 'conservative' || value === 'faithful') return 'balanced';
    if (value === 'visual_rewrite') return 'enhanced';
    return value || 'balanced';
}

function applyCreateConversationParamOverrides(params = {}) {
    const qualityEl = document.getElementById('create-gpt-conversation-quality');
    const sizeModeEl = document.getElementById('create-gpt-conversation-size-mode');
    const resolutionEl = document.getElementById('create-gpt-conversation-resolution');
    const aspectRatioEl = document.getElementById('create-gpt-conversation-aspect-ratio');
    const optimizationLevelEl = document.getElementById('create-gpt-conversation-optimization-level');

    if (qualityEl && params.quality) qualityEl.value = params.quality;
    if (sizeModeEl && params.image_size_mode) sizeModeEl.value = params.image_size_mode;
    if (resolutionEl && params.resolution) resolutionEl.value = params.resolution;
    if (aspectRatioEl && params.aspect_ratio) aspectRatioEl.value = params.aspect_ratio;
    if (optimizationLevelEl && params.prompt_optimization_level) optimizationLevelEl.value = normalizeCreateConversationOptimizationLevel(params.prompt_optimization_level);
}

function collectCreateConversationParams() {
    return {
        ...collectCurrentDynamicParams(),
        ...getCreateConversationParamOverrides(),
    };
}

function setCreateConversationStatus(message) {
    const statusEl = document.getElementById('create-gpt-conversation-status');
    if (statusEl) {
        statusEl.innerText = message;
    }
}

function getCreateConversationSelectedPath() {
    const selectedCards = Array.from(document.querySelectorAll('.gen-result-card.selected'));
    if (
        createConversationState.selectedPath
        && selectedCards.some(card => card.getAttribute('data-path') === createConversationState.selectedPath)
    ) {
        return createConversationState.selectedPath;
    }

    const selectedCard = selectedCards[selectedCards.length - 1] || document.querySelector('.gen-result-card');
    return selectedCard ? selectedCard.getAttribute('data-path') : '';
}

function renderCreateConversationHistory() {
    const historyEl = document.getElementById('create-gpt-conversation-history');
    if (!historyEl) return;

    const conversation = createConversationState.conversation;
    const turns = conversation?.turns || [];
    const activePath = conversation?.active_image_path || '';
    if (!turns.length) {
        historyEl.innerHTML = '<div class="text-muted small">还没有对话记录。</div>';
        return;
    }

    historyEl.innerHTML = turns.map(turn => `
        <div class="border rounded-4 bg-white p-3 mb-2 ${turn.output_image_path === activePath ? 'border-primary' : ''}">
            <div class="d-flex justify-content-between align-items-center mb-2">
                <span class="badge bg-primary-subtle text-primary border">第 ${turn.turn_index} 轮</span>
                <span class="text-muted small">${new Date(turn.created_at).toLocaleString()}</span>
            </div>
            <div class="fw-semibold mb-2">${escapeHtml(turn.instruction)}</div>
            <div class="small text-muted mb-2">当前输出：${escapeHtml(turn.output_image_path || '未记录')}</div>
            <div class="d-flex flex-wrap gap-2">
                <button type="button" class="btn btn-sm ${turn.output_image_path === activePath ? 'btn-primary' : 'btn-outline-primary'} rounded-pill" data-turn-id="${turn.id}" data-output-path="${escapeHtml(turn.output_image_path || '')}" onclick="activateCreateConversationTurn(this)">
                    <i class="bi bi-arrow-repeat me-1"></i>${turn.output_image_path === activePath ? '当前基底' : '切换为当前基底'}
                </button>
                ${turn.output_image_path ? `<button type="button" class="btn btn-sm btn-outline-success rounded-pill" data-output-path="${escapeHtml(turn.output_image_path)}" onclick="publishCreateConversationTurn(this)"><i class="bi bi-box-arrow-up me-1"></i>保存为新作品</button>` : ''}
                ${turn.output_image_path ? `<button type="button" class="btn btn-sm btn-outline-secondary rounded-pill" data-output-path="${escapeHtml(turn.output_image_path)}" onclick="appendCreateConversationTurn(this)"><i class="bi bi-collection me-1"></i>追加到现有作品</button>` : ''}
            </div>
        </div>
    `).join('');
}

function updateCreateConversationPanelVisibility() {
    const panel = getCreateConversationPanel();
    if (!panel) return;

    const modelId = document.getElementById('ai-model-select')?.value;
    const hasResults = document.querySelectorAll('.gen-result-card').length > 0;
    const eligible = isCreateConversationEligibleModel(modelId) && hasResults;

    panel.style.display = eligible ? 'block' : 'none';
    if (!isCreateConversationEligibleModel(modelId)) {
        hideCreatePromptMediationCard({ panelId: 'create-gpt-prompt-mediation-panel' });
        hideCreatePromptMediationCard({ panelId: 'create-gpt-conversation-mediation-panel' });
    }
    const recentPanel = getCreateConversationRecentPanel();
    if (recentPanel && !eligible) {
        recentPanel.style.display = 'none';
    }
    if (!eligible) return;

    const selectedPath = getCreateConversationSelectedPath();
    if (!createConversationState.conversationId) {
        setCreateConversationStatus(selectedPath ? `当前基底图：${selectedPath}` : '请先选中一张结果图作为当前基底。');
        return;
    }

    setCreateConversationStatus(selectedPath ? `当前会话基底：${selectedPath}` : '当前会话缺少基底图，请重新选择。');
}

function clearCreateConversationGallery() {
    const gallery = document.getElementById('result-gallery');
    if (!gallery) return;
    gallery.innerHTML = '';
    gallery.style.display = 'none';
    lastSavedPaths = [];
}

function resetCreateConversationState(options = {}) {
    const { preserveSelection = false } = options;
    createConversationState.conversationId = null;
    createConversationState.conversation = null;
    createConversationState.isSending = false;
    if (!preserveSelection) {
        createConversationState.selectedPath = null;
    }
    hideCreatePromptMediationCard({ panelId: 'create-gpt-conversation-mediation-panel' });
    renderCreateConversationHistory();
    updateCreateConversationPanelVisibility();
}

function updateResultGalleryLayout() {
    const gallery = document.getElementById('result-gallery');
    if (!gallery) return;

    const totalImages = gallery.querySelectorAll('.gen-result-card').length;
    if (totalImages === 1) {
        gallery.style.gridTemplateColumns = '1fr';
        gallery.style.gridTemplateRows = '1fr';
        gallery.style.gridAutoRows = 'auto';
    } else if (totalImages === 2) {
        gallery.style.gridTemplateColumns = '1fr 1fr';
        gallery.style.gridTemplateRows = '1fr';
        gallery.style.gridAutoRows = 'auto';
    } else {
        gallery.style.gridTemplateColumns = '1fr 1fr';
        gallery.style.gridTemplateRows = 'none';
        gallery.style.gridAutoRows = 'minmax(250px, auto)';
    }
}

function appendGeneratedResultCards(imageUrls, savedPaths, options = {}) {
    const { clearExistingSelection = false, resetGallery = false } = options;
    const gallery = document.getElementById('result-gallery');
    if (!gallery) return;

    if (resetGallery) {
        clearCreateConversationGallery();
    }

    gallery.style.display = 'grid';
    gallery.style.overflowY = 'auto';
    gallery.style.alignContent = 'start';
    gallery.style.paddingBottom = '100px';

    if (clearExistingSelection) {
        gallery.querySelectorAll('.gen-result-card.selected').forEach(card => card.classList.remove('selected'));
    }

    imageUrls.forEach((url, index) => {
        const localPath = savedPaths[index];
        if (!localPath) return;
        lastSavedPaths.push(localPath);
        gallery.insertAdjacentHTML('beforeend', `
            <div class="gen-result-card selected" data-path="${escapeHtml(localPath)}" onclick="toggleGenResultSelect(this)" style="min-height: 250px;">
                <img src="${url}" style="width: 100%; height: 100%; object-fit: contain; border-radius: 8px;">
                <div class="select-badge"><i class="bi bi-check-lg"></i></div>
            </div>
        `);
        createConversationState.selectedPath = localPath;
    });

    updateResultGalleryLayout();
    updateCreateConversationPanelVisibility();
}

function selectCreateConversationModel(modelKey) {
    if (!modelKey || !AI_CONFIG.models[modelKey]) return;
    const modelConfig = AI_CONFIG.models[modelKey];
    switchCategory(modelConfig.category);
    const targetCard = document.getElementById(`card-${modelKey}`);
    if (targetCard) {
        targetCard.click();
    }
}

function renderCreateConversationRecentList(conversations) {
    const recentPanel = getCreateConversationRecentPanel();
    const recentList = getCreateConversationRecentList();
    if (!recentPanel || !recentList) return;

    if (!conversations || conversations.length === 0) {
        recentPanel.style.display = 'none';
        recentList.innerHTML = '';
        return;
    }

    recentPanel.style.display = 'block';
    recentList.innerHTML = conversations.map(conversation => `
        <button type="button" class="btn btn-sm btn-outline-secondary text-start rounded-4 px-3 py-2" data-conversation-id="${conversation.conversation_id}" onclick="restoreCreateConversation(this)">
            <div class="fw-semibold text-truncate">${escapeHtml(conversation.last_instruction || conversation.initial_prompt || '未命名会话')}</div>
            <div class="small text-muted d-flex justify-content-between gap-2">
                <span>${escapeHtml(conversation.model_label || 'GPT Image 2')} · ${conversation.turn_count} 轮</span>
                <span>${new Date(conversation.updated_at).toLocaleString()}</span>
            </div>
        </button>
    `).join('');
}

async function loadRecentCreateConversations() {
    try {
        const response = await fetch('/api/gpt-image-conversations/recent/?source_page=create&limit=6');
        const data = await response.json();
        if (data.status === 'success') {
            renderCreateConversationRecentList(data.conversations || []);
        }
    } catch (error) {
        console.error(error);
    }
}

function rebuildCreateConversationGallery(conversation) {
    clearCreateConversationGallery();
    const turns = conversation?.turns || [];
    turns.forEach((turn, index) => {
        const imageUrls = turn.response_payload?.image_urls || [];
        const savedPaths = turn.response_payload?.saved_paths || [];
        if (imageUrls.length && savedPaths.length) {
            appendGeneratedResultCards(imageUrls, savedPaths, {
                resetGallery: index === 0,
                clearExistingSelection: false,
            });
        }
    });

    if (conversation?.active_image_path) {
        setCreateConversationSelectedCard(conversation.active_image_path);
    }
    if (document.querySelectorAll('.gen-result-card').length > 0) {
        document.getElementById('publish-bar').style.display = 'block';
    }
}

async function restoreCreateConversation(buttonEl) {
    const conversationId = buttonEl?.dataset?.conversationId;
    if (!conversationId) return;

    try {
        const response = await fetch(`/api/gpt-image-conversations/${conversationId}/`);
        const data = await response.json();
        if (data.status !== 'success') {
            throw new Error(data.message || '恢复会话失败');
        }

        const conversation = data.conversation;
        selectCreateConversationModel(conversation.model_key);
        if (conversation.initial_prompt) {
            document.getElementById('ai-prompt').value = conversation.initial_prompt;
        }
        applyCreateConversationParamOverrides(conversation.latest_params || {});
        renderCreateConversationPromptMediation(getLatestCreateConversationPromptMediation(conversation));

        createConversationState.conversationId = conversation.conversation_id;
        createConversationState.conversation = conversation;
        createConversationState.selectedPath = conversation.active_image_path || '';
        rebuildCreateConversationGallery(conversation);
        renderCreateConversationHistory();
        updateCreateConversationPanelVisibility();
        Swal.fire({ toast: true, position: 'top', icon: 'success', title: '已恢复最近会话', showConfirmButton: false, timer: 1800 });
    } catch (error) {
        Swal.fire('恢复失败', error.message || '未知错误', 'error');
    }
}

function setCreateConversationSelectedCard(path) {
    if (!path) return;
    const cards = Array.from(document.querySelectorAll('.gen-result-card'));
    if (!cards.length) return;

    cards.forEach(card => {
        card.classList.toggle('selected', card.getAttribute('data-path') === path);
    });
    createConversationState.selectedPath = path;
    updateCreateConversationPanelVisibility();
}

function publishCreateConversationTurn(buttonEl) {
    const outputPath = buttonEl?.dataset?.outputPath || '';
    if (!outputPath) return;
    setCreateConversationSelectedCard(outputPath);
    publishCreation();
}

function appendCreateConversationTurn(buttonEl) {
    const outputPath = buttonEl?.dataset?.outputPath || '';
    if (!outputPath) return;
    setCreateConversationSelectedCard(outputPath);
    openAddToGroupModal();
}

async function syncCreateConversationActiveResult(path) {
    if (!createConversationState.conversationId || !path) return;

    const formData = new FormData();
    formData.append('image_path', path);

    try {
        const response = await fetch(`/api/gpt-image-conversations/${createConversationState.conversationId}/active-result/`, {
            method: 'POST',
            body: formData,
        });
        const data = await response.json();
        if (data.status === 'success') {
            createConversationState.conversation = {
                ...(createConversationState.conversation || {}),
                ...data.conversation,
            };
            setCreateConversationStatus(`当前会话基底：${path}`);
        }
    } catch (error) {
        console.error(error);
    }
}

async function activateCreateConversationTurn(buttonEl) {
    const turnId = buttonEl?.dataset?.turnId;
    const outputPath = buttonEl?.dataset?.outputPath || '';
    if (!createConversationState.conversationId || !turnId) return;

    const formData = new FormData();
    formData.append('turn_id', turnId);
    if (outputPath) {
        formData.append('image_path', outputPath);
    }

    try {
        const response = await fetch(`/api/gpt-image-conversations/${createConversationState.conversationId}/active-result/`, {
            method: 'POST',
            body: formData,
        });
        const data = await response.json();
        if (data.status !== 'success') {
            throw new Error(data.message || '切换当前基底失败');
        }

        createConversationState.conversation = {
            ...(createConversationState.conversation || {}),
            ...data.conversation,
        };
        if (outputPath) {
            setCreateConversationSelectedCard(outputPath);
        }
        renderCreateConversationHistory();
    } catch (error) {
        Swal.fire('切换失败', error.message || '未知错误', 'error');
    }
}

async function ensureCreateConversation() {
    if (createConversationState.conversationId) {
        return createConversationState.conversation;
    }

    const modelChoice = document.getElementById('ai-model-select')?.value;
    if (!isCreateConversationEligibleModel(modelChoice)) {
        throw new Error('当前只有 GPT Image 2 支持对话式调图');
    }

    const activeImagePath = getCreateConversationSelectedPath();
    if (!activeImagePath) {
        throw new Error('请先选中一张生成结果，再开始对话调整');
    }

    const formData = new FormData();
    formData.append('source_page', 'create');
    formData.append('model_choice', modelChoice);
    formData.append('active_image_path', activeImagePath);
    formData.append('prompt', document.getElementById('ai-prompt')?.value || '');
    formData.append('latest_params', JSON.stringify(collectCreateConversationParams()));

    const response = await fetch('/api/gpt-image-conversations/', {
        method: 'POST',
        body: formData,
    });
    const data = await response.json();
    if (data.status !== 'success') {
        throw new Error(data.message || '创建调图会话失败');
    }

    createConversationState.conversationId = data.conversation.conversation_id;
    createConversationState.conversation = data.conversation;
    createConversationState.selectedPath = activeImagePath;
    renderCreateConversationHistory();
    updateCreateConversationPanelVisibility();
    loadRecentCreateConversations();
    return data.conversation;
}

async function sendCreateConversationMessage() {
    const inputEl = document.getElementById('create-gpt-conversation-input');
    const sendBtn = document.getElementById('create-gpt-conversation-send');
    if (!inputEl || !sendBtn || createConversationState.isSending) return;

    const instruction = inputEl.value.trim();
    if (!instruction) {
        Swal.fire('提示', '请输入本轮调图指令', 'warning');
        return;
    }

    createConversationState.isSending = true;
    sendBtn.disabled = true;
    sendBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>发送中';

    try {
        await ensureCreateConversation();
        const formData = new FormData();
        formData.append('instruction', instruction);
        Object.entries(collectCreateConversationParams()).forEach(([key, value]) => formData.append(key, value));
        if (currentExtraFiles.mask_url) {
            formData.append('mask_url', currentExtraFiles.mask_url);
        }

        const response = await fetch(`/api/gpt-image-conversations/${createConversationState.conversationId}/turns/`, {
            method: 'POST',
            body: formData,
        });
        const data = await response.json();
        if (data.status !== 'success') {
            throw new Error(data.message || '追加对话轮次失败');
        }

        createConversationState.conversation = data.conversation;
        renderCreateConversationPromptMediation(data.prompt_mediation || getLatestCreateConversationPromptMediation(data.conversation));
        renderCreateConversationHistory();
        appendGeneratedResultCards(data.image_urls || [], data.saved_paths || [], { clearExistingSelection: true });
        inputEl.value = '';
        loadRecentCreateConversations();
        Swal.fire({ toast: true, position: 'top', icon: 'success', title: '已追加一轮对话调图', showConfirmButton: false, timer: 2200 });
    } catch (error) {
        Swal.fire('对话调图失败', error.message || '未知错误', 'error');
    } finally {
        createConversationState.isSending = false;
        sendBtn.disabled = false;
        sendBtn.innerHTML = '<i class="bi bi-send me-1"></i>发送';
        updateCreateConversationPanelVisibility();
    }
}

function playNotificationSound(type) {
    const audioEl = document.getElementById(`audio-${type}`);
    if (audioEl) {
        audioEl.currentTime = 0;
        audioEl.play().catch(e => console.log("浏览器限制了自动播放音频"));
    }
}

async function startGeneration() {
    if (window.Notification && Notification.permission !== "granted" && Notification.permission !== "denied") {
        Notification.requestPermission();
    }

    const modelChoice = document.getElementById('ai-model-select').value;
    const promptText = document.getElementById('ai-prompt').value;
    const loopCount = parseInt(document.getElementById('ai-loop-count').value) || 1;

    const categoryId = document.getElementById('ai-category-select').value;
    const uploadConfig = getEffectiveUploadConfig(modelChoice, categoryId);
    const imgRequired = uploadConfig.imgRequired;
    const fileParams = getModelFileParams(modelChoice);

    if (imgRequired && currentFiles.length === 0) {
        Swal.fire('提示', '当前模式必须上传参考图片！', 'warning');
        return;
    }
    for (const fileParam of fileParams) {
        if (fileParam.required && !currentExtraFiles[fileParam.id]) {
            Swal.fire('提示', `请上传${fileParam.label}！`, 'warning');
            return;
        }
    }
    if (!promptText.trim()) {
        Swal.fire('提示', '请输入画面描述！', 'warning');
        return;
    }

    const btn = document.getElementById('btn-generate');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>生成中...';
    
    document.getElementById('canvas-idle').style.display = 'none';
    document.getElementById('publish-bar').style.display = 'none';
    
    const gallery = document.getElementById('result-gallery');
    if(gallery) {
        gallery.style.display = 'none';
        gallery.innerHTML = ''; 
        lastSavedPaths = []; 
    }
    resetCreateConversationState();
    document.getElementById('canvas-scanning').style.display = 'block';
    document.getElementById('canvas-loading').style.display = 'block';

    const promptTips = [
        "💡 小贴士：想要大片感？尝试在提示词加入「丁达尔效应」或「电影级体积光」。",
        "💡 小贴士：开启多轮生成时，您可以切到后台干别的，出图后系统会通知您。",
        "💡 小贴士：多图融合时，上传两张风格差异大的图片，可能会有巨大的惊喜！",
        "💡 小贴士：加入「胶片质感」或「噪点」，能让画面充满复古氛围。"
    ];
    
    let elapsedSeconds = 0;
    let tipIndex = 0;
    const timerElement = document.getElementById('loading-timer-sec');
    const tipsElement = document.getElementById('loading-tips');
    
    timerElement.innerText = "00:00";
    tipsElement.innerText = promptTips[0];
    tipsElement.style.opacity = 1;

    const loadingInterval = setInterval(() => {
        elapsedSeconds++;
        const m = Math.floor(elapsedSeconds / 60).toString().padStart(2, '0');
        const s = (elapsedSeconds % 60).toString().padStart(2, '0');
        timerElement.innerText = `${m}:${s}`;

        if (elapsedSeconds % 4 === 0) {
            tipsElement.style.opacity = 0; 
            setTimeout(() => {
                tipIndex++;
                tipsElement.innerText = promptTips[tipIndex % promptTips.length];
                tipsElement.style.opacity = 1; 
            }, 500); 
        }
    }, 1000);

    const formData = new FormData();
    formData.append('model_choice', modelChoice);
    formData.append('prompt', promptText);
    if (maxImagesAllowed > 0) {
        currentFiles.forEach(file => formData.append('base_images', file));
    }
    fileParams.forEach(fileParam => {
        const file = currentExtraFiles[fileParam.id];
        if (file) formData.append(fileParam.id, file);
    });
    document.querySelectorAll('.dynamic-param-input').forEach(input => {
        const paramId = input.getAttribute('data-param-id');
        const paramType = input.getAttribute('data-param-type');
        if (paramId === 'prompt_aspect_ratio') return;
        if (paramType === 'checkbox') {
            formData.append(paramId, input.checked); 
        } else {
            formData.append(paramId, input.value);
        }
    });
    if (isCreateConversationEligibleModel(modelChoice)) {
        formData.append('adaptive_prompt_optimization', 'true');
    }

    let successCount = 0;
    let failCount = 0;
    let errorMessages = [];
    
    for (let i = 1; i <= loopCount; i++) {
        if (loopCount > 1) {
            btn.innerHTML = `<span class="spinner-border spinner-border-sm me-2"></span>正在生成 第 ${i}/${loopCount} 轮...`;
        }

        const loadingTitle = document.querySelector('.loading-title');
        if (loadingTitle) {
            loadingTitle.innerHTML = `✨ 正在云端渲染您的专属画作 <br><span class="text-primary fs-6 fw-normal">(第 ${i} / ${loopCount} 轮)</span>`;
        }

        try {
            let nextOptimizationLevel = '';
            formData.delete('next_optimization_level');

            while (true) {
                if (nextOptimizationLevel) {
                    formData.set('next_optimization_level', nextOptimizationLevel);
                } else {
                    formData.delete('next_optimization_level');
                }

                const response = await fetch('/api/generate-direct/', {
                    method: 'POST',
                    body: formData 
                });
                const data = await response.json();

                if (data.status === 'success') {
                    playNotificationSound('success');
                    successCount++;
                    renderCreateGeneratePromptMediation(data.prompt_mediation || null);
                    document.getElementById('canvas-scanning').style.display = 'none';
                    document.getElementById('canvas-loading').style.display = 'none';
                    document.getElementById('publish-bar').style.display = 'block';
                    appendGeneratedResultCards(data.image_urls || [], data.saved_paths || []);

                    if (typeof notifyWhenBackground === 'function') {
                        notifyWhenBackground(`🎨 第 ${i} 轮生图完成！`, "已有新图片追加到画板，您可以回来看一眼。");
                    }
                    break;
                }

                renderCreateGeneratePromptMediation(data.prompt_mediation || null);
                if (data.status === 'moderation_failed') {
                    const shouldRetry = await confirmCreatePromptOptimizationEscalation(data, i);
                    if (shouldRetry) {
                        nextOptimizationLevel = data.next_optimization_level || '';
                        continue;
                    }
                } else {
                    Swal.fire({
                        title: `第 ${i} 轮生成失败`,
                        text: data.message,
                        icon: 'error',
                        toast: true,
                        position: 'top',
                        timer: 3000,
                        showConfirmButton: false
                    });
                }

                playNotificationSound('error');
                failCount++;
                errorMessages.push(`<strong>第 ${i} 轮:</strong> ${data.message || '未知错误'}`);
                if (typeof notifyWhenBackground === 'function') {
                    notifyWhenBackground("❌ 任务异常", `第 ${i} 轮触发了报错或拦截，已自动跳过。`);
                }
                break;
            }
        } catch (error) {
            playNotificationSound('error');
            failCount++;
            errorMessages.push(`<strong>第 ${i} 轮:</strong> 网络超时或服务端断开连接`);

            Swal.fire({
                title: `第 ${i} 轮请求异常`,
                text: '网络或服务端断开',
                icon: 'warning',
                toast: true,
                position: 'top',
                timer: 3000,
                showConfirmButton: false
            });
            if (typeof notifyWhenBackground === 'function') {
                notifyWhenBackground("⚠️ 网络异常", `第 ${i} 轮请求超时，正在尝试下一轮。`);
            }
            continue;
        }
    }

    clearInterval(loadingInterval);
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-stars me-2"></i>开始生成';
    document.getElementById('canvas-scanning').style.display = 'none';
    document.getElementById('canvas-loading').style.display = 'none';

    if (successCount === 0) {
        document.getElementById('canvas-idle').style.display = 'block';
    }
    let errorHtmlList = '';
    if (errorMessages.length > 0) {
        errorHtmlList = `<div class="text-start mt-3 p-2 bg-light border rounded custom-scrollbar" style="max-height: 120px; overflow-y: auto; font-size: 0.85rem; color: #dc3545;">
                            <ul class="mb-0 ps-3">`;
        errorMessages.forEach(msg => {
            errorHtmlList += `<li class="mb-1">${msg}</li>`;
        });
        errorHtmlList += `  </ul>
                          </div>`;
    }

    if (successCount > 0 && failCount === 0) {
        Swal.fire({ 
            title: '🎉 队列执行完毕！', 
            text: `共为您完美生成了 ${successCount} 轮图片。`, 
            icon: 'success', 
            toast: true, position: 'top-end', showConfirmButton: false, timer: 5000 
        });
    } else if (successCount > 0 && failCount > 0) {
        Swal.fire({ 
            title: '⚠️ 队列执行完毕', 
            html: `成功 <b>${successCount}</b> 轮，失败 <b class="text-danger">${failCount}</b> 轮。<br>已将成功结果展示在画板。${errorHtmlList}`, 
            icon: 'warning', 
            confirmButtonText: '知道了',
            confirmButtonColor: '#8a2be2'
        });
    } else if (successCount === 0 && failCount > 0) {
        Swal.fire({
            title: '全部生成失败', 
            html: `很遗憾，队列中的 <b>${loopCount}</b> 轮任务全部遭遇异常。${errorHtmlList}`, 
            icon: 'error',
            confirmButtonText: '关闭',
            confirmButtonColor: '#dc3545'
        });
    }
}

function publishCreation() {
    const selectedPaths = getSelectedSavedPaths();
    if (selectedPaths.length === 0) {
        Swal.fire('提示', '请至少在画板中勾选一张要保存的图片！', 'warning');
        return;
    }

    const activeModelCard = document.querySelector('.model-card.active');
    const modelName = activeModelCard ? activeModelCard.querySelector('.model-card-title').innerText.trim() : document.getElementById('ai-model-select').value;
    
    document.getElementById('pub-model').value = modelName;
    const activeModelId = document.getElementById('ai-model-select').value;
    const currentModelConfig = AI_CONFIG.models[activeModelId];
    document.getElementById('pub-provider').value = currentModelConfig ? (currentModelConfig.provider || 'other') : 'other';
    renderPublishTags(initialTagsForPublish);
    renderPublishChars(initialCharsForPublish);
    preparePublishPromptItems();
    renderPublishPromptItems();
    
    const promptText = document.getElementById('ai-prompt').value.trim();
    const titleInput = document.getElementById('pub-title');
    
    if (promptText) {
        titleInput.value = "正在由 AI 智能概括标题...";
        titleInput.disabled = true;
        
        fetch('/api/generate-title/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ prompt: promptText })
        })
        .then(res => res.json())
        .then(data => {
            if (data.status === 'success' && data.title) {
                titleInput.value = data.title;
            } else {
                titleInput.value = ""; 
                titleInput.placeholder = "自动概括失败，请手动输入";
            }
        })
        .catch(err => {
            titleInput.value = "";
            titleInput.placeholder = "请手动输入标题";
        })
        .finally(() => {
            titleInput.disabled = false;
        });
    } else {
        titleInput.value = "";
        titleInput.placeholder = "请输入标题...";
    }

    new bootstrap.Modal(document.getElementById('publishModal')).show();
}

function confirmPublish() {
    const titleInput = document.getElementById('pub-title').value.trim();
    const modalEl = document.getElementById('publishModal');
    const modalInstance = bootstrap.Modal.getInstance(modalEl);
    if (modalInstance) modalInstance.hide();

    Swal.fire({
        title: '正在打包并发布...',
        text: '请稍候，服务器正在生成记录',
        allowOutsideClick: false,
        didOpen: () => Swal.showLoading()
    });

    const formData = new FormData();
    syncPublishPromptItemsFromDom();
    const normalizedPrompts = normalizePublishPromptItems(currentPublishPromptItems);
    formData.append('prompt', document.getElementById('ai-prompt').value);
    formData.append('prompts_json', JSON.stringify(normalizedPrompts));
    formData.append('title', titleInput);
    formData.append('model_info', document.getElementById('pub-model').value.trim());
    formData.append('provider', document.getElementById('pub-provider').value);
    
    const finalTags = Array.from(currentSelectedTags).join(',');
    formData.append('tags', finalTags);
    const finalChars = Array.from(currentSelectedChars).join(',');
    formData.append('characters', finalChars);
    
    const selectedPaths = getSelectedSavedPaths();
    selectedPaths.forEach(path => {
        formData.append('saved_paths', path);
    });

    if (currentFiles && currentFiles.length > 0) {
        currentFiles.forEach(file => {
            formData.append('references', file);
        });
    }

    fetch('/api/publish-studio/', {
        method: 'POST',
        body: formData
    })
    .then(res => res.json())
    .then(data => {
        if (data.status === 'success') {
            Swal.fire({
                icon: 'success',
                title: '🎉 发布成功！',
                text: '已保存至您的提示词画廊。',
                showCancelButton: true,
                confirmButtonText: '<i class="bi bi-eye"></i> 前往查看该卡片',
                cancelButtonText: '留在此页继续创作',
                confirmButtonColor: '#8a2be2'
            }).then((result) => {
                if (result.isConfirmed) {
                    window.open(`/image/${data.group_id}/`, '_blank');
                } else {
                    document.getElementById('publish-bar').style.display = 'none';
                }
            });
        } else {
            Swal.fire('发布失败', data.message, 'error');
        }
    })
    .catch(err => {
        console.error(err);
        Swal.fire('请求异常', '网络或服务端报错，请查看控制台', 'error');
    });
}

let appendSearchTimeout;
function debounceAppendSearch() {
    const val = document.getElementById('appendSearchInput').value.trim();
    clearTimeout(appendSearchTimeout);
    
    if (!val) {
        document.getElementById('appendModalSubtitle').innerText = "系统已根据您当前使用的 Prompt 计算了全库相似度：";
        fetchSimilarGroupsForAppend();
        return;
    }
    
    appendSearchTimeout = setTimeout(() => {
        performAppendSearch(val);
    }, 500);
}

function performAppendSearch(q) {
    const container = document.getElementById('similarGroupsContainer');
    const activeModelCard = document.querySelector('.model-card.active');
    const currentModelName = activeModelCard ? activeModelCard.querySelector('.model-card-title').innerText.trim() : '';
    
    document.getElementById('appendModalSubtitle').innerText = `包含 "${q}" 的全库检索结果：`;
    container.innerHTML = '<div class="text-center text-muted py-5"><div class="spinner-border text-primary mb-3"></div><br>正在检索全库...</div>';

    fetch(`/api/groups/?q=${encodeURIComponent(q)}&include_variants=1`)
    .then(res => res.json())
    .then(data => {
        if (data.results) {
            renderSimilarGroups(data.results, currentModelName, true); 
        } else {
            container.innerHTML = `<div class="text-center text-danger py-4">搜索失败</div>`;
        }
    })
    .catch(err => {
        console.error(err);
        container.innerHTML = '<div class="text-center text-danger py-4">网络请求异常</div>';
    });
}

function openAddToGroupModal() {
    const selectedPaths = getSelectedSavedPaths();
    if (selectedPaths.length === 0) {
        Swal.fire('提示', '请至少在画板中勾选一张要追加的图片！', 'warning');
        return;
    }
    
    const searchInput = document.getElementById('appendSearchInput');
    if (searchInput) searchInput.value = '';
    const subtitle = document.getElementById('appendModalSubtitle');
    if (subtitle) subtitle.innerText = "系统已根据您当前使用的 Prompt 计算了全库相似度：";
    
    new bootstrap.Modal(document.getElementById('addToGroupModal')).show();
    fetchSimilarGroupsForAppend();
    
    setTimeout(() => {
        if (searchInput) searchInput.focus();
    }, 500);
}

function fetchSimilarGroupsForAppend() {
    const promptText = document.getElementById('ai-prompt').value.trim();
    const container = document.getElementById('similarGroupsContainer');
    const activeModelCard = document.querySelector('.model-card.active');
    const currentModelName = activeModelCard ? activeModelCard.querySelector('.model-card-title').innerText.trim() : '';
    container.innerHTML = '<div class="text-center text-muted py-5"><div class="spinner-border text-primary mb-3"></div><br>正在计算全库提示词相似度...</div>';

    fetch('/api/get-similar-groups-by-prompt/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: promptText })
    })
    .then(res => res.json())
    .then(data => {
        if (data.status === 'success') {
            renderSimilarGroups(data.results, currentModelName, false);
        } else {
            container.innerHTML = `<div class="text-center text-danger py-4">检索失败: ${data.message}</div>`;
        }
    })
    .catch(err => {
        console.error(err);
        container.innerHTML = '<div class="text-center text-danger py-4">网络请求异常</div>';
    });
}

function renderSimilarGroups(groups, currentModelName, isSearch = false) {
    const container = document.getElementById('similarGroupsContainer');
    if (!groups || groups.length === 0) {
        container.innerHTML = '<div class="text-center text-muted py-4"><i class="bi bi-inbox fs-1 d-block mb-2 opacity-50"></i>暂无作品。</div>';
        return;
    }

    if (currentSourceGroupId && !isSearch) { 
        const sourceIndex = groups.findIndex(g => String(g.id) === currentSourceGroupId);
        if (sourceIndex > -1) {
            const sourceGroup = groups.splice(sourceIndex, 1)[0];
            groups.unshift(sourceGroup);
        }
    }

    let html = '';
    groups.forEach((group, index) => {
        const isCurrentSource = (currentSourceGroupId && String(group.id) === currentSourceGroupId);

        const coverHtml = group.cover_url 
            ? `<img src="${group.cover_url}" class="rounded shadow-sm" style="width: 70px; height: 70px; object-fit: cover;">`
            : `<div class="rounded bg-light shadow-sm d-flex align-items-center justify-content-center text-muted" style="width: 70px; height: 70px;"><i class="bi bi-image fs-4"></i></div>`;

        let topBadgeHtml = '';
        if (isCurrentSource) {
            topBadgeHtml = `<span class="badge bg-success shadow-sm rounded-pill px-2 py-1"><i class="bi bi-pin-angle-fill me-1"></i>当前所属作品</span>`;
        } else if (group.similarity && !isSearch) {
            let badgeClass = 'bg-secondary';
            let simValue = parseInt(group.similarity);
            if(simValue > 80) badgeClass = 'bg-danger';
            else if(simValue > 50) badgeClass = 'bg-warning text-dark';
            else if(simValue > 20) badgeClass = 'bg-primary';
            topBadgeHtml = `<span class="badge ${badgeClass} rounded-pill">相似度 ${group.similarity}</span>`;
        } else if (isSearch) {
            topBadgeHtml = `<span class="badge bg-light text-secondary border rounded-pill"><i class="bi bi-search me-1"></i>检索结果</span>`;
        }

        const cleanCurrentModelName = currentModelName ? currentModelName.replace(/\s*[\(（].*?[\)）]$/, '').trim() : '';
        let isModelMatch = (cleanCurrentModelName && group.model_info && cleanCurrentModelName.toLowerCase() === group.model_info.toLowerCase());
        let modelBadge = '';
        if (group.model_info && group.model_info !== '无模型') {
            if (isModelMatch) {
                modelBadge = `<span class="badge text-white fw-bold me-2 shadow-sm" style="background: linear-gradient(135deg, #8a2be2 0%, #4a00e0 100%); font-size: 0.75rem;"><i class="bi bi-cpu-fill me-1"></i>${group.model_info} (同款)</span>`;
            } else {
                modelBadge = `<span class="badge bg-secondary fw-normal me-2" style="font-size: 0.75rem;"><i class="bi bi-cpu me-1"></i>${group.model_info}</span>`;
            }
        } else {
            modelBadge = `<span class="badge bg-light text-secondary border fw-normal me-2" style="font-size: 0.75rem;">无模型</span>`;
        }

        let charBadges = '';
        if (group.characters && group.characters.length > 0) {
            group.characters.forEach(char => {
                charBadges += `<span class="badge bg-info text-dark fw-normal me-2" style="font-size: 0.75rem;"><i class="bi bi-person-fill me-1"></i>${char}</span>`;
            });
        }

        const matchedPromptBadge = (!isSearch && group.matched_prompt_label)
            ? `<span class="badge bg-light text-secondary border fw-normal me-2" style="font-size: 0.75rem;"><i class="bi bi-chat-left-text me-1"></i>${group.matched_prompt_label}</span>`
            : '';

        const activeCardClass = isCurrentSource ? "border-success border-2 bg-success bg-opacity-10" : "";

        const safeTitle = group.title 
            ? group.title.replace(/"/g, '&quot;').replace(/'/g, '&#39;').replace(/[\r\n]+/g, ' ') 
            : '未命名作品';

        html += `
        <a href="javascript:void(0)" class="list-group-item list-group-item-action d-flex gap-3 align-items-center py-3 ${activeCardClass}" 
           data-group-id="${group.id}" 
           data-group-title="${safeTitle}" 
           onclick="confirmAppendToGroup(this)">
            ${coverHtml}
            <div class="flex-grow-1 overflow-hidden">
                <div class="d-flex w-100 justify-content-between align-items-center mb-1">
                    <h6 class="mb-0 fw-bold text-truncate" style="max-width: 70%;">${group.title}</h6>
                    ${topBadgeHtml}
                </div>
                <div class="mb-0 text-truncate mt-1 d-flex align-items-center">
                    ${modelBadge}
                    ${charBadges}${matchedPromptBadge}<span class="small text-muted text-truncate">${group.prompt_text}</span>
                </div>
            </div>
        </a>`;
    });
    container.innerHTML = html;
}

function confirmAppendToGroup(element) {
    const groupId = element.getAttribute('data-group-id');
    const groupTitle = element.getAttribute('data-group-title');

    Swal.fire({
        title: '确认追加?',
        html: `即将把新生成的图片收录进作品<br><strong class="text-primary">${groupTitle}</strong>`,
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: '确认追加',
        cancelButtonText: '取消',
        confirmButtonColor: '#8a2be2'
    }).then((result) => {
        if (result.isConfirmed) {
            executeAppendRequest(groupId);
        }
    });
}

function executeAppendRequest(groupId) {
    const modalEl = document.getElementById('addToGroupModal');
    const modalInstance = bootstrap.Modal.getInstance(modalEl);
    if (modalInstance) modalInstance.hide();

    Swal.fire({
        title: '正在打包并追加...',
        allowOutsideClick: false,
        didOpen: () => Swal.showLoading()
    });

    const formData = new FormData();
    formData.append('group_id', groupId);
    
    const selectedPaths = getSelectedSavedPaths();
    selectedPaths.forEach(path => {
        formData.append('saved_paths', path);
    });

    fetch('/api/append-to-existing-group/', {
        method: 'POST',
        body: formData
    })
    .then(res => res.json())
    .then(data => {
        if (data.status === 'success') {
            Swal.fire({
                icon: 'success',
                title: '🎉 追加成功！',
                text: data.message,
                showCancelButton: true,
                confirmButtonText: '<i class="bi bi-eye"></i> 前往查看',
                cancelButtonText: '留在此页继续创作',
                confirmButtonColor: '#8a2be2'
            }).then((result) => {
                if (result.isConfirmed) {
                    window.open(`/image/${data.group_id}/`, '_blank');
                } else {
                    document.getElementById('publish-bar').style.display = 'none';
                }
            });
        } else {
            Swal.fire('追加失败', data.message, 'error');
        }
    })
    .catch(err => {
        console.error(err);
        Swal.fire('请求异常', '网络或服务端报错', 'error');
    });
}

function showCreateCharRefs(charId, btnElement) {
    document.querySelectorAll('#charRefModal .char-filter-btn').forEach(btn => btn.classList.remove('active'));
    btnElement.classList.add('active');
    
    document.querySelectorAll('#charRefModal .char-ref-gallery').forEach(el => el.classList.add('d-none'));
    const targetGallery = document.getElementById('create-char-gallery-' + charId);
    if (targetGallery) targetGallery.classList.remove('d-none');
}

function extractExistingRefToCanvas(url) {
    if (maxImagesAllowed === 0) {
        Swal.fire('提示', '当前选中的生成模型不支持上传参考图！', 'info');
        return;
    }
    if (currentFiles.length >= maxImagesAllowed && maxImagesAllowed > 1) {
        Swal.fire('提示', `当前模型最多只能上传 ${maxImagesAllowed} 张参考图`, 'warning');
        return;
    }

    Swal.fire({
        title: '正在提取图鉴...',
        allowOutsideClick: false,
        didOpen: () => Swal.showLoading()
    });

    fetch(url)
        .then(res => res.blob())
        .then(blob => {
            const filename = url.split('/').pop().split('?')[0] || 'reference_image.jpg';
            const file = new File([blob], filename, { type: blob.type || 'image/jpeg' });
            clearMaskFileForReferenceChange();
            
            if (maxImagesAllowed === 1) {
                currentFiles = [file];
            } else {
                currentFiles.push(file);
            }
            renderPreviews(); 
            
            Swal.close();
            
            const modalEl = document.getElementById('charRefModal');
            const modalInstance = bootstrap.Modal.getInstance(modalEl);
            if (modalInstance) modalInstance.hide();
            
            Swal.fire({
                toast: true, position: 'top', showConfirmButton: false, timer: 2000,
                icon: 'success', title: '已成功提取至工作区'
            });
        })
        .catch(err => {
            console.error("提取参考图失败:", err);
            Swal.fire('提取失败', '无法读取服务器图片', 'error');
        });
}