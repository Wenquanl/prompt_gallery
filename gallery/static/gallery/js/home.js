// home.js
// 首页交互：Masonry布局、Tooltip、合并管理、首页弹窗上传

// 全局变量定义
let mergeModal;
let selectedMergeIds = new Set();
let currentPage = 1;
let currentQuery = '';
let isLoading = false;
let IS_LIKED_FILTER = false;
const templateModal = new bootstrap.Modal(document.getElementById('templateSelectModal'));
let templateSearchTimeout;
document.addEventListener('DOMContentLoaded', function() {
    // 读取 Django 传递的数据
    const filterScript = document.getElementById('current-filter-data');
    if (filterScript) {
        IS_LIKED_FILTER = JSON.parse(filterScript.textContent);
    }

    // 初始化瀑布流
    if (window.initMasonry) {
        initMasonry('#masonry-grid', '.grid-item');
    }
    
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

    // ================= [新增] 首页模态框上传逻辑 =================
    const homeUploadForm = document.getElementById('homeUploadForm');
    if (homeUploadForm) {
        homeUploadForm.addEventListener('submit', function(e) {
            e.preventDefault();
            
            const formData = new FormData(this);
            const btn = this.querySelector('button[type="submit"]');
            const originalText = btn.innerHTML;
            
            // 按钮 Loading 状态
            btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>发布中...';
            btn.disabled = true;

            fetch(this.action, {
                method: 'POST',
                body: formData,
                headers: { 
                    'X-Requested-With': 'XMLHttpRequest', // 标记为 AJAX
                    'X-CSRFToken': getCookie('csrftoken') 
                }
            })
            .then(res => res.json())
            .then(data => {
                btn.innerHTML = originalText;
                btn.disabled = false;

                if (data.status === 'success') {
                    // 1. 关闭 Modal
                    const modalEl = document.getElementById('homeUploadModal');
                    const bsModal = bootstrap.Modal.getInstance(modalEl);
                    if (bsModal) bsModal.hide();

                    // 2. 动态插入新卡片到顶部
                    if (data.html) {
                        const grid = document.getElementById('masonry-grid');
                        const tempDiv = document.createElement('div');
                        tempDiv.innerHTML = data.html;
                        const newNode = tempDiv.firstElementChild;
                        
                        // 移除空状态提示（如果存在）
                        const emptyState = grid.querySelector('.text-center.py-5');
                        if (emptyState) emptyState.remove();

                        // 插入到 DOM
                        grid.insertBefore(newNode, grid.firstChild); 

                        // 3. Masonry 布局更新
                        if (window.msnry) {
                            window.msnry.prepended([newNode]);
                            window.msnry.layout();
                        }
                    }
                    
                    // 4. 清空表单与预览
                    const previewBox = document.getElementById('home-upload-preview');
                    if (previewBox) previewBox.innerHTML = '';
                    homeUploadForm.reset();

                    // 5. 成功提示
                    Swal.fire({
                        icon: 'success',
                        title: '发布成功',
                        text: data.message,
                        timer: 2000,
                        showConfirmButton: false
                    });

                } else {
                    Swal.fire({
                        icon: 'error',
                        title: '发布失败',
                        text: data.message || '请重试',
                    });
                }
            })
            .catch(err => {
                console.error(err);
                btn.innerHTML = originalText;
                btn.disabled = false;
                Swal.fire('错误', '网络请求失败', 'error');
            });
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

function openTemplateModal() {
    templateModal.show();
    // 自动聚焦输入框
    setTimeout(() => document.getElementById('templateSearchInput').focus(), 500);
}

function debounceSearchTemplate() {
    clearTimeout(templateSearchTimeout);
    templateSearchTimeout = setTimeout(searchTemplates, 300);
}

function searchTemplates() {
    const query = document.getElementById('templateSearchInput').value.trim();
    const resultsContainer = document.getElementById('templateSearchResults');
    
    if (!query) {
        resultsContainer.innerHTML = '<div class="text-center text-muted py-3 small">请输入关键词搜索</div>';
        return;
    }

    resultsContainer.innerHTML = '<div class="text-center text-muted py-3"><div class="spinner-border spinner-border-sm text-primary"></div></div>';

    fetch(`/api/groups/?q=${encodeURIComponent(query)}`)
        .then(response => response.json())
        .then(data => {
            if (!data.results || data.results.length === 0) {
                resultsContainer.innerHTML = '<div class="text-center text-muted py-3 small">未找到匹配的卡片</div>';
                return;
            }

            let html = '<div class="list-group list-group-flush">';
            data.results.forEach(group => {
                // 构建封面图 HTML
                let imgHtml = group.cover_url 
                    ? `<img src="${group.cover_url}" class="rounded me-3" style="width: 48px; height: 48px; object-fit: cover;">`
                    : `<div class="rounded me-3 d-flex align-items-center justify-content-center bg-light text-muted" style="width: 48px; height: 48px;"><i class="bi bi-image"></i></div>`;

                html += `
                    <a href="/upload/?template_id=${group.id}" class="list-group-item list-group-item-action d-flex align-items-center p-2 border-0 rounded mb-1">
                        ${imgHtml}
                        <div class="flex-grow-1 overflow-hidden">
                            <div class="d-flex justify-content-between align-items-center">
                                <h6 class="mb-0 text-truncate text-dark">${group.title || '未命名'}</h6>
                                <span class="badge bg-light text-secondary border fw-normal">${group.model_info || '无模型'}</span>
                            </div>
                            <small class="text-muted text-truncate d-block" style="font-size: 0.8rem;">${group.prompt_text || '无提示词'}</small>
                        </div>
                        <i class="bi bi-chevron-right text-muted ms-2" style="font-size: 0.8rem;"></i>
                    </a>
                `;
            });
            html += '</div>';
            resultsContainer.innerHTML = html;
        })
        .catch(err => {
            console.error(err);
            resultsContainer.innerHTML = '<div class="text-center text-danger py-3 small">搜索出错</div>';
        });
}
// === 确保在 DOM 加载完成后初始化需要获取 DOM 的变量 ===
let addModelModal, seedreamModal;

document.addEventListener('DOMContentLoaded', () => {
    // 初始化 Bootstrap Modals
    const addModelEl = document.getElementById('addModelModal');
    if(addModelEl) {
        addModelModal = new bootstrap.Modal(addModelEl);
    }
    
    const seedreamEl = document.getElementById('seedreamModal');
    if(seedreamEl) {
        seedreamModal = new bootstrap.Modal(seedreamEl);
    }

    // 1. 初始化交叉观察器 (懒加载动画)
    const cardObserver = new IntersectionObserver((entries, observer) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('animate-show');
                observer.unobserve(entry.target); 
            }
        });
    }, {
        root: null,
        threshold: 0.1, 
        rootMargin: "0px 0px -50px 0px"
    });

    // 2. 找到所有的卡片并开始观察
    const cards = document.querySelectorAll('.gallery-card');
    cards.forEach((card, index) => {
        if (index < 10) {
            card.style.transitionDelay = `${index * 50}ms`;
        }
        cardObserver.observe(card);
    });

    // 3. 如果模型本来就很少（没有换行），自动隐藏展开按钮
    const container = document.getElementById('model-tags-container');
    const btn = document.getElementById('toggle-models-btn');
    if (container && btn) {
        if (container.scrollHeight <= 42) {
            btn.style.display = 'none';
            container.style.paddingRight = '0'; 
        }
    }
});

// === 添加模型相关的逻辑 ===
function openAddModelModal() {
    document.getElementById('newModelNameInput').value = '';
    addModelModal.show();
    setTimeout(() => document.getElementById('newModelNameInput').focus(), 300);
}

function submitAddModel() {
    const name = document.getElementById('newModelNameInput').value.trim();
    if(!name) return;
    
    const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
    
    fetch('/add-model/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        },
        body: JSON.stringify({ name: name })
    })
    .then(res => res.json())
    .then(data => {
        if(data.status === 'success') {
            addModelModal.hide();
            window.location.reload(); 
        } else {
            alert(data.message || '添加失败');
        }
    })
    .catch(err => alert('网络错误'));
}

