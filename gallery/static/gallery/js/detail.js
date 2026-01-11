/**
 * detail.js - 终极修复完整版 (V2)
 * 修复：版本关联搜索列表缩略图丢失问题
 * 包含：图片重叠修复、Masonry 布局塌陷修复、AJAX 上传、拖拽上传
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
    
    // 2. 初始化 Masonry 布局
    const grid = document.querySelector('#detail-masonry-grid');
    if (grid && typeof Masonry !== 'undefined') {
        // 初始化
        window.msnry = new Masonry(grid, {
            itemSelector: '.grid-item',
            percentPosition: true
        });

        // 初始加载也使用 imagesLoaded 防止刷新时重叠
        if (typeof imagesLoaded !== 'undefined') {
            imagesLoaded(grid).on('progress', function() {
                window.msnry.layout();
            });
        }
    }

    // 3. 键盘事件监听
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

    // 5. 初始化内嵌拖拽区
    setupInlineDragDrop('inline-trigger-gen', 'addImagesModal', 'gen');
    setupInlineDragDrop('inline-trigger-ref', 'addReferenceModal', 'ref');

    // 6. 初始化模态框内的拖拽逻辑
    setupDetailDragDrop('zone-modal-gen', 'input-modal-gen', 'preview-modal-gen', 'gen');
    setupDetailDragDrop('zone-modal-ref', 'input-modal-ref', 'preview-modal-ref', 'ref');
});

// ================= 图片模态框逻辑 =================

function showModal(id) {
    if (window.galleryImages) {
        const index = window.galleryImages.findIndex(img => img.id === id);
        if (index !== -1) {
            currentIndex = index;
            updateModalImage();
            imageModal.show();
        } else {
            console.error("Image ID not found:", id);
        }
    }
}

function changeImage(direction) {
    currentIndex += direction;
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

// 模态框点赞
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

// 列表点赞
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

// 删除确认
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
            Swal.fire({icon: 'success', title: '保存成功', toast: true, position: 'top-end', showConfirmButton: false, timer: 1500});
        } else {
            Swal.fire({ icon: 'error', title: '保存失败', text: res.message });
        }
    })
    .catch(err => { console.error(err); Swal.fire({ icon: 'error', title: '错误', text: '网络错误' }); });
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
    copyToClipboard(textElement.innerText); 
    const originalHTML = btnElement.innerHTML;
    const isPrimary = btnElement.classList.contains('btn-outline-primary');
    const isDanger = btnElement.classList.contains('btn-outline-danger');
    let originalClass = isPrimary ? 'btn-outline-primary' : (isDanger ? 'btn-outline-danger' : 'btn-outline-success');
    btnElement.innerHTML = '<i class="bi bi-check-lg me-1"></i>已复制';
    btnElement.classList.remove(originalClass); btnElement.classList.add('btn-success', 'text-white');
    setTimeout(() => {
        btnElement.innerHTML = originalHTML;
        btnElement.classList.remove('btn-success', 'text-white'); btnElement.classList.add(originalClass);
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
            const newTagHtml = `
                <span class="tag-interactive" id="tag-pill-${data.tag_id}">
                    <a href="/?q=${data.tag_name}">${data.tag_name}</a>
                    <span class="tag-remove-btn" onclick="removeTag(${groupPk}, ${data.tag_id}, '${data.tag_name}')" title="移除"><i class="bi bi-x-circle-fill"></i></span>
                </span>`;
            document.getElementById('btnAddTag').parentNode.insertAdjacentHTML('beforebegin', newTagHtml);
            input.value = ''; input.focus();
        } else {
            Swal.fire({ icon: 'error', title: '添加失败', text: data.message });
        }
    });
}

function removeTag(groupPk, tagId, tagName) {
    Swal.fire({
        title: '移除标签?', text: `确定要移除 "${tagName}" 吗？`, icon: 'warning',
        showCancelButton: true, confirmButtonColor: '#ff4757', confirmButtonText: '移除', cancelButtonText: '取消'
    }).then((result) => {
        if (result.isConfirmed) {
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
                    if (el) { el.style.transform = 'scale(0.8)'; el.style.opacity = '0'; setTimeout(() => el.remove(), 300); }
                } else { Swal.fire({ icon: 'error', title: '移除失败', text: data.message }); }
            });
        }
    });
}

// ================= 【核心修复】上传处理 =================

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
            // 1. 关闭模态框
            const modalId = (data.type === 'ref') ? 'addReferenceModal' : 'addImagesModal';
            const modalEl = document.getElementById(modalId);
            if (modalEl) bootstrap.Modal.getInstance(modalEl).hide();

            // 2. 处理生成图
            if (data.type === 'gen') {
                if (data.new_images_data && window.galleryImages) {
                    // ID 正序的数据倒序插入，确保最新图在最前
                    data.new_images_data.forEach(img => window.galleryImages.unshift(img));
                }

                if (data.new_images_html && data.new_images_html.length > 0) {
                    const grid = document.getElementById('detail-masonry-grid');
                    const emptyPlaceholder = grid.querySelector('.alert.alert-light');
                    if (emptyPlaceholder) emptyPlaceholder.parentNode.remove();

                    // A. 准备 DOM 元素
                    const tempDiv = document.createElement('div');
                    const newItems = [];
                    data.new_images_html.forEach(html => {
                        tempDiv.innerHTML = html;
                        const node = tempDiv.firstElementChild;
                        
                        // 【核心修复1】强制开启 eager 加载，让浏览器立刻请求图片
                        const img = node.querySelector('img');
                        if (img) img.setAttribute('loading', 'eager');
                        
                        grid.prepend(node); // 先插入到最前面
                        newItems.push(node);
                    });

                    // B. Masonry 重排逻辑
                    if (window.msnry) {
                        // 1. 告知 Masonry 有新元素
                        window.msnry.prepended(newItems);
                        
                        // 2. 定义重排函数
                        const onLayout = () => { window.msnry.layout(); };

                        // 3. 【核心修复2】使用 imagesLoaded 监听图片加载进度
                        if (typeof imagesLoaded !== 'undefined') {
                            imagesLoaded(newItems).on('progress', onLayout);
                        }

                        // 4. 【核心修复3】使用 ResizeObserver 监听卡片尺寸变化
                        // 这是防止塌陷的终极手段，只要图片撑开卡片，就立即重排
                        const ro = new ResizeObserver(entries => {
                            onLayout();
                        });
                        newItems.forEach(item => {
                            ro.observe(item);
                            // 监听内部图片本身
                            const img = item.querySelector('img');
                            if(img) ro.observe(img);
                        });
                        
                        // 5. 保底：立即排一次，延迟排几次
                        onLayout();
                        setTimeout(onLayout, 300);
                        setTimeout(onLayout, 1000);
                    }
                    
                    // 清空预览
                    modalGenFiles = [];
                    document.getElementById('preview-modal-gen').innerHTML = '';
                }
            } 
            // 3. 处理参考图
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

            // 4. 显示结果
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
                Swal.fire({ icon: 'success', title: `已添加 ${data.uploaded_count} 张图片`, toast: true, position: 'top-end', showConfirmButton: false, timer: 2000 });
            }
            form.reset();
        } else {
            Swal.fire({ icon: 'error', title: '操作失败', text: 'Server error' });
        }
    })
    .catch(error => {
        submitBtn.innerHTML = originalBtnContent;
        submitBtn.disabled = false;
        Swal.fire({ icon: 'error', title: '上传错误', text: error.message });
    });
}

// ================= 拖拽上传辅助函数 =================

function setupInlineDragDrop(triggerId, modalId, type) {
    const trigger = document.getElementById(triggerId); if (!trigger) return;
    let dragCounter = 0;

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

// ================= 导航栏滚动透明特效 =================
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

// ================= 版本关联管理 =================
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
    document.getElementById('linkSearchResults').innerHTML='<div class="text-center text-muted p-3">请输入关键词</div>'; 
    linkModal.show(); 
}

let st; 
function debounceSearchLink() { 
    clearTimeout(st); st=setTimeout(()=>{performLinkSearch(document.getElementById('linkSearchInput').value.trim())},500); 
}

// 【关键修复】恢复了搜索结果列表中的缩略图显示代码
function performLinkSearch(q) {
    if(!q)return;
    fetch(`/api/groups/?q=${encodeURIComponent(q)}`).then(r=>r.json()).then(d=>{
        const c = document.getElementById('linkSearchResults'); c.innerHTML='';
        if(!d.results.length) { c.innerHTML='<div class="text-center text-muted">无结果</div>'; return; }
        
        // 此处恢复了完整的 HTML 结构，包含缩略图 div
        d.results.forEach(i => {
            const html = `
                <div class="d-flex align-items-center p-2 border-bottom" onclick="confirmLinkGroup(${i.id},'${i.title.replace(/'/g, "\\'")}')" style="cursor:pointer">
                    <div class="rounded overflow-hidden bg-light me-3" style="width: 40px; height: 40px; flex-shrink: 0;">
                        ${i.cover_url ? `<img src="${i.cover_url}" class="w-100 h-100 object-fit-cover">` : ''}
                    </div>
                    <div class="flex-grow-1 overflow-hidden">
                        <div class="fw-bold text-truncate" style="font-size: 0.85rem;">${i.title}</div>
                        <div class="text-muted text-truncate small" style="font-size: 0.75rem;">${i.prompt_text.substring(0,30)}...</div>
                    </div>
                    <i class="bi bi-plus-lg text-primary ms-2"></i>
                </div>`;
            c.insertAdjacentHTML('beforeend', html);
        });
    });
}

function confirmLinkGroup(tid, ttitle) {
    const parts=location.pathname.split('/'); const cid=parts[parts.length-2]||parts[parts.length-1];
    if(cid==tid) { Swal.fire('不能关联自己'); return; }
    Swal.fire({title:`关联 "${ttitle}"?`,showCancelButton:true}).then(r=>{
        if(r.isConfirmed) fetch(`/api/link-group/${cid}/`,{method:'POST',body:JSON.stringify({target_id:tid}),headers:{'Content-Type':'application/json','X-CSRFToken':getCookie('csrftoken')}}).then(res=>res.json()).then(d=>{if(d.status==='success')location.reload();});
    });
}