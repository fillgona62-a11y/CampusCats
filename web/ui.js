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
function emptyIllustration(symbol) {
    if (symbol === 'search' || symbol === 'focus') {
        return `<svg class="empty-art" viewBox="0 0 96 72" aria-hidden="true"><circle cx="42" cy="34" r="18" fill="none" stroke="currentColor" stroke-width="2.2"/><path d="M55 47l14 14" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"/><path d="M34 32l3-8 5 4h2l5-4 3 8" fill="none" stroke="var(--ginger)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><circle cx="38" cy="36" r="1.4" fill="currentColor"/><circle cx="46" cy="36" r="1.4" fill="currentColor"/></svg>`;
    }
    if (symbol === 'book' || symbol === 'time') {
        return `<svg class="empty-art" viewBox="0 0 96 72" aria-hidden="true"><rect x="18" y="14" width="60" height="44" rx="8" fill="none" stroke="currentColor" stroke-width="2.2"/><path d="M48 16v40" stroke="currentColor" stroke-width="1.6" stroke-dasharray="3 3"/><path d="M27 36c3-6 9-6 12 0M57 38c4-5 10-5 13 0" fill="none" stroke="var(--ginger)" stroke-width="2" stroke-linecap="round"/><circle cx="33" cy="27" r="3" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>`;
    }
    return `<svg class="empty-art" viewBox="0 0 96 72" aria-hidden="true"><path d="M22 50c0-13 10-22 26-22s26 9 26 22" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/><path d="M30 33l-2-11 9 6M66 33l2-11-9 6" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/><path d="M39 41q3 3 6 0M51 41q3 3 6 0" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><path d="M72 48c7 0 11-5 8-11" fill="none" stroke="var(--ginger)" stroke-width="2.2" stroke-linecap="round"/><path d="M16 54h64" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" opacity=".35"/></svg>`;
}
export function empty(symbol, title, desc, action = '') {
    return `<section class="empty">${emptyIllustration(symbol)}<h3>${esc(title)}</h3><p>${esc(desc)}</p>${action}</section>`;
}
export function date(value) {
    if (!value)
        return '日期待补';
    const d = new Date(value);
    return Number.isNaN(d.valueOf()) ? '日期待补' : d.toLocaleDateString('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: 'long', day: 'numeric' });
}
export function status(value) {
    return `<span class="pill ${esc(value)}">${({ pending: '待辨认', confirmed: '身份已确认', rejected: '未采纳' })[value] || '待处理'}</span>`;
}
export async function api(path, body) {
    const idempotent = body === undefined || path === '/detect' || path === '/identify';
    const maxAttempts = idempotent ? 2 : 1;
    let response;
    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
        try {
            response = await fetch('/api' + path, {
                method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin', cache: 'no-store', headers: body === undefined ? {} : { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body)
            });
            if (attempt < maxAttempts && (response.status === 502 || response.status === 503 || response.status === 504)) {
                await new Promise(r => setTimeout(r, 450));
                continue;
            }
            break;
        }
        catch {
            if (attempt < maxAttempts) {
                await new Promise(r => setTimeout(r, 450));
                continue;
            }
            throw new Error('暂时连不上服务器，请检查网络后重试。');
        }
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
export const SEX_LABELS = { unknown: '性别待确认', female: '母猫', male: '公猫' };
export const NEUTERED_LABELS = { unknown: '绝育待确认', neutered: '已绝育', intact: '未绝育' };
export const CARE_LABELS = { school: '在校活跃', attention: '需关注健康', adopted: '已领养毕业', memorial: '喵星纪念' };

export function catTags(cat) {
    const tags = [];
    if (cat.care_status && cat.care_status !== 'school' && CARE_LABELS[cat.care_status])
        tags.push(['care-' + cat.care_status, CARE_LABELS[cat.care_status]]);
    if (cat.neutered && cat.neutered !== 'unknown' && NEUTERED_LABELS[cat.neutered])
        tags.push(['neuter-' + cat.neutered, NEUTERED_LABELS[cat.neutered]]);
    if (cat.sex && cat.sex !== 'unknown' && SEX_LABELS[cat.sex])
        tags.push(['sex', SEX_LABELS[cat.sex]]);
    return tags.length ? `<div class="cat-tags">${tags.map(([cls, label]) => `<span class="cat-tag ${esc(cls)}">${esc(label)}</span>`).join('')}</div>` : '';
}

export function catSearchText(cat) {
    return [
        cat.name,
        ...(cat.aliases || []),
        cat.coat,
        cat.breed,
        cat.temperament,
        cat.sex !== 'unknown' ? SEX_LABELS[cat.sex] : '',
        cat.neutered !== 'unknown' ? NEUTERED_LABELS[cat.neutered] : '',
        CARE_LABELS[cat.care_status] || '',
    ].filter(Boolean).join(' ').toLowerCase();
}

export function card(cat) {
    const badges = catTags(cat);
    return `<a class="cat-card" href="#cat/${Number(cat.id)}"><div class="card-media">${img(cat.thumbnail_url || cat.photo_url, cat.name, 'loading="lazy"')}${badges ? `<div class="card-badges">${badges}</div>` : ''}<div class="card-overlay"><h3>${esc(cat.name)}</h3><p class="card-sub">${esc(cat.coat || '花色待补')} · <strong>${Number(cat.sightings)}</strong> 次目击</p><p class="meta">${icon('pin')}${esc(cat.area || '区域待补')}</p></div></div></a>`;
}
export function candidates(s) {
    return (s.candidates || []).length ? `<p class="hint">按框内花色、明暗和纹理列出相似档案，仍需核对脸部和四肢的花纹。</p><div class="gallery">${s.candidates.map(card).join('')}</div>` : `<p class="hint">暂无可比对的候选。可以保留待辨认，等有清晰照片再核对。</p>`;
}
export function formValues(form) {
    return Object.fromEntries(new FormData(form).entries());
}
