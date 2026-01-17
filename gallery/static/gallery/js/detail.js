/**
 * detail.js - 终极修复完整版 (V7)
 * 包含：多选关联、AJAX 上传(无刷新)、Masonry 布局兼容、视频/图片分栏显示、图片防重叠
 */

let currentIndex = 0;
let imageModal = null; 
// 独立存储详情页模态框中的文件
let modalGenFiles = [];
let modalRefFiles = [];

// === 多选关联状态 ===
let selectedLinkIds = new Set();

// === 辅助函数：精准获取当前作品 ID ===
function getCurrentGroupId() {
    // 【修改】正则表达式改为同时支持 /detail/ 和 /image/ 路径
    const match = location.pathname.match(/\/(?:detail|image)\/(\d+)/);
    return match ? parseInt(match[1]) : null;
}

// === 新增：视频布局自适应函数 ===
function adjustVideoLayout(video) {
    if (video.videoWidth > 0 && video.videoHeight > 0) {
        // 1. 计算视频实际宽高比
        const ratioPercent = (video.videoHeight / video.videoWidth) * 100;
        const isVertical = video.videoHeight > video.videoWidth;
        
        const card = video.closest('.grid-item');
        const ratioContainer = video.closest('.ratio'); // 获取视频外层的容器

        // 2. 调整容器比例，消除黑边
        if (ratioContainer) {
            // 将容器的比例设置为视频的真实比例
            ratioContainer.style.setProperty('--bs-aspect-ratio', `${ratioPercent}%`);
        }

        // 3. 调整卡片宽度 (横屏全宽，竖屏窄卡片)
        if (card) {
            if (isVertical) {
                // 竖屏：窄卡片 (1/3 或 1/4 宽)
                card.classList.remove('video-wide-item', 'col-12');
                card.classList.add('col-6', 'col-md-4', 'col-lg-3');
            } else {
                // 横屏：全宽 (100% 宽)
                card.classList.add('video-wide-item', 'col-12');
                card.classList.remove('col-6', 'col-md-4', 'col-lg-3');
            }
        }
        
        // 4. 通知 Masonry 重新布局 (防止卡片重叠)
        if (window.msnryImages) {
            window.msnryImages.layout();
        }
    }
}

// === 初始化逻辑 ===
document.addEventListener('DOMContentLoaded', function() {
    // 1. 读取相册数据
    const dataElement = document.getElementById('gallery-data');
    if (dataElement) {
        window.galleryImages = JSON.parse(dataElement.textContent);
    }

    // 2. 初始化大图模态框
    const modalEl = document.getElementById('imageModal');
    if (modalEl) {
        imageModal = new bootstrap.Modal(modalEl);
        
        // 【新增】监听模态框关闭事件，关闭时自动暂停视频
        modalEl.addEventListener('hidden.bs.modal', function () {
            const vid = document.getElementById('previewVideo');
            if (vid) vid.pause();
        });
    }
    
    // 3. 初始化 Masonry (针对图片栏)
    // 注意：HTML中ID已改为 detail-masonry-grid-images
    const imgGrid = document.querySelector('#detail-masonry-grid-images');
    if (imgGrid && typeof Masonry !== 'undefined') {
        window.msnryImages = new Masonry(imgGrid, {
            itemSelector: '.grid-item', // 确保 HTML item 有此类名
            percentPosition: true
        });

        if (typeof imagesLoaded !== 'undefined') {
            imagesLoaded(imgGrid).on('progress', function() {
                window.msnryImages.layout();
            });
        }
    }

    //  视频布局自动调整 (针对页面加载时已存在的视频)
    const videos = document.querySelectorAll('#detail-masonry-grid-videos video');
    videos.forEach(vid => {
        if (vid.readyState >= 1) {
            adjustVideoLayout(vid);
        } else {
            vid.addEventListener('loadedmetadata', () => adjustVideoLayout(vid));
        }
    });

    // 4. 键盘事件
    document.addEventListener('keydown', function(event) {
        if (modalEl && modalEl.classList.contains('show')) {
            if (event.key === 'ArrowLeft') changeImage(-1);
            if (event.key === 'ArrowRight') changeImage(1);
            if (event.key === 'Escape') imageModal.hide();
        }
    });

    // 5. 点击外部关闭标签输入
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

    // 6. 初始化拖拽上传
    setupInlineDragDrop('inline-trigger-gen', 'addImagesModal', 'gen');
    setupInlineDragDrop('inline-trigger-ref', 'addReferenceModal', 'ref');
    setupDetailDragDrop('zone-modal-gen', 'input-modal-gen', 'preview-modal-gen', 'gen');
    setupDetailDragDrop('zone-modal-ref', 'input-modal-ref', 'preview-modal-ref', 'ref');

    // 8. 【新增】进入详情页时，如果有 source_img_id，则直接定位到该图片
    const urlParams = new URLSearchParams(window.location.search);
    const sourceId = urlParams.get('source_img_id');
    
    if (sourceId) {
        // 尝试找到目标元素的锚点 (ID 为 img-anchor-数字)
        const targetEl = document.getElementById(`img-anchor-${sourceId}`);
        if (targetEl) {
            // 使用 setTimeout 确保页面DOM已渲染
            setTimeout(() => {
                // 【核心】behavior: 'auto' 确保是瞬间跳转 (无滚动动画)
                // block: 'center' 确保目标位于屏幕中间
                targetEl.scrollIntoView({ behavior: 'auto', block: 'center' });
                
                // 【可选】添加高亮闪烁效果，方便用户在杂乱的图中一眼看到 (利用 style.css 已有的动画类)
                const card = targetEl.querySelector('.detail-img-card');
                if (card) {
                    card.classList.add('highlight-pulse');
                    setTimeout(() => card.classList.remove('highlight-pulse'), 2000);
                }
            }, 100); 
        }
    }

});

