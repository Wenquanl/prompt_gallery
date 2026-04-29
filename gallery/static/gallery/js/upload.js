/**
 * upload.js
 * 处理发布页面的拖拽上传、缩略图生成、预览管理以及【自动查重】和【批量带入】
 * [已修复] 视频预览增加透明遮罩，彻底禁用画中画/翻译/下载按钮
 */

// 全局文件存储数组 (本地上传的文件)
let genFiles = []; // 生成图
let refFiles = []; // 参考图
let uploadPromptItems = [];
let uploadPromptExpandedIndex = null;

// 专门存储从服务器带入的生成图信息，用于前端去重
let serverGenFiles = []; 

document.addEventListener('DOMContentLoaded', () => {
    // 1. 读取后端传递的临时文件数据
    const tempFilesScript = document.getElementById('server-temp-files');
    if (tempFilesScript) {
        try {
            window.SERVER_TEMP_FILES = JSON.parse(tempFilesScript.textContent);
        } catch (e) {
            console.error('JSON parse error', e);
        }
    }

    // 2. 初始化拖拽区域
    setupDragDrop('zone-gen', 'upload_images', 'preview-gen', 'gen');
    setupDragDrop('zone-ref', 'upload_references', 'preview-ref', 'ref');

    // 3. 初始化从后端带入的临时文件
    if (window.SERVER_TEMP_FILES && window.SERVER_TEMP_FILES.length > 0) {
        initServerFiles(window.SERVER_TEMP_FILES);
    }

    initUploadPromptList();
    initUploadTitleCharacterSync();
    initUploadPromptDuplicateSubmitCheck();
});

