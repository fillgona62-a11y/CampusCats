import { CARE_LABELS, NEUTERED_LABELS, SEX_LABELS, api, back, btn, busy, card, catSearchText, catTags, date, empty, esc, formValues, head, icon, img, notice, status } from './ui.js';
import { drawQr, fitText } from './qrcode.js';
import { capturePage } from './capture.js';
import { albumPage, encounterPage } from './album.js';
import { initAgentWidget } from './agent.js';
import { agentSettings } from './agent-settings.js';
import { surveyPage } from './surveys.js';
import { reviewPage, bindBreed } from './review.js';
import { campusMapPage } from './campus-map.js';
import { badgeList, communityPage } from './community.js';
const installedAndroid = location.pathname === '/_app/index.html';
const main = document.getElementById('content');
let serial = 0, clean = null, session = null, recoveryCode = '', lastFilter = '', filterArea = '', filterTag = '';

let androidAppInfo = null;
function getAndroidAppInfo() {
    if (!installedAndroid) return null;
    if (androidAppInfo) return androidAppInfo;
    try {
        const raw = window.prompt('campuscats-app:info', '');
        if (raw) androidAppInfo = JSON.parse(raw);
    } catch {}
    return androidAppInfo;
}

async function checkAppUpdate(manual = false) {
    if (!installedAndroid) return;
    const local = getAndroidAppInfo();
    try {
        const remote = await api('/app/version');
        if (!remote || !remote.version_code) return;
        const hasNew = !local || Number(remote.version_code) > Number(local.versionCode || 0);
        if (hasNew) {
            let bar = document.getElementById('app-update-bar');
            if (!bar) {
                bar = document.createElement('div');
                bar.id = 'app-update-bar';
                bar.className = 'app-update-bar';
                document.querySelector('.mast')?.after(bar);
            }
            bar.innerHTML = `<div class="shell app-update-inner"><span>发现客户端新版本 <strong>v${esc(remote.version_name)}</strong>${remote.notes ? ' · ' + esc(remote.notes) : ''}</span><div class="app-update-actions"><button type="button" class="btn" id="app-update-go">立即更新</button><button type="button" class="btn ghost" id="app-update-dismiss" aria-label="稍后再说">稍后</button></div></div>`;
            bar.querySelector('#app-update-go').onclick = () => {
                window.prompt('campuscats-app:update', remote.apk_url || '/downloads/CampusCats-Android.apk');
            };
            bar.querySelector('#app-update-dismiss').onclick = () => bar.remove();
            if (manual) notice(`发现新版本 v${remote.version_name}，点击顶部横幅立即安装。`);
        } else if (manual) {
            notice(`当前已是最新版客户端（v${local.versionName}）。`);
        }
    } catch {
        if (manual) notice('检查更新失败，请检查网络连接。');
    }
}

function androidUpdateBox() {
    if (!installedAndroid) return '';
    const info = getAndroidAppInfo();
    const verText = info?.versionName ? `当前客户端版本：v${esc(info.versionName)}（界面已支持联网自动热更新）` : '界面已支持联网自动热更新';
    return `<details class="surface"><summary>客户端版本与自助更新</summary><p class="hint">${verText}</p><div class="actions"><button type="button" class="btn light" data-check-update>检查客户端更新</button></div></details>`;
}

function androidOriginBox() {
    if (!installedAndroid) return '';
    return `<details class="surface"><summary>切换校园站点地址</summary><form class="android-origin-form"><p>默认连接预设校园服务器。学校更换域名时可在此填入新的 HTTPS 地址。</p><label class="field"><span>站点 HTTPS 地址</span><input name="origin" type="url" placeholder="https://cats.school.edu.cn" value="${esc(location.origin)}"></label><div class="actions"><button type="submit" class="btn light">保存并重连</button><button type="button" class="btn ghost" data-origin-reset>恢复默认地址</button></div></form></details>`;
}

