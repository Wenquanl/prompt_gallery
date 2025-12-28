/**
 * upload.js
 * 处理发布页面的拖拽上传、缩略图生成、预览管理以及【自动查重】
 */

// 全局文件存储数组
let genFiles = []; // 生成图
let refFiles = []; // 参考图

document.addEventListener('DOMContentLoaded', () => {
    setupDragDrop('zone-gen', 'upload_images', 'preview-gen', 'gen');
    setupDragDrop('zone-ref', 'upload_references', 'preview-ref', 'ref');
});

/**
 * 初始化拖拽区域
 */
function setupDragDrop(zoneId, inputName, previewId, type) {
    const zone = document.getElementById(zoneId);
    if (!zone) return;
    
    const input = zone.querySelector(`input[name="${inputName}"]`);
    const previewContainer = document.getElementById(previewId);

    // 阻止默认拖拽行为
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        zone.addEventListener(eventName, preventDefaults, false);
        document.body.addEventListener(eventName, preventDefaults, false);
    });

    // 高亮样式
    ['dragenter', 'dragover'].forEach(eventName => {
        zone.addEventListener(eventName, () => zone.classList.add('drag-over'), false);
    });
    ['dragleave', 'drop'].forEach(eventName => {
        zone.addEventListener(eventName, () => zone.classList.remove('drag-over'), false);
    });

    // 处理文件拖放
    zone.addEventListener('drop', (e) => {
        const dt = e.dataTransfer;
        const files = dt.files;
        handleFiles(files, type, input, previewContainer);
    }, false);

    // 处理点击上传
    input.addEventListener('change', (e) => {
        if (input.files.length > 0) {
            handleFiles(input.files, type, input, previewContainer);
        }
    });
}

function preventDefaults(e) {
    e.preventDefault();
    e.stopPropagation();
}

/**
 * 处理文件添加逻辑
 */
function handleFiles(newFiles, type, input, previewContainer) {
    const fileArray = (type === 'gen') ? genFiles : refFiles;
    let hasNew = false;
    // 用于查重的临时数组
    let filesToCheck = [];

    Array.from(newFiles).forEach(file => {
        // 简单去重 (同名且同大小视为同一个文件)
        const exists = fileArray.some(f => f.name === file.name && f.size === file.size);
        if (!exists) {
            fileArray.push(file);
            addPreviewItem(file, type, previewContainer);
            hasNew = true;
            if (type === 'gen') {
                filesToCheck.push(file);
            }
        }
    });

    if (hasNew) {
        updateInputFiles(type, input);
        
        // 【新增】如果是生成图，触发后端查重
        if (type === 'gen' && filesToCheck.length > 0) {
            checkDuplicates(filesToCheck, previewContainer);
        }
    }
}

/**
 * 【核心新增】自动查重逻辑
 */
function checkDuplicates(files, container) {
    // 构造 FormData
    const formData = new FormData();
    files.forEach(f => formData.append('images', f));
    
    // 获取 CSRF Token (依赖 common.js 或自行获取)
    let csrftoken = document.querySelector('[name=csrfmiddlewaretoken]')?.value;
    if (!csrftoken && window.getCookie) {
        csrftoken = getCookie('csrftoken');
    }

    // 显示“正在检测”状态 (可选优化)
    
    fetch('/check-duplicates/', {
        method: 'POST',
        body: formData,
        headers: { 'X-CSRFToken': csrftoken }
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success' && data.results) {
            data.results.forEach(res => {
                if (res.status === 'duplicate') {
                    markAsDuplicate(res.filename, container, res.existing_group_title);
                }
            });
            
            // 如果发现重复，提示用户
            if (data.has_duplicate) {
                // 可以使用 Swal 提示，也可以仅依赖红框
                const toast = Swal.mixin({
                    toast: true, position: 'top-end', showConfirmButton: false, timer: 3000
                });
                toast.fire({ icon: 'warning', title: '发现重复图片，已标红' });
            }
        }
    })
    .catch(err => console.error('Check duplicate failed:', err));
}

/**
 * 【核心新增】标记重复图片 UI
 */
