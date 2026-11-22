import { api, btn, busy, esc, head, icon, img, notice } from './ui.js';
const maximumSide = 1600;
const fullBox = [0, 0, 1, 1];
const canvas = (w, h) => Object.assign(document.createElement('canvas'), { width: w, height: h });
function bitmapFrame(source, w, h) {
    const ratio = Math.min(1, maximumSide / Math.max(w, h));
    const frame = canvas(Math.max(1, Math.round(w * ratio)), Math.max(1, Math.round(h * ratio)));
    const ctx = frame.getContext('2d');
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, frame.width, frame.height);
    ctx.drawImage(source, 0, 0, frame.width, frame.height);
    return frame;
}
function qualityHints(source, box = fullBox) {
    const w = source.videoWidth || source.width, h = source.videoHeight || source.height;
    if (!w || !h)
        return [];
    const hints = [], [x, y, bw, bh] = box;
    if (Math.min(w * bw, h * bh) < 150)
        hints.push('猫在画面里偏小，尽量让脸或侧身占据更多画面。');
    const thumb = canvas(88, 88), ctx = thumb.getContext('2d', { willReadFrequently: true });
    ctx.drawImage(source, x * w, y * h, bw * w, bh * h, 0, 0, 88, 88);
    const pixels = ctx.getImageData(0, 0, 88, 88).data;
    const luma = new Float32Array(88 * 88);
    let sum = 0, edge = 0;
    for (let i = 0; i < luma.length; i++) {
        const p = i * 4;
        luma[i] = .2126 * pixels[p] + .7152 * pixels[p + 1] + .0722 * pixels[p + 2];
        sum += luma[i];
    }
    for (let y = 1; y < 87; y++)
        for (let x = 1; x < 87; x++) {
            const i = y * 88 + x;
            edge += (luma[i - 1] + luma[i + 1] + luma[i - 88] + luma[i + 88] - 4 * luma[i]) ** 2;
        }
    const mean = sum / luma.length;
    if (mean < 48)
        hints.push('光线较暗，请换个明亮角度。');
    if (mean > 220)
        hints.push('画面偏亮，请避开逆光或强光。');
    if (edge / (86 * 86) < 55)
        hints.push('可见纹理较少，请稳住手机，尝试拍清脸部或侧身花纹。');
    return hints;
}
function cropData(frame, [x, y, w, h]) {
    const scale = Math.min(1, 420 / Math.max(w * frame.width, h * frame.height));
    const crop = canvas(Math.max(1, Math.round(frame.width * w * scale)), Math.max(1, Math.round(frame.height * h * scale)));
    crop.getContext('2d').drawImage(frame, x * frame.width, y * frame.height, w * frame.width, h * frame.height, 0, 0, crop.width, crop.height);
    return crop.toDataURL('image/jpeg', .85);
}
function newRequestId() {
    return globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`;
}
export function capturePage(main, onSuccess) {
    main.innerHTML = `<div class="narrow">${head('记录目击', '拍一张清楚的照片，先看看校园图鉴里有没有它。')}
    <section class="surface"><h2>拍摄或选取照片</h2><p>尽量让脸部或侧身花纹入镜。同框时，可以在照片上把每只猫分别框出来。</p>
    <div class="actions"><button type="button" class="btn" id="live-start">${icon('camera')}打开相机</button><button type="button" class="btn light" id="choose">${icon('image')}从相册选取</button></div>
    <input id="file" type="file" accept="image/*" hidden><input id="native" type="file" accept="image/*" capture="environment" hidden>
    <div id="live-panel" hidden><hr class="divider"><video class="live" id="viewfinder" autoplay muted playsinline></video><p id="live-quality" class="advice" role="status"></p><div class="actions"><button id="shutter" class="btn">拍下并查一查</button><button id="live-stop" class="btn light">关闭相机</button></div></div>
    <p id="file-error" class="form-error" role="alert"></p><button id="native-fallback" class="btn light" hidden>调用系统相机</button></section>
    <form id="capture-form" class="surface" hidden><h2>标记照片里的猫</h2><p>单只猫可直接使用整图。拖动框住一只猫，再拖动就能添加同框的另一只。</p>
    <div class="capture-stage"><div class="target-stage" id="stage" aria-label="在图上拖动添加猫框"><img id="preview" alt="本次目击照片"><div class="mark-layer" id="marks"></div></div></div>
    <div class="actions"><button type="button" class="btn ghost" id="undo">撤销上一个框</button><button type="button" class="btn ghost" id="reset">使用整图</button></div>
    <div class="advice" id="quality" role="status"></div><button type="button" class="btn light" id="identify">${icon('search')}查一查图鉴</button>
    <div id="results" aria-live="polite"></div><hr class="divider"><h2>保存这次目击</h2><label class="field"><span>校园区域</span><input name="area" required maxlength="60" placeholder="例如，图书馆周边"></label>
    <label class="field"><span>目击时间</span><input type="datetime-local" name="observed" required></label>
    <label class="field"><span>观察备注（选填）</span><textarea name="note" maxlength="800" rows="2" placeholder="例如，左前腿有一处橘色斑纹"></textarea></label><label class="hint"><input type="checkbox" name="automatic" checked> 允许自动关联已建档的猫</label><p class="hint">脸部特征充分吻合时自动记录重遇，其余目击待辨认。</p><p class="form-error" role="alert"></p><button type="submit" class="btn">${icon('book')}提交目击</button></form></div>`;
    const $ = selector => main.querySelector(selector), form = $('#capture-form'), stage = $('#stage'), marks = $('#marks'), video = $('#viewfinder');
    const now = new Date();
    form.elements.observed.value = new Date(now - now.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
    let stream = null, monitor = null, disposed = false, photo = '', frame = null, boxes = [], suggestions = [], start = null, requestId = newRequestId(), revision = 0, acquire = 0, fileVersion = 0;
    const targets = () => boxes.length ? boxes : [fullBox];
    function stopCamera() {
        acquire++;
        clearInterval(monitor);
        stream?.getTracks().forEach(t => t.stop());
        stream = null;
        video.srcObject = null;
        $('#live-panel').hidden = true;
    }
    function mark(box, label, extra = '') {
        const [x, y, w, h] = box;
        return `<span class="boxmark ${extra}" style="left:${x * 100}%;top:${y * 100}%;width:${w * 100}%;height:${h * 100}%"><b>${label}</b></span>`;
    }
    function draw(draft = null) {
        marks.innerHTML = targets().map((box, i) => mark(box, i + 1)).join('') + (draft ? mark(draft, boxes.length + 1, 'temp') : '');
    }
    function update() {
        revision++;
        requestId = newRequestId();
        suggestions = [];
        $('#results').replaceChildren();
        draw();
        $('#undo').disabled = !boxes.length;
        $('#quality').textContent = targets().map((box, i) => `猫 ${i + 1} · ${qualityHints(frame, box).join(' ') || '画面初检通过，可对照脸部和侧身花纹。'}`).join('　');
    }
    function useFrame(next) {
        frame = next;
        photo = frame.toDataURL('image/jpeg', .86);
        boxes = [];
        start = null;
        $('#preview').src = photo;
        form.hidden = false;
        $('#file-error').textContent = '';
        update();
    }
    function refCaption(cat) {
        return '候选参考照 · ' + esc(cat.name) + (cat.breed_status === 'verified' ? ' · ' + esc(cat.breed) + '（维护者已核验）' : '');
    }
    function previewResults(data) {
        suggestions = Array(data.results.length).fill(null);
        $('#results').innerHTML = `<hr class="divider"><h2>查图结果</h2><p>${data.reference_count ? '候选按外观相似程度排序。请选择有把握的档案，或保留待辨认。' : '图鉴还没有可比对的参考照。提交目击后，维护者可以为第一只猫建档。'}</p>` + data.results.map((r, i) => {
            const cats = r.candidates || [], warnings = r.warnings || r.quality || [];
            return `<section class="sheet"><h3>猫 ${i + 1}</h3>${r.breed_hint?.label ? `<p class="advice">图鉴相似档案的品种线索（待核实） · ${esc(r.breed_hint.label)}。至少两只相似候选的档案记有该品种，仍需核对这只猫的来源。</p>` : ''}<div class="compare"><figure>${img(cropData(frame, r.box), '本次取景')}<figcaption>本次取景</figcaption></figure>${cats[0] ? `<figure id="ref-${i}">${img(cats[0].photo_url, cats[0].name)}<figcaption>${refCaption(cats[0])}</figcaption></figure>` : ''}</div>${warnings.length ? `<p class="advice">${esc(warnings.join(' '))}</p>` : ''}${cats.length ? `<label class="field"><span>对照候选参考照</span><select data-ref="${i}">${cats.map((cat, j) => `<option value="${j}">${esc(cat.name)} · ${esc(cat.coat || '花色待补')}</option>`).join('')}</select></label><div class="actions"><button type="button" class="btn light" data-pick="${i}">建议匹配当前候选</button><button type="button" class="btn ghost" data-clear="${i}">暂时认不出</button></div>` : '<p class="hint">目前没有可用候选，可以提交为待辨认。</p>'}<p class="hint" id="selection-${i}">提交意向 · 待辨认</p></section>`;
        }).join('');
        $('#results').querySelectorAll('[data-ref]').forEach(select => select.onchange = () => {
            const index = Number(select.dataset.ref), cat = data.results[index].candidates[Number(select.value)];
            $(`#ref-${index}`).innerHTML = img(cat.photo_url, cat.name) + `<figcaption>${refCaption(cat)}</figcaption>`;
        });
        $('#results').querySelectorAll('[data-pick]').forEach(b => b.onclick = () => {
            const i = Number(b.dataset.pick), cat = data.results[i].candidates[Number($(`[data-ref="${i}"]`).value)];
            if (suggestions.some((id, index) => index !== i && id === cat.id)) {
                notice('同一张照片里的两只猫需要分别选择不同的档案。');
                return;
            }
            suggestions[i] = cat.id;
            requestId = newRequestId();
            $(`#selection-${i}`).textContent = `提交意向 · 建议匹配「${cat.name}」，等待复核`;
        });
        $('#results').querySelectorAll('[data-clear]').forEach(b => b.onclick = () => {
            const i = Number(b.dataset.clear);
            suggestions[i] = null;
            requestId = newRequestId();
            $(`#selection-${i}`).textContent = '提交意向 · 待辨认';
        });
    }
    async function identify() {
        const version = revision, result = await api('/identify', { photo, boxes: targets() });
        if (!disposed && version === revision) {
            previewResults(result);
            $('#results').scrollIntoView({ block: 'nearest' });
        }
    }
    $('#identify').onclick = e => busy(e.currentTarget, identify);
    const point = e => {
        const r = stage.getBoundingClientRect();
        return [Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), Math.min(1, Math.max(0, (e.clientY - r.top) / r.height))];
    };
    const between = (a, b) => [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.abs(a[0] - b[0]), Math.abs(a[1] - b[1])];
    stage.onpointerdown = e => {
        if (!e.isPrimary || e.button !== 0)
            return;
        if (boxes.length >= 8) {
            notice('一张照片最多标记 8 只猫。');
            return;
        }
        start = point(e);
        stage.setPointerCapture(e.pointerId);
    };
    stage.onpointermove = e => {
        if (start && e.isPrimary)
            draw(between(start, point(e)));
    };
    stage.onpointercancel = () => {
        start = null;
        draw();
    };
    stage.onpointerup = e => {
        if (!start || !e.isPrimary)
            return;
        const b = between(start, point(e));
        start = null;
        if (b[2] >= .04 && b[3] >= .04) {
            boxes.push(b);
            update();
        }
        else {
            draw();
            notice('请从猫的一侧拖向对角，框出可辨认的身体部分。');
        }
    };
    $('#undo').onclick = () => {
        boxes.pop();
        update();
    };
    $('#reset').onclick = () => {
        boxes = [];
        update();
    };
    $('#choose').onclick = () => $('#file').click();
    $('#native-fallback').onclick = () => $('#native').click();
    for (const el of [$('#file'), $('#native')])
        el.onchange = async () => {
            const file = el.files[0];
            el.value = '';
            if (!file)
                return;
            const version = ++fileVersion;
            stopCamera();
            const url = URL.createObjectURL(file), image = new Image();
            try {
                image.src = url;
                await image.decode();
                if (!disposed && version === fileVersion) {
                    useFrame(bitmapFrame(image, image.naturalWidth, image.naturalHeight));
                    await busy($('#identify'), identify);
                }
            }
            catch {
                $('#file-error').textContent = '这张图片无法读取，请选择 JPEG、PNG 或 WebP 照片。';
            }
            finally {
                URL.revokeObjectURL(url);
            }
        };
    $('#live-start').onclick = async (e) => {
        if (!navigator.mediaDevices?.getUserMedia) {
            $('#native').click();
            return;
        }
        const button = e.currentTarget;
        await busy(button, async () => {
            stopCamera();
            const attempt = ++acquire;
            try {
                const acquired = await navigator.mediaDevices.getUserMedia({ audio: false, video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 } } });
                if (disposed || attempt !== acquire) {
                    acquired.getTracks().forEach(t => t.stop());
                    return;
                }
                stream = acquired;
                $('#live-panel').hidden = false;
                video.srcObject = stream;
                await video.play();
                $('#file-error').textContent = '';
                $('#native-fallback').hidden = true;
                const tick = () => {
                    if (video.readyState < 2)
                        return;
                    $('#live-quality').textContent = qualityHints(video).join(' ') || '请让猫的脸部或侧身进入取景框。';
                };
                tick();
                monitor = setInterval(tick, 850);
            }
            catch {
                stopCamera();
                if (!disposed) {
                    $('#file-error').textContent = '无法打开实时取景。请允许相机权限，或使用系统相机拍照。';
                    $('#native-fallback').hidden = false;
                }
            }
        });
    };
    $('#live-stop').onclick = stopCamera;
    $('#shutter').onclick = async (e) => {
        if (!video.videoWidth) {
            notice('相机正在准备，请稍候。');
            return;
        }
        fileVersion++;
        useFrame(bitmapFrame(video, video.videoWidth, video.videoHeight));
        stopCamera();
        await busy($('#identify'), identify);
    };
    form.oninput = e => {
        if (e.target.name)
            requestId = newRequestId();
    };
    form.onsubmit = e => {
        e.preventDefault();
        const submit = form.querySelector('[type=submit]');
        busy(submit, async () => {
            const observed = new Date(form.elements.observed.value);
            if (Number.isNaN(observed.valueOf()) || observed.getTime() > Date.now() + 60000)
                throw new Error('请选择已经发生的目击时间。');
            if (!form.elements.area.value.trim())
                throw new Error('请填写校园区域。');
            const result = await api('/sightings', {
                photo, boxes: targets(), area: form.elements.area.value.trim(), note: form.elements.note.value.trim(), request_id: requestId, observed_at: observed.toISOString(),
                suggested_cat_ids: targets().map((_, i) => suggestions[i] ?? null),
                automatic: form.elements.automatic.checked
            });
            if (!disposed)
                onSuccess(result);
        }, form);
    };
    return () => {
        disposed = true;
        stopCamera();
    };
}
