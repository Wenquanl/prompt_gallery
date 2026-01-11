/**
 * detail.js - 终极修复完整版 (V3)
 * 更新：支持关联新版本时的多选、清除、批量提交
 */

let currentIndex = 0;
let imageModal = null; 
let modalGenFiles = [];
let modalRefFiles = [];

// === 多选关联状态 ===
let selectedLinkIds = new Set();

document.addEventListener('DOMContentLoaded', function() {
    const dataElement = document.getElementById('gallery-data');
    if (dataElement) {
        window.galleryImages = JSON.parse(dataElement.textContent);
    }
});

document.addEventListener('DOMContentLoaded', function() {
    const modalEl = document.getElementById('imageModal');
    if (modalEl) {
        imageModal = new bootstrap.Modal(modalEl);
    }
    
    const grid = document.querySelector('#detail-masonry-grid');
    if (grid && typeof Masonry !== 'undefined') {
        window.msnry = new Masonry(grid, {
            itemSelector: '.grid-item',
            percentPosition: true
        });

        if (typeof imagesLoaded !== 'undefined') {
            imagesLoaded(grid).on('progress', function() {
                window.msnry.layout();
            });
        }
    }

    document.addEventListener('keydown', function(event) {
        if (modalEl && modalEl.classList.contains('show')) {
            if (event.key === 'ArrowLeft') changeImage(-1);
            if (event.key === 'ArrowRight') changeImage(1);
            if (event.key === 'Escape') imageModal.hide();
        }
    });

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

    setupInlineDragDrop('inline-trigger-gen', 'addImagesModal', 'gen');
    setupInlineDragDrop('inline-trigger-ref', 'addReferenceModal', 'ref');
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
            const modalId = (data.type === 'ref') ? 'addReferenceModal' : 'addImagesModal';
            const modalEl = document.getElementById(modalId);
            if (modalEl) bootstrap.Modal.getInstance(modalEl).hide();

            if (data.type === 'gen') {
                if (data.new_images_data && window.galleryImages) {
                    data.new_images_data.forEach(img => window.galleryImages.unshift(img));
                }

                if (data.new_images_html && data.new_images_html.length > 0) {
                    const grid = document.getElementById('detail-masonry-grid');
                    const emptyPlaceholder = grid.querySelector('.alert.alert-light');
                    if (emptyPlaceholder) emptyPlaceholder.parentNode.remove();

                    const tempDiv = document.createElement('div');
                    const newItems = [];
                    data.new_images_html.forEach(html => {
                        tempDiv.innerHTML = html;
                        const node = tempDiv.firstElementChild;
                        const img = node.querySelector('img');
                        if (img) img.setAttribute('loading', 'eager');
                        grid.prepend(node);
                        newItems.push(node);
                    });

                    if (window.msnry) {
                        window.msnry.prepended(newItems);
                        const onLayout = () => { window.msnry.layout(); };
                        if (typeof imagesLoaded !== 'undefined') {
                            imagesLoaded(newItems).on('progress', onLayout);
                        }
                        const ro = new ResizeObserver(entries => { onLayout(); });
                        newItems.forEach(item => {
                            ro.observe(item);
                            const img = item.querySelector('img');
                            if(img) ro.observe(img);
                        });
                        onLayout();
                        setTimeout(onLayout, 300);
                        setTimeout(onLayout, 1000);
                    }
                    modalGenFiles = [];
                    document.getElementById('preview-modal-gen').innerHTML = '';
                }
            } else if (data.type === 'ref') {
                if (data.new_references_html && data.new_references_html.length > 0) {
                    const refGrid = document.getElementById('reference-grid');
                    if (refGrid) {
                        data.new_references_html.forEach(html => refGrid.insertAdjacentHTML('beforeend', html));
                    }
                    modalRefFiles = [];
                    document.getElementById('preview-modal-ref').innerHTML = '';
                }
            }

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
        trigger.addEventListener(eventName, (e) => { e.preventDefault(); e.stopPropagation(); }, false);
    });
    trigger.addEventListener('dragenter', () => { dragCounter++; trigger.classList.add('drag-over'); });
    trigger.addEventListener('dragleave', () => { dragCounter--; if (dragCounter === 0) trigger.classList.remove('drag-over'); });
    trigger.addEventListener('drop', (e) => {
        dragCounter = 0; trigger.classList.remove('drag-over');
        const files = e.dataTransfer.files;
        if (files && files.length > 0) {
            const modalEl = document.getElementById(modalId);
            if (modalEl) {
                bootstrap.Modal.getOrCreateInstance(modalEl).show();
                const input = document.getElementById(`input-modal-${type}`);
                const previewContainer = document.getElementById(`preview-modal-${type}`);
                if (input && previewContainer) handleModalFiles(files, type, input, previewContainer);
            }
        }
    });
}

