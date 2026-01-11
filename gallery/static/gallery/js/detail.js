/**
 * detail.js
 * 详情页交互：图片切换、提示词编辑、标签管理、点赞、删除
 * 依赖: Bootstrap 5, SweetAlert2, galleryImages (全局变量), common.js (getCookie, copyToClipboard, initMasonry)
 */

let currentIndex = 0;
let imageModal = null; 

document.addEventListener('DOMContentLoaded', function() {
    const dataElement = document.getElementById('gallery-data');
    if (dataElement) {
        window.galleryImages = JSON.parse(dataElement.textContent);
    }
    // 原有的初始化逻辑...
});

document.addEventListener('DOMContentLoaded', function() {
    // 1. 初始化模态框
    const modalEl = document.getElementById('imageModal');
    if (modalEl) {
        imageModal = new bootstrap.Modal(modalEl);
    }
    
    // 2. 初始化 Masonry 布局 (图片卡片)
    if (window.initMasonry) {
        initMasonry('#detail-masonry-grid', '.grid-item');
    }

    // 3. 键盘事件监听 (左右切换图片)
    document.addEventListener('keydown', function(event) {
        if (modalEl && modalEl.classList.contains('show')) {
            if (event.key === 'ArrowLeft') changeImage(-1);
            if (event.key === 'ArrowRight') changeImage(1);
            if (event.key === 'Escape') imageModal.hide();
        }
    });

    // 4. 点击外部收起标签输入框
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
});

// ================= 图片模态框逻辑 =================

function showModal(index) {
    currentIndex = index;
    updateModalImage();
    imageModal.show();
}

function changeImage(direction) {
    currentIndex += direction;
    // 循环播放
    if (currentIndex >= galleryImages.length) { currentIndex = 0; } 
    else if (currentIndex < 0) { currentIndex = galleryImages.length - 1; }
    updateModalImage();
}

function updateModalImage() {
    const imgElement = document.getElementById('previewImage');
    const downloadBtn = document.getElementById('modalDownloadBtn');
    const deleteForm = document.getElementById('modalDeleteForm');
    const counterElement = document.getElementById('imageCounter');
    const likeBtn = document.getElementById('modalLikeBtn');

    if (!galleryImages || galleryImages.length === 0) return;

    const currentImgData = galleryImages[currentIndex];

    // 图片切换动画效果
    imgElement.style.opacity = '0.5';
    imgElement.src = currentImgData.url;
    imgElement.onload = function() { imgElement.style.opacity = '1'; };

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

// 模态框内的点赞
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

// 列表中的点赞
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
            const imgData = galleryImages.find(img => img.id === pk);
            if (imgData) { imgData.isLiked = data.is_liked; }
        }
    });
}

// 通用删除确认
function confirmDelete(event) {
    event.preventDefault(); 
    const form = event.target.closest('form');
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
    }).then((result) => { if (result.isConfirmed) form.submit(); })
}

// ================= 提示词编辑逻辑 =================

function enableEdit(elementId, editBtn) {
    const box = document.getElementById(elementId);
    if (box.querySelector('.empty-text')) {
        box.dataset.wasEmpty = 'true';
        box.innerText = ''; 
    } else {
        box.dataset.originalText = box.innerText; 
    }
    box.contentEditable = "true";
    box.focus();
    toggleEditButtons(box, true);
}

function cancelEdit(elementId) {
    const box = document.getElementById(elementId);
    if (box.dataset.wasEmpty === 'true') {
        box.innerHTML = '<span class="empty-text">未填写</span>';
    } else if (box.dataset.originalText !== undefined) {
        box.innerText = box.dataset.originalText;
    }
    box.contentEditable = "false";
    delete box.dataset.originalText;
    delete box.dataset.wasEmpty;
    toggleEditButtons(box, false);
}