function normalizeUploadCharacterName(value) {
    return String(value || '')
        .trim()
        .replace(/^[\s"'“”‘’《》「」『』【】\[\]（）()]+|[\s"'“”‘’《》「」『』【】\[\]（）()]+$/g, '')
        .replace(/^(?:标题|作品|人物|角色|主角)\s*[:：]\s*/i, '')
        .replace(/\s+/g, ' ')
        .toLowerCase();
}

function getUploadCharacterOptions() {
    return Array.from(document.querySelectorAll('input[name="characters"]')).map(input => {
        const label = input.closest('label');
        const labelText = label ? label.textContent : '';
        return {
            input,
            name: labelText.replace(/\s+/g, ' ').trim(),
        };
    }).filter(item => item.name);
}

function findUploadCharacterByTitle(title) {
    const normalizedTitle = normalizeUploadCharacterName(title);
    if (!normalizedTitle) return null;

    const options = getUploadCharacterOptions();
    const exactMatch = options.find(item => normalizeUploadCharacterName(item.name) === normalizedTitle);
    if (exactMatch) return exactMatch;

    const containedMatches = options.filter(item => {
        const normalizedName = normalizeUploadCharacterName(item.name);
        return normalizedName.length >= 2 && normalizedTitle.includes(normalizedName);
    });
    return containedMatches.length === 1 ? containedMatches[0] : null;
}

function syncUploadCharacterFromTitle() {
    const titleInput = document.querySelector('input[name="title"]');
    const matched = findUploadCharacterByTitle(titleInput?.value || '');
    if (!matched || matched.input.checked) return;

    matched.input.checked = true;
    matched.input.dispatchEvent(new Event('change', { bubbles: true }));
}

function initUploadTitleCharacterSync() {
    const titleInput = document.querySelector('input[name="title"]');
    if (!titleInput) return;

    titleInput.addEventListener('input', syncUploadCharacterFromTitle);
    titleInput.addEventListener('keyup', syncUploadCharacterFromTitle);
    titleInput.addEventListener('change', syncUploadCharacterFromTitle);
    titleInput.addEventListener('blur', syncUploadCharacterFromTitle);
    titleInput.addEventListener('paste', () => setTimeout(syncUploadCharacterFromTitle, 0));
    setTimeout(syncUploadCharacterFromTitle, 0);
}

function normalizeUploadPromptItems(items) {
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

function escapeUploadPromptHtml(text) {
    const div = document.createElement('div');
    div.textContent = text || '';
    return div.innerHTML;
}

function getUploadPromptSummaryText(text, maxLength = 88) {
    const normalized = String(text || '').replace(/\s+/g, ' ').trim();
    if (!normalized) return '未填写';
    return normalized.length > maxLength ? `${normalized.slice(0, maxLength)}...` : normalized;
}

function getUploadPromptMetaText(text) {
    const source = String(text || '').trim();
    if (!source) return '空内容';
    const lineCount = source.split(/\r?\n/).filter(line => line.trim()).length || 1;
    return `${source.length} 字 · ${lineCount} 行`;
}

function toggleUploadPromptExpanded(index) {
    syncUploadPromptItemsFromDom();
    uploadPromptExpandedIndex = uploadPromptExpandedIndex === index ? null : index;
    renderUploadPromptList();
}

function normalizeUploadPromptForDuplicateCheck(text) {
    return String(text || '').replace(/\s+/g, ' ').trim().toLowerCase();
}

function buildUploadPromptDuplicateReport(items) {
    const seen = new Map();
    const duplicates = [];

    (items || []).forEach((item, index) => {
        const text = String(item?.text || '').trim();
        const normalized = normalizeUploadPromptForDuplicateCheck(text);
        if (!normalized) return;

        if (seen.has(normalized)) {
            const first = seen.get(normalized);
            let duplicate = duplicates.find(row => row.normalized === normalized);
            if (!duplicate) {
                duplicate = {
                    normalized,
                    text: first.text,
                    indexes: [first.index + 1],
                };
                duplicates.push(duplicate);
            }
            duplicate.indexes.push(index + 1);
            return;
        }

        seen.set(normalized, { text, index });
    });

    return duplicates;
}

function dedupeUploadPromptItems(items) {
    const seen = new Set();
    const deduped = [];

    (items || []).forEach((item) => {
        const text = String(item?.text || '').trim();
        const normalized = normalizeUploadPromptForDuplicateCheck(text);
        if (!normalized || seen.has(normalized)) return;
        seen.add(normalized);
        deduped.push({
            id: `prompt_${deduped.length + 1}`,
            label: `提示词${deduped.length + 1}`,
            text,
        });
    });

    return deduped;
}

function buildUploadPromptDuplicateAlertHtml(duplicates) {
    const rows = (duplicates || []).map((item, index) => `
        <div class="text-start border rounded-3 p-2 mb-2 bg-light">
            <div class="small fw-bold text-danger mb-1">重复项 ${index + 1}：提示词 ${item.indexes.join('、')}</div>
            <div class="small text-break">${escapeUploadPromptHtml(item.text)}</div>
        </div>
    `).join('');

    return `
        <div class="text-start">
            <div class="mb-3">检测到多个提示词内容相同。点击确认后会保留每组重复里的第一条，并删除后面的重复项。</div>
            ${rows}
        </div>
    `;
}

function initUploadPromptDuplicateSubmitCheck() {
    const form = document.getElementById('uploadForm');
    if (!form) return;

    form.addEventListener('submit', async (event) => {
        syncUploadPromptItemsFromDom();
        const duplicates = buildUploadPromptDuplicateReport(uploadPromptItems);
        if (!duplicates.length) return;

        event.preventDefault();
        event.stopPropagation();

        const result = await Swal.fire({
            icon: 'warning',
            title: '检测到重复提示词',
            html: buildUploadPromptDuplicateAlertHtml(duplicates),
            width: 680,
            showCancelButton: true,
            confirmButtonText: '确认去重并发布',
            cancelButtonText: '返回修改',
        });

        if (!result.isConfirmed) return;

        uploadPromptItems = dedupeUploadPromptItems(uploadPromptItems);
        uploadPromptExpandedIndex = null;
        renderUploadPromptList();

        if (typeof form.requestSubmit === 'function') {
            if (event.submitter) {
                form.requestSubmit(event.submitter);
            } else {
                form.requestSubmit();
            }
        } else {
            form.submit();
        }
    });
}

function getUploadPromptTranslationLabel(targetLanguage) {
    return targetLanguage === 'zh' ? '中文' : '英文';
}

async function translateUploadPromptText(text, targetLanguage = 'en') {
    const promptText = String(text || '').trim();
    if (!promptText) {
        Swal.fire('提示', '请先输入需要翻译的提示词。', 'info');
        return '';
    }

    Swal.fire({
        title: `正在翻译为${getUploadPromptTranslationLabel(targetLanguage)}...`,
        allowOutsideClick: false,
        didOpen: () => Swal.showLoading(),
    });

    const response = await fetch('/api/translate-prompt/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': window.getCookie ? getCookie('csrftoken') : '',
        },
        body: JSON.stringify({
            text: promptText,
            target_language: targetLanguage,
        }),
    });
    const data = await response.json();
    if (!response.ok || data.status !== 'success') {
        throw new Error(data.message || '翻译失败');
    }
    return data.translated_text || '';
}

async function confirmUploadPromptTranslation(translatedText, targetLanguage, confirmButtonText = '替换当前输入框') {
    const result = await Swal.fire({
        title: `翻译为${getUploadPromptTranslationLabel(targetLanguage)}`,
        html: `<textarea class="form-control text-start" rows="9" readonly>${escapeUploadPromptHtml(translatedText)}</textarea>`,
        width: 720,
        showCancelButton: true,
        showDenyButton: true,
        confirmButtonText,
        denyButtonText: '复制',
        cancelButtonText: '取消',
    });

    if (result.isDenied) {
        copyToClipboard(translatedText);
        return 'copied';
    }

    return result.isConfirmed ? 'replace' : 'cancel';
}

function initUploadPromptList() {
    const dataEl = document.getElementById('upload-prompt-list-data');
    if (!dataEl) return;

    try {
        uploadPromptItems = normalizeUploadPromptItems(JSON.parse(dataEl.textContent || '[]'));
    } catch (error) {
        console.error('初始化上传提示词失败', error);
        uploadPromptItems = [];
    }

    const addBtn = document.getElementById('btn-add-upload-prompt');
    if (addBtn) {
        addBtn.addEventListener('click', () => {
            syncUploadPromptItemsFromDom();
            uploadPromptItems.push({
                id: `prompt_${uploadPromptItems.length + 1}`,
                label: `提示词${uploadPromptItems.length + 1}`,
                text: '',
            });
            uploadPromptExpandedIndex = uploadPromptItems.length - 1;
            renderUploadPromptList();

            const inputs = document.querySelectorAll('#upload-prompt-list .upload-prompt-input');
            const lastInput = inputs[inputs.length - 1];
            if (lastInput) lastInput.focus();
        });
    }

    if (uploadPromptItems.length < 3) {
        while (uploadPromptItems.length < 3) {
            uploadPromptItems.push({
                id: `prompt_${uploadPromptItems.length + 1}`,
                label: `提示词${uploadPromptItems.length + 1}`,
                text: '',
            });
        }
    }

    if (uploadPromptExpandedIndex === null && uploadPromptItems.length > 0 && uploadPromptItems.every(item => !String(item.text || '').trim())) {
        uploadPromptExpandedIndex = 0;
    }

    renderUploadPromptList();
}

function renderUploadPromptList() {
    const container = document.getElementById('upload-prompt-list');
    if (!container) return;

    const displayItems = uploadPromptItems.length > 0
        ? uploadPromptItems
        : [{ id: 'prompt_1', label: '提示词1', text: '' }];

    container.innerHTML = displayItems.map((item, index) => {
        const safeText = escapeUploadPromptHtml(item.text);
        const isExpanded = uploadPromptExpandedIndex === index;
        const safeSummary = escapeUploadPromptHtml(getUploadPromptSummaryText(item.text));
        const safeMeta = escapeUploadPromptHtml(getUploadPromptMetaText(item.text));
        return `
            <div class="upload-prompt-card ${isExpanded ? 'is-expanded' : ''}">
                <div class="upload-prompt-card-header">
                    <div class="upload-prompt-title">
                        <span class="badge bg-white text-primary border rounded-pill px-3 py-2">提示词${index + 1}</span>
                        <span class="upload-prompt-meta">${safeMeta}</span>
                    </div>
                    <div class="upload-prompt-actions">
                    <button type="button" class="btn btn-sm btn-outline-dark rounded-pill px-3" onclick="toggleUploadPromptExpanded(${index})">
                        <i class="bi ${isExpanded ? 'bi-chevron-up' : 'bi-pencil'} me-1"></i>${isExpanded ? '收起' : '编辑'}
                    </button>
                    <button type="button" class="btn btn-sm btn-outline-primary rounded-pill px-3" onclick="translateUploadPromptItem(${index}, 'en')">
                        <i class="bi bi-translate me-1"></i>译英
                    </button>
                    <button type="button" class="btn btn-sm btn-outline-secondary rounded-pill px-3" onclick="translateUploadPromptItem(${index}, 'zh')">
                        <i class="bi bi-translate me-1"></i>译中
                    </button>
                    <button type="button" class="btn btn-sm btn-outline-danger rounded-pill px-3" onclick="removeUploadPromptItem(${index})">
                        <i class="bi bi-trash3 me-1"></i>删除
                    </button>
                    </div>
                </div>
                <div class="upload-prompt-summary ${isExpanded ? 'd-none' : ''}">${safeSummary}</div>
                <textarea class="form-control upload-prompt-input upload-prompt-textarea ${isExpanded ? '' : 'd-none'}" name="prompts" rows="5" data-index="${index}" placeholder="请输入提示词${index + 1}...">${safeText}</textarea>
            </div>
        `;
    }).join('');
}

async function translateUploadPromptItem(index, targetLanguage) {
    syncUploadPromptItemsFromDom();
    const input = document.querySelector(`#upload-prompt-list .upload-prompt-input[data-index="${index}"]`);
    if (!input) return;

    try {
        const translatedText = await translateUploadPromptText(input.value, targetLanguage);
        if (!translatedText) return;
        const action = await confirmUploadPromptTranslation(translatedText, targetLanguage);
        if (action !== 'replace') return;

        input.value = translatedText;
        uploadPromptExpandedIndex = index;
        uploadPromptItems[index] = {
            ...(uploadPromptItems[index] || { text: '' }),
            text: translatedText,
        };
        Swal.fire({
            icon: 'success',
            title: '已替换当前输入框',
            toast: true,
            position: 'top-end',
            showConfirmButton: false,
            timer: 1600,
        });
    } catch (error) {
        Swal.fire('翻译失败', error.message || '请确认本地 Qwen3 服务已启动。', 'error');
    }
}

function syncUploadPromptItemsFromDom() {
    const inputs = document.querySelectorAll('#upload-prompt-list .upload-prompt-input');
    uploadPromptItems = Array.from(inputs).map((input, index) => ({
        id: `prompt_${index + 1}`,
        label: `提示词${index + 1}`,
        text: input.value || '',
    }));
}

async function removeUploadPromptItem(index) {
    syncUploadPromptItemsFromDom();
    const promptText = uploadPromptItems[index]?.text || '';
    const preview = getUploadPromptSummaryText(promptText, 80);
    const result = await Swal.fire({
        title: `删除提示词${index + 1}？`,
        html: `<div class="text-start small text-muted">删除后这条提示词不会随本次发布保存。</div><div class="text-start border rounded-3 bg-light p-2 mt-3">${escapeUploadPromptHtml(preview)}</div>`,
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: '确认删除',
        cancelButtonText: '取消',
        confirmButtonColor: '#dc3545',
    });
    if (!result.isConfirmed) return;

    uploadPromptItems.splice(index, 1);
    if (uploadPromptExpandedIndex === index) {
        uploadPromptExpandedIndex = null;
    } else if (uploadPromptExpandedIndex > index) {
        uploadPromptExpandedIndex -= 1;
    }
    renderUploadPromptList();
}

/**
 * 初始化服务器端带入的临时文件
 */
function initServerFiles(files) {
    const container = document.getElementById('preview-gen');
    const form = document.getElementById('uploadForm');
    
    files.forEach(file => {
        serverGenFiles.push({
            name: file.name,
            size: file.size
        });

        // 1. 创建预览 DOM
        const div = document.createElement('div');
        div.className = 'preview-item server-file position-relative'; // 确保相对定位
        div.dataset.filename = file.name;
        
        // 删除按钮 (先创建，设置高层级)
        const delBtn = document.createElement('div');
        delBtn.className = 'btn-remove-preview';
        delBtn.innerHTML = '<i class="bi bi-x-lg"></i>';
        delBtn.title = '移除此图';
        delBtn.style.zIndex = '30'; // 【关键】确保在遮罩之上
        delBtn.onclick = (e) => {
            e.stopPropagation();
            div.remove();
            serverGenFiles = serverGenFiles.filter(f => f.name !== file.name);
            const hiddenInput = form.querySelector(`input[name="selected_files"][value="${file.name}"]`);
            if (hiddenInput) hiddenInput.remove();
        };

        const isVideo = file.name.match(/\.(mp4|mov|avi|webm|mkv)$/i);

        if (isVideo) {
            // 使用通用的视频构建函数
            setupVideoPreview(div, file.url);
        } else {
            const img = document.createElement('img');
            img.src = file.url;
            img.className = 'loaded w-100 h-100 object-fit-cover';
            div.appendChild(img);
        }

        // 确保删除按钮已添加
        if (!div.contains(delBtn)) div.appendChild(delBtn);
        
        container.appendChild(div);

        // 2. 注入隐藏域
        const input = document.createElement('input');
        input.type = 'hidden';
        input.name = 'selected_files';
        input.value = file.name;
        form.appendChild(input);
    });
}

/**
 * 初始化拖拽区域
 */
function setupDragDrop(zoneId, inputName, previewId, type) {
    const zone = document.getElementById(zoneId);
    if (!zone) return;
    
    const input = zone.querySelector(`input[name="${inputName}"]`);
    const previewContainer = document.getElementById(previewId);

    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        zone.addEventListener(eventName, preventDefaults, false);
        document.body.addEventListener(eventName, preventDefaults, false);
    });

    ['dragenter', 'dragover'].forEach(eventName => {
        zone.addEventListener(eventName, () => zone.classList.add('drag-over'), false);
    });
    ['dragleave', 'drop'].forEach(eventName => {
        zone.addEventListener(eventName, () => zone.classList.remove('drag-over'), false);
    });

    zone.addEventListener('drop', (e) => {
        const dt = e.dataTransfer;
        const files = dt.files;
        handleFiles(files, type, input, previewContainer);
    }, false);

    input.addEventListener('change', (e) => {
        if (input.files.length > 0) {
            handleFiles(input.files, type, input, previewContainer);
        }
    });
}

