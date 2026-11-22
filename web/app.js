import { api, back, btn, busy, card, date, empty, esc, formValues, head, icon, img, notice, status } from './ui.js';
import { capturePage } from './capture.js';
import { reviewPage, bindBreed } from './review.js';
const main = document.getElementById('content');
let serial = 0, clean = null, session = null, recoveryCode = '', lastFilter = '', filterArea = '';
const navItems = [['home', '首页', 'home'], ['atlas', '猫猫图鉴', 'book'], ['capture', '记录目击', 'camera'], ['me', '我的手记', 'user']];
function chrome(route) {
    let active = route === 'cat' ? 'atlas' : route;
    if (['login', 'register', 'recover'].includes(route))
        active = 'me';
    const items = [...navItems];
    if (session?.role === 'reviewer')
        items.push(['review', '维护', 'review']);
    for (const id of ['primary', 'mobile']) {
        document.getElementById(id).innerHTML = items.map(([key, text, symbol]) => `<a href="#${key}" ${key === active ? 'aria-current="page"' : ''}>${id === 'mobile' ? icon(symbol) : ''}${text}</a>`).join('');
    }
    document.getElementById('account').innerHTML = icon('user') + esc(session?.nickname || '登录');
    document.getElementById('account').href = session ? '#me' : '#login/me';
}
function home(data) {
    const stats = data.stats;
    main.innerHTML = `<section class="hero"><div class="hero-copy"><h1>校园猫图鉴</h1><p>拍下校园里的猫，用花纹认出老朋友，记下每一次相遇。</p>${btn('#capture', '记录一次目击', 'camera', 'lime')}</div>
    <figure class="hero-photo">${img('/assets/field-cat.jpg', '校园猫图鉴封面摄影', 'fetchpriority="high"')}<figcaption>封面摄影</figcaption></figure></section>
    <section class="stats" aria-label="校园猫数量统计">${[['cat', stats.cats, '只', '累计已建档'], ['time', stats.active, '只', '近 30 天有目击'], ['focus', stats.pending, '条', '待辨认记录']].map(([symbol, n, unit, label]) => `<div class="stat">${icon(symbol)}<div><strong>${Number(n)}<i>${unit}</i></strong><span>${label}</span></div></div>`).join('')}</section>
    <div class="section-head"><h2>最近目击的猫</h2><a href="#atlas">查看图鉴 ${icon('arrow')}</a></div>
    <div class="home-grid">${data.cats.length ? `<div class="gallery">${data.cats.slice(0, 3).map(card).join('')}</div>` : empty('cat', '第一只校园猫会是谁？', '拍下你遇见的猫。身份核实后，它就会出现在校园图鉴里。', btn('#capture', '提交第一条目击', 'camera', 'light'))}
    <a href="#guide" class="guide-tile"><span class="tile-icon">${icon('focus')}</span>${icon('arrow')}<div><h3>拍摄指南</h3><p>拍清花纹，也给辨认留下线索。</p></div></a></div>`;
}
function atlas(cats) {
    const areas = [...new Set(cats.map(c => c.area).filter(Boolean))].sort();
    if (!areas.includes(filterArea))
        filterArea = '';
    main.innerHTML = head('猫猫图鉴', '按名字、别名或花色，找找你见过的猫。') + `<div class="gallery-controls"><label class="search-box"><span class="screen-reader">搜索名字、别名或花色</span>${icon('search')}<input type="search" id="query" maxlength="80" placeholder="搜索名字、别名或花色"></label><select id="areas" aria-label="筛选区域"><option value="">全部区域</option>${areas.map(a => `<option value="${esc(a)}">${esc(a)}</option>`).join('')}</select></div><div id="gallery-results" aria-live="polite"></div>`;
    const input = main.querySelector('#query'), select = main.querySelector('#areas');
    input.value = lastFilter;
    select.value = filterArea;
    function filter() {
        lastFilter = input.value;
        filterArea = select.value;
        const q = lastFilter.trim().toLowerCase();
        const visible = cats.filter(cat => (!filterArea || cat.area === filterArea) && [cat.name, ...(cat.aliases || []), cat.coat, cat.breed].some(text => String(text || '').toLowerCase().includes(q)));
        main.querySelector('#gallery-results').innerHTML = visible.length ? `<p class="meta">共 ${visible.length} 只</p><div class="gallery">${visible.map(card).join('')}</div>` : cats.length ? empty('search', '没有找到匹配的猫', '可以试试别名、其他花色，或清除区域筛选。', '<button id="filter-reset" class="btn light">清除筛选</button>') : empty('book', '图鉴还在等第一只猫', '提交照片后，维护者会核对身份，并建立第一份档案。', btn('#capture', '记录一次目击', 'camera'));
        const reset = main.querySelector('#filter-reset');
        if (reset)
            reset.onclick = () => {
                input.value = '';
                select.value = '';
                filter();
            };
    }
    input.oninput = filter;
    select.onchange = filter;
    filter();
}
function entry(s) {
    const badge = s.identity_source === 'automatic' ? '<span class="pill confirmed">已自动归档</span>' : status(s.status);
    return `<article class="entry">${img(s.photo_url, '目击照片', 'loading="lazy"')}<div><h3>${s.cat_id ? `<a href="#cat/${Number(s.cat_id)}">${esc(s.cat_name || '已建档的猫')}</a>` : '目击记录 #' + Number(s.id)}</h3><p>${esc(s.area)} · ${esc(date(s.observed_at))}</p>${badge}${s.note ? `<p>${esc(s.note)}</p>` : ''}</div></article>`;
}
function catPage({ cat, sightings }) {
    const reviewer = session?.role === 'reviewer';
    main.innerHTML = back('#atlas', '返回猫猫图鉴') + `<div class="profile">${img(cat.photo_url, cat.name, 'class="photo"')}<div class="sheet">${head(cat.name, `档案 #${cat.id} · ${cat.sightings} 次目击`)}
 <p>${icon('pin')} ${esc(cat.area || '区域待补')} · 最近目击于${esc(date(cat.last_seen))}</p><p><strong>外观特征</strong>　${esc(cat.coat || '待补充')}</p>
 <p><strong>品种核验</strong>　${cat.breed_status === 'verified' ? esc(cat.breed) + '（已核验）' : '尚未确认'}</p>
 ${reviewer && cat.evidence ? `<p class="hint">核验记录 · ${esc(cat.evidence)}</p>` : ''}
 <p><strong>大家也叫它</strong>　${cat.aliases?.length ? cat.aliases.map(esc).join('、') : '暂无其他称呼'}</p>
 ${session ? `<details><summary>补充一个别名</summary><form id="alias"><label class="field"><span>你听过的称呼</span><input name="name" maxlength="40" required></label><p class="form-error"></p><button type="submit" class="btn light">提交别名审核</button></form></details>` : btn('#login/cat/' + cat.id, '登录后补充别名', '', 'light')}</div></div>
 ${reviewer ? `<details class="surface"><summary>维护品种核验</summary><form id="breed"><p>请根据能对应到这只猫的可靠来源核实。普通外观相似时保留“尚未确认”。</p><label class="field"><span>核验品种（留空可撤销）</span><input name="breed" maxlength="80" value="${esc(cat.breed || '')}"></label><label class="field"><span>可复核的证据来源或撤销原因</span><textarea name="evidence" required maxlength="800" rows="2"></textarea></label><p class="form-error"></p><button type="submit" class="btn">保存核验</button></form></details>` : ''}
 <div class="section-head"><h2>目击时间线</h2></div><div class="stack">${sightings.map(s => entry(s) + (reviewer ? `<details class="sheet"><summary>纠正目击 #${s.id} 的身份关联</summary><form data-reopen="${s.id}"><label class="field"><span>重审原因</span><input name="reason" required maxlength="400"></label><p class="form-error"></p><button type="submit" class="btn light">退回待辨认</button></form></details>` : '')).join('')}</div>`;
    const alias = main.querySelector('#alias');
    if (alias)
        alias.onsubmit = e => {
            e.preventDefault();
            busy(alias.querySelector('button'), async () => {
                await api(`/cats/${cat.id}/aliases`, formValues(alias));
                alias.reset();
                notice('别名已提交，审核通过后会出现在档案里。');
            });
        };
    const breed = main.querySelector('#breed');
    if (breed)
        bindBreed(breed, cat, route);
    main.querySelectorAll('[data-reopen]').forEach(form => form.onsubmit = e => {
        e.preventDefault();
        busy(form.querySelector('button'), async () => {
            await api(`/review/${form.dataset.reopen}`, { action: 'reopen', reason: form.elements.reason.value });
            notice('已退回待辨认。');
            location.hash = 'review';
        });
    });
}
function auth(mode, requested = 'me') {
    const target = /^(home|atlas|capture|me|review|cat\/\d+)$/.test(requested) ? requested : 'me';
    const create = mode === 'register', recover = mode === 'recover';
    const title = recover ? '找回密码' : create ? '创建观察账号' : '登录猫迹';
    main.innerHTML = `<div class="tiny">${back('#home', '返回首页')}${head(title, create ? '注册后可以提交目击，收集自己的重遇卡片。' : '')}<form class="surface" id="auth">${recover ? '' : `<div class="seg"><a class="${!create ? 'active' : ''}" href="#login/${target}">登录</a><a class="${create ? 'active' : ''}" href="#register/${target}">注册</a></div>`}
 <label class="field"><span>邮箱</span><input name="email" required type="email" autocomplete="email" maxlength="254"></label>
 ${create ? '<label class="field"><span>昵称</span><input name="nickname" required maxlength="32" autocomplete="nickname"></label>' : ''}
 ${recover ? '<label class="field"><span>账号恢复码</span><input name="recovery_code" required autocomplete="off"></label>' : ''}
 <label class="field"><span>${recover ? '新密码' : '密码'}</span><input name="password" required ${mode === 'login' ? '' : 'minlength="8"'} type="password" autocomplete="${mode === 'login' ? 'current-password' : 'new-password'}" maxlength="128">${mode === 'login' ? '' : '<small>至少 8 个字符。</small>'}</label><p class="form-error" role="alert"></p><div class="actions"><button type="submit" class="btn">${recover ? '重设密码' : create ? '注册并登录' : '登录'}</button>${mode === 'login' ? `<a class="link" href="#recover/${target}">忘记密码</a>` : ''}</div></form></div>`;
    const form = main.querySelector('form');
    form.onsubmit = e => {
        e.preventDefault();
        busy(form.querySelector('button'), async () => {
            const reply = await api('/' + mode, formValues(form));
            session = reply.user;
            recoveryCode = reply.recovery_code || '';
            chrome(mode);
            if (recoveryCode) {
                main.innerHTML = `<div class="tiny">${head('保存账号恢复码', '忘记密码时，可以用邮箱和恢复码重设密码。')}<section class="surface"><code style="user-select:all;overflow-wrap:anywhere">${esc(recoveryCode)}</code><p>请把这串字符保存到私人密码管理器。这一页关闭后将无法再次查看。</p>${btn('#' + target, '已保存，继续', 'arrow')}</section></div>`;
                recoveryCode = '';
            }
            else {
                notice('已登录。');
                if (location.hash === '#' + target)
                    await route();
                else
                    location.hash = target;
            }
        });
    };
}
async function saveReunion(r, element) {
    const fonts = '"Microsoft YaHei","PingFang SC",sans-serif';
    const get = async (url) => {
        const image = new Image();
        image.src = url;
        await image.decode();
        return image;
    };
    const photos = await Promise.all([get(r.first_photo_url), get(r.last_photo_url)]);
    const canvas = document.createElement('canvas');
    canvas.width = 1000;
    canvas.height = 770;
    const c = canvas.getContext('2d');
    c.fillStyle = '#f1f1df';
    c.fillRect(0, 0, 1000, 770);
    c.fillStyle = '#163f37';
    c.font = 'bold 46px ' + fonts;
    c.fillText(r.cat_name + '的重遇卡片', 35, 74, 920);
    c.font = '26px ' + fonts;
    c.fillText('相隔 ' + r.days + ' 天', 38, 125);
    photos.forEach((p, i) => {
        const x = 35 + i * 475, y = 165, w = 455, h = 450;
        c.fillStyle = '#dde0cd';
        c.fillRect(x, y, w, h);
        const scale = Math.min(w / p.naturalWidth, h / p.naturalHeight);
        const dw = p.naturalWidth * scale, dh = p.naturalHeight * scale;
        c.drawImage(p, x + (w - dw) / 2, y + (h - dh) / 2, dw, dh);
        c.fillStyle = '#163f37';
        c.font = '23px ' + fonts;
        c.fillText((i ? '最近目击' : '初次目击') + ' · ' + date(i ? r.last_at : r.first_at), x, 655, w);
    });
    c.fillStyle = '#526a60';
    c.font = '20px ' + fonts;
    c.fillText('猫迹 · 校园猫图鉴', 35, 731);
    element.innerHTML = img(canvas.toDataURL('image/png'), '可长按保存的重遇卡片', 'style="width:100%;height:auto;aspect-ratio:auto"') + '<p class="hint">可长按或右键保存卡片。</p>';
}
function me(data) {
    const { user, sightings, reunions } = data;
    main.innerHTML = `<div class="narrow">${head('我的手记', `${user.nickname} · ${user.email}`, `<button class="btn light" id="logout">退出登录</button>`)}
 ${user.role === 'reviewer' ? btn('#review', '进入维护工作台', 'review', 'light') : ''}
 <div class="section-head"><h2>重遇卡片</h2></div>${reunions.length ? reunions.map((r, i) => `<article class="recap"><h2>${esc(r.cat_name)} <span>相隔 ${Number(r.days)} 天</span></h2><div class="compare">${[[r.first_photo_url, r.first_at, '初次目击'], [r.last_photo_url, r.last_at, '最近目击']].map(([url, when, title]) => `<figure>${img(url, title, 'loading="lazy"')}<figcaption>${title} · ${esc(date(when))}</figcaption></figure>`).join('')}</div><button type="button" class="btn light" data-export="${i}">生成可保存卡片</button><div class="export-result"></div></article>`).join('') : empty('time', '下一次相遇，会留下对照', '再次记录同一只猫并确认身份后，就能在这里看到两次目击的照片。')}
 <div class="section-head"><h2>我的目击</h2><span>${sightings.length} 条</span></div><div class="stack">${sightings.length ? sightings.map(entry).join('') : empty('camera', '还没有目击记录', '在校园偶遇一只猫时，拍下一张照片。', btn('#capture', '记录目击', 'camera'))}</div>
 <details class="surface"><summary>账号管理</summary><form id="delete-account"><p>注销后将撤回你的目击、照片及由此产生的公开记录。请确认需要注销，再输入当前密码。</p><label class="field"><span>当前密码</span><input name="password" type="password" required autocomplete="current-password"></label><p class="form-error"></p><button class="btn light" type="submit">确认注销账号</button></form></details></div>`;
    const out = main.querySelector('#logout');
    out.onclick = () => busy(out, async () => {
        await api('/logout', {});
        session = null;
        location.hash = 'home';
        notice('已退出登录。');
    });
    main.querySelectorAll('[data-export]').forEach(b => b.onclick = () => busy(b, () => saveReunion(reunions[Number(b.dataset.export)], b.nextElementSibling)));
    const del = main.querySelector('#delete-account');
    del.onsubmit = e => {
        e.preventDefault();
        busy(del.querySelector('button'), async () => {
            await api('/account/delete', formValues(del));
            session = null;
            location.hash = 'home';
            notice('账号已注销。');
        });
    };
}
function guide() {
    main.innerHTML = `<div class="narrow">${back('#home', '返回首页')}${head('拍摄指南', '用看得清的照片，让下一位观察者有据可查。')}<section class="surface"><div class="guide-row"><h3>让猫留在原处</h3><p>保持距离，等它自然转身。用环境光拍下脸部、四肢或侧身。</p></div><div class="guide-row"><h3>给辨认留下线索</h3><p>尽量拍清鼻纹、足部白斑和尾部花色。如果猫在照片中太小，靠近裁切框比放大模糊图更有帮助。</p></div><div class="guide-row"><h3>同框时，逐只标记</h3><p>在照片上沿每只猫的身体画框，再逐一与已有档案比较。区域和时间可作为辅助线索。</p></div><div class="guide-row"><h3>分开记录花色和品种</h3><p>外观可以描述为“橘白短毛”。能对应到这只猫的可靠来源经维护者核对后，档案才会显示已核验的品种。</p></div></section>${btn('#capture', '去记录目击', 'camera')}</div>`;
}
async function route() {
    const version = ++serial;
    if (clean) {
        clean();
        clean = null;
    }
    const parts = location.hash.slice(1).split('/');
    let [page, id] = parts;
    if (!page || page === 'content')
        page = 'home';
    chrome(page);
    main.innerHTML = '<p class="loading">正在读取…</p>';
    window.scrollTo(0, 0);
    try {
        const personal = await api(page === 'me' ? '/me' : '/session');
        if (version !== serial)
            return;
        session = personal.user;
        chrome(page);
        if (['login', 'register', 'recover'].includes(page)) {
            auth(page, parts.slice(1).join('/') || 'me');
            return;
        }
        if (['capture', 'me', 'review'].includes(page) && !session) {
            auth('login', page);
            return;
        }
        if (page === 'me') {
            me(personal);
            return;
        }
        if (page === 'capture') {
            clean = capturePage(main, reply => {
                const automatic = reply.sightings.filter(s => s.identity_source === 'automatic').length;
                const pending = reply.sightings.filter(s => s.status === 'pending').length;
                const summary = [automatic && `${automatic} 条已自动归档`, pending && `${pending} 条待辨认`].filter(Boolean);
                notice(summary.length ? `${summary.join('，')}。可在手记查看。` : '提交成功，可在手记查看。');
                location.hash = 'me';
            });
            return;
        }
        if (page === 'guide') {
            guide();
            return;
        }
        if (page === 'review') {
            if (session?.role !== 'reviewer') {
                main.innerHTML = empty('review', '此页面需维护者权限', '可以返回首页浏览已建档的校园猫。', btn('#home', '返回首页'));
                return;
            }
            const [r, h] = await Promise.all([api('/review'), api('/home')]);
            if (version === serial)
                reviewPage(main, r, h.cats, route);
            return;
        }
        if (page === 'cat' && /^\d+$/.test(id)) {
            const d = await api('/cats/' + id);
            if (version === serial)
                catPage(d);
            return;
        }
        const result = await api('/home');
        if (version !== serial)
            return;
        if (page === 'atlas')
            atlas(result.cats);
        else
            home(result);
    }
    catch (e) {
        if (version === serial) {
            main.innerHTML = empty('focus', '暂时无法读取', e.message, '<button class="btn light" id="retry">重新读取</button>');
            main.querySelector('#retry').onclick = route;
        }
    }
}
window.addEventListener('hashchange', route);
window.addEventListener('pagehide', () => {
    if (clean)
        clean();
});
window.addEventListener('pageshow', e => {
    if (e.persisted)
        route();
});
if ('serviceWorker' in navigator && isSecureContext)
    navigator.serviceWorker.register('/sw.js').catch(() => { });
route();
