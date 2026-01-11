/**
 * 通用工具函数库
 * 包含：CSRF处理、复制剪贴板、点赞逻辑、分页跳转、Masonry瀑布流初始化
 */

// 1. 获取 CSRF Token
function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

const csrftoken = getCookie('csrftoken');

// 2. 复制提示词到剪贴板
function copyToClipboard(text, successTitle = '复制成功！') {
    if (!text) { 
        Swal.fire({
            icon: 'warning',
            title: '内容为空',
            toast: true,
            position: 'top-end',
            showConfirmButton: false,
            timer: 1500
        });
        return; 
    }
    
    navigator.clipboard.writeText(text).then(function() {
        const Toast = Swal.mixin({
            toast: true,
            position: 'top-end',
            showConfirmButton: false,
            timer: 2000,
            timerProgressBar: true,
            background: 'rgba(255, 255, 255, 0.95)',
            didOpen: (toast) => {
                toast.addEventListener('mouseenter', Swal.stopTimer);
                toast.addEventListener('mouseleave', Swal.resumeTimer);
            }
        });
        Toast.fire({ icon: 'success', title: successTitle });
    });
}

// 3. 通用点赞逻辑
function toggleLikeCommon(id, type, currentIsLiked, btnElement, removeOnUnlike = false) {
    const url = type === 'group' ? `/toggle-like-group/${id}/` : `/toggle-like-image/${id}/`;
    
    if (removeOnUnlike && currentIsLiked) {
        Swal.fire({
            title: '移除喜欢?',
            text: "确定要从喜欢的列表中移除吗？",
            icon: 'warning',
            showCancelButton: true,
            confirmButtonColor: '#ff4757',
            cancelButtonColor: '#6c757d',
            confirmButtonText: '是的，移除',
            cancelButtonText: '取消',
            background: 'rgba(255, 255, 255, 0.95)',
            customClass: { popup: 'rounded-4 shadow-lg border-0' }
        }).then((result) => {
            if (result.isConfirmed) {
                performLikeFetch(url, btnElement, id, type, true);
            }
        });
    } else {
        performLikeFetch(url, btnElement, id, type, false);
    }
}

function performLikeFetch(url, btn, id, type, shouldRemove) {
    const icon = btn.querySelector('i');
    
    fetch(url, {
        method: 'POST',
        headers: { 
            'X-CSRFToken': csrftoken, 
            'Content-Type': 'application/json' 
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            const isLiked = data.is_liked;
            
            if (isLiked) {
                btn.classList.add('active');
                icon.classList.remove('bi-heart');
                icon.classList.add('bi-heart-fill');
            } else {
                btn.classList.remove('active');
                icon.classList.remove('bi-heart-fill');
                icon.classList.add('bi-heart');
            }

            if (shouldRemove && !isLiked) {
                const card = btn.closest('.grid-item');
                if (card) {
                    card.style.opacity = '0';
                    setTimeout(() => { 
                        card.remove(); 
                        const grid = document.querySelector('#masonry-grid') || document.querySelector('#detail-masonry-grid');
                        if(grid && window.Masonry) {
                            Masonry.data(grid)?.layout();
                        }
                    }, 300);
                }
            }
            
            const funcName = type === 'group' ? 'toggleGroupLike' : 'toggleImageLike';
            btn.setAttribute('onclick', `${funcName}(event, ${id}, ${isLiked})`);
        }
    });
}

// 4. 分页跳转
function jumpToPage(maxPage) {
    const input = document.getElementById('jumpPageInput');
    if (!input) return;
    
    const page = input.value;
    if (page >= 1 && page <= maxPage) {
        const urlParams = new URLSearchParams(window.location.search);
        urlParams.set('page', page);
        window.location.search = urlParams.toString();
    } else {
        Swal.fire('页码错误', `请输入 1 到 ${maxPage} 之间的页码`, 'warning');
    }
}