function preventDefaults(e) {
    e.preventDefault();
    e.stopPropagation();
}

/**
 * 处理文件添加逻辑
 */
function handleFiles(newFiles, type, input, previewContainer) {
    const fileArray = (type === 'gen') ? genFiles : refFiles;
    let hasNew = false;
    let filesToCheck = [];
    let ignoredCount = 0;

    Array.from(newFiles).forEach(file => {
        const existsLocal = fileArray.some(f => f.name === file.name && f.size === file.size);
        let existsServer = false;
        if (type === 'gen') {
            existsServer = serverGenFiles.some(f => f.name === file.name && f.size === file.size);
        }

        if (!existsLocal && !existsServer) {
            fileArray.push(file);
            addPreviewItem(file, type, previewContainer);
            hasNew = true;
            if (type === 'gen') {
                filesToCheck.push(file);
            }
        } else {
            ignoredCount++;
        }
    });

    if (hasNew) {
        updateInputFiles(type, input);
        if (type === 'gen' && filesToCheck.length > 0) {
            checkDuplicates(filesToCheck, previewContainer);
        }
    }

    if (ignoredCount > 0) {
        const toast = Swal.mixin({
            toast: true, position: 'top', showConfirmButton: false, timer: 3000, timerProgressBar: true,
        });
        toast.fire({ icon: 'info', title: `已自动过滤 ${ignoredCount} 张重复图片` });
    }
}

