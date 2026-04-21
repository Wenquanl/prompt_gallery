// 1. 获取后端传来的超级配置对象 (通过 HTML 中的 JSON script 标签)
let AI_CONFIG = {};
try {
    const configEl = document.getElementById('ai-config-data');
    if (configEl) {
        AI_CONFIG = JSON.parse(configEl.textContent);
    }
} catch (e) {
    console.error("加载 AI_CONFIG 失败", e);
}

let currentFiles = []; 
let maxImagesAllowed = 0;
let lastSavedPaths = []; 
let initialTagsForPublish = [];
let initialCharsForPublish = [];
let allAvailableTags = [];
let allAvailableChars = [];
let currentSelectedTags = new Set(); 
let currentSelectedChars = new Set();
let currentSourceGroupId = null;

document.addEventListener('DOMContentLoaded', () => {
    initDynamicUI();
    setupDragAndDrop();

    const urlParams = new URLSearchParams(window.location.search);
    currentSourceGroupId = urlParams.get('template_id') || urlParams.get('group_id') || null;

    // 解析全库标签
    try {
        const tagsEl = document.getElementById('all-tags-data');
        if (tagsEl) allAvailableTags = JSON.parse(tagsEl.textContent);
        
        const charsEl = document.getElementById('all-chars-data');
        if (charsEl) allAvailableChars = JSON.parse(charsEl.textContent);
    } catch(e) { console.log("解析系统标签失败", e); }

    // 绑定人物自定义输入框的回车事件
    const customCharInput = document.getElementById('pub-custom-char');
    if (customCharInput) {
        customCharInput.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                const newChars = this.value.split(/[,，]/); 
                let added = false;
                newChars.forEach(char => {
                    const c = char.trim();
                    if (c && !currentSelectedChars.has(c)) {
                        currentSelectedChars.add(c);
                        if (!allAvailableChars.includes(c)) allAvailableChars.push(c);
                        added = true;
                    }
                });
                if (added) {
                    this.value = '';
                    renderPublishChars(Array.from(currentSelectedChars));
                }
            }
        });
    }
    
    // 绑定自定义标签框的回车事件
    const customTagInput = document.getElementById('pub-custom-tag');
    if (customTagInput) {
        customTagInput.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                const newTags = this.value.split(/[,，]/); 
                let added = false;
                
                newTags.forEach(tag => {
                    const t = tag.trim();
                    if (t && !currentSelectedTags.has(t)) {
                        currentSelectedTags.add(t);
                        if (!allAvailableTags.includes(t)) {
                            allAvailableTags.push(t);
                        }
                        added = true;
                    }
                });
                
                if (added) {
                    this.value = ''; 
                    renderPublishTags(Array.from(currentSelectedTags)); 
                }
            }
        });
    }

    // 接收并处理从详情页带入的预填充数据
    try {
        const initialDataEl = document.getElementById('initial-data');
        const initialDataText = initialDataEl ? initialDataEl.textContent.trim() : "";
        if (initialDataText && initialDataText !== "{}" && initialDataText !== "null") {
            const initialData = JSON.parse(initialDataText);
            if (!currentSourceGroupId && initialData.group_id) currentSourceGroupId = String(initialData.group_id);
            if (!currentSourceGroupId && initialData.id) currentSourceGroupId = String(initialData.id);

            if (initialData.prompt) {
                document.getElementById('ai-prompt').value = initialData.prompt;
            }
            
            if (initialData.tags && initialData.tags.length > 0) {
                initialTagsForPublish = initialData.tags; 
            }
            if (initialData.characters && initialData.characters.length > 0) {
                initialCharsForPublish = initialData.characters; 
            }
            let modelToastMsg = null;
            
            if (initialData.model_info && typeof initialData.model_info === 'string') {
                const dbModelName = initialData.model_info.trim().toLowerCase();
                let targetModelId = null;
                let targetCategoryId = null;

                for (const [key, model] of Object.entries(AI_CONFIG.models)) {
                    if (model.title && model.title.trim().toLowerCase() === dbModelName) {
                        targetModelId = key;
                        targetCategoryId = model.category;
                        break;
                    }
                }

                if (targetModelId) {
                    switchCategory(targetCategoryId);
                    const targetCard = document.getElementById(`card-${targetModelId}`);
                    if (targetCard) targetCard.click();
                    
                    modelToastMsg = {
                        icon: 'success',
                        title: `已为您自动匹配模型：${initialData.model_info}`
                    };
                } else {
                    modelToastMsg = {
                        icon: 'info',
                        title: `模型【${initialData.model_info}】暂不支持云端调用，已选择默认模型。`
                    };
                }
            }

            const fireModelToast = () => {
                if (modelToastMsg) {
                    setTimeout(() => {
                        Swal.fire({
                            toast: true, position: 'top', showConfirmButton: false, timer: 4500,
                            icon: modelToastMsg.icon, title: modelToastMsg.title
                        });
                    }, 600); 
                }
            };

            if (initialData.reference_urls && initialData.reference_urls.length > 0) {
                Swal.fire({
                    title: '正在导入参考图...',
                    allowOutsideClick: false,
                    didOpen: () => Swal.showLoading()
                });

                Promise.all(initialData.reference_urls.map(url => 
                    fetch(url)
                        .then(res => res.blob())
                        .then(blob => {
                            const filename = url.split('/').pop().split('?')[0] || 'reference_image.jpg';
                            return new File([blob], filename, { type: blob.type || 'image/jpeg' });
                        })
                )).then(files => {
                    if (maxImagesAllowed === 1) {
                        currentFiles = [files[0]]; 
                    } else if (maxImagesAllowed > 1) {
                        currentFiles = [...currentFiles, ...files].slice(0, maxImagesAllowed); 
                    }
                    renderPreviews();
                    Swal.close();
                    fireModelToast();
                }).catch(err => {
                    console.error("加载参考图失败:", err);
                    Swal.fire('导入提示', '部分参考图导入失败，请手动上传', 'warning');
                });
            } else {
                fireModelToast();
            }
        }
    } catch(e) {
        console.error("❌ 无预填充数据或解析失败，错误详情:", e);
    }

    const dynamicContainer = document.getElementById('dynamic-params-container');
    
    function handleDynamicInput(e) {
        if (e.target.classList.contains('dynamic-param-input')) {
            const modelChoice = document.getElementById('ai-model-select').value;
            if (modelChoice.toLowerCase().includes('seedream')) {
                const paramId = e.target.getAttribute('data-param-id');
                
                if (paramId === 'max_images' || paramId === 'num_images') {
                    updateSeedreamPrompt(e.target.value);
                } else if (paramId === 'prompt_aspect_ratio') {
                    updateSeedreamAspectRatio(e.target.value);
                }
            }
        }
    }

    dynamicContainer.addEventListener('input', handleDynamicInput);
    dynamicContainer.addEventListener('change', handleDynamicInput);
});

