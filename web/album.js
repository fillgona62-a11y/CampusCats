import { back, btn, busy, date, empty, esc, head, icon, img, status } from './ui.js';
import { drawQr, fitText } from './qrcode.js';

function albumCats(visits, area) {
    const cats = new Map();
    // The API orders rows by the latest photo first, including ties.
    for (const visit of visits) {
        if (area && visit.area !== area) continue;
        const cat = cats.get(visit.cat_id);
        if (cat) {
            cat.encounters += visit.encounters;
            if (visit.first_at < cat.first_at) cat.first_at = visit.first_at;
        } else {
            cats.set(visit.cat_id, { ...visit });
        }
    }
    return [...cats.values()];
}

function albumCard(cat, area) {
    const href = '#encounter/' + Number(cat.frame_id) + '/' + Number(cat.sighting_id);
    return `<a class="album-card" href="${href}">
        <div class="album-photo">${img('/media/thumb/' + Number(cat.sighting_id) + '.jpg', cat.name, 'loading="lazy"')}
        <span>${cat.encounters === 1 ? '初遇' : '遇见 ' + Number(cat.encounters) + ' 次'}</span></div>
        <div class="album-caption"><h3>${esc(cat.name)}</h3>
        <p>${icon('pin')} 最近在${esc(cat.area)}</p><small>${area ? '此处初遇' : '初遇'} · ${esc(date(cat.first_at))}</small></div></a>`;
}

export function albumPage(main, data) {
    const all = albumCats(data.visits, '');
    const places = [...new Set(data.visits.map(visit => visit.area))];
    const total = Number(data.campus_total);
    main.innerHTML = `<div class="narrow">${back('#me', '返回我的手记')}
        <section class="album-cover"><div><h1>我的猫册</h1><p>校园已建档 ${total} 只，你遇见了 <strong>${all.length}</strong> 只。</p>
        ${total ? `<progress value="${all.length}" max="${total}" aria-label="我遇见的校园猫"></progress>` : ''}
        </div>${btn('#capture', '记录目击', 'camera', 'lime')}</section>
        ${data.pending ? `<p class="album-pending">${icon('time')} 还有 ${Number(data.pending)} 条目击待辨认。<a href="#me">查看手记</a></p>` : ''}
        <section><div class="section-head"><h2>相遇地点</h2>${places.length ? `<label class="album-filter"><span class="screen-reader">按校园区域筛选</span><select id="album-area"><option value="">全部区域</option>${places.map(place => `<option value="${esc(place)}">${esc(place)}</option>`).join('')}</select></label>` : ''}</div>
        <div id="album-cards" aria-live="polite"></div></section></div>`;
    const select = main.querySelector('#album-area');
    function show() {
        const area = select?.value || '';
        const cats = area ? albumCats(data.visits, area) : all;
        main.querySelector('#album-cards').innerHTML = cats.length ?
            `<p class="meta">${area ? esc(area) : '全部区域'} · ${cats.length} 只</p><div class="album-grid">${cats.map(cat => albumCard(cat, area)).join('')}</div>` :
            empty('book', data.pending ? '照片已收到，等认出它' : '留一页给你遇见的第一只猫',
                '目击的身份确认后，你拍的照片、时间和地点会收进这里。', btn('#capture', '记录一次目击', 'camera', 'light'));
    }
    if (select) select.onchange = show;
    show();
}

