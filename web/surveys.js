import {api, back, btn, busy, date, empty, esc, head, icon, notice} from './ui.js';

function checkForm(data, user) {
    if (!user) return `<section class="surface"><h2>参加十分钟观察</h2><p>在一个固定位置安静观察。同行时，由一人记录这十分钟内同时看见的最多只数。</p>${btn('#login/surveys','登录后参加','time')}</section>`;
    if (!data.active) return `<form class="surface" id="survey-start"><h2>开始十分钟观察</h2>
        <p>到达观察点再开始计时。留在原处，记下同时看见的最多只数。多人同行时由一人提交。</p>
        <label class="field"><span>校园区域</span><input required name="area" maxlength="60" list="known-areas" placeholder="例如，图书馆（琴园环路）或 兵器博物馆 / 兵器广场"><small>同一地点沿用已有名称，只填写大致区域。</small></label>
        <datalist id="known-areas">${data.areas.map(a => '<option value="' + esc(a.area) + '"></option>').join('')}</datalist>
        <p class="form-error" role="alert"></p><button class="btn" type="submit">${icon('time')} 开始计时</button></form>`;
    return `<form class="surface" id="survey-finish"><h2>${esc(data.active.area)} · 本次观察</h2>
        <p class="survey-clock" role="timer" aria-label="剩余观察时间"></p>
        <p>只记录开始后的十分钟。例如，先看见两只，过一会儿只看见一只，这次就填 2。中途离开可以放弃本次观察。</p>
        <label class="field"><span>同时看见的最多只数</span><input name="peak" inputmode="numeric" type="number" min="0" max="999" step="1" required placeholder="全程没看到，请填 0"></label>
        <p class="form-error" role="alert"></p><button id="survey-submit" type="submit" class="btn" disabled>完成观察并提交</button>
        <details class="survey-withdraw"><summary>放弃这次观察</summary><p>放弃后，这次计时会结束。</p><button type="button" class="btn light" data-withdraw="${data.active.id}">确认放弃</button></details></form>`;
}

function weeklyReport(data) {
    const total = data.areas.reduce((sum, a) => sum + a.visits, 0);
    const covered = data.areas.filter(a => a.visits > 0).length;
    const rows = data.areas.map(a => `<article class="survey-area"><h3>${esc(a.area)}</h3>
        <div>${a.visits ? `<strong>${a.visits} 次中有 ${a.seen} 次见猫</strong><p>零目击 ${a.visits - a.seen} 次 · 单次最多同时看见 ${a.peak} 只</p>` : '<strong>本周待观察</strong>'}
        <small>上周${a.previous_visits ? ' ' + a.previous_visits + ' 次中有 ' + a.previous_seen + ' 次见猫' : '暂无观察'}</small></div></article>`).join('');
    return `<section><div class="section-head"><h2>本周区域周报</h2></div><p>自 ${esc(data.week_start)} 起，已在 ${covered} 个区域完成 ${total} 次观察。</p>
        ${rows ? `<div class="surface survey-areas">${rows}</div><button type="button" class="btn light" id="survey-csv">下载区域周报 CSV</button>` : empty('pin','还没有区域记录','第一份完成的观察会出现在这里，整场零目击也会计入。')}
        <p class="hint">周报列出已有建档目击或已完成观察的区域。见猫次数受时段、天气和观察位置影响，全校已建档的猫数可在首页查看。</p></section>`;
}

function downloadReport(data) {
    const header = ['周起始日期','校园区域','本周观察次数','本周见猫次数','本周零目击次数','单次最多同时见猫只数','上周观察次数','上周见猫次数'];
    const rows = data.areas.map(a => [data.week_start,a.area,a.visits,a.seen,a.visits-a.seen,a.peak ?? '',a.previous_visits,a.previous_seen]);
    function cell(value) {
        const s = String(value);
        return '"' + (/^\s*[=+@\-\t\r\n]/.test(s) ? "'" : '') + s.replaceAll('"','""') + '"';
    }
    const csv = [header,...rows].map(row => row.map(cell).join(',')).join('\r\n');
    const url = URL.createObjectURL(new Blob(['\uFEFF',csv],{type:'text/csv;charset=utf-8'}));
    const link = document.createElement('a');
    link.href = url;
    link.download = '猫迹-校园观察-' + data.week_start + '.csv';
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
}

export function surveyPage(main, data, user, reload) {
    main.innerHTML = `<div class="narrow">${back('#home','返回首页')}${head('校园定点观察','每次在一处观察十分钟。记录看见的猫，也记录认真看过却没有遇见的日子。')}
        ${checkForm(data,user)}${weeklyReport(data)}
        ${data.recent.length ? `<details class="surface"><summary>我最近完成的观察</summary>${data.recent.map(s => `<details class="survey-withdraw"><summary>${esc(date(s.started * 1000))} · ${esc(s.area)} · 最多 ${s.peak} 只</summary><p>记录有误时可以撤回，周报会随之更新。</p><button type="button" class="btn light" data-withdraw="${s.id}">撤回这条记录</button></details>`).join('')}</details>` : ''}</div>`;
    let disposed = false, timer;
    async function save(path, body, message) {
        await api(path, body);
        if (!disposed) {
            notice(message);
            await reload();
        }
    }
    const start = main.querySelector('#survey-start');
    if (start) {
        const key = globalThis.crypto?.randomUUID?.() || Date.now() + '-' + Math.random().toString(36).slice(2);
        start.onsubmit = event => {
            event.preventDefault();
            busy(start.querySelector('button'), () => save('/surveys/start',{area:start.elements.area.value.trim(), request_id:key},'已开始计时。'));
        };
    }
    const finish = main.querySelector('#survey-finish');
    if (finish) {
        const button = finish.querySelector('#survey-submit');
        const deadline = Date.now() + (data.active.started + data.duration - data.now) * 1000;
        const tick = () => {
            const left = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
            finish.querySelector('.survey-clock').textContent = left ? Math.floor(left / 60) + ':' + String(left % 60).padStart(2, '0') : '十分钟已到';
            if (!left) {
                button.disabled = false;
                clearInterval(timer);
            }
        };
        timer = setInterval(tick, 1000);
        tick();
        finish.onsubmit = event => {
            event.preventDefault();
            busy(button, () => save('/surveys/' + data.active.id + '/finish',{peak:finish.elements.peak.valueAsNumber},'观察已计入区域周报。'));
        };
    }
    main.querySelectorAll('[data-withdraw]').forEach(button => {
        button.onclick = () => busy(button, () => save('/surveys/' + button.dataset.withdraw + '/withdraw',{},'已撤回本次观察。'));
    });
    const download = main.querySelector('#survey-csv');
    if (download) download.onclick = () => downloadReport(data);
    return () => { disposed = true; clearInterval(timer); };
}