// ...将原先写在 HTML 中的剩余所有 JavaScript 方法全部复制到这里（从 updateSeedreamPrompt 到 extractExistingRefToCanvas 等方法）
// 为了节省篇幅和防止你复制出错，剩余所有自定义 functions 直接无缝追加在此处即可（和原版逻辑完全一致）

function updateSeedreamPrompt(count) {
    const promptInput = document.getElementById('ai-prompt');
    let text = promptInput.value;
    const prefixRegex = /^生成\d+张图片：/;
    if (prefixRegex.test(text)) {
        promptInput.value = text.replace(prefixRegex, `生成${count}张图片：`);
    } else {
        promptInput.value = `生成${count}张图片：` + text;
    }
}

function removeSeedreamPrompt() {
    const promptInput = document.getElementById('ai-prompt');
    const prefixRegex = /^生成\d+张图片：/;
    if (prefixRegex.test(promptInput.value)) {
        promptInput.value = promptInput.value.replace(prefixRegex, '');
    }
}

function updateSeedreamAspectRatio(ratio) {
    const promptInput = document.getElementById('ai-prompt');
    let text = promptInput.value;
    const ratioRegex = /(?:，|\s)*画面比例：\d+:\d+/g;
    text = text.replace(ratioRegex, '').trim();
    if (ratio !== 'none') {
        if (text.length > 0) {
            text += `，画面比例：${ratio}`;
        } else {
            text = `画面比例：${ratio}`;
        }
    }
    promptInput.value = text;
}

function removeSeedreamAspectRatio() {
    const promptInput = document.getElementById('ai-prompt');
    const ratioRegex = /(?:，|\s)*画面比例：\d+:\d+/g;
    promptInput.value = promptInput.value.replace(ratioRegex, '').trim();
}

function initDynamicUI() {
    const tabsContainer = document.getElementById('dynamic-category-tabs');
    const cardsContainer = document.getElementById('dynamic-model-cards');
    
    if (!AI_CONFIG.categories) return;

    AI_CONFIG.categories.forEach((cat, index) => {
        const isActive = index === 0 ? 'active' : '';
        tabsContainer.innerHTML += `
            <li class="nav-item" role="presentation">
                <button class="nav-link ${isActive}" data-bs-toggle="tab" data-bs-target="#tab-${cat.id}" 
                        type="button" onclick="switchCategory('${cat.id}')">${cat.title}</button>
            </li>
        `;
        const showClass = index === 0 ? 'show active' : '';
        let cardsHtml = `<div class="tab-pane fade ${showClass}" id="tab-${cat.id}" role="tabpanel"><div class="row g-2">`;
        for (const [modelId, model] of Object.entries(AI_CONFIG.models)) {
            if (model.category === cat.id) {
                cardsHtml += `
                    <div class="col-6">
                        <div class="model-card" id="card-${modelId}" onclick="selectModel('${modelId}', '${cat.id}', this)">
                            <div class="model-card-title">${model.title} <i class="bi bi-check-circle-fill check-icon" style="display:none;"></i></div>
                            <p class="model-card-desc">${model.desc}</p>
                        </div>
                    </div>
                `;
            }
        }
        cardsHtml += `</div></div>`;
        cardsContainer.innerHTML += cardsHtml;
    });
    switchCategory(AI_CONFIG.categories[0].id);
}

function switchCategory(categoryId) {
    document.getElementById('ai-category-select').value = categoryId;
    const catConfig = AI_CONFIG.categories.find(c => c.id === categoryId);
    maxImagesAllowed = catConfig.img_max;

    const imgBlock = document.getElementById('ai-image-upload-block');
    const fileInput = document.getElementById('file-input-hidden');
    const imgHelp = document.getElementById('ai-img-help');

    if (maxImagesAllowed === 0) {
        imgBlock.style.display = 'none';
    } else {
        imgBlock.style.display = 'block';
        imgHelp.innerHTML = catConfig.img_help;
        if (maxImagesAllowed === 1) fileInput.removeAttribute('multiple');
        else fileInput.setAttribute('multiple', 'multiple');
    }
    
    currentFiles = [];
    renderPreviews();

    const activeTabPane = document.getElementById(`tab-${categoryId}`);
    const firstCard = activeTabPane.querySelector('.model-card');
    if (firstCard) firstCard.click();
}