/**
 * 自动查重逻辑
 */
function checkDuplicates(files, container) {
    const formData = new FormData();
    files.forEach(f => formData.append('images', f));
    
    let csrftoken = document.querySelector('[name=csrfmiddlewaretoken]')?.value;
    if (!csrftoken && window.getCookie) {
        csrftoken = getCookie('csrftoken');
    }

    fetch('/check-duplicates/', {
        method: 'POST',
        body: formData,
        headers: { 'X-CSRFToken': csrftoken }
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success' && data.results) {
            data.results.forEach(res => {
                if (res.status === 'duplicate') {
                    markAsDuplicate(res.filename, container, res.existing_group_title);
                }
            });
            
            if (data.has_duplicate) {
                const toast = Swal.mixin({
                    toast: true, position: 'top-end', showConfirmButton: false, timer: 3000
                });
                toast.fire({ icon: 'warning', title: '发现重复内容，已标红' });
            }
        }
    })
    .catch(err => console.error('Check duplicate failed:', err));
}

function markAsDuplicate(filename, container, groupTitle) {
    const items = container.querySelectorAll('.preview-item');
    items.forEach(item => {
        if (item.dataset.filename === filename) {
            item.classList.add('duplicate');
            if (!item.querySelector('.duplicate-badge')) {
                const badge = document.createElement('div');
                badge.className = 'duplicate-badge';
                badge.innerHTML = '<i class="bi bi-exclamation-circle-fill me-1"></i>已存在';
                badge.title = `系统中已存在该内容 (位于: ${groupTitle})`;
                item.appendChild(badge);
            }
        }
    });
}