function markAsDuplicate(filename, container, groupTitle) {
    // 遍历 DOM 找到对应的 preview-item
    const items = container.querySelectorAll('.preview-item');
    items.forEach(item => {
        if (item.dataset.filename === filename) {
            item.classList.add('duplicate');
            
            // 添加警告标签
            if (!item.querySelector('.duplicate-badge')) {
                const badge = document.createElement('div');
                badge.className = 'duplicate-badge';
                badge.innerHTML = '<i class="bi bi-exclamation-circle-fill me-1"></i>已存在';
                badge.title = `系统中已存在该图 (位于: ${groupTitle})`;
                item.appendChild(badge);
            }
        }
    });
}

/**
 * 更新 input[type=file] 的值
 */
function updateInputFiles(type, input) {
    const fileArray = (type === 'gen') ? genFiles : refFiles;
    const dataTransfer = new DataTransfer();
    fileArray.forEach(file => {
        dataTransfer.items.add(file);
    });
    input.files = dataTransfer.files;
}

/**
 * 添加预览 DOM 元素
 */
function addPreviewItem(file, type, container) {
    const div = document.createElement('div');
    div.className = 'preview-item';
    // 绑定文件名，方便查重定位
    div.dataset.filename = file.name; 
    
    // 1. Loading 占位
    div.innerHTML = '<div class="spinner-border text-secondary spinner-border-sm"></div>';
    
    // 2. 删除按钮
    const delBtn = document.createElement('div');
    delBtn.className = 'btn-remove-preview';
    delBtn.innerHTML = '<i class="bi bi-x-lg"></i>';
    delBtn.title = '移除此图';
    delBtn.onclick = (e) => {
        e.stopPropagation();
        removeFileItem(e.target, type, container);
    };
    div.appendChild(delBtn);
    
    // 3. 插入 DOM
    container.appendChild(div);

    // 4. 异步生成高清缩略图
    createThumbnail(file).then(thumbnailUrl => {
        const spinner = div.querySelector('.spinner-border');
        if(spinner) spinner.remove();

        if (thumbnailUrl) {
            const img = document.createElement('img');
            img.src = thumbnailUrl;
            img.decoding = 'async';
            setTimeout(() => img.classList.add('loaded'), 50);
            div.insertBefore(img, delBtn);
        } else {
            div.innerHTML = '<i class="bi bi-file-earmark-x text-danger"></i>';
            div.appendChild(delBtn);
        }
    });
}

/**
 * 移除文件
 */
function removeFileItem(target, type, container) {
    const itemDiv = target.closest('.preview-item');
    if (!itemDiv) return;

    const index = Array.from(container.children).indexOf(itemDiv);
    
    if (index !== -1) {
        const fileArray = (type === 'gen') ? genFiles : refFiles;
        fileArray.splice(index, 1);
        itemDiv.remove();
        
        const zoneId = (type === 'gen') ? 'zone-gen' : 'zone-ref';
        const inputName = (type === 'gen') ? 'upload_images' : 'upload_references';
        const zone = document.getElementById(zoneId);
        const input = zone.querySelector(`input[name="${inputName}"]`);
        
        updateInputFiles(type, input);
    }
}

/**
 * 生成高质量缩略图
 */
function createThumbnail(file) {
    return new Promise((resolve) => {
        if (!file.type.startsWith('image/')) {
            resolve(null);
            return;
        }

        const reader = new FileReader();
        reader.onload = (e) => {
            const img = new Image();
            img.onload = () => {
                const canvas = document.createElement('canvas');
                const ctx = canvas.getContext('2d');
                
                const maxSize = 320;
                let width = img.width;
                let height = img.height;
                
                if (width > height) {
                    if (width > maxSize) {
                        height *= maxSize / width;
                        width = maxSize;
                    }
                } else {
                    if (height > maxSize) {
                        width *= maxSize / height;
                        height = maxSize;
                    }
                }
                canvas.width = width;
                canvas.height = height;
                
                ctx.imageSmoothingEnabled = true;
                ctx.imageSmoothingQuality = 'high';
                
                ctx.drawImage(img, 0, 0, width, height);
                resolve(canvas.toDataURL('image/jpeg', 0.9)); 
            };
            img.onerror = () => resolve(null);
            img.src = e.target.result;
        };
        reader.readAsDataURL(file);
    });
}