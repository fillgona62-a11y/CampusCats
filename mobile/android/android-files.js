import { notice } from './ui.js';

async function save(url, name) {
    try {
        const blob = await (await fetch(url)).blob();
        const encoded = await new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result.slice(reader.result.indexOf(',') + 1));
            reader.onerror = reject;
            reader.readAsDataURL(blob);
        });
        if (!window.prompt('campuscats-save:' + name, encoded)) notice('暂时无法保存，请重试。');
    } catch {
        notice('读取文件失败，请重新生成。');
    }
}
document.addEventListener('click', event => {
    const link = event.target.closest('a[download]');
    if (link && (link.href.startsWith('data:image/png;') || link.href.startsWith('blob:' + location.origin + '/'))) {
        event.preventDefault();
        save(link.href, link.download);
    }
}, true);
document.addEventListener('contextmenu', event => {
    if (event.target instanceof HTMLImageElement && event.target.src.startsWith('data:image/png;')) {
        event.preventDefault();
        save(event.target.src, '琴园有猫-卡片.png');
    }
});