function selectModel(modelId, categoryId, element) {
    document.querySelectorAll('.model-card').forEach(card => card.classList.remove('active'));
    element.classList.add('active');
    document.getElementById('ai-model-select').value = modelId;
    renderDynamicParams(modelId);
}

function renderDynamicParams(modelId) {
    const container = document.getElementById('dynamic-params-container');
    container.innerHTML = ''; 
    
    const params = AI_CONFIG.models[modelId].params;
    if (!params || params.length === 0) return; 

    let html = `<div class="p-3 bg-light rounded-3 border"><label class="form-label fw-bold text-secondary small mb-3"><i class="bi bi-gear-fill me-1"></i>模型专属参数</label><div class="row g-3">`;

    params.forEach(param => {
        html += `<div class="col-12">`;
        if (param.type === 'select') {
            html += `<label class="form-label small text-muted mb-1">${param.label}</label>
                     <select class="form-select form-select-sm dynamic-param-input shadow-sm" data-param-id="${param.id}">`;
            param.options.forEach(opt => {
                html += `<option value="${opt.value}" ${opt.value === param.default ? 'selected' : ''}>${opt.text}</option>`;
            });
            html += `</select>`;
        } else if (param.type === 'range') {
            const percent = ((param.default - param.min) / (param.max - param.min)) * 100;
            html += `
                <div class="d-flex justify-content-between align-items-center mb-1">
                    <label class="form-label small text-muted mb-0">${param.label}</label>
                    <span class="badge bg-white text-primary border border-primary" id="val-${param.id}">${param.default}</span>
                </div>
                
                <input type="range" class="custom-range-slider dynamic-param-input" 
                       data-param-id="${param.id}" data-param-type="range"
                       min="${param.min}" max="${param.max}" step="${param.step}" value="${param.default}"
                       style="background-size: ${percent}% 100%;"
                       oninput="
                           document.getElementById('val-${param.id}').innerText = this.value;
                           this.style.backgroundSize = ((this.value - this.min) / (this.max - this.min)) * 100 + '% 100%';
                       ">
            `;
        }else if (param.type === 'checkbox') {
            const isChecked = param.default ? 'checked' : '';
            html += `
                <div class="form-check form-switch mt-2">
                    <input class="form-check-input dynamic-param-input" type="checkbox" role="switch" 
                           id="param-${param.id}" data-param-id="${param.id}" data-param-type="checkbox" ${isChecked}>
                    <label class="form-check-label small text-muted fw-bold" for="param-${param.id}">${param.label}</label>
                </div>`;
        }
        html += `</div>`;
    });
    html += `</div></div>`;
    container.innerHTML = html;

    if (modelId.toLowerCase().includes('seedream')) {
        const numInput = container.querySelector('.dynamic-param-input[data-param-id="max_images"], .dynamic-param-input[data-param-id="num_images"]');
        if (numInput) {
            updateSeedreamPrompt(numInput.value);
        }
        const ratioInput = container.querySelector('.dynamic-param-input[data-param-id="prompt_aspect_ratio"]');
        if (ratioInput) {
            updateSeedreamAspectRatio(ratioInput.value);
        }
    } else {
        removeSeedreamPrompt();
        removeSeedreamAspectRatio(); 
    }
}

function setupDragAndDrop() {
    const dropZone = document.getElementById('drop-zone');
    if(!dropZone) return;
    dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.classList.add('dragover'); });
    dropZone.addEventListener('dragleave', (e) => { e.preventDefault(); dropZone.classList.remove('dragover'); });
    dropZone.addEventListener('drop', (e) => { e.preventDefault(); dropZone.classList.remove('dragover'); handleFiles(e.dataTransfer.files); });
}

function renderPublishTags(preSelectedTags) {
    const container = document.getElementById('pub-tags-container');
    container.innerHTML = '';
    preSelectedTags.forEach(t => currentSelectedTags.add(t));
    const combinedTags = Array.from(new Set([...allAvailableTags, ...preSelectedTags]));
    
    if (combinedTags.length === 0) {
        container.innerHTML = '<span class="text-muted small">暂无系统标签，请在下方手动添加</span>';
        return;
    }

    combinedTags.forEach(tag => {
        const badge = document.createElement('span');
        badge.className = 'pub-tag-badge';
        if (currentSelectedTags.has(tag)) {
            badge.classList.add('active');
            badge.innerHTML = `<i class="bi bi-check2 me-1"></i>${tag}`; 
        } else {
            badge.textContent = tag;
        }
        badge.onclick = function() {
            if (currentSelectedTags.has(tag)) {
                currentSelectedTags.delete(tag);
                this.classList.remove('active');
                this.textContent = tag; 
            } else {
                currentSelectedTags.add(tag);
                this.classList.add('active');
                this.innerHTML = `<i class="bi bi-check2 me-1"></i>${tag}`;
            }
        };
        container.appendChild(badge);
    });
}

function renderPublishChars(preSelectedChars) {
    const container = document.getElementById('pub-chars-container');
    container.innerHTML = '';
    preSelectedChars.forEach(c => currentSelectedChars.add(c));
    const combinedChars = Array.from(new Set([...allAvailableChars, ...preSelectedChars]));
    
    if (combinedChars.length === 0) {
        container.innerHTML = '<span class="text-muted small">暂无记录人物，请在下方手动添加</span>';
        return;
    }

    combinedChars.forEach(char => {
        const badge = document.createElement('span');
        badge.className = 'pub-tag-badge'; 
        if (currentSelectedChars.has(char)) {
            badge.className = 'pub-tag-badge active pub-tag-char-active'; 
            badge.innerHTML = `<i class="bi bi-person-check-fill me-1"></i>${char}`;
        } else {
            badge.className = 'pub-tag-badge'; 
            badge.innerHTML = `<i class="bi bi-person me-1"></i>${char}`;
        }
        badge.onclick = function() {
            if (currentSelectedChars.has(char)) {
                currentSelectedChars.delete(char);
                this.className = 'pub-tag-badge';
                this.innerHTML = `<i class="bi bi-person me-1"></i>${char}`;
            } else {
                currentSelectedChars.add(char);
                this.className = 'pub-tag-badge active pub-tag-char-active';
                this.innerHTML = `<i class="bi bi-person-check-fill me-1"></i>${char}`;
            }
        };
        container.appendChild(badge);
    });
}

