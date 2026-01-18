/**
 * 全库查重功能逻辑 (最终修复版)
 * 修复点：不再通过后缀名猜测视频，而是依据 MIME 类型和后端字段，彻底解决裂图。
 */

let checkModalInstance;
let currentBatchId = null;

// === 1. 打开模态框 ===
function openCheckModal() {
    const modalEl = document.getElementById('checkDuplicatesModal');
    if (!modalEl) return;
    
    if (!checkModalInstance) {
        checkModalInstance = new bootstrap.Modal(modalEl);
    }
    
    const resultsArea = document.getElementById('checkResultsArea');
    if (resultsArea) resultsArea.style.display = 'none';
    
    const uploadArea = document.querySelector('.upload-area-dashed');
    if (uploadArea) {
        uploadArea.innerHTML = `
            <i class="bi bi-cloud-upload display-4 text-muted mb-2"></i>
            <p class="mb-0 text-muted">点击选择或拖拽图片/视频到这里</p>
            <small class="text-secondary">支持批量上传，系统将自动比对数据库哈希值</small>
            <input type="file" id="checkInput" multiple accept="image/*,video/*" hidden>
        `;
        uploadArea.style.pointerEvents = 'auto';
        uploadArea.style.cursor = 'pointer';
        
        uploadArea.onclick = function(e) {
            if (e.target.id !== 'checkInput') {
                document.getElementById('checkInput').click();
            }
        };
        
        const input = document.getElementById('checkInput');
        input.onchange = function() {
            if (this.files.length > 0) handleCheckUpload(this.files);
        };
    }
    
    checkModalInstance.show();
}

// === 2. 初始化事件 ===
document.addEventListener('DOMContentLoaded', function() {
    const dropZone = document.querySelector('.upload-area-dashed');
    if (dropZone) {
        ['dragenter', 'dragover'].forEach(e => {
            dropZone.addEventListener(e, (ev) => {
                ev.preventDefault();
                dropZone.classList.add('bg-light', 'border-primary');
            });
        });

        ['dragleave', 'drop'].forEach(e => {
            dropZone.addEventListener(e, (ev) => {
                ev.preventDefault();
                dropZone.classList.remove('bg-light', 'border-primary');
            });
        });

        dropZone.addEventListener('drop', (e) => {
            if (e.dataTransfer.files.length > 0) handleCheckUpload(e.dataTransfer.files);
        });
        
        const input = document.getElementById('checkInput');
        if (input) {
            input.addEventListener('change', function() {
                if (this.files.length > 0) handleCheckUpload(this.files);
            });
        }
    }
});

// === 3. 上传处理 ===
function handleCheckUpload(files) {
    const uploadArea = document.querySelector('.upload-area-dashed');
    const originalContent = uploadArea.innerHTML;
    
    uploadArea.innerHTML = '<div class="spinner-border text-primary mb-3"></div><p>正在上传并对比全库哈希值...</p>';
    uploadArea.style.pointerEvents = 'none';
    
    const fileMap = {};
    const formData = new FormData();
    
    Array.from(files).forEach(file => {
        formData.append('images', file);
        fileMap[file.name] = file;
    });

    const csrftoken = getCookie('csrftoken');

    fetch('/check-duplicates/', {
        method: 'POST',
        headers: { 'X-CSRFToken': csrftoken },
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        uploadArea.innerHTML = originalContent;
        uploadArea.style.pointerEvents = 'auto';
        
        uploadArea.onclick = function(e) {
            if (e.target.id !== 'checkInput') document.getElementById('checkInput').click();
        };
        const input = document.getElementById('checkInput');
        input.onchange = function() { handleCheckUpload(this.files); };

        if (data.status === 'success') {
            currentBatchId = data.batch_id;
            renderCheckResults(data.results, data.has_duplicate, fileMap);
        } else {
            Swal.fire('错误', data.message || '查重请求失败', 'error');
        }
    })
    .catch(err => {
        console.error(err);
        uploadArea.innerHTML = originalContent;
        uploadArea.style.pointerEvents = 'auto';
        Swal.fire('错误', '网络请求错误', 'error');
    });
}

// === 4. 生成媒体 HTML (核心修复) ===
// 增加 explicitIsVideo 参数，不再只靠猜
function getMediaHtml(url, explicitIsVideo, isSmall = false) {
    const sizeStyle = isSmall 
        ? 'width:30px; height:30px;' 
        : 'width:60px; height:60px; margin-right:10px;';
    const borderClass = isSmall ? 'border-danger' : 'border-success';

    if (explicitIsVideo) {
        return `
            <div class="overflow-hidden rounded bg-dark position-relative d-inline-block border ${isSmall ? '' : borderClass}" style="${sizeStyle}">
                <video src="${url}" class="w-100 h-100 object-fit-cover" muted loop onmouseover="this.play()" onmouseout="this.pause()"></video>
                <i class="bi bi-play-circle-fill position-absolute top-50 start-50 translate-middle text-white opacity-75" style="font-size: ${isSmall?'10px':'20px'}; pointer-events: none;"></i>
            </div>
        `;
    } else {
        return `
            <img src="${url}" class="rounded bg-light border ${isSmall ? '' : borderClass}" style="${sizeStyle} object-fit: contain;">
        `;
    }
}

