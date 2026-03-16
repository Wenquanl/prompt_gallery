document.addEventListener('DOMContentLoaded', function() {
    var grid = document.querySelector('#masonry-grid');
    if (grid) {
        var msnry = new Masonry(grid, { itemSelector: '.grid-item', percentPosition: true });
        
        imagesLoaded(grid).on('progress', function(instance, image) { 
            msnry.layout(); 
        }).on('done', function() {
            if (window.location.hash) {
                const targetId = window.location.hash.substring(1);
                const targetEl = document.getElementById(targetId);
                if (targetEl) {
                    setTimeout(() => {
                        targetEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
                        targetEl.style.transition = "transform 0.3s ease";
                        targetEl.style.transform = "scale(1.02)";
                        setTimeout(() => { targetEl.style.transform = "scale(1)"; }, 300);
                    }, 200);
                }
            }
        });
    }

    // === 搜索框拖拽上传逻辑 ===
    const searchForm = document.getElementById('searchForm');
    const fileInput = document.getElementById('fileInput');

    if (searchForm) {
        // 1. 阻止默认行为
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            searchForm.addEventListener(eventName, (e) => {
                e.preventDefault();
                e.stopPropagation();
            }, false);
        });

        // 2. 拖拽进入时的视觉反馈
        ['dragenter', 'dragover'].forEach(eventName => {
            searchForm.addEventListener(eventName, () => {
                searchForm.style.border = '2px dashed #0d6efd'; 
                searchForm.style.backgroundColor = 'rgba(13, 110, 253, 0.05)';
                searchForm.style.transform = 'scale(1.02)';
            }, false);
        });

        // 3. 拖拽离开或放下后的样式复原
        ['dragleave', 'drop'].forEach(eventName => {
            searchForm.addEventListener(eventName, () => {
                searchForm.style.border = ''; 
                searchForm.style.backgroundColor = '';
                searchForm.style.transform = '';
            }, false);
        });

        // 4. 处理文件放下
        searchForm.addEventListener('drop', (e) => {
            const dt = e.dataTransfer;
            const files = dt.files;

            if (files.length > 0) {
                const file = files[0];
                if (file.type.startsWith('image/') || file.type.startsWith('video/')) {
                    fileInput.files = files; 
                    handleImageUpload(); 
                } else {
                    Swal.fire({
                        icon: 'error',
                        title: '格式不支持',
                        text: '请拖入图片或视频文件',
                        confirmButtonColor: '#0d6efd'
                    });
                }
            }
        }, false);
    }
});

function handleImageUpload() {
    const fileInput = document.getElementById('fileInput');
    const form = document.getElementById('searchForm');
    const textInput = document.getElementById('textInput');
    
    if (fileInput.files.length > 0) {
        form.method = 'post';
        textInput.value = "正在分析文件..."; 
        textInput.disabled = true;
        form.submit();
    }
}

function toggleLikeInGallery(btn, pk) {
    // 从 HTML 中获取后端的配置数据
    const configEl = document.getElementById('liked-images-config');
    let isHomeSearch = false;
    let csrfToken = '';
    
    if (configEl) {
        const config = JSON.parse(configEl.textContent);
        isHomeSearch = config.isHomeSearch;
        csrfToken = config.csrfToken;
    } else {
        csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
    }
    
    fetch(`/toggle-like-image/${pk}/`, {
        method: 'POST',
        headers: { 'X-CSRFToken': csrfToken, 'Content-Type': 'application/json' }
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            const icon = btn.querySelector('i');
            if (data.is_liked) {
                icon.className = 'bi bi-heart-fill';
                btn.style.opacity = '1';
            } else {
                icon.className = 'bi bi-heart';
                if (!isHomeSearch) {
                    const card = document.getElementById(`card-img-${pk}`).closest('.grid-item');
                    card.style.opacity = '0';
                    setTimeout(() => {
                        card.remove();
                        // 修复开始：使用 reloadItems
                        var grid = document.querySelector('#masonry-grid');
                        var msnry = Masonry.data(grid);
                        if(msnry) {
                            msnry.reloadItems(); 
                            msnry.layout();      
                        }
                    }, 300);
                } else {
                    btn.style.opacity = '0.3';
                }
            }
        }
    });
}