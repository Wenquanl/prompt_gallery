/**
 * 全库查重功能逻辑 (透明遮罩终极版 + 性能修复版)
 * 核心原理：在视频上覆盖一层透明 div，彻底阻断浏览器对视频的鼠标捕捉。
 */

let checkModalInstance;
let currentBatchId = null;
let blobUrlCache = []; // 【新增】用于记录生成的本地预览 URL，防止内存泄漏

// === 1. 打开模态框 ===
function openCheckModal() {
    const modalEl = document.getElementById('checkDuplicatesModal');
    if (!modalEl) return;
    
    if (!checkModalInstance) {
        checkModalInstance = new bootstrap.Modal(modalEl);
        
        // 【修复 1】：监听模态框关闭事件，彻底清理内存和状态
        modalEl.addEventListener('hidden.bs.modal', () => {
            blobUrlCache.forEach(url => URL.revokeObjectURL(url));
            blobUrlCache = []; // 清空缓存
            
            const resultsArea = document.getElementById('checkResultsArea');
            if (resultsArea) resultsArea.style.display = 'none';
        });
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
    }
});

// === 3. 上传处理 ===
function handleCheckUpload(files) {
    const uploadArea = document.querySelector('.upload-area-dashed');
    const originalContent = uploadArea.innerHTML;
    
    uploadArea.innerHTML = '<div class="spinner-border text-primary mb-3"></div><p class="fw-bold mt-2">正在扫描并进行全库哈希比对...</p>';
    uploadArea.style.pointerEvents = 'none';
    
    const fileMap = {};
    const formData = new FormData();
    
    Array.from(files).forEach(file => {
        formData.append('images', file);
        fileMap[file.name] = file;
    });

    // 【修复 3】：更稳健的 CSRF Token 获取方式（双重保险）
    let csrftoken = getCookie('csrftoken');
    if (!csrftoken) {
        const csrfInput = document.querySelector('[name=csrfmiddlewaretoken]');
        if (csrfInput) csrftoken = csrfInput.value;
    }

    fetch('/check-duplicates/', {
        method: 'POST',
        headers: { 'X-CSRFToken': csrftoken },
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        uploadArea.innerHTML = originalContent;
        uploadArea.style.pointerEvents = 'auto';
        
        // 重新绑定事件
        uploadArea.onclick = function(e) {
            if (e.target.id !== 'checkInput') document.getElementById('checkInput').click();
        };
        const input = document.getElementById('checkInput');
        if(input) input.onchange = function() { handleCheckUpload(this.files); };

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

// === 4. 生成媒体 HTML ===
function getMediaHtml(url, explicitIsVideo, isSmall = false) {
    const sizeStyle = isSmall 
        ? 'width:30px; height:30px;' 
        : 'width:60px; height:60px; margin-right:10px;';
    const borderClass = isSmall ? 'border-danger' : 'border-success';

    if (explicitIsVideo) {
        // 【修复 2】：使用 .catch(() => {}) 吞掉快速移入移出导致的 play() 中断报错
        return `
            <div class="overflow-hidden rounded bg-dark position-relative d-inline-block border ${isSmall ? '' : borderClass}" 
                 style="${sizeStyle}"
                 onmouseenter="let v=this.querySelector('video'); if(v) { v.play().catch(()=>{}); }" 
                 onmouseleave="let v=this.querySelector('video'); if(v) v.pause()">
                 
                <video 
                    src="${url}" 
                    class="w-100 h-100 object-fit-cover position-absolute top-0 start-0" 
                    muted 
                    loop 
                    playsinline
                    style="z-index: 0;">
                </video>
                
                <div class="position-absolute top-0 start-0 w-100 h-100" style="z-index: 10; background: transparent;"></div>
                
                <i class="bi bi-play-circle-fill position-absolute top-50 start-50 translate-middle text-white opacity-75" 
                   style="font-size: ${isSmall?'10px':'20px'}; z-index: 20; pointer-events: none;"></i>
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

    // 在生成新的一批预览图前，清理上一批的内存
    blobUrlCache.forEach(url => URL.revokeObjectURL(url));
    blobUrlCache = [];

    results.forEach(item => {
        // --- 1. 处理左侧（新上传文件） ---
        let displayUrl = item.thumbnail_url;
        let isVideo = false;
        
        if (fileMap && fileMap[item.filename]) {
            const file = fileMap[item.filename];
            displayUrl = URL.createObjectURL(file);
            blobUrlCache.push(displayUrl); // 【修复 1】：记录本地 URL 以便后续释放内存
            isVideo = file.type.startsWith('video/'); 
        } else {
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
                    return `
                        <a href="${detailUrlPrefix}${d.group_id}/" target="_blank" class="me-1" title="点击查看原作品 (ID:${d.id})">
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
                        <div class="text-truncate small text-muted mt-1" title="${item.filename}">${item.filename}</div>
                        ${item.existing_group_title ? `<div class="small text-dark mt-1 text-truncate">位于: <strong>${item.existing_group_title}</strong></div>` : ''}
                    </div>
                </div>
            `;
        } else {
            html = `
                <div class="check-item mb-2 p-2 rounded border d-flex align-items-center">
                    ${mainMediaHtml}
                    <div class="flex-grow-1 min-width-0">
                        <div class="text-success small fw-bold"><i class="bi bi-check-circle-fill me-1"></i>通过检测，为全新文件</div>
                        <div class="text-truncate small text-muted mt-1" title="${item.filename}">${item.filename}</div>
                    </div>
                </div>
            `;
        }
        list.insertAdjacentHTML('beforeend', html);
    });

    summary.innerHTML = `本次共检测 <strong>${results.length}</strong> 个文件，发现 <strong><span class="text-danger">${duplicateCount}</span></strong> 个重复`;
    if (resultsArea) resultsArea.style.display = 'block';
    
    // 更新底部按钮
    const nextUrl = `/upload/?batch_id=${currentBatchId}`;
    if (actionArea) {
        if (hasDuplicate) {
            // 【修复 4】：优化文案，让用户明确知道接下来该怎么做
            actionArea.innerHTML = `
                <div class="alert alert-warning border-0 small d-inline-block text-start mb-3 p-2 w-100">
                    <i class="bi bi-exclamation-triangle-fill text-warning me-1"></i> 发现重复文件！<br>
                    建议点击右下角继续，并在<strong>下一个发布页中手动“X”掉</strong>这些重复项。
                </div>
                <div class="d-flex justify-content-end gap-2">
                    <button class="btn btn-secondary rounded-pill px-4" data-bs-dismiss="modal">取消</button>
                    <a href="${nextUrl}" class="btn btn-primary rounded-pill px-4">前往发布页处理 <i class="bi bi-arrow-right"></i></a>
                </div>
            `;
        } else {
            actionArea.innerHTML = `
                <div class="text-success mb-3 fw-bold text-center"><i class="bi bi-emoji-smile me-2"></i>太棒了！所有文件均未重复。</div>
                <div class="text-center">
                    <a href="${nextUrl}" class="btn btn-lg btn-primary rounded-pill px-5 shadow fw-bold">
                        <i class="bi bi-cloud-arrow-up me-2"></i>前往发布
                    </a>
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