function updateInputFiles(type, input) {
    const fileArray = (type === 'gen') ? genFiles : refFiles;
    const dataTransfer = new DataTransfer();
    fileArray.forEach(file => {
        dataTransfer.items.add(file);
    });
    input.files = dataTransfer.files;
}

/**
 * 添加预览 DOM 元素 (本地文件)
 */
function addPreviewItem(file, type, container) {
    const div = document.createElement('div');
    div.className = 'preview-item position-relative';
    div.dataset.filename = file.name; 
    
    // Loading
    const spinner = document.createElement('div');
    spinner.className = 'spinner-border text-secondary spinner-border-sm position-absolute top-50 start-50 translate-middle';
    div.appendChild(spinner);
    
    // 删除按钮 (提前创建)
    const delBtn = document.createElement('div');
    delBtn.className = 'btn-remove-preview';
    delBtn.innerHTML = '<i class="bi bi-x-lg"></i>';
    delBtn.title = '移除此文件';
    delBtn.style.zIndex = '30'; // 【关键】确保在遮罩之上
    delBtn.onclick = (e) => {
        e.stopPropagation();
        removeFileItem(e.target, type, container);
    };
    div.appendChild(delBtn);
    
    container.appendChild(div);

    // 检查视频
    if (file.type.startsWith('video/') || file.name.match(/\.(mp4|mov|avi|webm|mkv)$/i)) {
        spinner.remove();
        // 使用通用视频构建函数
        setupVideoPreview(div, URL.createObjectURL(file));
        return;
    }

    // 检查图片
    createThumbnail(file).then(thumbnailUrl => {
        spinner.remove();
        if (thumbnailUrl) {
            const img = document.createElement('img');
            img.src = thumbnailUrl;
            img.className = 'loaded w-100 h-100 object-fit-cover';
            // 插入到删除按钮之前，保证按钮在最上面 (其实有 z-index 保护，顺序无所谓了，但习惯上这样)
            div.insertBefore(img, delBtn);
        } else {
            div.innerHTML = '<i class="bi bi-file-earmark-x text-danger fs-3 position-absolute top-50 start-50 translate-middle"></i>';
            div.appendChild(delBtn); // innerHTML 会清空子元素，需重新添加按钮
        }
    });
}

