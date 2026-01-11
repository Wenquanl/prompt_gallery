/**
 * detail.js
 * 详情页交互：图片切换、提示词编辑、标签管理、点赞、删除、AJAX上传(修复版)、版本关联
 * 依赖: Bootstrap 5, SweetAlert2, galleryImages (全局变量), common.js
 */

let currentIndex = 0;
let imageModal = null; 
// 独立存储详情页模态框中的文件
let modalGenFiles = [];
let modalRefFiles = [];

// 初始化全局数据
document.addEventListener('DOMContentLoaded', function() {
    const dataElement = document.getElementById('gallery-data');
    if (dataElement) {
        window.galleryImages = JSON.parse(dataElement.textContent);
    }
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

    // 5. 初始化内嵌拖拽区 (修复样式响应)
    setupInlineDragDrop('inline-trigger-gen', 'addImagesModal', 'gen');
    setupInlineDragDrop('inline-trigger-ref', 'addReferenceModal', 'ref');

    // 6. 初始化模态框内的拖拽逻辑
    setupDetailDragDrop('zone-modal-gen', 'input-modal-gen', 'preview-modal-gen', 'gen');
    setupDetailDragDrop('zone-modal-ref', 'input-modal-ref', 'preview-modal-ref', 'ref');
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

// ================= 图片上传处理 (AJAX 通用版 - 修复) =================

function handleImageUpload(event) {
    event.preventDefault(); 
    
    const form = event.target;
    const formData = new FormData(form);
    const submitBtn = form.querySelector('button[type="submit"]');
    
    const originalBtnContent = submitBtn.innerHTML;
    submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>上传处理中...';
    submitBtn.disabled = true;

    const csrftoken = getCookie('csrftoken');

    fetch(form.action, {
        method: 'POST',
        body: formData,
        headers: { 
            'X-Requested-With': 'XMLHttpRequest', // 必须：防止后端返回 302 跳转
            'X-CSRFToken': csrftoken 
        }
    })
    .then(response => {
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        return response.json();
    })
    .then(data => {
        submitBtn.innerHTML = originalBtnContent;
        submitBtn.disabled = false;

        if (data.status === 'success' || data.status === 'warning') {
            // 1. 关闭对应模态框
            const modalId = (data.type === 'ref') ? 'addReferenceModal' : 'addImagesModal';
            const modalEl = document.getElementById(modalId);
            if (modalEl) {
                const modalInstance = bootstrap.Modal.getInstance(modalEl);
                if (modalInstance) modalInstance.hide();
            }

            // 2. 动态插入内容
            if (data.type === 'gen') {
                // [生成图]
                if (data.new_images_html && data.new_images_html.length > 0) {
                    const grid = document.getElementById('detail-masonry-grid');
                    const emptyPlaceholder = grid.querySelector('.alert.alert-light');
                    if (emptyPlaceholder) emptyPlaceholder.parentNode.remove();

                    const tempDiv = document.createElement('div');
                    const newItems = [];
                    data.new_images_html.forEach(html => {
                        tempDiv.innerHTML = html;
                        const node = tempDiv.firstElementChild;
                        grid.appendChild(node);
                        newItems.push(node);
                    });

                    if (window.msnry) {
                        window.msnry.appended(newItems);
                        window.msnry.layout();
                    }
                    
                    modalGenFiles = [];
                    document.getElementById('preview-modal-gen').innerHTML = '';
                }
            } else if (data.type === 'ref') {
                // [参考图]
                if (data.new_references_html && data.new_references_html.length > 0) {
                    // 确保 detail.html 中参考图容器有 id="reference-grid"
                    const refGrid = document.getElementById('reference-grid');
                    if (refGrid) {
                        data.new_references_html.forEach(html => {
                            refGrid.insertAdjacentHTML('beforeend', html);
                        });
                    }
                    
                    modalRefFiles = [];
                    document.getElementById('preview-modal-ref').innerHTML = '';
                }
            }

            // 3. 提示结果
            if (data.status === 'warning') {
                let listItems = '';
                if (data.duplicates && data.duplicates.length > 0) {
                    data.duplicates.forEach(dup => {
                        listItems += `
                            <div class="duplicate-item">
                                <img src="${dup.existing_url || ''}" class="duplicate-alert-img">
                                <div class="duplicate-text-content">
                                    <div class="duplicate-filename" title="${dup.name}">${dup.name}</div>
                                    <div class="duplicate-source">
                                        已存在于：<strong>《${dup.existing_group_title}》</strong>
                                    </div>
                                    <div class="duplicate-badge"><i class="bi bi-shield-fill-x me-1"></i>已拦截</div>
                                </div>
                            </div>
                        `;
                    });
                }
                const duplicateHtml = `
                    <div class="text-start mb-2 text-muted small">以下图片因重复而被系统自动拦截：</div>
                    <div class="duplicate-scroll-container">${listItems}</div>
                    <div class="text-end text-muted small mt-2">
                        成功上传: <span class="text-success fw-bold">${data.uploaded_count}</span> 张 
                        / 拦截: <span class="text-danger fw-bold">${data.duplicates ? data.duplicates.length : 0}</span> 张
                    </div>
                `;
                Swal.fire({
                    title: `<span class="text-danger fw-bold"><i class="bi bi-exclamation-triangle-fill me-2"></i>重复拦截报告</span>`,
                    html: duplicateHtml,
                    confirmButtonText: '知道了',
                    confirmButtonColor: '#2c3e50',
                    width: '600px',
                    background: '#fff',
                    customClass: { popup: 'rounded-4 shadow-lg border-0' }
                });
            } else {
                Swal.fire({
                    icon: 'success',
                    title: '添加成功',
                    text: `已添加 ${data.uploaded_count} 张图片`,
                    toast: true, position: 'top-end', showConfirmButton: false, timer: 2000
                });
            }
            form.reset();

        } else {
            Swal.fire({ icon: 'error', title: '操作失败', text: '服务器未返回预期状态' });
        }
    })
    .catch(error => {
        console.error(error);
        submitBtn.innerHTML = originalBtnContent;
        submitBtn.disabled = false;
        Swal.fire({ icon: 'error', title: '上传错误', text: error.message });
    });
}

// ================= 拖拽上传逻辑 (修复样式闪烁) =================

function setupInlineDragDrop(triggerId, modalId, type) {
    const trigger = document.getElementById(triggerId);
    if (!trigger) return;

    let dragCounter = 0; // 引入计数器解决子元素闪烁问题

    trigger.addEventListener('click', () => {
        const modalEl = document.getElementById(modalId);
        if (modalEl) bootstrap.Modal.getOrCreateInstance(modalEl).show();
    });

    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        trigger.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
        }, false);
    });

    trigger.addEventListener('dragenter', () => {
        dragCounter++;
        trigger.classList.add('drag-over');
    });

    trigger.addEventListener('dragleave', () => {
        dragCounter--;
        if (dragCounter === 0) {
            trigger.classList.remove('drag-over');
        }
    });

    trigger.addEventListener('drop', (e) => {
        dragCounter = 0;
        trigger.classList.remove('drag-over');
        
        const files = e.dataTransfer.files;
        if (files && files.length > 0) {
            const modalEl = document.getElementById(modalId);
            if (modalEl) {
                bootstrap.Modal.getOrCreateInstance(modalEl).show();
                const input = document.getElementById(`input-modal-${type}`);
                const previewContainer = document.getElementById(`preview-modal-${type}`);
                if (input && previewContainer) {
                    handleModalFiles(files, type, input, previewContainer);
                }
            }
        }
    });
}