// === 5. 渲染结果 ===
function renderCheckResults(results, hasDuplicate, fileMap) {
    const list = document.getElementById('resultsList');
    const resultsArea = document.getElementById('checkResultsArea');
    const actionArea = document.getElementById('actionArea');
    const summary = document.getElementById('checkSummary');

    list.innerHTML = '';
    let duplicateCount = 0;
    const detailUrlPrefix = "/image/"; 

    results.forEach(item => {
        // --- 1. 处理左侧（新上传文件） ---
        let displayUrl = item.thumbnail_url;
        let isVideo = false;
        
        // 优先用本地文件对象，精准判断类型
        if (fileMap && fileMap[item.filename]) {
            const file = fileMap[item.filename];
            displayUrl = URL.createObjectURL(file);
            // 【核心】使用浏览器识别的 MIME 类型
            isVideo = file.type.startsWith('video/'); 
        } else {
            // 兜底：如果文件名有视频后缀，认为是视频
            isVideo = !!item.filename.match(/\.(mp4|mov|avi|webm|mkv|m4v)$/i);
        }
        
        const mainMediaHtml = getMediaHtml(displayUrl, isVideo, false);
        
        // --- 2. 处理右侧（重复文件） ---
        let html = '';
        if (item.status === 'duplicate') {
            duplicateCount++;
            
            let existingThumbsHtml = '';
            if (item.duplicates && item.duplicates.length > 0) {
                 existingThumbsHtml = item.duplicates.map(d => {
                    // 【核心】使用后端返回的 is_video 字段
                    return `
                        <a href="${detailUrlPrefix}${d.group_id}/" target="_blank" class="me-1" title="查看 ID:${d.id}">
                            ${getMediaHtml(d.url, d.is_video, true)}
                        </a>
                    `;
                 }).join('');
            }

            html = `
                <div class="check-item bg-danger bg-opacity-10 mb-2 p-2 rounded d-flex align-items-center">
                    ${mainMediaHtml}
                    <div class="flex-grow-1 min-width-0">
                        <div class="d-flex justify-content-between align-items-center">
                            <strong class="text-danger small"><i class="bi bi-exclamation-circle-fill me-1"></i>已存在</strong>
                            <div class="d-flex align-items-center">${existingThumbsHtml}</div>
                        </div>
                        <div class="text-truncate small text-muted mt-1">${item.filename}</div>
                        ${item.existing_group_title ? `<div class="small text-dark mt-1">位于: <strong>${item.existing_group_title}</strong></div>` : ''}
                    </div>
                </div>
            `;
        } else {
            html = `
                <div class="check-item mb-2 p-2 rounded border d-flex align-items-center">
                    ${mainMediaHtml}
                    <div class="flex-grow-1">
                        <div class="text-success small fw-bold"><i class="bi bi-check-circle-fill me-1"></i>通过检测</div>
                        <div class="text-truncate small text-muted mt-1">${item.filename}</div>
                    </div>
                </div>
            `;
        }
        list.insertAdjacentHTML('beforeend', html);
    });

    summary.innerHTML = `共检测 ${results.length} 张，发现 ${duplicateCount} 张重复`;
    if (resultsArea) resultsArea.style.display = 'block';
    
    // 更新底部按钮
    const nextUrl = `/upload/?batch_id=${currentBatchId}`;
    if (actionArea) {
        if (hasDuplicate) {
            actionArea.innerHTML = `
                <div class="alert alert-warning border-0 small d-inline-block text-start mb-3 p-2 w-100">
                    <i class="bi bi-exclamation-triangle me-1"></i> 发现重复项！建议剔除重复后再发布。
                </div>
                <div class="d-flex justify-content-end gap-2">
                    <button class="btn btn-secondary rounded-pill px-4" data-bs-dismiss="modal">关闭</button>
                    <a href="${nextUrl}" class="btn btn-primary rounded-pill px-4">仍要发布 <i class="bi bi-arrow-right"></i></a>
                </div>
            `;
        } else {
            actionArea.innerHTML = `
                <div class="text-success mb-3 fw-bold text-center"><i class="bi bi-emoji-smile me-2"></i>完美！没有发现重复。</div>
                <div class="text-center">
                    <a href="${nextUrl}" class="btn btn-lg btn-primary rounded-pill px-5 shadow fw-bold"><i class="bi bi-plus-lg me-2"></i>去发布新作品</a>
                </div>
            `;
        }
    }
}

function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}