function handleFiles(files) {
    if (!files || files.length === 0 || maxImagesAllowed === 0) return;
    if (maxImagesAllowed === 1) {
        currentFiles = [files[0]]; 
    } else {
        currentFiles = [...currentFiles, ...Array.from(files)].slice(0, maxImagesAllowed); 
    }
    renderPreviews();
}

function renderPreviews() {
    const container = document.getElementById('preview-container');
    container.innerHTML = ''; 
    currentFiles.forEach((file, index) => {
        const wrapper = document.createElement('div');
        wrapper.className = 'preview-wrapper m-1';
        const img = document.createElement('img');
        img.className = 'preview-item shadow-sm';
        const reader = new FileReader();
        reader.onload = (e) => { img.src = e.target.result; }
        reader.readAsDataURL(file);
        
        const removeBtn = document.createElement('button');
        removeBtn.className = 'btn-remove-preview';
        removeBtn.innerHTML = '<i class="bi bi-x"></i>';
        removeBtn.onclick = (e) => {
            e.preventDefault();
            e.stopPropagation(); 
            removeFile(index);
        };
        wrapper.appendChild(img);
        wrapper.appendChild(removeBtn);
        container.appendChild(wrapper);
    });
}

function removeFile(index) {
    currentFiles.splice(index, 1);
    renderPreviews();
}

function toggleGenResultSelect(element) {
    element.classList.toggle('selected');
}

function getSelectedSavedPaths() {
    const selectedCards = document.querySelectorAll('.gen-result-card.selected');
    const paths = [];
    selectedCards.forEach(card => {
        paths.push(card.getAttribute('data-path'));
    });
    return paths;
}

function playNotificationSound(type) {
    const audioEl = document.getElementById(`audio-${type}`);
    if (audioEl) {
        audioEl.currentTime = 0;
        audioEl.play().catch(e => console.log("浏览器限制了自动播放音频"));
    }
}