function setupDetailDragDrop(zoneId, inputId, previewId, type) {
    const zone = document.getElementById(zoneId);
    if (!zone) return; 
    
    const input = document.getElementById(inputId);
    const previewContainer = document.getElementById(previewId);
    let dragCounter = 0;

    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        zone.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
        }, false);
    });

    zone.addEventListener('dragenter', () => {
        dragCounter++;
        zone.classList.add('drag-over');
    });
    
    zone.addEventListener('dragleave', () => {
        dragCounter--;
        if (dragCounter === 0) zone.classList.remove('drag-over');
    });

    zone.addEventListener('drop', (e) => {
        dragCounter = 0;
        zone.classList.remove('drag-over');
        handleModalFiles(e.dataTransfer.files, type, input, previewContainer);
    });

    input.addEventListener('change', () => {
        if (input.files.length > 0) {
            handleModalFiles(input.files, type, input, previewContainer);
        }
    });
}

// 辅助函数：文件处理
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

    createModalThumbnail(file).then(url => {
        const spinner = div.querySelector('.spinner-border');
        if (spinner) spinner.remove();
        
        if (url) {
            const img = document.createElement('img');
            img.src = url;
            div.insertBefore(img, delBtn);
        } else {
            div.innerHTML += '<span class="small text-danger">Error</span>';
        }
    });
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

// ================= 导航栏滚动透明特效 (JS部分) =================

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