/**
 * 【新增】视频预览构建通用函数 (透明遮罩终极版)
 * 原理：Video底层 + 透明Div中层(挡鼠标) + Icon上层 + Container监听鼠标
 */
function setupVideoPreview(container, url) {
    // 1. 视频层 (z-index: 0, 屏蔽鼠标)
    const video = document.createElement('video');
    video.src = url;
    video.className = 'w-100 h-100 object-fit-cover position-absolute top-0 start-0';
    video.style.zIndex = '0';
    video.style.pointerEvents = 'none'; // 【绝杀】彻底屏蔽浏览器按钮
    video.muted = true;
    video.loop = true;
    video.disablePictureInPicture = true;
    video.setAttribute('controlsList', 'nodownload noremoteplayback noplaybackrate');
    video.setAttribute('playsinline', '');

    // 2. 透明遮罩层 (z-index: 10, 承接鼠标事件，让浏览器以为这里没视频)
    const mask = document.createElement('div');
    mask.className = 'position-absolute top-0 start-0 w-100 h-100';
    mask.style.zIndex = '10';
    mask.style.background = 'transparent';

    // 3. 播放图标 (z-index: 20)
    const icon = document.createElement('div');
    icon.className = 'position-absolute top-50 start-50 translate-middle text-white opacity-75';
    icon.style.zIndex = '20';
    icon.style.pointerEvents = 'none';
    icon.innerHTML = '<i class="bi bi-play-circle-fill fs-4" style="text-shadow: 0 2px 4px rgba(0,0,0,0.5);"></i>';

    // 交互：在容器上监听
    container.addEventListener('mouseenter', () => video.play().catch(()=>{}));
    container.addEventListener('mouseleave', () => { video.pause(); video.currentTime = 0; });

    container.appendChild(video);
    container.appendChild(mask);
    container.appendChild(icon);
    
    // 注意：删除按钮已经在外部创建并添加，z-index 为 30，所以会浮在最上面
}

