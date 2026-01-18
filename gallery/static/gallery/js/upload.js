/**
 * upload.js
 * 处理发布页面的拖拽上传、缩略图生成、预览管理以及【自动查重】和【批量带入】
 * [已修复] 视频预览增加透明遮罩，彻底禁用画中画/翻译/下载按钮
 */

// 全局文件存储数组 (本地上传的文件)
let genFiles = []; // 生成图
let refFiles = []; // 参考图

// 专门存储从服务器带入的生成图信息，用于前端去重
let serverGenFiles = []; 

document.addEventListener('DOMContentLoaded', () => {
    // 1. 读取后端传递的临时文件数据
    const tempFilesScript = document.getElementById('server-temp-files');
    if (tempFilesScript) {
        try {
            window.SERVER_TEMP_FILES = JSON.parse(tempFilesScript.textContent);
        } catch (e) {
            console.error('JSON parse error', e);
        }
    }

    // 2. 初始化拖拽区域
    setupDragDrop('zone-gen', 'upload_images', 'preview-gen', 'gen');
    setupDragDrop('zone-ref', 'upload_references', 'preview-ref', 'ref');

    // 3. 初始化从后端带入的临时文件
    if (window.SERVER_TEMP_FILES && window.SERVER_TEMP_FILES.length > 0) {
        initServerFiles(window.SERVER_TEMP_FILES);
    }
});

/**
 * 初始化服务器端带入的临时文件
 */
function initServerFiles(files) {
    const container = document.getElementById('preview-gen');
    const form = document.getElementById('uploadForm');
    
    files.forEach(file => {
        serverGenFiles.push({
            name: file.name,
            size: file.size
        });

        // 1. 创建预览 DOM
        const div = document.createElement('div');
        div.className = 'preview-item server-file position-relative'; // 确保相对定位
        div.dataset.filename = file.name;
        
        // 删除按钮 (先创建，设置高层级)
        const delBtn = document.createElement('div');
        delBtn.className = 'btn-remove-preview';
        delBtn.innerHTML = '<i class="bi bi-x-lg"></i>';
        delBtn.title = '移除此图';
        delBtn.style.zIndex = '30'; // 【关键】确保在遮罩之上
        delBtn.onclick = (e) => {
            e.stopPropagation();
            div.remove();
            serverGenFiles = serverGenFiles.filter(f => f.name !== file.name);
            const hiddenInput = form.querySelector(`input[name="selected_files"][value="${file.name}"]`);
            if (hiddenInput) hiddenInput.remove();
        };

        const isVideo = file.name.match(/\.(mp4|mov|avi|webm|mkv)$/i);

        if (isVideo) {
            // 使用通用的视频构建函数
            setupVideoPreview(div, file.url);
        } else {
            const img = document.createElement('img');
            img.src = file.url;
            img.className = 'loaded w-100 h-100 object-fit-cover';
            div.appendChild(img);
        }

        // 确保删除按钮已添加
        if (!div.contains(delBtn)) div.appendChild(delBtn);
        
        container.appendChild(div);

        // 2. 注入隐藏域
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
        const files = dt.files;
        handleFiles(files, type, input, previewContainer);
    }, false);

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
    let filesToCheck = [];
    let ignoredCount = 0;

    Array.from(newFiles).forEach(file => {
        const existsLocal = fileArray.some(f => f.name === file.name && f.size === file.size);
        let existsServer = false;
        if (type === 'gen') {
            existsServer = serverGenFiles.some(f => f.name === file.name && f.size === file.size);
        }

        if (!existsLocal && !existsServer) {
            fileArray.push(file);
            addPreviewItem(file, type, previewContainer);
            hasNew = true;
            if (type === 'gen') {
                filesToCheck.push(file);
            }
        } else {
            ignoredCount++;
        }
    });

    if (hasNew) {
        updateInputFiles(type, input);
        if (type === 'gen' && filesToCheck.length > 0) {
            checkDuplicates(filesToCheck, previewContainer);
        }
    }

    if (ignoredCount > 0) {
        const toast = Swal.mixin({
            toast: true, position: 'top', showConfirmButton: false, timer: 3000, timerProgressBar: true,
        });
        toast.fire({ icon: 'info', title: `已自动过滤 ${ignoredCount} 张重复图片` });
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
                toast.fire({ icon: 'warning', title: '发现重复内容，已标红' });
            }
        }
    })
    .catch(err => console.error('Check duplicate failed:', err));
}