async function startGeneration() {
    if (window.Notification && Notification.permission !== "granted" && Notification.permission !== "denied") {
        Notification.requestPermission();
    }

    const modelChoice = document.getElementById('ai-model-select').value;
    const promptText = document.getElementById('ai-prompt').value;
    const loopCount = parseInt(document.getElementById('ai-loop-count').value) || 1;

    const categoryId = document.getElementById('ai-category-select').value;
    const catConfig = AI_CONFIG.categories.find(c => c.id === categoryId);
    const imgRequired = catConfig.img_required !== undefined ? catConfig.img_required : (maxImagesAllowed > 0);

    if (imgRequired && currentFiles.length === 0) {
        Swal.fire('提示', '当前模式必须上传参考图片！', 'warning');
        return;
    }
    if (!promptText.trim()) {
        Swal.fire('提示', '请输入画面描述！', 'warning');
        return;
    }

    const btn = document.getElementById('btn-generate');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>生成中...';
    
    document.getElementById('canvas-idle').style.display = 'none';
    document.getElementById('publish-bar').style.display = 'none';
    
    const gallery = document.getElementById('result-gallery');
    if(gallery) {
        gallery.style.display = 'none';
        gallery.innerHTML = ''; 
        lastSavedPaths = []; 
    }
    document.getElementById('canvas-scanning').style.display = 'block';
    document.getElementById('canvas-loading').style.display = 'block';

    const promptTips = [
        "💡 小贴士：想要大片感？尝试在提示词加入「丁达尔效应」或「电影级体积光」。",
        "💡 小贴士：开启多轮生成时，您可以切到后台干别的，出图后系统会通知您。",
        "💡 小贴士：多图融合时，上传两张风格差异大的图片，可能会有巨大的惊喜！",
        "💡 小贴士：加入「胶片质感」或「噪点」，能让画面充满复古氛围。"
    ];
    
    let elapsedSeconds = 0;
    let tipIndex = 0;
    const timerElement = document.getElementById('loading-timer-sec');
    const tipsElement = document.getElementById('loading-tips');
    
    timerElement.innerText = "00:00";
    tipsElement.innerText = promptTips[0];
    tipsElement.style.opacity = 1;

    const loadingInterval = setInterval(() => {
        elapsedSeconds++;
        const m = Math.floor(elapsedSeconds / 60).toString().padStart(2, '0');
        const s = (elapsedSeconds % 60).toString().padStart(2, '0');
        timerElement.innerText = `${m}:${s}`;

        if (elapsedSeconds % 4 === 0) {
            tipsElement.style.opacity = 0; 
            setTimeout(() => {
                tipIndex++;
                tipsElement.innerText = promptTips[tipIndex % promptTips.length];
                tipsElement.style.opacity = 1; 
            }, 500); 
        }
    }, 1000);

    const formData = new FormData();
    formData.append('model_choice', modelChoice);
    formData.append('prompt', promptText);
    if (maxImagesAllowed > 0) {
        currentFiles.forEach(file => formData.append('base_images', file));
    }
    document.querySelectorAll('.dynamic-param-input').forEach(input => {
        const paramId = input.getAttribute('data-param-id');
        const paramType = input.getAttribute('data-param-type');
        if (paramId === 'prompt_aspect_ratio') return;
        if (paramType === 'checkbox') {
            formData.append(paramId, input.checked); 
        } else {
            formData.append(paramId, input.value);
        }
    });

    let successCount = 0;
    let failCount = 0;
    let errorMessages = [];
    
    for (let i = 1; i <= loopCount; i++) {
        if (loopCount > 1) {
            btn.innerHTML = `<span class="spinner-border spinner-border-sm me-2"></span>正在生成 第 ${i}/${loopCount} 轮...`;
        }

        const loadingTitle = document.querySelector('.loading-title');
        if (loadingTitle) {
            loadingTitle.innerHTML = `✨ 正在云端渲染您的专属画作 <br><span class="text-primary fs-6 fw-normal">(第 ${i} / ${loopCount} 轮)</span>`;
        }

        try {
            const response = await fetch('/api/generate-direct/', {
                method: 'POST',
                body: formData 
            });
            const data = await response.json();

            if (data.status === 'success') {
                playNotificationSound('success');
                successCount++;
                document.getElementById('canvas-scanning').style.display = 'none';
                document.getElementById('canvas-loading').style.display = 'none';
                lastSavedPaths.push(...data.saved_paths);
                document.getElementById('publish-bar').style.display = 'block';

                gallery.style.display = 'grid';
                gallery.style.overflowY = 'auto'; 
                gallery.style.alignContent = 'start'; 
                gallery.style.paddingBottom = '100px'; 

                data.image_urls.forEach((url, index) => {
                    const localPath = data.saved_paths[index];
                    gallery.innerHTML += `
                        <div class="gen-result-card selected" data-path="${localPath}" onclick="toggleGenResultSelect(this)" style="min-height: 250px;">
                            <img src="${url}" style="width: 100%; height: 100%; object-fit: contain; border-radius: 8px;">
                            <div class="select-badge"><i class="bi bi-check-lg"></i></div>
                        </div>
                    `;
                });

                const totalImages = gallery.querySelectorAll('.gen-result-card').length;
                if (totalImages === 1) {
                    gallery.style.gridTemplateColumns = '1fr';
                    gallery.style.gridTemplateRows = '1fr';
                    gallery.style.gridAutoRows = 'auto';
                } else if (totalImages === 2) {
                    gallery.style.gridTemplateColumns = '1fr 1fr';
                    gallery.style.gridTemplateRows = '1fr';
                    gallery.style.gridAutoRows = 'auto';
                } else {
                    gallery.style.gridTemplateColumns = '1fr 1fr'; 
                    gallery.style.gridTemplateRows = 'none'; 
                    gallery.style.gridAutoRows = 'minmax(250px, auto)'; 
                }

                if (typeof notifyWhenBackground === 'function') {
                    notifyWhenBackground(`🎨 第 ${i} 轮生图完成！`, "已有新图片追加到画板，您可以回来看一眼。");
                }

            } else {
                playNotificationSound('error');
                failCount++;
                errorMessages.push(`<strong>第 ${i} 轮:</strong> ${data.message || '未知错误'}`);

                Swal.fire({
                    title: `第 ${i} 轮生成失败`,
                    text: data.message,
                    icon: 'error',
                    toast: true,
                    position: 'top',
                    timer: 3000,
                    showConfirmButton: false
                });
                if (typeof notifyWhenBackground === 'function') {
                    notifyWhenBackground("❌ 任务异常", `第 ${i} 轮触发了报错或拦截，已自动跳过。`);
                }
                continue;
            }
        } catch (error) {
            playNotificationSound('error');
            failCount++;
            errorMessages.push(`<strong>第 ${i} 轮:</strong> 网络超时或服务端断开连接`);

            Swal.fire({
                title: `第 ${i} 轮请求异常`,
                text: '网络或服务端断开',
                icon: 'warning',
                toast: true,
                position: 'top',
                timer: 3000,
                showConfirmButton: false
            });
            if (typeof notifyWhenBackground === 'function') {
                notifyWhenBackground("⚠️ 网络异常", `第 ${i} 轮请求超时，正在尝试下一轮。`);
            }
            continue;
        }
    }

    clearInterval(loadingInterval);
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-stars me-2"></i>开始生成';
    document.getElementById('canvas-scanning').style.display = 'none';
    document.getElementById('canvas-loading').style.display = 'none';

    if (successCount === 0) {
        document.getElementById('canvas-idle').style.display = 'block';
    }
    let errorHtmlList = '';
    if (errorMessages.length > 0) {
        errorHtmlList = `<div class="text-start mt-3 p-2 bg-light border rounded custom-scrollbar" style="max-height: 120px; overflow-y: auto; font-size: 0.85rem; color: #dc3545;">
                            <ul class="mb-0 ps-3">`;
        errorMessages.forEach(msg => {
            errorHtmlList += `<li class="mb-1">${msg}</li>`;
        });
        errorHtmlList += `  </ul>
                          </div>`;
    }

    if (successCount > 0 && failCount === 0) {
        Swal.fire({ 
            title: '🎉 队列执行完毕！', 
            text: `共为您完美生成了 ${successCount} 轮图片。`, 
            icon: 'success', 
            toast: true, position: 'top-end', showConfirmButton: false, timer: 5000 
        });
    } else if (successCount > 0 && failCount > 0) {
        Swal.fire({ 
            title: '⚠️ 队列执行完毕', 
            html: `成功 <b>${successCount}</b> 轮，失败 <b class="text-danger">${failCount}</b> 轮。<br>已将成功结果展示在画板。${errorHtmlList}`, 
            icon: 'warning', 
            confirmButtonText: '知道了',
            confirmButtonColor: '#8a2be2'
        });
    } else if (successCount === 0 && failCount > 0) {
        Swal.fire({
            title: '全部生成失败', 
            html: `很遗憾，队列中的 <b>${loopCount}</b> 轮任务全部遭遇异常。${errorHtmlList}`, 
            icon: 'error',
            confirmButtonText: '关闭',
            confirmButtonColor: '#dc3545'
        });
    }
}