/**
 * 移除文件
 */
function removeFileItem(target, type, container) {
    const itemDiv = target.closest('.preview-item');
    if (!itemDiv) return;

    if (itemDiv.classList.contains('server-file')) {
        itemDiv.remove();
        return;
    }

    const localItems = Array.from(container.querySelectorAll('.preview-item:not(.server-file)'));
    const index = localItems.indexOf(itemDiv);
    
    if (index !== -1) {
        const fileArray = (type === 'gen') ? genFiles : refFiles;
        fileArray.splice(index, 1);
        itemDiv.remove();
        
        const zoneId = (type === 'gen') ? 'zone-gen' : 'zone-ref';
        const inputName = (type === 'gen') ? 'upload_images' : 'upload_references';
        const zone = document.getElementById(zoneId);
        const input = zone.querySelector(`input[name="${inputName}"]`);
        
        updateInputFiles(type, input);
    }
}

/**
 * 生成高质量缩略图 (仅图片)
 */
function createThumbnail(file) {
    return new Promise((resolve) => {
        if (!file.type.startsWith('image/')) {
            resolve(null);
            return;
        }

        const reader = new FileReader();
        reader.onload = (e) => {
            const img = new Image();
            img.onload = () => {
                const canvas = document.createElement('canvas');
                const ctx = canvas.getContext('2d');
                const maxSize = 320;
                let width = img.width;
                let height = img.height;
                if (width > height) {
                    if (width > maxSize) {
                        height *= maxSize / width;
                        width = maxSize;
                    }
                } else {
                    if (height > maxSize) {
                        width *= maxSize / height;
                        height = maxSize;
                    }
                }
                canvas.width = width;
                canvas.height = height;
                ctx.imageSmoothingEnabled = true;
                ctx.imageSmoothingQuality = 'high';
                ctx.drawImage(img, 0, 0, width, height);
                resolve(canvas.toDataURL('image/jpeg', 0.9)); 
            };
            img.onerror = () => resolve(null);
            img.src = e.target.result;
        };
        reader.readAsDataURL(file);
    });
}

function showCharRefs(charId, btnElement) {
        document.querySelectorAll('.char-filter-btn').forEach(btn => btn.classList.remove('active'));
        btnElement.classList.add('active');
        document.querySelectorAll('.char-ref-gallery').forEach(el => el.classList.add('d-none'));
        const targetGallery = document.getElementById('char-gallery-' + charId);
        if (targetGallery) targetGallery.classList.remove('d-none');
    }
    
    function toggleCharRefSelect(card, refId) {
        card.classList.toggle('selected');
        const badge = card.querySelector('.select-badge');
        const hiddenContainer = document.getElementById('hidden-existing-refs');
        if (card.classList.contains('selected')) {
            card.style.borderColor = '#0d6efd';
            badge.classList.remove('d-none');
            const input = document.createElement('input');
            input.type = 'hidden';
            input.name = 'existing_ref_ids';
            input.value = refId;
            input.id = 'hidden-ref-' + refId;
            hiddenContainer.appendChild(input);
        } else {
            card.style.borderColor = 'transparent';
            badge.classList.add('d-none');
            const input = document.getElementById('hidden-ref-' + refId);
            if (input) input.remove();
        }
    }