async function renderSouvenir(sighting, frame, element) {
    const photo = new Image();
    photo.src = '/media/crop/' + Number(sighting.id) + '.jpg';
    await photo.decode();
    const canvas = document.createElement('canvas');
    const dpr = 2;
    canvas.width = 800 * dpr;
    canvas.height = 930 * dpr;
    const ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);
    ctx.fillStyle = '#fffdf3';
    ctx.fillRect(0, 0, 800, 930);
    ctx.fillStyle = '#e5e6d9';
    ctx.fillRect(28, 28, 744, 585);
    const scale = Math.min(744 / photo.naturalWidth, 585 / photo.naturalHeight);
    const w = photo.naturalWidth * scale, h = photo.naturalHeight * scale;
    ctx.drawImage(photo, 28 + (744 - w) / 2, 28 + (585 - h) / 2, w, h);
    ctx.fillStyle = '#183b34';
    ctx.font = 'bold 46px "Songti SC","SimSun",serif';
    ctx.fillText(fitText(ctx, sighting.cat_name, 560), 36, 680);
    ctx.font = '25px "PingFang SC","Microsoft YaHei",sans-serif';
    ctx.fillStyle = '#38554b';
    ctx.fillText(fitText(ctx, frame.area + ' · ' + date(frame.observed_at), 560), 36, 738);
    ctx.fillText(sighting.encounter_number === 1 ? '初次相遇' : '第 ' + sighting.encounter_number + ' 次相遇', 36, 784);
    const catUrl = `${location.origin}/#cat/${Number(sighting.cat_id)}`;
    if (drawQr(ctx, catUrl, 628, 636, 140, '#163f37', '#ffffff')) {
        ctx.font = '16px "PingFang SC","Microsoft YaHei",sans-serif';
        ctx.fillStyle = '#526a60';
        ctx.fillText('扫码查看档案', 650, 796);
    }
    ctx.fillStyle = '#163f37';
    ctx.fillRect(0, 845, 800, 85);
    ctx.fillStyle = '#fffdf3';
    ctx.font = '25px "PingFang SC","Microsoft YaHei",sans-serif';
    ctx.fillText('猫迹 · 校园猫图鉴', 36, 897);
    const url = canvas.toDataURL('image/png');
    element.innerHTML = img(url, '可长按保存的相遇卡', 'class="souvenir-image"') +
        `<a class="link" href="${url}" download="猫迹-相遇卡-${Number(sighting.id)}.png">下载相遇卡</a><span class="hint">也可长按图片保存</span>`;
}

export function encounterPage(main, frame, selectedId) {
    main.innerHTML = `<div class="narrow">${back('#me', '返回我的手记')}
        ${head('这次相遇', date(frame.observed_at) + ' · ' + frame.area)}
        <div class="stack">${frame.sightings.map((s, index) => {
            const confirmed = s.status === 'confirmed';
            const title = confirmed ? s.cat_name : (s.status === 'pending' ? '等待辨认' : '未采纳的目击');
            const detail = confirmed ? (s.encounter_number === 1 ? '这是你第一次遇见它。' : '这是你第 ' + Number(s.encounter_number) + ' 次遇见它。') :
                (s.status === 'pending' ? '照片已保存。身份确认后，这只猫会出现在你的猫册里。' : '这条目击已结束审核。');
            return `<article class="encounter-card" id="encounter-cat-${Number(s.id)}" tabindex="-1">
                ${img('/media/crop/' + Number(s.id) + '.jpg', '本次目击的第 ' + (index + 1) + ' 只猫', 'loading="lazy"')}
                <div>${frame.sightings.length > 1 ? `<small>同框 · 第 ${index + 1} 只</small>` : ''}
                <h2>${esc(title)}</h2>${s.automatic ? '<span class="pill confirmed">已自动归档</span>' : status(s.status)}
                <p>${detail}</p>${confirmed ? `<div class="actions"><button class="btn" data-souvenir="${index}">制作相遇卡</button>${btn('#cat/' + Number(s.cat_id), '查看校园档案', 'book', 'light')}</div><div class="souvenir"></div>` : ''}</div></article>`;
        }).join('')}</div><div class="actions receipt-actions">${btn('#album', '打开我的猫册', 'book')}${btn('#capture', '记录下一次目击', 'camera', 'light')}</div></div>`;
    main.querySelectorAll('[data-souvenir]').forEach(button => {
        button.onclick = () => busy(button, () => renderSouvenir(frame.sightings[Number(button.dataset.souvenir)], frame, button.parentElement.nextElementSibling));
    });
    if (selectedId && frame.sightings.length > 1) document.getElementById('encounter-cat-' + selectedId)?.focus();
}