function bindAndroidOrigin(container) {
    if (!installedAndroid) return;
    container.querySelectorAll('[data-check-update]').forEach(btnEl => {
        btnEl.onclick = () => busy(btnEl, () => checkAppUpdate(true));
    });
    container.querySelectorAll('.android-origin-form').forEach(form => {
        form.onsubmit = e => {
            e.preventDefault();
            const val = form.elements.origin.value.trim().replace(/\/+$/, '');
            if (!window.prompt('campuscats-origin:set', val))
                notice('请输入合法的 HTTPS 站点根地址（不含路径和参数）。');
        };
        const reset = form.querySelector('[data-origin-reset]');
        if (reset) reset.onclick = () => window.prompt('campuscats-origin:reset', '');
    });
}
const navItems = [['home', '首页', 'home'], ['atlas', '猫猫图鉴', 'book'], ['capture', '记录目击', 'camera'], ['me', '我的手记', 'user']];
function chrome(route) {
    let active = route === 'cat' ? 'atlas' : route === 'device-capture' ? 'capture' : route === 'device' ? 'me' : route;
    if (['login', 'register', 'recover', 'album', 'encounter'].includes(route))
        active = 'me';
    const items = [...navItems];
    if (session?.role === 'reviewer')
        items.push(['review', '维护', 'review']);
    for (const id of ['primary', 'mobile']) {
        document.getElementById(id).innerHTML = items.map(([key, text, symbol]) => `<a href="#${key === 'capture' && installedAndroid && !session ? 'device-capture' : key}" ${key === active ? 'aria-current="page"' : ''}>${id === 'mobile' ? icon(symbol) : ''}${text}</a>`).join('');
    }
    document.getElementById('account').innerHTML = icon('user') + esc(session?.nickname || '登录');
    document.getElementById('account').href = session ? '#me' : '#login/me';
}
function home(data = null, unavailable = false) {
    const capture = installedAndroid && (!data || !session) ? '#device-capture' : '#capture';
    const shortcuts = [['map','pin','沈理猫地图'], ['album','book','我的猫册'], ['surveys','time','定点观察'], ['guide','focus','拍摄指南']];
    if (installedAndroid) shortcuts.unshift(['device','image','本机草稿']);
    const allZero = data && Number(data.stats.cats) === 0 && Number(data.stats.active) === 0 && Number(data.stats.pending) === 0;
    const statsBlock = allZero
        ? `<div class="field-welcome"><strong>图鉴刚刚开张</strong><span>等你拍下校园里的第一只猫</span></div>`
        : `<dl class="field-counts" aria-label="校园目击统计">${[['cats','已建档','只'],['active','近30天见过','只'],['pending','待辨认','条']].map(([key,label,unit]) => `<div><dt>${label}</dt><dd>${data ? Number(data.stats[key]) : '—'}<small>${unit}</small></dd></div>`).join('')}</dl>`;
    main.innerHTML = `<div class="field-home"><section class="field-cover">
      <img src="/assets/field-cat.jpg" alt="阳光树荫下趴在校园石阶上的猫" fetchpriority="high">
      <div><h1>沈阳理工校园猫图鉴</h1><p class="cover-sub">沈阳理工大学校内测试 · 记下琴园与兵器广场边的每一次相遇。</p>${btn(capture, '拍照记录', 'camera', 'cover-action')}</div>
    </section>
    <div class="home-actions-row">
      <a class="photo-lookup" href="#lookup">${icon('search')}<div><strong>照片查查</strong><span>查重 · 识别花色</span></div>${icon('arrow')}</a>
      <button type="button" class="home-agent-btn" id="home-agent">${icon('cat')}<div><strong>猫猫助手</strong><span>问找猫 · 查近期目击</span></div>${icon('arrow')}</button>
    </div>
    <a class="album-shortcut" href="#community">${icon('focus')}<div><strong>校园猫论坛</strong><small>${data?.community_inbox ? `有 ${Number(data.community_inbox)} 条辨认或命名等你参与` : '参与身份投票与新猫命名'}</small></div>${icon('arrow')}</a>
    ${statsBlock}
    <section><div class="section-head"><h2>最近目击</h2><a href="#atlas">全部图鉴 ${icon('arrow')}</a></div>
      ${data?.cats.length ? `<div class="gallery${data.cats.length === 1 ? ' single' : ''}">${data.cats.slice(0,3).map(card).join('')}</div>` :
        `<div class="field-empty">${icon('cat')}<div><strong>${data ? '还没有已建档的猫' : unavailable ? '图鉴暂时连不上' : '正在读取图鉴…'}</strong>${data ? '<p>第一只猫建档后，照片就会出现在这里。</p>' : unavailable ? '<button type="button" class="link" id="retry">重新连接</button>' : ''}</div></div>`}
    </section>
    <div class="field-links cols-${shortcuts.length}">${shortcuts.map(([url,symbol,title]) => `<a href="#${url}">${icon(symbol)}<span>${title}</span>${icon('arrow')}</a>`).join('')}</div>${unavailable ? androidOriginBox() : ''}</div>`;
    if (unavailable) {
        main.querySelector('#retry').onclick = route;
        bindAndroidOrigin(main);
    }
    main.querySelector('#home-agent').onclick = () => document.querySelector('#agent-fab').click();
}
function atlas(cats) {
    const areas = [...new Set(cats.map(c => c.area).filter(Boolean))].sort();
    if (!areas.includes(filterArea))
        filterArea = '';
    main.innerHTML = head('猫猫图鉴', '按名字、别名、花色或状态，找找你见过的猫。') + `<div class="gallery-controls"><label class="search-box"><span class="screen-reader">搜索名字、别名、花色或性格</span>${icon('search')}<input type="search" id="query" maxlength="80" placeholder="搜索名字、别名、花色或性格"></label><select id="areas" aria-label="筛选区域"><option value="">全部区域</option>${areas.map(a => `<option value="${esc(a)}">${esc(a)}</option>`).join('')}</select><select id="tag-filter" aria-label="筛选状态"><option value="">全部状态</option><option value="neutered">已绝育</option><option value="intact">未绝育</option><option value="attention">需关注健康</option><option value="adopted">已领养毕业</option></select></div><div id="gallery-results" aria-live="polite"></div>`;
    const input = main.querySelector('#query'), select = main.querySelector('#areas'), tagSelect = main.querySelector('#tag-filter');
    input.value = lastFilter;
    select.value = filterArea;
    tagSelect.value = filterTag;
    function matchTag(cat) {
        if (!filterTag) return true;
        if (filterTag === 'neutered' || filterTag === 'intact') return cat.neutered === filterTag;
        return cat.care_status === filterTag;
    }
    function filter() {
        lastFilter = input.value;
        filterArea = select.value;
        filterTag = tagSelect.value;
        const q = lastFilter.trim().toLowerCase();
        const visible = cats.filter(cat => (!filterArea || cat.area === filterArea) && matchTag(cat) && (!q || catSearchText(cat).includes(q)));
        main.querySelector('#gallery-results').innerHTML = visible.length ? `<p class="meta">共 ${visible.length} 只</p><div class="gallery">${visible.map(card).join('')}</div>` : cats.length ? empty('search', '没有找到匹配的猫', '可以试试别名、其他花色，或清除筛选条件。', '<button id="filter-reset" class="btn light">清除筛选</button>') : empty('book', '图鉴还在等第一只猫', '提交照片后，维护者会核对身份，并建立第一份档案。', btn('#capture', '记录一次目击', 'camera'));
        const reset = main.querySelector('#filter-reset');
        if (reset)
            reset.onclick = () => {
                input.value = '';
                select.value = '';
                tagSelect.value = '';
                filter();
            };
    }
    input.oninput = filter;
    select.onchange = filter;
    tagSelect.onchange = filter;
    filter();
}
function entry(s) {
    const badge = s.identity_source === 'automatic' ? '<span class="pill confirmed">已自动归档</span>' : status(s.status);
    return `<article class="entry">${img('/media/thumb/' + Number(s.id) + '.jpg', '目击照片', 'loading="lazy"')}<div><h3>${s.cat_id ? `<a href="#cat/${Number(s.cat_id)}">${esc(s.cat_name || '已建档的猫')}</a>` : '目击记录 #' + Number(s.id)}</h3><p>${esc(s.area)} · ${esc(date(s.observed_at))}${typeof s.latitude === 'number' && typeof s.longitude === 'number' ? ` · 坐标 ${s.latitude.toFixed(4)}, ${s.longitude.toFixed(4)}` : ''}</p>${badge}${s.note ? `<p>${esc(s.note)}</p>` : ''}</div>${s.frame_id ? `<a class="link" href="#encounter/${Number(s.frame_id)}">查看这次相遇</a>` : ''}</article>`;
}
function catPage({ cat, sightings }, allCats = []) {
    const reviewer = session?.role === 'reviewer';
    const mergeTargets = allCats.filter(c => c.id !== cat.id);
    main.innerHTML = back('#atlas', '返回猫猫图鉴') + `<div class="profile">${img(cat.photo_url, cat.name, 'class="photo"')}<div class="sheet">${head(cat.name, `档案 #${cat.id} · ${cat.sightings} 次目击`)}${catTags(cat)}
 <p>${icon('pin')} ${esc(cat.area || '区域待补')} · 最近目击于${esc(date(cat.last_seen))}</p><p><strong>外观特征</strong>　${esc(cat.coat || '待补充')}</p>
 <p><strong>性别与绝育</strong>　${esc(SEX_LABELS[cat.sex] || '性别待确认')} · ${esc(NEUTERED_LABELS[cat.neutered] || '绝育待确认')} · ${esc(CARE_LABELS[cat.care_status] || '在校活跃')}</p>
 ${cat.temperament ? `<p><strong>相处提示</strong>　${esc(cat.temperament)}</p>` : ''}
 <p><strong>品种核验</strong>　${cat.breed_status === 'verified' ? esc(cat.breed) + '（已核验）' : '尚未确认'}</p>
 ${reviewer && cat.evidence ? `<p class="hint">核验记录 · ${esc(cat.evidence)}</p>` : ''}
 <p><strong>大家也叫它</strong>　${cat.aliases?.length ? cat.aliases.map(esc).join('、') : '暂无其他称呼'}</p>
 ${session ? `<details><summary>补充一个别名</summary><form id="alias"><label class="field"><span>你听过的称呼</span><input name="name" maxlength="40" required></label><p class="form-error"></p><button type="submit" class="btn light">提交别名审核</button></form></details>` : btn('#login/cat/' + cat.id, '登录后补充别名', '', 'light')}</div></div>
 ${reviewer ? `<details class="surface"><summary>编辑档案信息（花色 · 绝育 · 状态 · 性格）</summary><form id="cat-profile"><div class="form-grid"><label class="field"><span>档案名</span><input name="name" required maxlength="60" value="${esc(cat.name)}"></label><label class="field"><span>花色或毛长</span><input name="coat" maxlength="80" value="${esc(cat.coat || '')}"></label></div>
 <div class="form-grid"><label class="field"><span>性别</span><select name="sex">${Object.entries(SEX_LABELS).map(([k, v]) => `<option value="${k}" ${cat.sex === k ? 'selected' : ''}>${esc(v)}</option>`).join('')}</select></label>
 <label class="field"><span>绝育状态</span><select name="neutered">${Object.entries(NEUTERED_LABELS).map(([k, v]) => `<option value="${k}" ${cat.neutered === k ? 'selected' : ''}>${esc(v)}</option>`).join('')}</select></label>
 <label class="field"><span>在校状态</span><select name="care_status">${Object.entries(CARE_LABELS).map(([k, v]) => `<option value="${k}" ${cat.care_status === k ? 'selected' : ''}>${esc(v)}</option>`).join('')}</select></label></div>
 <label class="field"><span>性格与相处提示</span><input name="temperament" maxlength="120" value="${esc(cat.temperament || '')}" placeholder="例如，亲人可摸 / 怕生勿扰 / 护食勿碰"></label>
 <label class="field"><span>更新说明（选填）</span><input name="reason" maxlength="400" placeholder="例如，春季绝育回放登记"></label>
 <p class="form-error"></p><div class="actions"><button type="submit" class="btn">保存档案信息</button>${cat.cover_sighting_id ? `<button type="button" class="btn light" id="clear-cover">恢复默认最新照封面</button>` : ''}</div></form></details>
 <details class="surface"><summary>维护品种核验</summary><form id="breed"><p>请根据能对应到这只猫的可靠来源核实。普通外观相似时保留“尚未确认”。</p><label class="field"><span>核验品种（留空可撤销）</span><input name="breed" maxlength="80" value="${esc(cat.breed || '')}"></label><label class="field"><span>可复核的证据来源或撤销原因</span><textarea name="evidence" required maxlength="800" rows="2"></textarea></label><p class="form-error"></p><button type="submit" class="btn">保存核验</button></form></details>
 ${mergeTargets.length ? `<details class="surface"><summary>合并重复档案</summary><form id="merge-cat"><p>若确认当前档案「${esc(cat.name)}」与另一份已有档案其实是同一只猫，可将其目击记录与别名合并过去。原档案名会自动保留为别名。</p><label class="field"><span>并入目标档案</span><select name="target_id" required><option value="">选择保留的目标档案</option>${mergeTargets.map(t => `<option value="${Number(t.id)}">${esc(t.name)} (#${Number(t.id)} · ${esc(t.coat || '花色待补')})</option>`).join('')}</select></label><label class="field"><span>合并依据</span><textarea name="reason" required maxlength="800" rows="2" placeholder="写明判断为同一只猫的花纹或线下核实依据"></textarea></label><p class="form-error"></p><button type="submit" class="btn light">确认合并档案</button></form></details>` : ''}` : ''}
 <div class="section-head"><h2>目击时间线</h2></div><div class="stack">${sightings.map(s => entry(s) + (reviewer ? `<details class="sheet"><summary>维护目击 #${s.id}${cat.cover_sighting_id === s.id ? '（当前精选封面）' : ''}</summary><div class="actions" style="margin-bottom:10px">${cat.cover_sighting_id === s.id ? '<span class="pill confirmed">当前档案封面</span>' : `<button type="button" class="btn light" data-pin-cover="${s.id}">设为档案封面</button>`}</div><form data-reopen="${s.id}"><label class="field"><span>重审退回原因</span><input name="reason" required maxlength="400"></label><p class="form-error"></p><button type="submit" class="btn light">退回待辨认</button></form></details>` : '')).join('')}</div>`;
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
    const profileForm = main.querySelector('#cat-profile');
    if (profileForm) {
        profileForm.onsubmit = e => {
            e.preventDefault();
            busy(profileForm.querySelector('[type=submit]'), async () => {
                await api(`/cats/${cat.id}/profile`, formValues(profileForm));
                notice('档案信息已更新。');
                await route();
            }, profileForm);
        };
        const clearCover = main.querySelector('#clear-cover');
        if (clearCover) {
            clearCover.onclick = () => busy(clearCover, async () => {
                await api(`/cats/${cat.id}/profile`, { cover_sighting_id: null, reason: '恢复默认封面' });
                notice('已恢复默认最新照封面。');
                await route();
            });
        }
    }
    const mergeForm = main.querySelector('#merge-cat');
    if (mergeForm) {
        mergeForm.onsubmit = e => {
            e.preventDefault();
            busy(mergeForm.querySelector('[type=submit]'), async () => {
                const v = formValues(mergeForm);
                const res = await api(`/cats/${cat.id}/merge`, { target_id: Number(v.target_id), reason: v.reason.trim() });
                notice('档案已合并。');
                location.hash = 'cat/' + res.target_id;
            }, mergeForm);
        };
    }
    main.querySelectorAll('[data-pin-cover]').forEach(b => b.onclick = () => busy(b, async () => {
        await api(`/cats/${cat.id}/profile`, { cover_sighting_id: Number(b.dataset.pinCover), reason: '设置精选封面照' });
        notice('已设为档案封面照。');
        await route();
    }));
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
    const target = /^(home|atlas|map|agent-settings|capture(?:\/\d{1,16})?|community(?:\/\d{1,5})?|me|review|album|surveys|cat\/\d{1,18}|encounter\/\d{1,18}(?:\/\d{1,18})?)$/.test(requested) ? requested : 'me';
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
            resetAgent();
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
    const dpr = 2;
    canvas.width = 1000 * dpr;
    canvas.height = 800 * dpr;
    const c = canvas.getContext('2d');
    c.scale(dpr, dpr);
    c.fillStyle = '#f1f1df';
    c.fillRect(0, 0, 1000, 800);
    c.fillStyle = '#163f37';
    c.font = 'bold 46px ' + fonts;
    c.fillText(fitText(c, r.cat_name + '的重遇卡片', 780), 35, 74);
    c.font = '26px ' + fonts;
    c.fillText('相隔 ' + r.days + ' 天', 38, 125);
    photos.forEach((p, i) => {
        const x = 35 + i * 475, y = 160, w = 455, h = 445;
        c.fillStyle = '#dde0cd';
        c.fillRect(x, y, w, h);
        const scale = Math.min(w / p.naturalWidth, h / p.naturalHeight);
        const dw = p.naturalWidth * scale, dh = p.naturalHeight * scale;
        c.drawImage(p, x + (w - dw) / 2, y + (h - dh) / 2, dw, dh);
        c.fillStyle = '#163f37';
        c.font = '23px ' + fonts;
        c.fillText(fitText(c, (i ? '最近目击' : '初次目击') + ' · ' + date(i ? r.last_at : r.first_at), w), x, 645);
    });
    const catUrl = `${location.origin}/#cat/${Number(r.cat_id)}`;
    if (drawQr(c, catUrl, 855, 665, 110, '#163f37', '#ffffff')) {
        c.fillStyle = '#526a60';
        c.font = '16px ' + fonts;
        c.fillText('扫码查看校园档案', 715, 755);
    }
    c.fillStyle = '#526a60';
    c.font = '21px ' + fonts;
    c.fillText('猫迹 · 校园猫图鉴', 35, 755);
    const url = canvas.toDataURL('image/png');
    element.innerHTML = img(url, '可长按保存的重遇卡片', 'style="width:100%;height:auto;aspect-ratio:auto"') +
        `<div class="actions" style="margin-top:8px"><a class="link" href="${url}" download="猫迹-重遇卡-${Number(r.cat_id)}.png">下载重遇卡</a><span class="hint">也可长按或右键保存卡片。</span></div>`;
}
function me(data) {
    const { user, sightings, reunions } = data;
    main.innerHTML = `<div class="narrow">${head('我的手记', `${user.nickname} · ${user.email}`, `<button class="btn light" id="logout">退出登录</button>`)}
 ${user.role === 'reviewer' ? btn('#review', '进入维护工作台', 'review', 'light') : ''}
 <section class="surface"><h2>我的徽章</h2>${badgeList(data.badges)}${btn('#community', data.community_inbox ? `校园猫论坛 · ${Number(data.community_inbox)} 条可参与` : '校园猫论坛', 'focus', 'light')}</section>
 <a class="album-shortcut" href="#album">${icon('book')}<div><strong>我的猫册</strong><small>按校园区域翻看你遇见的猫</small></div>${icon('arrow')}</a>
 ${btn('#surveys', '继续定点观察或查看周报', 'pin', 'light')}
 <div class="section-head"><h2>重遇卡片</h2></div>${reunions.length ? reunions.map((r, i) => `<article class="recap"><h2>${esc(r.cat_name)} <span>相隔 ${Number(r.days)} 天</span></h2><div class="compare">${[[r.first_photo_url, r.first_at, '初次目击'], [r.last_photo_url, r.last_at, '最近目击']].map(([url, when, title]) => `<figure>${img(url, title, 'loading="lazy"')}<figcaption>${title} · ${esc(date(when))}</figcaption></figure>`).join('')}</div><button type="button" class="btn light" data-export="${i}">生成可保存卡片</button><div class="export-result"></div></article>`).join('') : empty('time', '下一次相遇，会留下对照', '再次记录同一只猫并确认身份后，就能在这里看到两次目击的照片。')}
 <div class="section-head"><h2>我的目击</h2><span>${sightings.length} 条</span></div><div class="stack">${sightings.length ? sightings.map(entry).join('') : empty('camera', '还没有目击记录', '在校园偶遇一只猫时，拍下一张照片。', btn('#capture', '记录目击', 'camera'))}</div>
 ${androidUpdateBox()}
 ${androidOriginBox()}
 <details class="surface"><summary>猫猫助手与模型设置</summary><p class="hint">可在此配置你的个人 AI 接口${user.role === 'reviewer' ? '或全校共用的模型服务' : ''}，未设置时默认使用校园图鉴助手。</p><div class="actions">${btn('#agent-settings', '配置 AI 助手接口', 'focus', 'light')}</div></details>
 <details class="surface"><summary>账号管理</summary><form id="delete-account"><p>注销后将撤回你的目击、照片及由此产生的公开记录。请确认需要注销，再输入当前密码。</p><label class="field"><span>当前密码</span><input name="password" type="password" required autocomplete="current-password"></label><p class="form-error"></p><button class="btn light" type="submit">确认注销账号</button></form></details></div>`;
    bindAndroidOrigin(main);
    const out = main.querySelector('#logout');
    out.onclick = () => busy(out, async () => {
        await api('/logout', {});
        resetAgent();
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
            resetAgent();
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
    main.dataset.page = page;
    chrome(page);
    main.innerHTML = '<p class="loading">正在读取…</p>';
    window.scrollTo(0, 0);
    const localLinks = btn('#device', '本机草稿', 'book', 'light') + btn('#guide', '拍摄指南', 'focus', 'light');
    try {
        if (page === 'guide') { guide(); return; }
        if (page === 'lookup') {
            clean = capturePage(main, null, {lookupOnly:true});
            return;
        }
        if (installedAndroid && (page === 'device' || page === 'device-capture')) {
            const device = await import('./device.js');
            if (version !== serial) return;
            if (page === 'device') await device.devicePage(main, () => version === serial);
            else clean = capturePage(main, () => { location.hash = 'device'; }, {saveLocal:device.saveNote});
            return;
        }
        if (installedAndroid && page === 'home')
            home();
        const personal = await api(page === 'me' ? '/me' : '/session');
        if (version !== serial)
            return;
        if (session?.id !== personal.user?.id) resetAgent();
        session = personal.user;
        chrome(page);
        if (['login', 'register', 'recover'].includes(page)) {
            auth(page, parts.slice(1).join('/') || 'me');
            return;
        }
        if (['capture', 'me', 'review', 'album', 'encounter', 'agent-settings', 'community'].includes(page) && !session) {
            auth('login', parts.join('/'));
            return;
        }
        if (page === 'me') {
            me(personal);
            return;
        }
        if (page === 'community') {
            const number = /^\d{1,5}$/.test(id || '') ? Number(id) : 0;
            const board = await api(number ? '/community/page/' + number : '/community');
            if (version === serial) communityPage(main, board, number, () => version === serial && route());
            return;
        }
        if (page === 'agent-settings') {
            const settings = await api('/agent/settings');
            if (version === serial) agentSettings(main, settings, resetAgent);
            return;
        }
        if (page === 'surveys') {
            const data = await api('/surveys');
            if (version === serial) clean = surveyPage(main, data, session, route);
            return;
        }
        if (page === 'album') {
            const data = await api('/me/album');
            if (version === serial) albumPage(main, data);
            return;
        }
        if (page === 'encounter' && /^\d{1,18}$/.test(id)) {
            const data = await api('/me/frames/' + id);
            if (version === serial) encounterPage(main, data, parts[2]);
            return;
        }
        if (page === 'capture') {
            let draft = null, device = null;
            if (installedAndroid && id) {
                device = await import('./device.js');
                draft = await device.getNote(id);
                if (version !== serial) return;
                if (!draft) throw new Error('本机未找到这份草稿。');
            }
            clean = capturePage(main, reply => {
                if (draft) device.removeNote(draft.id).catch(() => notice('已上传，可在本机草稿中删除原稿。'));
                if (reply.community?.length) {
                    notice(reply.community.some(topic => topic.state === 'private_name') ? '发现了新猫，请在论坛为它命名。' : '需要辨认的目击已发布到校园猫论坛。');
                    location.hash = 'community';
                } else {
                    location.hash = 'encounter/' + reply.sightings[0].frame_id;
                }
            }, {draft});
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
            const [d, homeData] = await Promise.all([
                api('/cats/' + id),
                session?.role === 'reviewer' ? api('/home').catch(() => ({ cats: [] })) : Promise.resolve({ cats: [] }),
            ]);
            if (version === serial)
                catPage(d, homeData.cats || []);
            return;
        }
        const result = await api('/home');
        if (version !== serial)
            return;
        if (page === 'map')
            clean = await campusMapPage(main, result.cats, areaName => {
                sessionStorage.setItem('campuscats:prefill-area', areaName);
                location.hash = installedAndroid && !session ? 'device-capture' : 'capture';
            }, () => version === serial);
        else if (page === 'atlas')
            atlas(result.cats);
        else
            home(result);
    }
    catch (e) {
        if (version === serial) {
            if (installedAndroid && page === 'home') { home(null, true); return; }
            main.innerHTML = empty('focus', '暂时无法读取', e.message, '<div class="actions"><button class="btn light" id="retry">重新读取</button>' + (installedAndroid ? localLinks : '') + '</div>') + androidOriginBox();
            main.querySelector('#retry').onclick = route;
            bindAndroidOrigin(main);
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
if (!installedAndroid && 'serviceWorker' in navigator && isSecureContext)
    navigator.serviceWorker.register('/sw.js').catch(() => { });
const resetAgent = initAgentWidget();
route();
if (installedAndroid) checkAppUpdate(false);