function savePrompt(elementId, pk, type) {
    const box = document.getElementById(elementId);
    const newText = box.innerText;
    const data = {};
    const csrftoken = getCookie('csrftoken');
    
    if (type === 'positive') { data.prompt_text = newText; }
    else if (type === 'positive_zh') { data.prompt_text_zh = newText; }
    else if (type === 'model') { data.model_info = newText; }
    else { data.negative_prompt = newText; }

    fetch(`/update-prompts/${pk}/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrftoken },
        body: JSON.stringify(data)
    })
    .then(response => response.json())
    .then(res => {
        if (res.status === 'success') {
            box.contentEditable = "false";
            const copyBtn = box.parentElement.querySelector('.btn-outline-primary, .btn-outline-danger, .btn-outline-success');
            if (copyBtn) copyBtn.disabled = !newText.trim();
            if (!newText.trim()) { box.innerHTML = '<span class="empty-text">未填写</span>'; }
            toggleEditButtons(box, false);
            
            Swal.fire({
                icon: 'success', 
                title: '保存成功',
                toast: true,
                position: 'top-end',
                showConfirmButton: false,
                timer: 1500
            });
        } else {
            Swal.fire({ icon: 'error', title: '保存失败', text: res.message });
        }
    })
    .catch(err => { console.error(err); Swal.fire({ icon: 'error', title: '错误', text: '网络错误，请重试' }); });
}

function toggleEditButtons(boxElement, isEditing) {
    const header = boxElement.parentElement.querySelector('.section-header');
    const editBtn = header.querySelector('.btn-edit-prompt');
    const actionsDiv = header.querySelector('.edit-actions');
    if (isEditing) {
        editBtn.style.display = 'none';
        actionsDiv.style.display = 'block';
    } else {
        editBtn.style.display = 'inline-block';
        actionsDiv.style.display = 'none';
    }
}

function copyTextHandler(elementId, btnElement) {
    const textElement = document.getElementById(elementId);
    if (textElement.querySelector('.empty-text')) return;

    const text = textElement.innerText;
    copyToClipboard(text); 

    const originalHTML = btnElement.innerHTML;
    const isPrimary = btnElement.classList.contains('btn-outline-primary');
    const isDanger = btnElement.classList.contains('btn-outline-danger');
    let originalClass;
    if (isPrimary) originalClass = 'btn-outline-primary';
    else if (isDanger) originalClass = 'btn-outline-danger';
    else originalClass = 'btn-outline-success';

    btnElement.innerHTML = '<i class="bi bi-check-lg me-1"></i>已复制';
    btnElement.classList.remove(originalClass); btnElement.classList.add('btn-success', 'text-white');
    setTimeout(() => {
        btnElement.innerHTML = originalHTML;
        btnElement.classList.remove('btn-success', 'text-white'); btnElement.classList.add(originalClass);
    }, 2000);
}

// ================= 标签交互逻辑 =================

function showTagInput() {
    const btn = document.getElementById('btnAddTag');
    if(btn) btn.style.display = 'none';
    
    const container = document.getElementById('tagInputContainer');
    if(container) container.classList.add('show');
    
    const input = document.getElementById('newTagInput');
    if(input) setTimeout(() => input.focus(), 100);
}

function handleTagKey(event, groupPk) {
    if (event.key === 'Enter') {
        event.preventDefault();
        addTag(groupPk);
    } else if (event.key === 'Escape') {
        resetTagInput();
    }
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
    if (!tagName) { 
        input.focus(); 
        return; 
    }

    const csrftoken = getCookie('csrftoken');
    fetch(`/add-tag/${groupPk}/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrftoken },
        body: JSON.stringify({ tag_name: tagName })
    })
    .then(res => res.json())
    .then(data => {
        if (data.status === 'success') {
            const newTagHtml = `
                <span class="tag-interactive" id="tag-pill-${data.tag_id}">
                    <a href="/?q=${data.tag_name}">${data.tag_name}</a>
                    <span class="tag-remove-btn" onclick="removeTag(${groupPk}, ${data.tag_id}, '${data.tag_name}')" title="移除">
                        <i class="bi bi-x-circle-fill"></i>
                    </span>
                </span>
            `;
            document.getElementById('btnAddTag').parentNode.insertAdjacentHTML('beforebegin', newTagHtml);
            input.value = '';
            input.focus();
        } else {
            Swal.fire({ icon: 'error', title: '添加失败', text: data.message });
        }
    })
    .catch(err => Swal.fire({ icon: 'error', title: '错误', text: '网络请求失败' }));
}