function publishCreation() {
    const selectedPaths = getSelectedSavedPaths();
    if (selectedPaths.length === 0) {
        Swal.fire('提示', '请至少在画板中勾选一张要保存的图片！', 'warning');
        return;
    }

    const activeModelCard = document.querySelector('.model-card.active');
    const modelName = activeModelCard ? activeModelCard.querySelector('.model-card-title').innerText.trim() : document.getElementById('ai-model-select').value;
    
    document.getElementById('pub-model').value = modelName;
    const activeModelId = document.getElementById('ai-model-select').value;
    const currentModelConfig = AI_CONFIG.models[activeModelId];
    document.getElementById('pub-provider').value = currentModelConfig ? (currentModelConfig.provider || 'other') : 'other';
    renderPublishTags(initialTagsForPublish);
    renderPublishChars(initialCharsForPublish);
    
    const promptText = document.getElementById('ai-prompt').value.trim();
    const titleInput = document.getElementById('pub-title');
    
    if (promptText) {
        titleInput.value = "正在由 AI 智能概括标题...";
        titleInput.disabled = true;
        
        fetch('/api/generate-title/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ prompt: promptText })
        })
        .then(res => res.json())
        .then(data => {
            if (data.status === 'success' && data.title) {
                titleInput.value = data.title;
            } else {
                titleInput.value = ""; 
                titleInput.placeholder = "自动概括失败，请手动输入";
            }
        })
        .catch(err => {
            titleInput.value = "";
            titleInput.placeholder = "请手动输入标题";
        })
        .finally(() => {
            titleInput.disabled = false;
        });
    } else {
        titleInput.value = "";
        titleInput.placeholder = "请输入标题...";
    }

    new bootstrap.Modal(document.getElementById('publishModal')).show();
}

function confirmPublish() {
    const titleInput = document.getElementById('pub-title').value.trim();
    const modalEl = document.getElementById('publishModal');
    const modalInstance = bootstrap.Modal.getInstance(modalEl);
    if (modalInstance) modalInstance.hide();

    Swal.fire({
        title: '正在打包并发布...',
        text: '请稍候，服务器正在生成记录',
        allowOutsideClick: false,
        didOpen: () => Swal.showLoading()
    });

    const formData = new FormData();
    formData.append('prompt', document.getElementById('ai-prompt').value);
    formData.append('title', titleInput);
    formData.append('model_info', document.getElementById('pub-model').value.trim());
    formData.append('provider', document.getElementById('pub-provider').value);
    
    const finalTags = Array.from(currentSelectedTags).join(',');
    formData.append('tags', finalTags);
    const finalChars = Array.from(currentSelectedChars).join(',');
    formData.append('characters', finalChars);
    
    const selectedPaths = getSelectedSavedPaths();
    selectedPaths.forEach(path => {
        formData.append('saved_paths', path);
    });

    if (currentFiles && currentFiles.length > 0) {
        currentFiles.forEach(file => {
            formData.append('references', file);
        });
    }

    fetch('/api/publish-studio/', {
        method: 'POST',
        body: formData
    })
    .then(res => res.json())
    .then(data => {
        if (data.status === 'success') {
            Swal.fire({
                icon: 'success',
                title: '🎉 发布成功！',
                text: '已保存至您的提示词画廊。',
                showCancelButton: true,
                confirmButtonText: '<i class="bi bi-eye"></i> 前往查看该卡片',
                cancelButtonText: '留在此页继续创作',
                confirmButtonColor: '#8a2be2'
            }).then((result) => {
                if (result.isConfirmed) {
                    window.open(`/image/${data.group_id}/`, '_blank');
                } else {
                    document.getElementById('publish-bar').style.display = 'none';
                }
            });
        } else {
            Swal.fire('发布失败', data.message, 'error');
        }
    })
    .catch(err => {
        console.error(err);
        Swal.fire('请求异常', '网络或服务端报错，请查看控制台', 'error');
    });
}

let appendSearchTimeout;
function debounceAppendSearch() {
    const val = document.getElementById('appendSearchInput').value.trim();
    clearTimeout(appendSearchTimeout);
    
    if (!val) {
        document.getElementById('appendModalSubtitle').innerText = "系统已根据您当前使用的 Prompt 计算了全库相似度：";
        fetchSimilarGroupsForAppend();
        return;
    }
    
    appendSearchTimeout = setTimeout(() => {
        performAppendSearch(val);
    }, 500);
}

function performAppendSearch(q) {
    const container = document.getElementById('similarGroupsContainer');
    const activeModelCard = document.querySelector('.model-card.active');
    const currentModelName = activeModelCard ? activeModelCard.querySelector('.model-card-title').innerText.trim() : '';
    
    document.getElementById('appendModalSubtitle').innerText = `包含 "${q}" 的全库检索结果：`;
    container.innerHTML = '<div class="text-center text-muted py-5"><div class="spinner-border text-primary mb-3"></div><br>正在检索全库...</div>';

    fetch(`/api/groups/?q=${encodeURIComponent(q)}&include_variants=1`)
    .then(res => res.json())
    .then(data => {
        if (data.results) {
            renderSimilarGroups(data.results, currentModelName, true); 
        } else {
            container.innerHTML = `<div class="text-center text-danger py-4">搜索失败</div>`;
        }
    })
    .catch(err => {
        console.error(err);
        container.innerHTML = '<div class="text-center text-danger py-4">网络请求异常</div>';
    });
}