// ================= 图片模态框逻辑 (大图预览) =================

function openModal(el, index) {
    
    
    // 兼容：如果传入的是 DOM 元素，尝试获取 ID
    // 如果传入的是 index (旧逻辑)，则直接使用
    if (typeof el === 'object') {
        // 这里只是为了阻止视频点击，实际打开逻辑复用 showModal 或直接往下走
        // 假设 showModal(id) 是主入口
    }
    
    // 如果直接传了 index
    if (typeof index === 'number') {
        currentIndex = index;
        updateModalImage();
        imageModal.show();
    }
}

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
    if (!window.galleryImages) return;
    currentIndex += direction;
    if (currentIndex >= galleryImages.length) { currentIndex = 0; } 
    else if (currentIndex < 0) { currentIndex = galleryImages.length - 1; }
    updateModalImage();
}

function updateModalImage() {
    const imgElement = document.getElementById('previewImage');
    const vidElement = document.getElementById('previewVideo'); // 必须能在 HTML 中找到这个 ID
    const downloadBtn = document.getElementById('modalDownloadBtn');
    const deleteForm = document.getElementById('modalDeleteForm');
    const counterElement = document.getElementById('imageCounter');
    const likeBtn = document.getElementById('modalLikeBtn');

    if (!galleryImages || galleryImages.length === 0) return;

    const currentImgData = galleryImages[currentIndex];

    // === 核心修改：区分视频和图片 ===
    if (currentImgData.isVideo) {
        // 1. 如果是视频
        if (imgElement) {
            imgElement.style.display = 'none';
            imgElement.src = ""; // 停止加载图片
        }
        
        if (vidElement) {
            vidElement.style.display = 'block';
            vidElement.src = currentImgData.url;
            vidElement.load(); // 【关键】强制重载视频，防止一直转圈
            
            // 尝试自动播放
            const playPromise = vidElement.play();
            if (playPromise !== undefined) {
                playPromise.catch(error => {
                    console.log("自动播放被拦截:", error);
                });
            }
        }
    } else {
        // 2. 如果是图片
        if (vidElement) {
            vidElement.style.display = 'none';
            vidElement.pause();
            vidElement.removeAttribute('src'); // 清除视频源
            vidElement.load(); // 停止视频缓冲
        }
        
        if (imgElement) {
            imgElement.style.display = 'block';
            imgElement.style.opacity = '0.5';
            imgElement.src = currentImgData.url;
            imgElement.onload = function() { imgElement.style.opacity = '1'; };
        }
    }

    // 更新按钮链接和状态
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
            if (window.galleryImages) {
                const imgData = galleryImages.find(img => img.id === pk);
                if (imgData) { imgData.isLiked = data.is_liked; }
            }
        }
    });
}

