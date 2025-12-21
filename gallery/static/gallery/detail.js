/**
 * 详情页交互逻辑
 * 依赖: Bootstrap 5, galleryImages (全局变量, 包含 {url, id})
 */

let currentIndex = 0;
let imageModal = null; 

document.addEventListener('DOMContentLoaded', function() {
    const modalEl = document.getElementById('imageModal');
    if (modalEl) {
        imageModal = new bootstrap.Modal(modalEl);
    }

    document.addEventListener('keydown', function(event) {
        if (modalEl && modalEl.classList.contains('show')) {
            if (event.key === 'ArrowLeft') changeImage(-1);
            if (event.key === 'ArrowRight') changeImage(1);
            if (event.key === 'Escape') imageModal.hide();
        }
    });
});

function showModal(index) {
    currentIndex = index;
    updateModalImage();
    imageModal.show();
}

function changeImage(direction) {
    currentIndex += direction;
    if (currentIndex >= galleryImages.length) {
        currentIndex = 0;
    } else if (currentIndex < 0) {
        currentIndex = galleryImages.length - 1;
    }
    updateModalImage();
}

function updateModalImage() {
    const imgElement = document.getElementById('previewImage');
    const downloadBtn = document.getElementById('modalDownloadBtn');
    const deleteForm = document.getElementById('modalDeleteForm');
    const counterElement = document.getElementById('imageCounter'); // 获取计数器元素

    // 获取当前图片的数据对象
    const currentImgData = galleryImages[currentIndex];

    // 1. 设置图片
    imgElement.style.opacity = '0.5';
    imgElement.src = currentImgData.url;
    imgElement.onload = function() {
        imgElement.style.opacity = '1';
    };

    // 2. 更新下载按钮
    if (downloadBtn) {
        downloadBtn.href = currentImgData.url;
    }

    // 3. 更新删除表单的 Action URL
    if (deleteForm) {
        deleteForm.action = `/delete-image/${currentImgData.id}/`;
    }

    // 4. 【新增】更新页码计数器
    if (counterElement) {
        counterElement.innerText = `${currentIndex + 1} / ${galleryImages.length}`;
    }
}

function copyText(elementId, btnElement) {
    const textElement = document.getElementById(elementId);
    if (textElement.querySelector('.empty-text')) return;

    const text = textElement.innerText;
    navigator.clipboard.writeText(text).then(() => {
        const originalHTML = btnElement.innerHTML;
        const isPrimary = btnElement.classList.contains('btn-outline-primary');
        const originalClass = isPrimary ? 'btn-outline-primary' : 'btn-outline-danger';

        btnElement.innerHTML = '<i class="bi bi-check-lg me-1"></i>已复制';
        btnElement.classList.remove(originalClass);
        btnElement.classList.add('btn-success', 'text-white');

        setTimeout(() => {
            btnElement.innerHTML = originalHTML;
            btnElement.classList.remove('btn-success', 'text-white');
            btnElement.classList.add(originalClass);
        }, 2000);
    }).catch(err => {
        console.error('复制失败:', err);
        alert('复制失败，请手动复制');
    });
}