function openAddToGroupModal() {
    const selectedPaths = getSelectedSavedPaths();
    if (selectedPaths.length === 0) {
        Swal.fire('提示', '请至少在画板中勾选一张要追加的图片！', 'warning');
        return;
    }
    
    const searchInput = document.getElementById('appendSearchInput');
    if (searchInput) searchInput.value = '';
    const subtitle = document.getElementById('appendModalSubtitle');
    if (subtitle) subtitle.innerText = "系统已根据您当前使用的 Prompt 计算了全库相似度：";
    
    new bootstrap.Modal(document.getElementById('addToGroupModal')).show();
    fetchSimilarGroupsForAppend();
    
    setTimeout(() => {
        if (searchInput) searchInput.focus();
    }, 500);
}

function fetchSimilarGroupsForAppend() {
    const promptText = document.getElementById('ai-prompt').value.trim();
    const container = document.getElementById('similarGroupsContainer');
    const activeModelCard = document.querySelector('.model-card.active');
    const currentModelName = activeModelCard ? activeModelCard.querySelector('.model-card-title').innerText.trim() : '';
    container.innerHTML = '<div class="text-center text-muted py-5"><div class="spinner-border text-primary mb-3"></div><br>正在计算全库提示词相似度...</div>';

    fetch('/api/get-similar-groups-by-prompt/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: promptText })
    })
    .then(res => res.json())
    .then(data => {
        if (data.status === 'success') {
            renderSimilarGroups(data.results, currentModelName, false);
        } else {
            container.innerHTML = `<div class="text-center text-danger py-4">检索失败: ${data.message}</div>`;
        }
    })
    .catch(err => {
        console.error(err);
        container.innerHTML = '<div class="text-center text-danger py-4">网络请求异常</div>';
    });
}