// === 标题双击编辑功能 ===
function enableTitleEdit(element, pk) {
    const originalText = element.innerText;
    
    element.contentEditable = "true";
    element.focus();
    element.style.outline = "2px solid #0d6efd"; 
    element.style.borderRadius = "4px";
    element.style.padding = "0 5px";

    const range = document.createRange();
    range.selectNodeContents(element);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);

    const save = () => {
        element.onkeydown = null;
        element.onblur = null;
        
        element.contentEditable = "false";
        element.style.outline = "";
        element.style.borderRadius = "";
        element.style.padding = "";

        const newText = element.innerText.trim();

        if (newText === originalText || newText === "") {
            element.innerText = originalText;
            if (newText === "") Swal.fire('提示', '标题不能为空', 'warning');
            return;
        }

        const csrftoken = getCookie('csrftoken');
        fetch(`/update-prompts/${pk}/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrftoken },
            body: JSON.stringify({ title: newText })
        })
        .then(res => res.json())
        .then(data => {
            if (data.status === 'success') {
                Swal.fire({
                    icon: 'success', title: '标题已更新', toast: true, position: 'top-end', showConfirmButton: false, timer: 1500
                });
            } else {
                element.innerText = originalText;
                Swal.fire('更新失败', data.message || '未知错误', 'error');
            }
        })
        .catch(err => {
            element.innerText = originalText;
            console.error(err);
            Swal.fire('错误', '网络请求失败', 'error');
        });
    };

    element.onkeydown = (e) => {
        if (e.key === 'Enter') { e.preventDefault(); element.blur(); }
        else if (e.key === 'Escape') { element.innerText = originalText; element.blur(); }
    };
    element.onblur = save;
}

// === AJAX 删除逻辑 (兼容分栏) ===
function confirmDelete(event) {
    event.preventDefault(); 
    const btn = event.currentTarget;
    const form = btn.closest('form');
    const url = form.action;
    
    const isModal = btn.closest('#imageModal') !== null;
    // 关键判断：当前点击的是否为参考图区域
    const isReference = btn.closest('#reference-grid') !== null;

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
    }).then((result) => { 
        if (result.isConfirmed) {
            const csrftoken = getCookie('csrftoken');
            const originalHtml = btn.innerHTML;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
            btn.disabled = true;

            fetch(url, {
                method: 'POST',
                headers: { 'X-CSRFToken': csrftoken, 'X-Requested-With': 'XMLHttpRequest' }
            })
            .then(response => response.json())
            .then(data => {
                if (data.status === 'success') {
                    // 处理整组删除
                    if (data.type === 'group') {
                        window.location.href = '/'; 
                        return;
                    }
                    
                    const deletedId = parseInt(data.pk);

                    // ===========================================
                    // 1. 处理参考图删除 (您丢失的逻辑补回来了)
                    // ===========================================
                    if (isReference) {
                        const col = btn.closest('.col');
                        if (col) {
                            col.style.transition = 'all 0.3s ease';
                            col.style.transform = 'scale(0)';
                            setTimeout(() => col.remove(), 300);
                        }
                    }
                    // ===========================================
                    // 2. 处理生成图/视频删除 (包含之前的强制修复)
                    // ===========================================
                    else {
                        if (window.galleryImages) {
                            const idx = window.galleryImages.findIndex(img => img.id === deletedId);
                            if (idx !== -1) window.galleryImages.splice(idx, 1);
                        }

                        // 查找元素
                        let gridItem = document.getElementById(`img-anchor-${deletedId}`);
                        if (!gridItem) gridItem = document.getElementById(`card-img-${deletedId}`);

                        if (gridItem) {
                            // 更新数量角标
                            const isVideoContainer = gridItem.closest('#detail-masonry-grid-videos');
                            const badgeId = isVideoContainer ? 'video-count-badge' : 'image-count-badge';
                            const badge = document.getElementById(badgeId);

                            if (badge) {
                                let currentCount = parseInt(badge.innerText) || 0;
                                if (currentCount > 0) {
                                    badge.innerText = currentCount - 1;
                                    badge.classList.add('text-danger'); 
                                    setTimeout(() => badge.classList.remove('text-danger'), 2000);
                                }
                            }

                            // 强制删除逻辑
                            if (!isVideoContainer && window.msnryImages) {
                                try { window.msnryImages.remove(gridItem); } catch (e) {}
                            }
                            
                            // 无论如何强制从 DOM 移除
                            gridItem.remove();

                            if (!isVideoContainer && window.msnryImages) {
                                window.msnryImages.layout();
                            }
                        }

                        if (isModal) {
                            if (!window.galleryImages || window.galleryImages.length === 0) {
                                const modalInstance = bootstrap.Modal.getInstance(document.getElementById('imageModal'));
                                if (modalInstance) modalInstance.hide();
                            } else {
                                if (currentIndex >= window.galleryImages.length) {
                                    currentIndex = window.galleryImages.length - 1;
                                }
                                updateModalImage();
                            }
                        }
                    }

                    Swal.fire({
                        icon: 'success', title: '已删除', toast: true, position: 'top-end', showConfirmButton: false, timer: 1500
                    });

                } else {
                    btn.innerHTML = originalHtml;
                    btn.disabled = false;
                    Swal.fire('删除失败', data.message || '未知错误', 'error');
                }
            })
            .catch(error => {
                console.error(error);
                btn.innerHTML = originalHtml;
                btn.disabled = false;
                Swal.fire('错误', '网络请求失败', 'error');
            });
        }
    });
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

// ================= 【核心修改】上传处理 (支持无刷新 + 分栏) =================

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

            // === 生成内容处理 (图片/视频) ===
            if (data.type === 'gen') {
                
                // 1. 更新数量统计
                let addedImages = 0;
                let addedVideos = 0;
                
                if (data.new_images_data && window.galleryImages) {
                    // 【修复】将新数据正确合并到全局数据源，防止大图预览报错
                    // 使用 reverse() 确保插入顺序正确（因为 unshift 是插入头部）
                    [...data.new_images_data].reverse().forEach(img => {
                        // 确保字段兼容性
                        img.isVideo = img.is_video || img.isVideo || false;
                        window.galleryImages.unshift(img);
                        
                        if (img.isVideo) addedVideos++; else addedImages++;
                    });
                }

                // 2. 更新徽章数字
                const imgBadge = document.getElementById('image-count-badge');
                if (imgBadge && addedImages > 0) {
                    imgBadge.innerText = (parseInt(imgBadge.innerText) || 0) + addedImages;
                    imgBadge.classList.add('text-primary'); setTimeout(() => imgBadge.classList.remove('text-primary'), 2000);
                }
                const vidBadge = document.getElementById('video-count-badge');
                if (vidBadge && addedVideos > 0) {
                    vidBadge.innerText = (parseInt(vidBadge.innerText) || 0) + addedVideos;
                    vidBadge.classList.add('text-primary'); setTimeout(() => vidBadge.classList.remove('text-primary'), 2000);
                }

                // 3. 插入 HTML 卡片
                if (data.new_images_html && data.new_images_html.length > 0) {
                    const imgContainer = document.getElementById('detail-masonry-grid-images');
                    const vidContainer = document.getElementById('detail-masonry-grid-videos');

                    const tempDiv = document.createElement('div');
                    const newImagesNodes = [];
                    
                    data.new_images_html.forEach((html, index) => {
                        const meta = data.new_images_data ? data.new_images_data[index] : null;
                        const isVideo = meta ? (meta.is_video || meta.isVideo) : false;
                        const targetContainer = isVideo ? vidContainer : imgContainer;
                        
                        if (targetContainer) {
                            const emptyPlaceholder = targetContainer.querySelector('.alert');
                            if (emptyPlaceholder) emptyPlaceholder.parentNode.remove();

                            tempDiv.innerHTML = html;
                            const node = tempDiv.firstElementChild;
                            
                            // 【核心修复】只设置 eager 加载，绝对不要隐藏图片！
                            const img = node.querySelector('img');
                            if (img) {
                                img.setAttribute('loading', 'eager');
                                // img.onerror = ... <--- 删除了这行会导致白图的罪魁祸首
                                
                                // 可选：如果加载失败，尝试重新加载一次原图 (增强稳定性)
                                img.onerror = function() {
                                    if (!this.dataset.retried) {
                                        this.dataset.retried = true;
                                        this.src = meta.url; // 尝试加载原图
                                    }
                                };
                            }
                            
                            targetContainer.prepend(node);
                            
                            if (isVideo) {
                                const newVid = node.querySelector('video');
                                if (newVid) newVid.addEventListener('loadedmetadata', () => adjustVideoLayout(newVid));
                            } else {
                                newImagesNodes.push(node);
                            }
                        }
                    });

                    // 4. 刷新 Masonry (仅针对图片栏)
                    if (window.msnryImages && newImagesNodes.length > 0) {
                        window.msnryImages.prepended(newImagesNodes);
                        
                        const onLayout = () => { window.msnryImages.layout(); };
                        if (typeof imagesLoaded !== 'undefined') {
                            imagesLoaded(newImagesNodes).on('progress', onLayout);
                        }
                        
                        // 多重延时布局，防止图片加载慢导致重叠
                        onLayout();
                        setTimeout(onLayout, 300);
                        setTimeout(onLayout, 1000);
                    }
                    
                    modalGenFiles = [];
                    document.getElementById('preview-modal-gen').innerHTML = '';
                }
            } 
            // === 参考图处理 ===
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
                Swal.fire({ icon: 'success', title: data.message || `已添加 ${data.uploaded_count} 个文件`, toast: true, position: 'top-end', showConfirmButton: false, timer: 2000 });
            }
            form.reset();
        } else {
            Swal.fire({ icon: 'error', title: '操作失败', text: 'Server error' });
        }
    })
    .catch(error => {
        submitBtn.innerHTML = originalBtnContent;
        submitBtn.disabled = false;
        console.error(error);
        Swal.fire({ icon: 'error', title: '上传错误', text: error.message });
    });
}

// ================= 拖拽上传辅助函数 (修复 Video 预览) =================

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
    
    // 1. 创建删除按钮 (先不添加到 DOM，等内容添加完再放最后，确保在最上层)
    const delBtn = document.createElement('div');
    delBtn.className = 'btn-remove-preview-modal';
    delBtn.innerHTML = '<i class="bi bi-x-lg"></i>';
    delBtn.style.zIndex = '10'; 
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

    container.appendChild(div);

    // 2. 根据类型添加内容
    if (file.type.startsWith('video/') || file.name.match(/\.(mp4|mov|avi|webm|mkv)$/i)) {
        const video = document.createElement('video');
        video.src = URL.createObjectURL(file);
        video.muted = true;
        video.className = 'w-100 h-100 object-fit-cover';
        video.preload = 'metadata';
        
        const icon = document.createElement('div');
        icon.className = 'position-absolute top-50 start-50 translate-middle text-white';
        icon.innerHTML = '<i class="bi bi-camera-video-fill fs-4" style="text-shadow:0 0 5px rgba(0,0,0,0.5)"></i>';
        icon.style.zIndex = '5';
        
        div.appendChild(icon);
        div.appendChild(video);
        // 【关键修复】视频最后添加按钮，确保按钮在视频图层之上
        div.appendChild(delBtn); 
    } else {
        // 图片逻辑
        // 【关键修复】不要使用 innerHTML +=，这会销毁 delBtn 的事件绑定
        const spinner = document.createElement('div');
        spinner.className = 'spinner-border text-secondary spinner-border-sm position-absolute top-50 start-50';
        div.appendChild(spinner);
        
        // 先把按钮加上去 (确保 loading 时也能删除)
        div.appendChild(delBtn); 

        createModalThumbnail(file).then(url => {
            spinner.remove();
            if (url) {
                const img = document.createElement('img');
                img.src = url;
                img.className = 'w-100 h-100 object-fit-cover';
                // 使用 insertBefore 将图片插在按钮之前，保证按钮依旧在最上面
                div.insertBefore(img, delBtn);
            } else {
                const err = document.createElement('span');
                err.className = 'small text-danger position-absolute top-50 start-50 translate-middle';
                err.innerText = 'Error';
                div.insertBefore(err, delBtn);
            }
        });
    }
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

// ================= 版本关联管理 (支持多选) =================

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
    document.getElementById('linkSearchInput').value = '';
    document.getElementById('linkSearchResults').innerHTML = '<div class="text-center text-muted p-3">请输入关键词</div>'; 
    selectedLinkIds.clear();
    updateLinkSelectionUI();
    linkModal.show(); 
}

function updateLinkSelectionUI() {
    document.getElementById('linkSelectedCount').textContent = selectedLinkIds.size;
    document.querySelectorAll('.search-result-item').forEach(el => {
        const id = parseInt(el.dataset.id);
        const icon = el.querySelector('.select-icon');
        if (selectedLinkIds.has(id)) {
            el.classList.add('bg-primary', 'bg-opacity-10', 'border-primary'); 
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
    if (selectedLinkIds.has(id)) { selectedLinkIds.delete(id); } else { selectedLinkIds.add(id); }
    updateLinkSelectionUI();
}

function clearLinkSelection() {
    selectedLinkIds.clear(); updateLinkSelectionUI();
}

let st; 
function debounceSearchLink() { 
    clearTimeout(st); st=setTimeout(()=>{performLinkSearch(document.getElementById('linkSearchInput').value.trim())},500); 
}

function performLinkSearch(q) {
    if(!q) return;
    fetch(`/api/groups/?q=${encodeURIComponent(q)}`).then(r=>r.json()).then(d=>{
        const c = document.getElementById('linkSearchResults'); c.innerHTML='';
        if(!d.results.length) { c.innerHTML='<div class="text-center text-muted">无结果</div>'; return; }
        
        const currentPk = getCurrentGroupId();
        d.results.forEach(i => {
            if (i.id === currentPk) return; 

            const isSelected = selectedLinkIds.has(i.id);
            const bgClass = isSelected ? 'bg-primary bg-opacity-10 border-primary' : '';
            const iconClass = isSelected ? 'bi-check-circle-fill text-primary' : 'bi-circle text-muted';

            const html = `
                <div class="d-flex align-items-center p-2 border-bottom search-result-item ${bgClass}" 
                     data-id="${i.id}" 
                     onclick="toggleLinkSelection(${i.id})" 
                     style="cursor:pointer; transition: all 0.2s;">
                    <div class="me-3"><i class="bi ${iconClass} select-icon fs-5"></i></div>
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

function submitLinkSelection() {
    if (selectedLinkIds.size === 0) { Swal.fire('提示', '请至少选择一个版本', 'warning'); return; }
    const currentPk = getCurrentGroupId();
    if (!currentPk) { Swal.fire('错误', '无法确定当前作品 ID', 'error'); return; }

    Swal.fire({
        title: `确认关联 ${selectedLinkIds.size} 个版本?`, icon: 'question', showCancelButton: true, confirmButtonText: '确认关联'
    }).then((result) => {
        if (result.isConfirmed) {
            fetch(`/api/link-group/${currentPk}/`, {
                method: 'POST',
                body: JSON.stringify({ target_ids: Array.from(selectedLinkIds) }),
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') }
            })
            .then(res => res.json())
            .then(data => {
                if (data.status === 'success') {
                    Swal.fire('成功', '版本关联成功', 'success').then(() => location.reload());
                } else { Swal.fire('失败', data.message, 'error'); }
            });
        }
    });
}