function setupDetailDragDrop(zoneId, inputId, previewId, type) {
    const zone = document.getElementById(zoneId); if (!zone) return; 
    const input = document.getElementById(inputId);
    const previewContainer = document.getElementById(previewId);
    let dragCounter = 0;
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        zone.addEventListener(eventName, (e) => { e.preventDefault(); e.stopPropagation(); }, false);
    });
    zone.addEventListener('dragenter', () => { dragCounter++; zone.classList.add('drag-over'); });
    zone.addEventListener('dragleave', () => { dragCounter--; if (dragCounter === 0) zone.classList.remove('drag-over'); });
    zone.addEventListener('drop', (e) => {
        dragCounter = 0; zone.classList.remove('drag-over');
        handleModalFiles(e.dataTransfer.files, type, input, previewContainer);
    });
    input.addEventListener('change', () => {
        if (input.files.length > 0) handleModalFiles(input.files, type, input, previewContainer);
    });
}

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

// ================= 版本关联管理 (升级版：支持多选) =================

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
    
    // 初始化清空状态
    document.getElementById('linkSearchInput').value = '';
    document.getElementById('linkSearchResults').innerHTML = '<div class="text-center text-muted p-3">请输入关键词</div>'; 
    selectedLinkIds.clear();
    updateLinkSelectionUI();
    
    linkModal.show(); 
}

// 更新UI状态：选中计数、列表项高亮
function updateLinkSelectionUI() {
    document.getElementById('linkSelectedCount').textContent = selectedLinkIds.size;
    
    // 遍历当前显示的列表项，更新样式
    document.querySelectorAll('.search-result-item').forEach(el => {
        const id = parseInt(el.dataset.id);
        const icon = el.querySelector('.select-icon');
        
        if (selectedLinkIds.has(id)) {
            el.classList.add('bg-primary', 'bg-opacity-10', 'border-primary'); // 高亮背景
            icon.classList.replace('bi-circle', 'bi-check-circle-fill');
            icon.classList.add('text-primary');
        } else {
            el.classList.remove('bg-primary', 'bg-opacity-10', 'border-primary');
            icon.classList.replace('bi-check-circle-fill', 'bi-circle');
            icon.classList.remove('text-primary');
        }
    });
}

function toggleLinkSelection(id) {
    if (selectedLinkIds.has(id)) {
        selectedLinkIds.delete(id);
    } else {
        selectedLinkIds.add(id);
    }
    updateLinkSelectionUI();
}

function clearLinkSelection() {
    selectedLinkIds.clear();
    updateLinkSelectionUI();
}

let st; 
function debounceSearchLink() { 
    clearTimeout(st); st=setTimeout(()=>{performLinkSearch(document.getElementById('linkSearchInput').value.trim())},500); 
}

// 执行搜索并渲染
function performLinkSearch(q) {
    if(!q) return;
    fetch(`/api/groups/?q=${encodeURIComponent(q)}`).then(r=>r.json()).then(d=>{
        const c = document.getElementById('linkSearchResults'); c.innerHTML='';
        if(!d.results.length) { c.innerHTML='<div class="text-center text-muted">无结果</div>'; return; }
        
        const currentPathParts = location.pathname.split('/');
        const currentPk = parseInt(currentPathParts[currentPathParts.length-2] || currentPathParts[currentPathParts.length-1]);

        d.results.forEach(i => {
            // 排除自己
            if (i.id === currentPk) return;

            // 渲染列表项
            const isSelected = selectedLinkIds.has(i.id);
            const bgClass = isSelected ? 'bg-primary bg-opacity-10 border-primary' : '';
            const iconClass = isSelected ? 'bi-check-circle-fill text-primary' : 'bi-circle text-muted';

            const html = `
                <div class="d-flex align-items-center p-2 border-bottom search-result-item ${bgClass}" 
                     data-id="${i.id}" 
                     onclick="toggleLinkSelection(${i.id})" 
                     style="cursor:pointer; transition: all 0.2s;">
                    
                    <div class="me-3">
                        <i class="bi ${iconClass} select-icon fs-5"></i>
                    </div>

                    <div class="rounded overflow-hidden bg-light me-3" style="width: 40px; height: 40px; flex-shrink: 0;">
                        ${i.cover_url ? `<img src="${i.cover_url}" class="w-100 h-100 object-fit-cover">` : ''}
                    </div>
                    
                    <div class="flex-grow-1 overflow-hidden">
                        <div class="fw-bold text-truncate" style="font-size: 0.85rem;">${i.title}</div>
                        <div class="text-muted text-truncate small" style="font-size: 0.75rem;">${i.prompt_text.substring(0,30)}...</div>
                    </div>
                </div>`;
            c.insertAdjacentHTML('beforeend', html);
        });
    });
}

// 批量提交
function submitLinkSelection() {
    if (selectedLinkIds.size === 0) {
        Swal.fire('提示', '请至少选择一个版本', 'warning');
        return;
    }

    const pathParts = window.location.pathname.split('/');
    const currentPk = pathParts[pathParts.length - 2] || pathParts[pathParts.length - 1]; 

    Swal.fire({
        title: `确认关联 ${selectedLinkIds.size} 个版本?`,
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: '确认关联'
    }).then((result) => {
        if (result.isConfirmed) {
            fetch(`/api/link-group/${currentPk}/`, {
                method: 'POST',
                body: JSON.stringify({ target_ids: Array.from(selectedLinkIds) }),
                headers: { 
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCookie('csrftoken') 
                }
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