function renderSimilarGroups(groups, currentModelName, isSearch = false) {
    const container = document.getElementById('similarGroupsContainer');
    if (!groups || groups.length === 0) {
        container.innerHTML = '<div class="text-center text-muted py-4"><i class="bi bi-inbox fs-1 d-block mb-2 opacity-50"></i>暂无作品。</div>';
        return;
    }

    if (currentSourceGroupId && !isSearch) { 
        const sourceIndex = groups.findIndex(g => String(g.id) === currentSourceGroupId);
        if (sourceIndex > -1) {
            const sourceGroup = groups.splice(sourceIndex, 1)[0];
            groups.unshift(sourceGroup);
        }
    }

    let html = '';
    groups.forEach((group, index) => {
        const isCurrentSource = (currentSourceGroupId && String(group.id) === currentSourceGroupId);

        const coverHtml = group.cover_url 
            ? `<img src="${group.cover_url}" class="rounded shadow-sm" style="width: 70px; height: 70px; object-fit: cover;">`
            : `<div class="rounded bg-light shadow-sm d-flex align-items-center justify-content-center text-muted" style="width: 70px; height: 70px;"><i class="bi bi-image fs-4"></i></div>`;

        let topBadgeHtml = '';
        if (isCurrentSource) {
            topBadgeHtml = `<span class="badge bg-success shadow-sm rounded-pill px-2 py-1"><i class="bi bi-pin-angle-fill me-1"></i>当前所属作品</span>`;
        } else if (group.similarity && !isSearch) {
            let badgeClass = 'bg-secondary';
            let simValue = parseInt(group.similarity);
            if(simValue > 80) badgeClass = 'bg-danger';
            else if(simValue > 50) badgeClass = 'bg-warning text-dark';
            else if(simValue > 20) badgeClass = 'bg-primary';
            topBadgeHtml = `<span class="badge ${badgeClass} rounded-pill">相似度 ${group.similarity}</span>`;
        } else if (isSearch) {
            topBadgeHtml = `<span class="badge bg-light text-secondary border rounded-pill"><i class="bi bi-search me-1"></i>检索结果</span>`;
        }

        const cleanCurrentModelName = currentModelName ? currentModelName.replace(/\s*[\(（].*?[\)）]$/, '').trim() : '';
        let isModelMatch = (cleanCurrentModelName && group.model_info && cleanCurrentModelName.toLowerCase() === group.model_info.toLowerCase());
        let modelBadge = '';
        if (group.model_info && group.model_info !== '无模型') {
            if (isModelMatch) {
                modelBadge = `<span class="badge text-white fw-bold me-2 shadow-sm" style="background: linear-gradient(135deg, #8a2be2 0%, #4a00e0 100%); font-size: 0.75rem;"><i class="bi bi-cpu-fill me-1"></i>${group.model_info} (同款)</span>`;
            } else {
                modelBadge = `<span class="badge bg-secondary fw-normal me-2" style="font-size: 0.75rem;"><i class="bi bi-cpu me-1"></i>${group.model_info}</span>`;
            }
        } else {
            modelBadge = `<span class="badge bg-light text-secondary border fw-normal me-2" style="font-size: 0.75rem;">无模型</span>`;
        }

        let charBadges = '';
        if (group.characters && group.characters.length > 0) {
            group.characters.forEach(char => {
                charBadges += `<span class="badge bg-info text-dark fw-normal me-2" style="font-size: 0.75rem;"><i class="bi bi-person-fill me-1"></i>${char}</span>`;
            });
        }

        const matchedPromptBadge = (!isSearch && group.matched_prompt_label)
            ? `<span class="badge bg-light text-secondary border fw-normal me-2" style="font-size: 0.75rem;"><i class="bi bi-chat-left-text me-1"></i>${group.matched_prompt_label}</span>`
            : '';

        const activeCardClass = isCurrentSource ? "border-success border-2 bg-success bg-opacity-10" : "";

        const safeTitle = group.title 
            ? group.title.replace(/"/g, '&quot;').replace(/'/g, '&#39;').replace(/[\r\n]+/g, ' ') 
            : '未命名作品';

        html += `
        <a href="javascript:void(0)" class="list-group-item list-group-item-action d-flex gap-3 align-items-center py-3 ${activeCardClass}" 
           data-group-id="${group.id}" 
           data-group-title="${safeTitle}" 
           onclick="confirmAppendToGroup(this)">
            ${coverHtml}
            <div class="flex-grow-1 overflow-hidden">
                <div class="d-flex w-100 justify-content-between align-items-center mb-1">
                    <h6 class="mb-0 fw-bold text-truncate" style="max-width: 70%;">${group.title}</h6>
                    ${topBadgeHtml}
                </div>
                <div class="mb-0 text-truncate mt-1 d-flex align-items-center">
                    ${modelBadge}
                    ${charBadges}${matchedPromptBadge}<span class="small text-muted text-truncate">${group.prompt_text}</span>
                </div>
            </div>
        </a>`;
    });
    container.innerHTML = html;
}

function confirmAppendToGroup(element) {
    const groupId = element.getAttribute('data-group-id');
    const groupTitle = element.getAttribute('data-group-title');

    Swal.fire({
        title: '确认追加?',
        html: `即将把新生成的图片收录进作品<br><strong class="text-primary">${groupTitle}</strong>`,
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: '确认追加',
        cancelButtonText: '取消',
        confirmButtonColor: '#8a2be2'
    }).then((result) => {
        if (result.isConfirmed) {
            executeAppendRequest(groupId);
        }
    });
}

function executeAppendRequest(groupId) {
    const modalEl = document.getElementById('addToGroupModal');
    const modalInstance = bootstrap.Modal.getInstance(modalEl);
    if (modalInstance) modalInstance.hide();

    Swal.fire({
        title: '正在打包并追加...',
        allowOutsideClick: false,
        didOpen: () => Swal.showLoading()
    });

    const formData = new FormData();
    formData.append('group_id', groupId);
    
    const selectedPaths = getSelectedSavedPaths();
    selectedPaths.forEach(path => {
        formData.append('saved_paths', path);
    });

    fetch('/api/append-to-existing-group/', {
        method: 'POST',
        body: formData
    })
    .then(res => res.json())
    .then(data => {
        if (data.status === 'success') {
            Swal.fire({
                icon: 'success',
                title: '🎉 追加成功！',
                text: data.message,
                showCancelButton: true,
                confirmButtonText: '<i class="bi bi-eye"></i> 前往查看',
                cancelButtonText: '留在此页继续创作',
                confirmButtonColor: '#8a2be2'
            }).then((result) => {
                if (result.isConfirmed) {
                    window.open(`/image/${data.group_id}/`, '_blank');
                } else {
                    document.getElementById('publish-bar').style.display = 'none';
                }
            });
        } else {
            Swal.fire('追加失败', data.message, 'error');
        }
    })
    .catch(err => {
        console.error(err);
        Swal.fire('请求异常', '网络或服务端报错', 'error');
    });
}

function showCreateCharRefs(charId, btnElement) {
    document.querySelectorAll('#charRefModal .char-filter-btn').forEach(btn => btn.classList.remove('active'));
    btnElement.classList.add('active');
    
    document.querySelectorAll('#charRefModal .char-ref-gallery').forEach(el => el.classList.add('d-none'));
    const targetGallery = document.getElementById('create-char-gallery-' + charId);
    if (targetGallery) targetGallery.classList.remove('d-none');
}

function extractExistingRefToCanvas(url) {
    if (maxImagesAllowed === 0) {
        Swal.fire('提示', '当前选中的生成模型不支持上传参考图！', 'info');
        return;
    }
    if (currentFiles.length >= maxImagesAllowed && maxImagesAllowed > 1) {
        Swal.fire('提示', `当前模型最多只能上传 ${maxImagesAllowed} 张参考图`, 'warning');
        return;
    }

    Swal.fire({
        title: '正在提取图鉴...',
        allowOutsideClick: false,
        didOpen: () => Swal.showLoading()
    });

    fetch(url)
        .then(res => res.blob())
        .then(blob => {
            const filename = url.split('/').pop().split('?')[0] || 'reference_image.jpg';
            const file = new File([blob], filename, { type: blob.type || 'image/jpeg' });
            
            if (maxImagesAllowed === 1) {
                currentFiles = [file];
            } else {
                currentFiles.push(file);
            }
            renderPreviews(); 
            
            Swal.close();
            
            const modalEl = document.getElementById('charRefModal');
            const modalInstance = bootstrap.Modal.getInstance(modalEl);
            if (modalInstance) modalInstance.hide();
            
            Swal.fire({
                toast: true, position: 'top', showConfirmButton: false, timer: 2000,
                icon: 'success', title: '已成功提取至工作区'
            });
        })
        .catch(err => {
            console.error("提取参考图失败:", err);
            Swal.fire('提取失败', '无法读取服务器图片', 'error');
        });
}