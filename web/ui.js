const paths = {
    home: 'M3 11 12 4l9 7v9h-6v-6H9v6H3z',
    book: 'M3 5q5-2 9 1 4-3 9-1v14q-5-2-9 1-4-3-9-1z M12 6v14',
    camera: 'M3 7h4l2-3h6l2 3h4v13H3z M15.5 13a3.5 3.5 0 1 1-7 0 3.5 3.5 0 1 1 7 0z',
    user: 'M16 8a4 4 0 1 1-8 0 4 4 0 1 1 8 0z M4 21a8 8 0 0 1 16 0',
    arrow: 'M4 12h15m-6-6 6 6-6 6', pin: 'M19 10c0 5-7 11-7 11S5 15 5 10a7 7 0 1 1 14 0z M14 10a2 2 0 1 1-4 0 2 2 0 1 1 4 0z',
    search: 'M17 10a7 7 0 1 1-14 0 7 7 0 1 1 14 0z M15 15l6 6',
    cat: 'M4 11l1-8 6 4h2l6-4 1 8a8 8 0 1 1-16 0z M8 12h.1m7.8 0h.1m-5 3 1 1 1-1',
    time: 'M21 12a9 9 0 1 1-18 0 9 9 0 1 1 18 0z M12 6v6l4 2',
    focus: 'M3 8V3h5m8 0h5v5m0 8v5h-5m-8 0H3v-5 M15 12a3 3 0 1 1-6 0 3 3 0 1 1 6 0z',
    review: 'M5 4h14v16H5z M8 12l3 3 5-6', leaf: 'M4 19C2 8 12 5 21 3c-1 12-5 17-14 15 M4 21l11-12',
    image: 'M3 3h18v18H3z M3 17l5-5 4 4 4-6 5 7 M9 8h.1',
};
export function icon(name) {
    return `<svg aria-hidden="true" class="icon" viewBox="0 0 24 24"><path d="${paths[name] || paths.cat}"/></svg>`;
}
export function esc(value) {
    return String(value ?? '').replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
}
export function btn(href, label, symbol = '', kind = '') {
    return `<a class="btn ${kind}" href="${esc(href)}">${symbol ? icon(symbol) : ''}${esc(label)}</a>`;
}
export function img(src, alt, extra = '') {
    return `<img src="${esc(src)}" alt="${esc(alt)}" ${extra}>`;
}
export function head(title, sub = '', action = '') {
    return `<div class="page-head"><div><h1>${esc(title)}</h1>${sub ? `<p>${esc(sub)}</p>` : ''}</div>${action}</div>`;
}
export function back(href, label) {
    return `<a class="back" href="${esc(href)}">${icon('arrow')}${esc(label)}</a>`;
}
export function empty(symbol, title, desc, action = '') {
    return `<section class="empty"><span class="empty-emblem">${icon(symbol)}</span><h3>${esc(title)}</h3><p>${esc(desc)}</p>${action}</section>`;
}
export function date(value) {
    if (!value)
        return '日期待补';
    const d = new Date(value);
    return Number.isNaN(d.valueOf()) ? '日期待补' : d.toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric' });
}
export function status(value) {
    return `<span class="pill ${esc(value)}">${({ pending: '待辨认', confirmed: '身份已确认', rejected: '未采纳' })[value] || '待处理'}</span>`;
}
export async function api(path, body) {
    let response;
    try {
        response = await fetch('/api' + path, {
            method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin', cache: 'no-store', headers: body === undefined ? {} : { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body)
        });
    }
    catch {
        throw new Error('暂时连不上服务器，请检查网络后重试。');
    }
    const data = await response.json().catch(() => ({ error: '服务器响应异常，请稍后重试。' }));
    if (!response.ok || data.error) {
        const err = new Error(data.error || '请求失败，请重试。');
        err.status = response.status;
        throw err;
    }
    return data;
}
export function notice(text) {
    const n = document.querySelector('#notice');
    n.textContent = text;
    clearTimeout(notice.timer);
    notice.timer = setTimeout(() => {
        n.textContent = '';
    }, 4500);
}
export async function busy(control, operation, form = control.closest('form')) {
    if (control.disabled)
        return;
    const message = form?.querySelector('.form-error');
    if (message)
        message.textContent = '';
    control.disabled = true;
    try {
        await operation();
    }
    catch (error) {
        if (message)
            message.textContent = error.message;
        else
            notice(error.message);
    }
    finally {
        control.disabled = false;
    }
}
export function card(cat) {
    return `<a class="cat-card" href="#cat/${Number(cat.id)}">${img(cat.thumbnail_url || cat.photo_url, cat.name, 'loading="lazy"')}<div class="card-body"><h3>${esc(cat.name)}</h3><p>${esc(cat.coat || '花色待补')} · ${Number(cat.sightings)} 次目击</p><p class="meta">${icon('pin')}${esc(cat.area || '区域待补')}</p></div></a>`;
}
export function candidates(s) {
    return (s.candidates || []).length ? `<p class="hint">按框内花色、明暗和纹理列出相似档案，仍需核对脸部和四肢的花纹。</p><div class="gallery">${s.candidates.map(card).join('')}</div>` : `<p class="hint">暂无可比对的候选。可以保留待辨认，等有清晰照片再核对。</p>`;
}
export function formValues(form) {
    return Object.fromEntries(new FormData(form).entries());
}
