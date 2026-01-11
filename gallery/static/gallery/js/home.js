// 全局变量定义
let mergeModal;
let selectedMergeIds = new Set();
let currentPage = 1;
let currentQuery = '';
let isLoading = false;
let IS_LIKED_FILTER = false;

document.addEventListener('DOMContentLoaded', function() {
    // 读取 Django 传递的数据
    const filterScript = document.getElementById('current-filter-data');
    if (filterScript) {
        IS_LIKED_FILTER = JSON.parse(filterScript.textContent);
    }

    initMasonry('#masonry-grid', '.grid-item');
    
    // 初始化 Tooltips
    var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });

    // Merge 搜索监听 (防抖)
    let debounceTimer;
    const mergeInput = document.getElementById('mergeSearchInput');
    if (mergeInput) {
        mergeInput.addEventListener('input', function(e) {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(() => {
                currentQuery = e.target.value.trim();
                loadMergeData(1, true);
            }, 500);
        });
    }
});

// === 业务逻辑函数 ===

function copyHomePrompt(event, text) {
    event.preventDefault(); 
    event.stopPropagation();
    copyToClipboard(text, '提示词复制成功！');
}

function toggleGroupLike(event, pk, currentIsLiked) {
    event.preventDefault(); 
    event.stopPropagation();
    toggleLikeCommon(pk, 'group', currentIsLiked, event.currentTarget, IS_LIKED_FILTER);
}

// === 合并功能 (Merge) 逻辑 ===

function openMergeModal() {
    if (!mergeModal) {
        mergeModal = new bootstrap.Modal(document.getElementById('mergeManagerModal'));
    }
    mergeModal.show();
    
    if (document.getElementById('mergeListContent').children.length === 0) {
        loadMergeData(1, true);
    }
}

function loadMergeData(page, reset = false) {
    if (isLoading) return;
    isLoading = true;
    
    const container = document.getElementById('mergeListContent');
    const loadMoreBtn = document.getElementById('mergeLoadMore');
    
    if (reset) {
        container.innerHTML = '<div class="text-center py-5 text-muted"><i class="bi bi-hourglass-split me-2"></i>加载中...</div>';
        currentPage = 1;
    }

    fetch(`api/groups/?page=${page}&q=${encodeURIComponent(currentQuery)}`)
        .then(res => res.json())
        .then(data => {
            if (reset) container.innerHTML = '';
            
            if (data.results.length === 0 && reset) {
                container.innerHTML = '<div class="text-center py-5 text-muted">未找到相关内容</div>';
                loadMoreBtn.style.display = 'none';
                return;
            }

            data.results.forEach(item => {
                const isChecked = selectedMergeIds.has(String(item.id)) ? 'checked' : '';
                const activeClass = isChecked ? 'border-primary bg-primary bg-opacity-10' : 'border-0 bg-white';
                
                let badgeHtml = '';
                if (item.count > 1) {
                    badgeHtml = `<span class="badge bg-dark bg-opacity-75 rounded-pill position-absolute bottom-0 end-0 m-2 shadow-sm border border-light border-opacity-25" 
                                    style="font-size: 0.75rem; backdrop-filter: blur(2px); z-index: 2;">
                                    <i class="bi bi-layers-fill me-1 text-warning"></i>${item.count} 版本
                                </span>`;
                }
                
                const html = `
                    <div class="card shadow-sm merge-item-card ${activeClass} position-relative" 
                        onclick="toggleMergeSelection(this, '${item.id}')" 
                        style="cursor: pointer; transition: all 0.2s;">
                        ${badgeHtml} <div class="card-body p-2 d-flex align-items-center">
                            <div class="me-3 ps-2">
                                <input type="checkbox" class="form-check-input merge-checkbox" 
                                    ${isChecked} style="transform: scale(1.2); pointer-events: none;">
                            </div>
                            <div class="rounded overflow-hidden bg-secondary me-3" style="width: 60px; height: 60px; flex-shrink: 0;">
                                ${item.cover_url ? `<img src="${item.cover_url}" class="w-100 h-100 object-fit-cover">` : '<div class="w-100 h-100 d-flex align-items-center justify-content-center text-white"><i class="bi bi-image"></i></div>'}
                            </div>
                            <div class="flex-grow-1 overflow-hidden">
                                <div class="d-flex justify-content-between align-items-center pe-2">
                                    <h6 class="mb-1 text-truncate fw-bold text-dark" style="max-width: 70%;">${item.title}</h6>
                                    <span class="badge bg-light text-muted border fw-normal">${item.created_at}</span>
                                </div>
                                <div class="small text-muted text-truncate">${item.prompt_text}</div>
                                <div class="small text-primary mt-1">
                                    <i class="bi bi-robot me-1"></i>${item.model_info || '未知模型'}
                                </div>
                            </div>
                        </div>
                    </div>
                `;
                container.insertAdjacentHTML('beforeend', html);
            });

            if (data.has_next) {
                loadMoreBtn.style.display = 'block';
                currentPage = page;
            } else {
                loadMoreBtn.style.display = 'none';
            }
        })
        .catch(err => {
            console.error(err);
            if(reset) container.innerHTML = '<div class="text-center text-danger py-4">加载失败，请重试</div>';
        })
        .finally(() => {
            isLoading = false;
        });
}

function toggleMergeSelection(card, id) {
    const checkbox = card.querySelector('.merge-checkbox');
    id = String(id);
    
    if (selectedMergeIds.has(id)) {
        selectedMergeIds.delete(id);
        checkbox.checked = false;
        card.classList.remove('border-primary', 'bg-primary', 'bg-opacity-10');
        card.classList.add('border-0', 'bg-white');
    } else {
        selectedMergeIds.add(id);
        checkbox.checked = true;
        card.classList.remove('border-0', 'bg-white');
        card.classList.add('border-primary', 'bg-primary', 'bg-opacity-10');
    }
    
    document.getElementById('mergeSelectedCount').textContent = selectedMergeIds.size;
    const clearBtn = document.getElementById('mergeClearBtn');
    clearBtn.style.display = selectedMergeIds.size > 0 ? 'block' : 'none';
}

function submitMerge() {
    if (selectedMergeIds.size < 2) {
        Swal.fire('提示', '请至少选择两个组进行合并', 'warning');
        return;
    }

    Swal.fire({
        title: '确认合并?',
        text: `确认将选中的 ${selectedMergeIds.size} 个版本归为同一类?`,
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: '确定',
        cancelButtonText: '取消'
    }).then((result) => {
        if (result.isConfirmed) {
            fetch('/api/merge-groups/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCookie('csrftoken')
                },
                body: JSON.stringify({
                    group_ids: Array.from(selectedMergeIds)
                })
            })
            .then(res => res.json())
            .then(data => {
                if (data.status === 'success') {
                    Swal.fire('成功', data.message, 'success').then(() => {
                        window.location.reload();
                    });
                } else {
                    Swal.fire('失败', data.message, 'error');
                }
            });
        }
    });
}

function clearMergeSelection() {
    selectedMergeIds.clear();
    document.getElementById('mergeSelectedCount').textContent = 0;
    document.getElementById('mergeClearBtn').style.display = 'none';
    
    document.querySelectorAll('.merge-item-card').forEach(card => {
        const checkbox = card.querySelector('.merge-checkbox');
        if (checkbox) checkbox.checked = false;
        card.classList.remove('border-primary', 'bg-primary', 'bg-opacity-10');
        card.classList.add('border-0', 'bg-white');
    });
}