function toggleModels() {
    const container = document.getElementById('model-tags-container');
    const isExpanded = container.classList.contains('is-expanded');
    
    if (!isExpanded) {
        container.classList.add('is-expanded');
        const exactHeight = container.scrollHeight;
        container.style.maxHeight = exactHeight + 'px';
    } else {
        container.classList.remove('is-expanded');
        container.style.maxHeight = '36px'; 
    }
}

// === 右键编辑模型标签逻辑 ===
function handleTagContextMenu(event, element) {
    event.preventDefault(); 
    const oldName = element.getAttribute('data-tag-name');

    Swal.fire({
        title: '编辑模型标签',
        text: '修改后的名称将同步更新到所有关联的画作卡片',
        input: 'text',
        inputValue: oldName,
        showCancelButton: true,
        confirmButtonText: '保存修改',
        cancelButtonText: '取消',
        confirmButtonColor: '#8a2be2',
        inputValidator: (value) => {
            if (!value || value.trim() === '') {
                return '标签名称不能为空！';
            }
            if (value.trim() === oldName) {
                return '名称未发生改变';
            }
        }
    }).then((result) => {
        if (result.isConfirmed) {
            const newName = result.value.trim();
            submitEditModel(oldName, newName);
        }
    });
}

function submitEditModel(oldName, newName) {
    const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';

    Swal.fire({
        title: '正在更新...',
        allowOutsideClick: false,
        didOpen: () => Swal.showLoading()
    });

    fetch('/edit-model/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        },
        body: JSON.stringify({ old_name: oldName, new_name: newName })
    })
    .then(res => res.json())
    .then(data => {
        if(data.status === 'success') {
            Swal.fire({
                icon: 'success', title: '修改成功', toast: true,
                position: 'top-end', showConfirmButton: false, timer: 1500
            }).then(() => window.location.reload()); 
        } else {
            Swal.fire('修改失败', data.message || '未知错误', 'error');
        }
    })
    .catch(err => {
        console.error(err);
        Swal.fire('错误', '网络或服务端异常', 'error');
    });
}