function markAsDuplicate(filename, container, groupTitle) {
    const items = container.querySelectorAll('.preview-item');
    items.forEach(item => {
        if (item.dataset.filename === filename) {
            item.classList.add('duplicate');
            if (!item.querySelector('.duplicate-badge')) {
                const badge = document.createElement('div');
                badge.className = 'duplicate-badge';
                badge.innerHTML = '<i class="bi bi-exclamation-circle-fill me-1"></i>已存在';
                badge.title = `系统中已存在该内容 (位于: ${groupTitle})`;
                item.appendChild(badge);
            }
        }
    });
}

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
    div.className = 'preview-item position-relative';
    div.dataset.filename = file.name; 
    
    // Loading
    const spinner = document.createElement('div');
    spinner.className = 'spinner-border text-secondary spinner-border-sm position-absolute top-50 start-50 translate-middle';
    div.appendChild(spinner);
    
    // 删除按钮 (提前创建)
    const delBtn = document.createElement('div');
    delBtn.className = 'btn-remove-preview';
    delBtn.innerHTML = '<i class="bi bi-x-lg"></i>';
    delBtn.title = '移除此文件';
    delBtn.style.zIndex = '30'; // 【关键】确保在遮罩之上
    delBtn.onclick = (e) => {
        e.stopPropagation();
        removeFileItem(e.target, type, container);
    };
    div.appendChild(delBtn);
    
    container.appendChild(div);

    // 检查视频
    if (file.type.startsWith('video/') || file.name.match(/\.(mp4|mov|avi|webm|mkv)$/i)) {
        spinner.remove();
        // 使用通用视频构建函数
        setupVideoPreview(div, URL.createObjectURL(file));
        return;
    }

    // 检查图片
    createThumbnail(file).then(thumbnailUrl => {
        spinner.remove();
        if (thumbnailUrl) {
            const img = document.createElement('img');
            img.src = thumbnailUrl;
            img.className = 'loaded w-100 h-100 object-fit-cover';
            // 插入到删除按钮之前，保证按钮在最上面 (其实有 z-index 保护，顺序无所谓了，但习惯上这样)
            div.insertBefore(img, delBtn);
        } else {
            div.innerHTML = '<i class="bi bi-file-earmark-x text-danger fs-3 position-absolute top-50 start-50 translate-middle"></i>';
            div.appendChild(delBtn); // innerHTML 会清空子元素，需重新添加按钮
        }
    });
}

/**
 * 【新增】视频预览构建通用函数 (透明遮罩终极版)
 * 原理：Video底层 + 透明Div中层(挡鼠标) + Icon上层 + Container监听鼠标
 */
function setupVideoPreview(container, url) {
    // 1. 视频层 (z-index: 0, 屏蔽鼠标)
    const video = document.createElement('video');
    video.src = url;
    video.className = 'w-100 h-100 object-fit-cover position-absolute top-0 start-0';
    video.style.zIndex = '0';
    video.style.pointerEvents = 'none'; // 【绝杀】彻底屏蔽浏览器按钮
    video.muted = true;
    video.loop = true;
    video.disablePictureInPicture = true;
    video.setAttribute('controlsList', 'nodownload noremoteplayback noplaybackrate');
    video.setAttribute('playsinline', '');

    // 2. 透明遮罩层 (z-index: 10, 承接鼠标事件，让浏览器以为这里没视频)
    const mask = document.createElement('div');
    mask.className = 'position-absolute top-0 start-0 w-100 h-100';
    mask.style.zIndex = '10';
    mask.style.background = 'transparent';

    // 3. 播放图标 (z-index: 20)
    const icon = document.createElement('div');
    icon.className = 'position-absolute top-50 start-50 translate-middle text-white opacity-75';
    icon.style.zIndex = '20';
    icon.style.pointerEvents = 'none';
    icon.innerHTML = '<i class="bi bi-play-circle-fill fs-4" style="text-shadow: 0 2px 4px rgba(0,0,0,0.5);"></i>';

    // 交互：在容器上监听
    container.addEventListener('mouseenter', () => video.play().catch(()=>{}));
    container.addEventListener('mouseleave', () => { video.pause(); video.currentTime = 0; });

    container.appendChild(video);
    container.appendChild(mask);
    container.appendChild(icon);
    
    // 注意：删除按钮已经在外部创建并添加，z-index 为 30，所以会浮在最上面
}

/**
 * 移除文件
 */
function removeFileItem(target, type, container) {
    const itemDiv = target.closest('.preview-item');
    if (!itemDiv) return;

    if (itemDiv.classList.contains('server-file')) {
        itemDiv.remove();
        return;
    }

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
 * 生成高质量缩略图 (仅图片)
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