/**
 * upload.js
 * 处理发布页面的拖拽上传、缩略图生成、预览管理以及【自动查重】和【批量带入】
 */

// 全局文件存储数组 (本地上传的文件)
let genFiles = []; // 生成图
let refFiles = []; // 参考图

document.addEventListener('DOMContentLoaded', () => {
    setupDragDrop('zone-gen', 'upload_images', 'preview-gen', 'gen');
    setupDragDrop('zone-ref', 'upload_references', 'preview-ref', 'ref');

    // 【新增】初始化从后端带入的临时文件 (查重后带入)
    if (window.SERVER_TEMP_FILES && window.SERVER_TEMP_FILES.length > 0) {
        initServerFiles(window.SERVER_TEMP_FILES);
    }
});

/**
 * 初始化服务器端带入的临时文件
 * 为每个文件生成预览，并注入 hidden input 供表单提交
 */
function initServerFiles(files) {
    const container = document.getElementById('preview-gen');
    const form = document.getElementById('uploadForm');
    
    files.forEach(file => {
        // 1. 创建预览 DOM
        const div = document.createElement('div');
        div.className = 'preview-item server-file'; // 标记为服务器文件
        div.dataset.filename = file.name;
        
        // 图片 (直接使用 URL)
        const img = document.createElement('img');
        img.src = file.url;
        img.className = 'loaded';
        div.appendChild(img);
        
        // 删除按钮
        const delBtn = document.createElement('div');
        delBtn.className = 'btn-remove-preview';
        delBtn.innerHTML = '<i class="bi bi-x-lg"></i>';
        delBtn.title = '移除此图';
        delBtn.onclick = (e) => {
            e.stopPropagation();
            // 移除 DOM
            div.remove();
            // 移除对应的 Hidden Input
            const hiddenInput = form.querySelector(`input[name="selected_files"][value="${file.name}"]`);
            if (hiddenInput) hiddenInput.remove();
        };
        div.appendChild(delBtn);
        
        container.appendChild(div);

        // 2. 向表单注入隐藏域，告诉后端这个文件需要保存
        const input = document.createElement('input');
        input.type = 'hidden';
        input.name = 'selected_files';
        input.value = file.name;
        form.appendChild(input);
    });
}

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
        
        // 如果是生成图，触发后端查重
        if (type === 'gen' && filesToCheck.length > 0) {
            checkDuplicates(filesToCheck, previewContainer);
        }
    }
}

/**
 * 自动查重逻辑
 */
function checkDuplicates(files, container) {
    const formData = new FormData();
    files.forEach(f => formData.append('images', f));
    
    let csrftoken = document.querySelector('[name=csrfmiddlewaretoken]')?.value;
    if (!csrftoken && window.getCookie) {
        csrftoken = getCookie('csrftoken');
    }

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
            
            if (data.has_duplicate) {
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
 * 标记重复图片 UI
 */
function markAsDuplicate(filename, container, groupTitle) {
    const items = container.querySelectorAll('.preview-item');
    items.forEach(item => {
        if (item.dataset.filename === filename) {
            item.classList.add('duplicate');
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
 * 添加预览 DOM 元素 (本地文件)
 */
function addPreviewItem(file, type, container) {
    const div = document.createElement('div');
    div.className = 'preview-item';
    div.dataset.filename = file.name; 
    
    div.innerHTML = '<div class="spinner-border text-secondary spinner-border-sm"></div>';
    
    const delBtn = document.createElement('div');
    delBtn.className = 'btn-remove-preview';
    delBtn.innerHTML = '<i class="bi bi-x-lg"></i>';
    delBtn.title = '移除此图';
    delBtn.onclick = (e) => {
        e.stopPropagation();
        removeFileItem(e.target, type, container);
    };
    div.appendChild(delBtn);
    container.appendChild(div);

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
 * 【修改】增加了对 server-file 的过滤，防止索引错位
 */
function removeFileItem(target, type, container) {
    const itemDiv = target.closest('.preview-item');
    if (!itemDiv) return;

    // 如果是服务器端带入的文件，直接移除 DOM，不涉及 genFiles 数组的操作
    // (实际上 server-file 的点击事件在 initServerFiles 中已经独立绑定了，这里是为了兼容性)
    if (itemDiv.classList.contains('server-file')) {
        itemDiv.remove();
        return;
    }

    // 计算索引时，需要过滤掉 server-file，只计算本地文件的索引
    const localItems = Array.from(container.querySelectorAll('.preview-item:not(.server-file)'));
    const index = localItems.indexOf(itemDiv);
    
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