// === 远端API 图片生成逻辑 ===
function openSeedreamModal() {
    document.getElementById('seedream-images').value = '';
    document.getElementById('seedream-prompt').value = '';
    document.getElementById('seedream-loading').style.display = 'none';
    document.getElementById('btn-seedream-generate').disabled = false;
    toggleAIModelUI(); 
    seedreamModal.show();
}

function toggleAIModelUI() {
    const selectEl = document.getElementById('ai-model-select');
    if(!selectEl) return;
    const selectedOption = selectEl.options[selectEl.selectedIndex];
    const category = selectedOption.getAttribute('data-category'); 

    const imgBlock = document.getElementById('ai-image-upload-block');
    const imgInput = document.getElementById('seedream-images');
    const imgHelp = document.getElementById('ai-img-help');

    if (category === 't2i') {
        imgBlock.style.display = 'none'; 
    } else if (category === 'i2i') {
        imgBlock.style.display = 'block';
        imgInput.removeAttribute('multiple');
        imgHelp.innerHTML = '当前为 <b class="text-primary">单图模式</b>：请上传 1 张参考图片。';
    } else if (category === 'multi') {
        imgBlock.style.display = 'block';
        imgInput.setAttribute('multiple', 'multiple');
        imgHelp.innerHTML = '当前为 <b class="text-success">多图模式</b>：按住 Ctrl / Command 键可多选 (最多10张)。';
    }
}

function generateSeedream() {
    const selectEl = document.getElementById('ai-model-select');
    const modelChoice = selectEl.value;
    const category = selectEl.options[selectEl.selectedIndex].getAttribute('data-category');
    
    const fileInput = document.getElementById('seedream-images');
    const promptText = document.getElementById('seedream-prompt').value;

    if (category !== 't2i' && fileInput.files.length === 0) {
        Swal.fire('提示', '当前模型必须上传参考图片！', 'warning');
        return;
    }
    if (!promptText.trim()) {
        Swal.fire('提示', '请输入提示词！', 'warning');
        return;
    }

    const btn = document.getElementById('btn-seedream-generate');
    const loading = document.getElementById('seedream-loading');
    
    btn.disabled = true;
    loading.style.display = 'block';

    const formData = new FormData();
    formData.append('model_choice', modelChoice);
    formData.append('prompt', promptText);
    
    if (category !== 't2i') {
        for (let i = 0; i < fileInput.files.length; i++) {
            formData.append('base_images', fileInput.files[i]);
        }
    }

    fetch('/api/generate-direct/', {
        method: 'POST',
        body: formData 
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            seedreamModal.hide();
            Swal.fire({
                title: '🎉 生成完毕！',
                text: data.message,
                imageUrl: data.image_url,
                imageHeight: 300,
                imageAlt: 'AI Generated Image',
                confirmButtonText: 'OK'
            });
        } else {
            Swal.fire('❌ 发生错误', data.message, 'error');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        Swal.fire('❌ 请求失败', '网络错误或服务端报错，请查看后台', 'error');
    })
    .finally(() => {
        btn.disabled = false;
        loading.style.display = 'none';
    });
}