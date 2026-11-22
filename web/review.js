import { api, back, busy, btn, card, date, empty, esc, formValues, head, img, notice, status } from './ui.js';
export function reviewPage(main, data, cats, refresh) {
    main.innerHTML = `<div class="narrow">${head('维护工作台', '逐只核对目击照片和档案。证据不足时可以保留待辨认。')}
    <div class="section-head"><h2>待辨认目击</h2><span>${data.sightings.length} 条</span></div>
    ${data.sightings.map(s => `<article class="surface" data-review="${s.id}"><h2>目击 #${s.id}</h2><p>${esc(date(s.observed_at))} · ${esc(s.area)} ${status(s.status)}</p>
    ${s.note ? `<p>${esc(s.note)}</p>` : ''}${s.suggested_cat_id ? `<p class="advice">提交者建议匹配档案 #${Number(s.suggested_cat_id)}。</p>` : ''}
    ${s.frame_url ? `<details><summary>查看同框全图</summary>${img(s.frame_url, '本次上传的完整画面', 'style="display:block;max-width:100%;max-height:380px;margin:10px auto"')}</details>` : ''}
    <div class="compare"><figure>${img(s.photo_url, '待辨认的猫', 'loading="lazy"')}<figcaption>本次目击</figcaption></figure><figure class="ref-image"></figure></div>
    ${s.quality?.length ? `<p class="advice">${esc(s.quality.join(' '))}</p>` : ''}
    <details class="pending-peers"><summary>对照其他待辨认照片</summary><div class="peer-list"></div></details>
    <form><label class="field"><span>复核决定</span><select name="action" required><option value="">选择操作</option><option value="match">关联已有档案</option><option value="new">确认为新猫并建档</option><option value="reject">未采纳这条目击</option></select></label>
    <label class="field" data-part="match" hidden><span>对照档案</span><select name="cat_id"><option value="">选择已有档案</option></select></label>
    <div data-part="new" hidden><label class="field"><span>档案名</span><input name="name" maxlength="50"></label><label class="field"><span>花色或毛长</span><input name="coat" maxlength="60" placeholder="例如，橘白短毛"></label></div>
    <label class="field"><span>核对依据</span><textarea name="reason" required maxlength="800" rows="2" placeholder="写明可辨认的花纹、部位或未采纳原因"></textarea></label><p class="form-error" role="alert"></p><button class="btn" type="submit">保存复核决定</button></form></article>`).join('') || empty('review', '暂无待辨认目击', '新的待辨认记录会出现在这里。')}
    <div class="section-head"><h2>待审核别名</h2><span>${data.aliases.length} 个</span></div>
    ${data.aliases.map(a => `<div class="sheet row" data-alias="${a.id}"><div><strong>${esc(a.name)}</strong><div class="meta">${esc(a.cat_name)}</div></div><div class="actions"><button class="btn light" data-approve="yes">通过</button><button class="btn ghost" data-approve="no">不采纳</button></div></div>`).join('') || empty('book', '暂无待审核别名', '同学提交的新称呼会出现在这里。')}</div>`;
    main.querySelectorAll('[data-review]').forEach(article => {
        const id = Number(article.dataset.review), current = data.sightings.find(s => s.id === id), form = article.querySelector('form');
        const peers = article.querySelector('.pending-peers');
        peers.ontoggle = async () => {
            if (!peers.open || peers.dataset.loaded)
                return;
            peers.dataset.loaded = 'loading';
            const list = peers.querySelector('.peer-list');
            list.textContent = '正在读取待辨认照片…';
            try {
                const result = await api('/review/' + id + '/similar');
                list.innerHTML = (result.sightings.length ? '<div class="compare">' + result.sightings.map(peer => '<figure>' + img(peer.photo_url, '待辨认目击', 'loading="lazy"') + '<figcaption>目击 #' + Number(peer.id) + ' · ' + esc(peer.area) + ' · ' + esc(date(peer.observed_at)) + '</figcaption></figure>').join('') + '</div>' : '<p class="hint">暂未找到外观接近的其他待辨认目标。</p>') + (result.limited ? '<p class="hint">已对照最近 250 条待辨认目标。</p>' : '');
                peers.dataset.loaded = 'done';
            }
            catch (error) {
                delete peers.dataset.loaded;
                list.textContent = error.message;
            }
        };
        const select = form.elements.cat_id;
        const candidateIds = (current.candidates || []).map(cat => cat.id);
        const sorted = [...(current.candidates || []), ...cats.filter(cat => !candidateIds.includes(cat.id))];
        sorted.forEach(cat => select.add(new Option(`${candidateIds.includes(cat.id) ? '候选 · ' : ''}${cat.name} (#${cat.id})`, String(cat.id))));
        const show = () => {
            const cat = sorted.find(c => c.id === Number(select.value)) || sorted[0];
            article.querySelector('.ref-image').innerHTML = cat ? img(cat.photo_url, cat.name, 'loading="lazy"') + `<figcaption>参考照 · ${esc(cat.name)}</figcaption>` : '<figcaption>尚无参考档案</figcaption>';
        };
        select.onchange = show;
        show();
        form.elements.action.onchange = () => {
            const action = form.elements.action.value;
            form.querySelectorAll('[data-part]').forEach(el => el.hidden = el.dataset.part !== action);
            select.required = action === 'match';
            form.elements.name.required = action === 'new';
        };
        form.onsubmit = e => {
            e.preventDefault();
            busy(form.querySelector('[type=submit]'), async () => {
                const v = formValues(form), payload = { action: v.action, reason: v.reason.trim() };
                if (v.action === 'new') {
                    payload.name = v.name.trim();
                    payload.coat = v.coat.trim();
                    payload.catalog_revision = data.catalog_revision;
                }
                if (v.action === 'match')
                    payload.cat_id = Number(v.cat_id);
                await api(`/review/${id}`, payload);
                notice('复核决定已保存。');
                await refresh();
            });
        };
    });
    main.querySelectorAll('[data-approve]').forEach(b => b.onclick = () => busy(b, async () => {
        const id = Number(b.closest('[data-alias]').dataset.alias);
        await api(`/aliases/${id}/review`, { approve: b.dataset.approve === 'yes' });
        await refresh();
    }));
}
export function bindBreed(form, cat, refresh) {
    form.onsubmit = e => {
        e.preventDefault();
        busy(form.querySelector('[type=submit]'), async () => {
            const values = formValues(form);
            await api(`/cats/${cat.id}/breed`, { breed: values.breed.trim(), evidence: values.evidence.trim() });
            notice('品种核验信息已保存。');
            await refresh();
        });
    };
}
