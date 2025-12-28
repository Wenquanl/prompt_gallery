/**
 * 全库查重功能逻辑
 */

let checkModalInstance;
let currentBatchId = null;

// 打开模态框
function openCheckModal() {
    const modalEl = document.getElementById('checkDuplicatesModal');
    if (!modalEl) return;
    
    if (!checkModalInstance) {
        checkModalInstance = new bootstrap.Modal(modalEl);
    }
    
    // 重置输入和界面
    document.getElementById('checkInput').value = '';
    document.getElementById('checkResultsArea').style.display = 'none';
    
    const uploadArea = document.querySelector('.upload-area-dashed');
    uploadArea.innerHTML = `
        <i class="bi bi-cloud-upload display-4 text-muted mb-2"></i>
        <p class="mb-0 text-muted">点击选择或拖拽图片到这里</p>
        <small class="text-secondary">支持批量上传，系统将自动比对数据库哈希值</small>
        <input type="file" id="checkInput" multiple accept="image/*" hidden onchange="handleCheckUpload(this)">
    `;
    uploadArea.style.pointerEvents = 'auto';
    
    checkModalInstance.show();
}

// 初始化拖拽事件 (等待 DOM 加载)
document.addEventListener('DOMContentLoaded', function() {
    const dropZone = document.querySelector('.upload-area-dashed');
    if (dropZone) {
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            dropZone.addEventListener(eventName, preventDefaults, false);
        });

        function preventDefaults(e) {
            e.preventDefault();
            e.stopPropagation();
        }

        dropZone.addEventListener('dragover', () => dropZone.classList.add('bg-light', 'border-primary'));
        dropZone.addEventListener('dragleave', () => dropZone.classList.remove('bg-light', 'border-primary'));

        dropZone.addEventListener('drop', handleDrop, false);

        function handleDrop(e) {
            dropZone.classList.remove('bg-light', 'border-primary');
            const dt = e.dataTransfer;
            const files = dt.files;
            
            const input = document.getElementById('checkInput');
            input.files = files; 
            handleCheckUpload(input);
        }
    }
});

// 处理上传检测
function handleCheckUpload(input) {
    if (!input.files || input.files.length === 0) return;

    const formData = new FormData();
    for (let i = 0; i < input.files.length; i++) {
        formData.append('images', input.files[i]);
    }

    const uploadArea = document.querySelector('.upload-area-dashed');
    const originalContent = uploadArea.innerHTML;
    
    uploadArea.innerHTML = '<div class="spinner-border text-primary mb-3"></div><p>正在上传并对比全库哈希值...</p>';
    uploadArea.style.pointerEvents = 'none';

    // 使用 common.js 中的 getCookie 获取 token
    const csrftoken = getCookie('csrftoken'); 

    fetch('/check-duplicates/', {
        method: 'POST',
        body: formData,
        headers: { 'X-CSRFToken': csrftoken }
    })
    .then(response => response.json())
    .then(data => {
        uploadArea.innerHTML = originalContent;
        uploadArea.style.pointerEvents = 'auto';

        if (data.status === 'success') {
            currentBatchId = data.batch_id;
            renderCheckResults(data.results, data.has_duplicate);
        } else {
            Swal.fire('错误', data.message || '查重请求失败', 'error');
        }
    })
    .catch(err => {
        uploadArea.innerHTML = originalContent;
        uploadArea.style.pointerEvents = 'auto';
        console.error(err);
        Swal.fire('错误', '网络请求错误', 'error');
    });
}

// 渲染结果
function renderCheckResults(results, hasDuplicate) {
    const resultsArea = document.getElementById('checkResultsArea');
    const list = document.getElementById('resultsList');
    const actionArea = document.getElementById('actionArea');
    const summary = document.getElementById('checkSummary');

    list.innerHTML = '';
    let duplicateCount = 0;
    
    // 详情页 URL 前缀 (硬编码为 /image/，需与 urls.py 匹配)
    const detailUrlPrefix = "/image/"; 

    results.forEach(item => {
        let html = '';
        if (item.status === 'duplicate') {
            duplicateCount++;
            html = `
                <div class="check-item bg-danger bg-opacity-10">
                    <img src="${item.thumbnail_url}" class="check-thumb">
                    <div class="flex-grow-1 min-width-0">
                        <div class="d-flex justify-content-between">
                            <strong class="text-danger small"><i class="bi bi-exclamation-circle-fill me-1"></i>已存在</strong>
                        </div>
                        <div class="text-truncate small text-muted mt-1">${item.filename}</div>
                        <div class="small text-dark mt-1 d-flex align-items-center">
                            位于: <strong>${item.existing_group_title}</strong>
                            <a href="${detailUrlPrefix}${item.existing_group_id}/" target="_blank" class="btn btn-xs btn-outline-secondary rounded-pill py-0 ms-2" style="font-size: 11px; height: 18px; line-height: 16px;">
                                查看旧卡片 <i class="bi bi-arrow-right-short"></i>
                            </a>
                        </div>
                    </div>
                </div>
            `;
        } else {
            html = `
                <div class="check-item">
                    <img src="${item.thumbnail_url}" class="check-thumb" style="object-fit: cover; border-color: #198754;">
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
    resultsArea.style.display = 'block';

    // 引导发布链接
    const nextUrl = `/upload/?batch_id=${currentBatchId}`;
    
    if (hasDuplicate) {
        actionArea.innerHTML = `
            <div class="alert alert-warning border-0 small d-inline-block text-start mb-3">
                <i class="bi bi-exclamation-triangle me-1"></i> 发现重复图片！建议剔除重复项后再发布。
            </div>
            <div>
                <button class="btn btn-secondary rounded-pill px-4 me-2" data-bs-dismiss="modal">关闭</button>
                <a href="${nextUrl}" class="btn btn-primary rounded-pill px-4">
                    仍要发布 <i class="bi bi-arrow-right"></i>
                </a>
            </div>
        `;
    } else {
        actionArea.innerHTML = `
            <div class="text-success mb-3 fw-bold"><i class="bi bi-emoji-smile me-2"></i>完美！没有发现重复图片。</div>
            <a href="${nextUrl}" class="btn btn-lg btn-primary rounded-pill px-5 shadow fw-bold">
                <i class="bi bi-plus-lg me-2"></i>去发布新作品
            </a>
        `;
    }
}