/**
 * 5. 优化的 Masonry 初始化函数
 * 使用 requestAnimationFrame 防抖，解决布局鬼畜抖动问题
 * @param {string} gridSelector - 网格容器的选择器 (e.g., '#masonry-grid')
 * @param {string} itemSelector - 卡片项的选择器 (e.g., '.grid-item')
 */
function initMasonry(gridSelector, itemSelector = '.grid-item') {
    const grid = document.querySelector(gridSelector);
    if (!grid || !window.Masonry || !window.imagesLoaded) return;

    const msnry = new Masonry(grid, {
        itemSelector: itemSelector,
        percentPosition: true,
        transitionDuration: '0.3s' // 缩短过渡时间，视觉更利落
    });

    let layoutPending = false;

    // 封装 layout 调用，方便多次复用
    function triggerLayout() {
        if (!layoutPending) {
            layoutPending = true;
            requestAnimationFrame(() => {
                msnry.layout();
                layoutPending = false;
            });
        }
    }

    imagesLoaded(grid).on('progress', function(instance, image) {
        // 图片淡入效果
        if (image.isLoaded) {
            image.img.classList.add('loaded');
        }
        // 核心优化：使用 requestAnimationFrame 节流 Layout 更新
        triggerLayout();
    }).on('done', function() {
        // 确保所有图片加载完成后，执行最后一次完美的布局
        triggerLayout();
        
        // 【新增】监听字体加载：防止字体加载滞后导致文字换行、高度变化从而重叠
        if (document.fonts) {
            document.fonts.ready.then(() => {
                triggerLayout();
            });
        }
        
        // 处理 URL hash 跳转 (高亮特定卡片)
        if (window.location.hash) {
            const targetId = window.location.hash.substring(1);
            const targetEl = document.getElementById(targetId);
            if (targetEl) {
                setTimeout(() => {
                    targetEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    const card = targetEl.querySelector('.gallery-card') || targetEl.querySelector('.detail-img-card');
                    if(card) card.classList.add('highlight-pulse');
                }, 500);
            }
        }
    });
    
    // 【新增】窗口大小改变时强制刷新一次（防止 Resize 偶尔计算失误）
    window.addEventListener('resize', () => {
        triggerLayout();
    });

    return msnry;
}

// 6. 导航栏搜索框逻辑 (解耦版)
document.addEventListener('DOMContentLoaded', function() {
    const searchInput = document.getElementById('navSearchInput');
    const clearBtn = document.getElementById('navSearchClearBtn');

    if (searchInput && clearBtn) {
        
        // 控制按钮显示的函数
        const updateClearBtnVisibility = () => {
            if (searchInput.value.trim().length > 0) {
                clearBtn.style.display = 'block';
            } else {
                clearBtn.style.display = 'none';
            }
        };

        // 初始化状态
        updateClearBtnVisibility();

        // 监听输入事件
        searchInput.addEventListener('input', updateClearBtnVisibility);
        
        // 监听聚焦事件 (聚焦时如果有内容也显示)
        searchInput.addEventListener('focus', updateClearBtnVisibility);

        // 监听失焦事件
        // 使用 setTimeout 延迟隐藏，否则点击清除按钮时，Blur 会先触发导致按钮消失，点击无效
        searchInput.addEventListener('blur', function() {
            setTimeout(() => {
                clearBtn.style.display = 'none';
            }, 200);
        });

        // 监听清除按钮点击
        clearBtn.addEventListener('click', function(e) {
            e.preventDefault(); // 阻止默认行为
            searchInput.value = ''; // 清空输入
            updateClearBtnVisibility(); // 更新按钮状态
            searchInput.focus(); // 保持焦点在输入框，方便继续输入
        });
        
        // 防止点击按钮本身导致输入框失焦 (辅助)
        clearBtn.addEventListener('mousedown', function(e) {
            e.preventDefault();
        });
    }
});