function removeTag(groupPk, tagId, tagName) {
    Swal.fire({
        title: '移除标签?',
        text: `确定要移除 "${tagName}" 吗？`,
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: '#ff4757',
        cancelButtonColor: '#6c757d',
        confirmButtonText: '是的, 移除',
        cancelButtonText: '取消',
        background: 'rgba(255, 255, 255, 0.95)',
        customClass: { popup: 'rounded-4 shadow-lg border-0' }
    }).then((result) => {
        if (result.isConfirmed) {
            performRemoveTag(groupPk, tagId);
        }
    });
}

function performRemoveTag(groupPk, tagId) {
    const csrftoken = getCookie('csrftoken');
    fetch(`/remove-tag/${groupPk}/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrftoken },
        body: JSON.stringify({ tag_id: tagId })
    })
    .then(res => res.json())
    .then(data => {
        if (data.status === 'success') {
            const el = document.getElementById(`tag-pill-${tagId}`);
            if (el) {
                el.style.transform = 'scale(0.8)';
                el.style.opacity = '0';
                setTimeout(() => el.remove(), 300);
            }
        } else {
            Swal.fire({ icon: 'error', title: '移除失败', text: data.message });
        }
    });
}

// ================= 图片上传处理 (添加图片到现有组) =================

function handleImageUpload(event) {
    event.preventDefault(); 
    
    const form = event.target;
    const formData = new FormData(form);
    const submitBtn = form.querySelector('button[type="submit"]');
    
    const originalBtnContent = submitBtn.innerHTML;
    submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>上传并校验中...';
    submitBtn.disabled = true;

    // 获取 CSRF Token
    const csrftoken = getCookie('csrftoken');

    fetch(form.action, {
        method: 'POST',
        body: formData,
        headers: { 
            'X-Requested-With': 'XMLHttpRequest',
            'X-CSRFToken': csrftoken // 新增 CSRF 头部
        }
    })
    .then(response => response.json())
    .then(data => {
        submitBtn.innerHTML = originalBtnContent;
        submitBtn.disabled = false;

        if (data.status === 'success') {
            window.location.reload();
        } else if (data.status === 'warning') {
            // 隐藏上传弹窗
            const uploadModalEl = document.getElementById('addImagesModal');
            if (uploadModalEl) {
                const uploadModal = bootstrap.Modal.getInstance(uploadModalEl);
                if (uploadModal) uploadModal.hide();
            }

            // 构建重复图片列表
            let listItems = '';
            data.duplicates.forEach(dup => {
                listItems += `
                    <div class="duplicate-item">
                        <img src="${dup.existing_url || ''}" class="duplicate-alert-img">
                        <div class="duplicate-text-content">
                            <div class="duplicate-filename" title="${dup.name}">${dup.name}</div>
                            <div class="duplicate-source">
                                已存在于：<strong>《${dup.existing_group_title}》</strong>
                            </div>
                            <div class="duplicate-badge"><i class="bi bi-shield-fill-x me-1"></i>已拦截重复上传</div>
                        </div>
                    </div>
                `;
            });

            const duplicateHtml = `
                <div class="text-start mb-2 text-muted small">以下图片因重复而被系统自动拦截：</div>
                <div class="duplicate-scroll-container">
                    ${listItems}
                </div>
                <div class="text-end text-muted small mt-2">
                    成功上传: <span class="text-success fw-bold">${data.uploaded_count}</span> 张 
                    / 拦截: <span class="text-danger fw-bold">${data.duplicates.length}</span> 张
                </div>
            `;

            Swal.fire({
                title: `<span class="text-danger fw-bold"><i class="bi bi-exclamation-triangle-fill me-2"></i>重复拦截报告</span>`,
                html: duplicateHtml,
                icon: null,
                confirmButtonText: '知道了',
                confirmButtonColor: '#2c3e50',
                width: '600px',
                background: '#fff',
                customClass: { popup: 'rounded-4 shadow-lg border-0' }
            }).then(() => {
                if (data.uploaded_count > 0) {
                    window.location.reload();
                }
            });
        } else {
            Swal.fire({ icon: 'error', title: '上传失败', text: '请重试' });
        }
    })
    .catch(error => {
        console.error('Error:', error);
        submitBtn.innerHTML = originalBtnContent;
        submitBtn.disabled = false;
        Swal.fire({ icon: 'error', title: '网络错误', text: '无法连接到服务器或响应格式错误' });
    });
}

// ================= 详情页拖拽上传逻辑 =================

// 独立存储详情页模态框中的文件
let modalGenFiles = [];
let modalRefFiles = [];

document.addEventListener('DOMContentLoaded', function() {
    // 初始化两个模态框的拖拽
    setupDetailDragDrop('zone-modal-gen', 'input-modal-gen', 'preview-modal-gen', 'gen');
    setupDetailDragDrop('zone-modal-ref', 'input-modal-ref', 'preview-modal-ref', 'ref');
});

function setupDetailDragDrop(zoneId, inputId, previewId, type) {
    const zone = document.getElementById(zoneId);
    if (!zone) return; // 详情页可能不存在某些元素，安全退出
    
    const input = document.getElementById(inputId);
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
        handleModalFiles(dt.files, type, input, previewContainer);
    }, false);

    input.addEventListener('change', (e) => {
        if (input.files.length > 0) {
            handleModalFiles(input.files, type, input, previewContainer);
        }
    });
}

function preventDefaults(e) {
    e.preventDefault(); e.stopPropagation();
}

function handleModalFiles(newFiles, type, input, previewContainer) {
    const fileArray = (type === 'gen') ? modalGenFiles : modalRefFiles;
    
    Array.from(newFiles).forEach(file => {
        // 简单查重：检查文件名和大小
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
    div.innerHTML = '<div class="spinner-border text-secondary spinner-border-sm"></div>';
    
    const delBtn = document.createElement('div');
    delBtn.className = 'btn-remove-preview-modal';
    delBtn.innerHTML = '<i class="bi bi-x-lg"></i>';
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
    div.appendChild(delBtn);
    container.appendChild(div);

    // 生成缩略图
    createModalThumbnail(file).then(url => {
        const spinner = div.querySelector('.spinner-border');
        if(spinner) spinner.remove();
        
        if (url) {
            const img = document.createElement('img');
            img.src = url;
            div.insertBefore(img, delBtn);
        } else {
            div.innerHTML = '<div class="text-center pt-4 text-danger small">无法预览</div>';
            div.appendChild(delBtn);
        }
    });
}

// 简易缩略图生成 (复用逻辑)
function createModalThumbnail(file) {
    return new Promise((resolve) => {
        if (!file.type.startsWith('image/')) { resolve(null); return; }
        const reader = new FileReader();
        reader.onload = (e) => {
            const img = new Image();
            img.onload = () => {
                const canvas = document.createElement('canvas');
                const ctx = canvas.getContext('2d');
                const maxSize = 200; // 模态框预览图不需要太大
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

// ================= 13. 导航栏滚动透明特效 (JS部分) =================

document.addEventListener('DOMContentLoaded', function() {
    // 仅在详情页运行
    if (!document.body.classList.contains('detail-page')) return;

    const navbar = document.querySelector('.navbar-glass');
    const scrollLeft = document.querySelector('.detail-scroll-left');
    const scrollRight = document.querySelector('.detail-scroll-right');
    
    if (navbar && (scrollLeft || scrollRight)) {
        
        function updateNavbar() {
            // 获取左右两侧的滚动距离
            const scrollTopLeft = scrollLeft ? scrollLeft.scrollTop : 0;
            const scrollTopRight = scrollRight ? scrollRight.scrollTop : 0;
            
            // 只要有一侧滚动超过 10px，就取消透明（变为磨砂）
            if (scrollTopLeft > 10 || scrollTopRight > 10) {
                navbar.classList.remove('navbar-transparent');
            } else {
                // 回到顶部，变透明
                navbar.classList.add('navbar-transparent');
            }
        }

        // 初始化执行
        updateNavbar();

        // 监听滚动
        if(scrollLeft) scrollLeft.addEventListener('scroll', updateNavbar);
        if(scrollRight) scrollRight.addEventListener('scroll', updateNavbar);
    }
});

// ================= 版本关联管理 =================

// 1. 解除关联
function unlinkSibling(event, siblingId) {
    event.preventDefault(); 
    event.stopPropagation();
    
    Swal.fire({
        title: '解除关联?',
        text: "该版本将独立成为一个新的作品组，不再显示在当前列表。",
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: '确定解除',
        cancelButtonText: '取消',
        confirmButtonColor: '#ffc107'
    }).then((result) => {
        if (result.isConfirmed) {
            const csrftoken = getCookie('csrftoken');
            fetch(`/api/unlink-group/${siblingId}/`, {
                method: 'POST',
                headers: { 'X-CSRFToken': csrftoken }
            })
            .then(res => res.json())
            .then(data => {
                if (data.status === 'success') {
                    Swal.fire('已解除', '', 'success').then(() => location.reload());
                } else {
                    Swal.fire('失败', data.message, 'error');
                }
            });
        }
    });
}

// 2. 打开关联模态框
let linkModal;
function openLinkModal() {
    if (!linkModal) {
        linkModal = new bootstrap.Modal(document.getElementById('linkVersionModal'));
    }
    document.getElementById('linkSearchInput').value = '';
    document.getElementById('linkSearchResults').innerHTML = '<div class="text-center text-muted py-3 small">请输入关键词搜索</div>';
    linkModal.show();
}

// 3. 搜索防抖
let searchTimer;
function debounceSearchLink() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
        const query = document.getElementById('linkSearchInput').value.trim();
        if (query) performLinkSearch(query);
    }, 500);
}

// 4. 执行搜索
function performLinkSearch(query) {
    const container = document.getElementById('linkSearchResults');
    container.innerHTML = '<div class="text-center py-3"><div class="spinner-border spinner-border-sm text-primary"></div></div>';
    
    // 复用 group_list_api 进行搜索
    fetch(`/api/groups/?q=${encodeURIComponent(query)}`)
        .then(res => res.json())
        .then(data => {
            container.innerHTML = '';
            if (!data.results || data.results.length === 0) {
                container.innerHTML = '<div class="text-center text-muted py-3 small">未找到相关内容</div>';
                return;
            }
            
            // 当前页面的 ID，用于排除自己
            // 假设 URL 是 /detail/123/，简单解析一下或从 DOM 获取
            // 这里简单处理：不做前端排除，由后端处理或用户自己看
            
            data.results.forEach(item => {
                const html = `
                    <div class="search-result-item d-flex align-items-center p-2 rounded border-bottom" onclick="confirmLinkGroup(${item.id}, '${item.title.replace(/'/g, "\\'")}')">
                        <div class="rounded overflow-hidden bg-light me-3" style="width: 40px; height: 40px; flex-shrink: 0;">
                            ${item.cover_url ? `<img src="${item.cover_url}" class="w-100 h-100 object-fit-cover">` : ''}
                        </div>
                        <div class="flex-grow-1 overflow-hidden">
                            <div class="fw-bold text-truncate" style="font-size: 0.85rem;">${item.title}</div>
                            <div class="text-muted text-truncate small" style="font-size: 0.75rem;">${item.prompt_text}</div>
                        </div>
                        <i class="bi bi-plus-lg text-primary ms-2"></i>
                    </div>
                `;
                container.insertAdjacentHTML('beforeend', html);
            });
        });
}

// 5. 确认关联
function confirmLinkGroup(targetId, targetTitle) {
    // 获取当前页面 Group ID (从URL或DOM中获取，这里假设 detail.html 中有一个全局变量或从URL解析)
    // 更稳妥的方式是在 HTML 中埋入 currentGroupId
    // 这里我们解析 URL: /detail/123/
    const pathParts = window.location.pathname.split('/');
    const currentPk = pathParts[pathParts.length - 2] || pathParts[pathParts.length - 1]; // 简单容错

    if (currentPk == targetId) {
        Swal.fire('提示', '不能关联自己', 'warning');
        return;
    }

    Swal.fire({
        title: '确认关联?',
        text: `将 "${targetTitle}" 作为当前作品的一个版本?`,
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: '确认关联'
    }).then((result) => {
        if (result.isConfirmed) {
            const csrftoken = getCookie('csrftoken');
            fetch(`/api/link-group/${currentPk}/`, {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrftoken 
                },
                body: JSON.stringify({ target_id: targetId })
            })
            .then(res => res.json())
            .then(data => {
                if (data.status === 'success') {
                    Swal.fire('成功', '版本关联成功', 'success').then(() => location.reload());
                } else {
                    Swal.fire('失败', data.message, 'error');
                }
            });
        }
    });
}