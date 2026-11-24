import { api, esc, icon, img } from './ui.js';

function resizeToDataUrl(file, maxSide = 1280) {
    return new Promise((resolve, reject) => {
        const url = URL.createObjectURL(file);
        const image = new Image();
        image.onload = () => {
            try {
                const ratio = Math.min(1, maxSide / Math.max(image.naturalWidth, image.naturalHeight));
                const w = Math.max(1, Math.round(image.naturalWidth * ratio));
                const h = Math.max(1, Math.round(image.naturalHeight * ratio));
                const c = document.createElement('canvas');
                c.width = w;
                c.height = h;
                const ctx = c.getContext('2d');
                ctx.fillStyle = '#fff';
                ctx.fillRect(0, 0, w, h);
                ctx.drawImage(image, 0, 0, w, h);
                resolve(c.toDataURL('image/jpeg', 0.85));
            } catch (err) {
                reject(err);
            } finally {
                URL.revokeObjectURL(url);
            }
        };
        image.onerror = () => {
            URL.revokeObjectURL(url);
            reject(new Error('无法读取该图片'));
        };
        image.src = url;
    });
}

export function initAgentWidget() {
    if (document.getElementById('agent-root'))
        return () => {};
    const root = document.createElement('div');
    root.id = 'agent-root';
    root.innerHTML = `
      <button type="button" id="agent-fab" class="agent-fab" aria-haspopup="dialog" aria-controls="agent-drawer" aria-expanded="false" aria-label="打开猫猫助手" title="猫猫助手">${icon('cat')}</button>
      <dialog id="agent-drawer" class="agent-drawer" aria-label="猫猫助手对话">
        <header class="agent-head">
          <div><strong>猫猫助手</strong><small id="agent-mode">正在连接…</small></div>
          <button type="button" id="agent-close" class="agent-close" aria-label="关闭">×</button>
        </header>
        <div id="agent-log" class="agent-log" aria-live="polite">
          <div class="agent-msg bot">你好！可以发一张猫照片问我「库里记录过吗？是什么品种？」，或直接搜校园里见过的猫。</div>
        </div>
        <div class="agent-quick">
          <button type="button" data-q="全校现在记录了几只猫？">全校统计</button>
          <button type="button" data-q="最近7天有哪些猫被目击？">近期目击</button>
          <button type="button" data-q="本周哪些区域还缺定点观察？">定点周报</button>
        </div>
        <div id="agent-photo-bar" class="agent-photo-bar" hidden>
          <img id="agent-thumb" alt="待识别照片">
          <span>已附带照片（将自动查重并识别品种）</span>
          <button type="button" id="agent-photo-clear">移除</button>
        </div>
        <label id="agent-cloud-label" class="hint" hidden><input type="checkbox" id="agent-cloud"> 允许将本次照片发送给配置的视觉模型</label>
        <form id="agent-form" class="agent-form">
          <input id="agent-file" type="file" accept="image/*" hidden>
          <button type="button" id="agent-pick" class="btn light" title="附带猫照片">传图</button>
          <input id="agent-input" type="text" maxlength="500" placeholder="问找猫、查重或品种…" autocomplete="off">
          <button type="submit" id="agent-send" class="btn">发送</button>
        </form>
      </dialog>`;
    document.body.appendChild(root);

    const fab = root.querySelector('#agent-fab');
    document.querySelector('#account').before(fab);
    const drawer = root.querySelector('#agent-drawer');
    const log = root.querySelector('#agent-log');
    const modeEl = root.querySelector('#agent-mode');
    const form = root.querySelector('#agent-form');
    const input = root.querySelector('#agent-input');
    const fileInput = root.querySelector('#agent-file');
    const photoBar = root.querySelector('#agent-photo-bar');
    const thumb = root.querySelector('#agent-thumb');

    let pendingPhoto = '';
    const history = [];
    const initial = log.innerHTML;
    let generation = 0;
    const cloud = root.querySelector('#agent-cloud');

    function appendMsg(role, text, extraHtml = '') {
        const div = document.createElement('div');
        div.className = `agent-msg ${role}`;
        div.innerHTML = `<div class="agent-text">${esc(text).replace(/\n/g, '<br>')}</div>${extraHtml}`;
        log.appendChild(div);
        log.scrollTop = log.scrollHeight;
        return div;
    }

    function renderCards(cards) {
        if (!cards || !cards.length) return '';
        return `<div class="agent-cards">${cards.slice(0, 4).map(c =>
            `<a class="agent-card" href="#cat/${Number(c.id)}">${img(c.thumbnail_url || c.photo_url, c.name)}<div><strong>${esc(c.name)}</strong><small>${esc(c.coat || '花色待补')} · ${esc(c.area || '区域待补')}</small></div></a>`
        ).join('')}</div>`;
    }

    async function loadStatus() {
        try {
            const st = await api('/agent/status');
            root.querySelector('#agent-cloud-label').hidden = st.vision_mode !== 'vlm';
            if (st.mode === 'llm') {
                modeEl.textContent = st.scope === 'personal' ? '我的专属助手 · 在线' : '校园图鉴助手 · 在线';
            } else {
                modeEl.textContent = '校园图鉴查询';
            }
        } catch {
            modeEl.textContent = '暂时连不上服务器';
        }
    }

    function toggle(open) {
        if (open && !drawer.open) {
            drawer.showModal();
            document.documentElement.classList.add('chat-open');
            fab.setAttribute('aria-expanded', 'true');
            loadStatus();
            requestAnimationFrame(() => input.focus());
        } else if (!open && drawer.open) drawer.close();
    }

    drawer.onclose = () => {
        document.documentElement.classList.remove('chat-open');
        fab.setAttribute('aria-expanded', 'false');
    };
    window.addEventListener('hashchange', () => toggle(false));
    window.addEventListener('campuscats:ask-agent', e => {
        const prompt = String(e.detail?.prompt || '').trim();
        toggle(true);
        if (prompt) {
            input.value = prompt;
            requestAnimationFrame(() => input.focus());
        }
    });
    fab.onclick = () => toggle(true);
    root.querySelector('#agent-close').onclick = () => toggle(false);
    root.querySelector('#agent-pick').onclick = () => fileInput.click();
    root.querySelector('#agent-photo-clear').onclick = () => {
        pendingPhoto = '';
        photoBar.hidden = true;
    };

    fileInput.onchange = async () => {
        const file = fileInput.files[0];
        fileInput.value = '';
        if (!file) return;
        try {
            const turn = generation;
            const ready = await resizeToDataUrl(file);
            if (turn !== generation) return;
            pendingPhoto = ready;
            thumb.src = pendingPhoto;
            photoBar.hidden = false;
        } catch (err) {
            appendMsg('bot', err.message || '图片读取失败，请重试。');
        }
    };

    async function send(text) {
        const msg = text.trim();
        if (!msg && !pendingPhoto) return;
        const turn = generation;
        const photoToSend = pendingPhoto;
        const useCloud = cloud.checked;
        cloud.checked = false;
        pendingPhoto = '';
        photoBar.hidden = true;
        input.value = '';
        appendMsg('user', msg || '（已发送照片，请帮我查重并识别品种）');
        const loading = appendMsg('bot', '正在查询图鉴并分析…');
        try {
            const payload = { message: msg, history: history.slice(-6) };
            if (photoToSend) Object.assign(payload, { photo: photoToSend, cloud_photo: useCloud });
            const res = await api('/agent/chat', payload);
            if (turn !== generation) return;
            loading.remove();
            appendMsg('bot', res.reply || '已完成查询。', renderCards(res.cards));
            history.push({ role: 'user', content: msg || '上传了一张猫照片进行识别' });
            history.push({ role: 'assistant', content: res.reply || '' });
        } catch (err) {
            loading.textContent = `暂时无法回答：${err.message || '请稍后再试。'}`;
        }
    }

    form.onsubmit = e => {
        e.preventDefault();
        send(input.value);
    };
    root.querySelectorAll('[data-q]').forEach(btn => {
        btn.onclick = () => send(btn.dataset.q);
    });
    return () => {
        generation++;
        history.length = 0;
        pendingPhoto = '';
        input.value = '';
        cloud.checked = false;
        thumb.removeAttribute('src');
        photoBar.hidden = true;
        log.innerHTML = initial;
        toggle(false);
    };
}
