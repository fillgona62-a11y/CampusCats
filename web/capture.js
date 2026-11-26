import { api, btn, busy, esc, head, icon, img, notice } from './ui.js';
import { locateAccurate, nearestSyluLandmark, reverseGeocodeAmap } from './campus-map.js';
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
function resizedDataUrl(sourceCanvas, maxSide, quality = .82) {
    if (!sourceCanvas) return '';
    const w = sourceCanvas.width, h = sourceCanvas.height;
    const ratio = Math.min(1, maxSide / Math.max(w, h));
    if (ratio >= 0.999) return sourceCanvas.toDataURL('image/jpeg', quality);
    const out = canvas(Math.max(1, Math.round(w * ratio)), Math.max(1, Math.round(h * ratio)));
    out.getContext('2d').drawImage(sourceCanvas, 0, 0, out.width, out.height);
    return out.toDataURL('image/jpeg', quality);
}
function newRequestId() {
    return globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`;
}
function recordBadge(rs) {
    if (!rs) return '';
    const map = {
        not_a_cat: ['danger', '非猫咪画面'],
        poor_quality: ['empty', '请补拍清晰照片'],
        ambiguous: ['possible', '多个相似候选'],
        weak_candidate: ['weak', '外观弱相似 · 注意区分异猫'],
        possible_match: ['possible', '疑似已在库'],
        no_candidate: ['empty', '暂未找到相似档案'],
        no_reference: ['empty', '暂无参考库']
    };
    const [cls, label] = map[rs.status] || ['empty', '待比对'];
    return `<div class="record-box ${cls}"><span class="record-badge ${cls}">${label}</span><p>${esc(rs.summary || '')}</p></div>`;
}
function aiProfileCard(ai) {
    if (!ai) return '';
    const sourceTag = ai.source === 'vlm'
        ? '云端视觉模型拍板'
        : ai.source === 'local_assist'
            ? '本地毛色辅助（不作最终品种判定）'
            : ai.source === 'local_clip'
                ? '本地深度模型辅助'
                : '本地颜色初判';
    const neuter = ai.neutered_hint === 'yes' ? '疑似可见剪耳绝育标记' : ai.neutered_hint === 'no' ? '未见明显剪耳' : '';
    const chips = [...(ai.features || []), ...(neuter ? [neuter] : [])];
    return `<div class="ai-profile-card"><div class="ai-profile-head"><strong>品种与花色识别</strong><span class="ai-tag">${sourceTag}</span></div>
    <p><strong>推测品种：</strong>${esc(ai.breed || '未知')}　<strong>花色：</strong>${esc(ai.coat || '待补充')}</p>
    ${chips.length ? `<div class="ai-chips">${chips.map(c => `<span>${esc(c)}</span>`).join('')}</div>` : ''}
    ${ai.summary ? `<p class="hint">${esc(ai.summary)}</p>` : ''}</div>`;
}
export function capturePage(main, onSuccess, {saveLocal, draft, lookupOnly = false} = {}) {
    const title = lookupOnly ? '照片查查' : saveLocal ? '拍照记录' : '记录目击';
    const description = lookupOnly ? '拍照或选图后会联网比对校园图鉴，并查看花色初判。' :
        saveLocal ? '可将照片存为本机草稿，也可以点「照片查查」联网比对。' : '拍一张清楚的照片，先看看校园图鉴里有没有它。';
    main.innerHTML = `<div class="narrow">${head(title, description)}
    <section class="surface"><h2>拍摄或选取照片</h2><p>尽量让脸部或侧身花纹入镜。同框时，可以在照片上把每只猫分别框出来。</p>
    <div class="actions"><button type="button" class="btn" id="live-start">${icon('camera')}打开相机</button><button type="button" class="btn light" id="choose">${icon('image')}从相册选取</button></div>
    <input id="file" type="file" accept="image/*" hidden><input id="native" type="file" accept="image/*" capture="environment" hidden>
    <div id="live-panel" hidden><hr class="divider"><video class="live" id="viewfinder" autoplay muted playsinline></video><p id="live-quality" class="advice" role="status"></p><div class="actions"><button id="shutter" class="btn">拍下并查一查</button><button id="live-stop" class="btn light">关闭相机</button></div></div>
    <p id="file-error" class="form-error" role="alert"></p><button id="native-fallback" class="btn light" hidden>调用系统相机</button></section>
    <form id="capture-form" class="surface" hidden><h2>目击照片</h2>
    <div class="mark-tools"><button type="button" class="btn light" id="mark-toggle" aria-pressed="false" aria-controls="stage">框选同框猫</button><button type="button" class="btn ghost" id="undo" hidden>撤销上一框</button></div>
    <p id="mark-help" class="hint" aria-live="polite"></p>
    <div class="capture-stage"><div class="target-stage" id="stage" aria-describedby="mark-help"><img id="preview" alt="本次目击照片" draggable="false"><div class="mark-layer" id="marks"></div></div></div>
    <div class="advice" id="quality" role="status"></div><label class="hint" id="cloud-option" hidden><input name="cloud_photo" type="checkbox"> 启用第二关云端精准拍板（只将拼好的候选对比图发给视觉模型判定同猫、毛色与剪耳）</label><button type="button" class="btn light" id="identify">${icon('search')}照片查查 · 查重与花色识别</button>
    <p id="lookup-status" role="status" class="hint"></p><div id="results" aria-live="polite"></div><div id="record-fields" ${lookupOnly ? 'hidden inert' : ''}><hr class="divider"><h2>保存这次目击</h2><label class="field"><span>校园区域</span><input name="area" list="capture-areas" required maxlength="60" placeholder="例如，图书馆（琴园环路）或 兵器博物馆 / 兵器广场"><small>优先选择已有区域名称，方便归入同一地点统计。</small></label><div class="actions" style="margin:-4px 0 10px"><button type="button" class="btn ghost" id="locate-btn">${icon('pin')}定位当前位置</button><span id="geo-status" class="hint" style="margin:0">拍照或选图时会询问位置权限以关联猫猫出现地点。</span></div><datalist id="capture-areas"></datalist>
    <label class="field"><span>目击时间</span><input type="datetime-local" name="observed" required></label>
    <label class="field"><span>观察备注（选填）</span><textarea name="note" maxlength="800" rows="2" placeholder="例如，左前腿有一处橘色斑纹"></textarea></label><label class="hint"><input type="checkbox" name="automatic" checked> 允许自动关联已建档的猫</label><p class="hint">脸部特征充分吻合时自动记录重遇，其余目击待辨认。</p><p class="form-error" role="alert"></p><button type="submit" class="btn">${icon('book')}提交目击</button></div></form></div>`;
    const $ = selector => main.querySelector(selector), form = $('#capture-form'), stage = $('#stage'), marks = $('#marks'), video = $('#viewfinder');
    const now = new Date();
    form.elements.observed.value = new Date(now - now.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
    const prefillArea = sessionStorage.getItem('campuscats:prefill-area');
    if (prefillArea) {
        sessionStorage.removeItem('campuscats:prefill-area');
        if (!draft?.area) form.elements.area.value = prefillArea;
    }
    let stream = null, monitor = null, disposed = false, photo = '', frame = null, boxes = [], suggestions = [], start = null, requestId = newRequestId(), revision = 0, acquire = 0, fileVersion = 0;
    let gps = null, areaManuallyEdited = false, hasCloudVision = false;
    async function requestLocation(force = false) {
        if (lookupOnly || disposed) return;
        const geoEl = $('#geo-status');
        if (gps && !force) return;
        if (geoEl) geoEl.textContent = '正在高精度定位…';
        try {
            const loc = await locateAccurate({ timeout: 10000 });
            if (disposed) return;
            const acc = loc.accuracy || 0;
            gps = { latitude: loc.wgsLat, longitude: loc.wgsLng, location_accuracy: acc };
            const amapAddr = loc.address || await reverseGeocodeAmap(loc.gcjLat, loc.gcjLng, true).catch(() => null);
            if (disposed) return;
            const lm = nearestSyluLandmark(loc.gcjLat, loc.gcjLng, true);
            const bestName = amapAddr || lm?.name || '';
            if (bestName && !areaManuallyEdited && (!form.elements.area.value.trim() || force)) {
                form.elements.area.value = bestName;
            }
            if (geoEl) {
                const accTxt = acc ? `（误差约 ${acc}m）` : '';
                geoEl.textContent = amapAddr
                    ? `高德精准定位：${amapAddr}${accTxt}`
                    : lm
                        ? `已关联位置：${lm.name}（约 ${lm.distanceMeters}m${acc ? `，误差 ${acc}m` : ''}）`
                        : `已记录坐标：${loc.wgsLat.toFixed(4)}, ${loc.wgsLng.toFixed(4)}${accTxt}，请补充区域名`;
            }
        } catch (err) {
            if (disposed || !geoEl) return;
            geoEl.textContent = err?.code === 1
                ? '未授予位置权限，请手动选择校园区域。'
                : '定位超时或信号弱，请到开阔处重试或手动选择校园区域。';
        }
    }
    let drawing = false, pointerId = null;
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
        marks.innerHTML = boxes.map((box, i) => mark(box, i + 1)).join('') + (draft ? mark(draft, boxes.length + 1, 'temp') : '');
    }
    function setDrawing(active) {
        drawing = active;
        start = null;
        if (pointerId !== null && stage.hasPointerCapture(pointerId)) stage.releasePointerCapture(pointerId);
        pointerId = null;
        stage.classList.toggle('drawing', active);
        const toggle = $('#mark-toggle');
        toggle.setAttribute('aria-pressed', String(active));
        toggle.textContent = active ? '取消框选' : boxes.length ? '再框一只' : '框选同框猫';
        toggle.disabled = boxes.length >= 8;
        $('#undo').hidden = !boxes.length;
        $('#mark-help').textContent = active ? '在照片上沿对角拖动，松手完成一个框。' :
            boxes.length ? `已标记 ${boxes.length} 只猫。` : '单只猫可直接使用整张照片。';
        draw();
    }
    function update() {
        revision++;
        requestId = newRequestId();
        suggestions = [];
        $('#results').replaceChildren();
        $('#identify').disabled = false;
        const submitBtn = form.querySelector('[type=submit]');
        if (submitBtn) submitBtn.disabled = false;
        $('#lookup-status').textContent = '';
        setDrawing(false);
        $('#quality').textContent = targets().map((box, i) => `猫 ${i + 1} · ${qualityHints(frame, box).join(' ') || '画面初检通过，可对照脸部和侧身花纹。'}`).join('　');
    }
    async function autoDetectAndIdentify(version) {
        const feedback = $('#lookup-status');
        feedback.textContent = '正在自动检测画面中的猫猫…';
        let noCatDetected = false;
        try {
            const detPhoto = resizedDataUrl(frame, 800, 0.78) || photo;
            const det = await api('/detect', { photo: detPhoto });
            if (disposed || version !== revision) return;
            if (det?.boxes?.length) {
                boxes = det.boxes.slice(0, 8);
                draw();
                $('#undo').hidden = !boxes.length;
                $('#mark-toggle').textContent = boxes.length ? '再框一只' : '框选同框猫';
                $('#mark-help').textContent = boxes.length > 1
                    ? `已自动框出同框的 ${boxes.length} 只猫，将逐只比对档案与识别品种。`
                    : `已自动框出 1 只猫，可直接查重或手动调整。`;
                $('#quality').textContent = targets().map((box, i) => `猫 ${i + 1} · ${qualityHints(frame, box).join(' ') || '画面初检通过，可对照脸部和侧身花纹。'}`).join('　');
            } else if (det?.detector_enabled) {
                noCatDetected = true;
                const subjectMsg = det.non_cat_type === 'person'
                    ? '画面识别为人像且未检测到猫咪，已拦截误识别与花色匹配。'
                    : det.non_cat_type === 'dog'
                        ? '画面识别为犬类而非猫咪，已拦截误识别。'
                        : '画面中未识别到猫（可能是人像、景物或猫体过小被遮挡），已跳过花色与档案匹配。';
                $('#mark-help').textContent = '未在画面中检测到猫。如远景中确实有猫，请点「框选同框猫」手动框出猫咪位置。';
                $('#results').innerHTML = `<hr class="divider"><section class="sheet"><div class="record-box danger"><span class="record-badge danger">未检测到猫咪</span><p>${esc(subjectMsg)}如果照片局部确实有猫，请手动框选猫身后再点「照片查查」。</p></div></section>`;
                const submitBtn = form.querySelector('[type=submit]');
                if (submitBtn && !saveLocal) submitBtn.disabled = true;
                feedback.textContent = '';
            }
        } catch {
            // Fall back silently to full-frame / manual box
        }
        if (!noCatDetected && !saveLocal && !disposed && version === revision) {
            await identify();
        } else if (feedback.textContent.startsWith('正在自动检测')) {
            feedback.textContent = '';
        }
    }
    function useFrame(next) {
        form.elements.cloud_photo.checked = hasCloudVision;
        frame = next;
        photo = frame.toDataURL('image/jpeg', .86);
        boxes = [];
        start = null;
        $('#preview').src = photo;
        form.hidden = false;
        $('#file-error').textContent = '';
        update();
        requestLocation();
    }
    function refCaption(cat) {
        const pct = typeof cat.similarity === 'number' ? ` · 匹配度约 ${Math.round(cat.similarity * 100)}%` : '';
        const pts = cat.local_inliers >= 12 ? ` · 花纹几何命中 ${Number(cat.local_inliers)} 点` : '';
        return '候选参考照 · ' + esc(cat.name) + pct + pts + (cat.breed_status === 'verified' ? ' · ' + esc(cat.breed) + '（维护者已核验）' : '');
    }
    function vlmCompareCard(vc) {
        if (!vc || vc.source !== 'vlm') return '';
        const labelMap = { same_cat: '视觉复核 · 高度疑似同一只', different_cat: '视觉复核 · 存在明显差异', uncertain: '视觉复核 · 建议人工再核对' };
        const tone = vc.verdict === 'same_cat' ? 'ok' : vc.verdict === 'different_cat' ? 'warn' : 'muted';
        const matchList = (vc.matching_features || []).length ? `<p class="meta">一致特征：${vc.matching_features.map(esc).join('、')}</p>` : '';
        const diffList = (vc.differences || []).length ? `<p class="meta">差异/待核对：${vc.differences.map(esc).join('、')}</p>` : '';
        return `<div class="surface" style="margin:10px 0;padding:12px 14px"><p><strong class="pill ${tone}">${labelMap[vc.verdict] || '视觉复核'}</strong></p>${vc.reason ? `<p style="margin-top:6px">${esc(vc.reason)}</p>` : ''}${matchList}${diffList}</div>`;
    }
    function previewResults(data) {
        suggestions = Array(data.results.length).fill(null);
        $('#results').innerHTML = `<hr class="divider"><h2>查图与识别结果</h2><p>${data.reference_count ? '已比对图鉴参考照，可查看每只猫的候选档案。' : '图鉴还没有可比对的参考照。提交目击后，维护者可以为第一只猫建档。'}</p>` + data.results.map((r, i) => {
            const cats = r.candidates || [], warnings = r.warnings || r.quality || [];
            return `<section class="sheet"><h3>猫 ${i + 1}</h3>${recordBadge(r.record_status)}${vlmCompareCard(r.vlm_compare)}${aiProfileCard(r.ai_profile)}${r.breed_hint?.label ? `<p class="advice">图鉴相似档案的品种线索（待核实） · ${esc(r.breed_hint.label)}。至少两只相似候选的档案记有该品种，仍需核对这只猫的来源。</p>` : ''}<div class="compare"><figure>${img(cropData(frame, r.box), '本次取景')}<figcaption>本次取景</figcaption></figure>${cats[0] ? `<figure id="ref-${i}">${img(cats[0].photo_url, cats[0].name)}<figcaption>${refCaption(cats[0])}</figcaption></figure>` : ''}</div>${warnings.length ? `<p class="advice">${esc(warnings.join(' '))}</p>` : ''}${cats.length ? `<label class="field"><span>对照候选参考照</span><select data-ref="${i}">${cats.map((cat, j) => `<option value="${j}">${esc(cat.name)} · ${esc(cat.coat || '花色待补')}${typeof cat.similarity === 'number' ? `（约 ${Math.round(cat.similarity * 100)}%）` : ''}</option>`).join('')}</select></label><div class="actions" ${lookupOnly || saveLocal ? 'hidden' : ''}><button type="button" class="btn light" data-pick="${i}">建议匹配当前候选</button><button type="button" class="btn ghost" data-clear="${i}">暂时认不出</button></div>` : '<p class="hint">目前没有可用候选。</p>'}<div class="actions"><button type="button" class="btn ghost" data-ask-agent="${i}">问问猫猫助手</button></div><p class="hint" id="selection-${i}" ${lookupOnly || saveLocal ? 'hidden' : ''}>提交意向 · 待辨认</p></section>`;
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
        $('#results').querySelectorAll('[data-ask-agent]').forEach(b => b.onclick = () => {
            const i = Number(b.dataset.askAgent), r = data.results[i];
            const top = r.candidates?.[0];
            const parts = [];
            if (top) parts.push(`刚查图最像「${top.name}」`);
            if (r.ai_profile?.coat) parts.push(`花色初判为${r.ai_profile.coat}`);
            if (r.ai_profile?.breed && r.ai_profile.breed !== '未知') parts.push(`推测品种${r.ai_profile.breed}`);
            const prompt = (parts.length ? parts.join('，') + '。' : '刚拍到一只校园猫，') + '请帮我查查它的历史目击、常出没区域和辨认特征。';
            window.dispatchEvent(new CustomEvent('campuscats:ask-agent', { detail: { prompt } }));
        });
    }
    async function identify() {
        const version = revision;
        const area = form.elements.area.value.trim();
        const idPhoto = resizedDataUrl(frame, 1024, 0.82) || photo;
        const payload = { photo: idPhoto, boxes: targets(), area, cloud_photo: form.elements.cloud_photo.checked };
        const feedback = $('#lookup-status');
        const trigger = $('#identify');
        trigger.disabled = true;
        feedback.textContent = '正在比对校园图鉴…';
        try {
            const result = await api('/identify', payload);
            if (disposed || version !== revision) return;
            if (!result?.results?.length) throw new Error('未取得识别结果，请再查一次。');
            previewResults(result);
            feedback.textContent = '';
        } catch (error) {
            if (!disposed && version === revision) feedback.textContent = error.message;
        } finally {
            if (!disposed && version === revision) trigger.disabled = false;
        }
    }
    if (saveLocal) {
        form.elements.automatic.closest('label').hidden = true;
        form.elements.automatic.closest('label').nextElementSibling.hidden = true;
        form.querySelector('[type=submit]').textContent = '保存到本机';
        $('#shutter').textContent = '拍下照片';
    }
    api('/agent/status').then(status => {
        if (!disposed) {
            hasCloudVision = status.vision_mode === 'vlm';
            $('#cloud-option').hidden = !hasCloudVision;
            if (hasCloudVision) form.elements.cloud_photo.checked = true;
        }
    }).catch(() => {});
    if (!lookupOnly) {
        api('/areas').then(res => {
            if (!disposed && res?.areas?.length) {
                $('#capture-areas').innerHTML = res.areas.map(a => `<option value="${esc(a)}"></option>`).join('');
            }
        }).catch(() => {});
    }
    $('#identify').onclick = identify;
    $('#locate-btn')?.addEventListener('click', () => requestLocation(true));
    form.elements.area?.addEventListener('input', () => { areaManuallyEdited = true; });
    const point = e => {
        const r = stage.getBoundingClientRect();
        return [Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), Math.min(1, Math.max(0, (e.clientY - r.top) / r.height))];
    };
    const between = (a, b) => [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.abs(a[0] - b[0]), Math.abs(a[1] - b[1])];
    $('#mark-toggle').onclick = () => setDrawing(!drawing);
    stage.onpointerdown = e => {
        if (!drawing || !e.isPrimary || e.button !== 0 || pointerId !== null)
            return;
        pointerId = e.pointerId;
        start = point(e);
        stage.setPointerCapture(e.pointerId);
    };
    stage.onpointermove = e => {
        if (start && e.pointerId === pointerId)
            draw(between(start, point(e)));
    };
    stage.onpointercancel = stage.onlostpointercapture = e => {
        if (e.pointerId === pointerId) setDrawing(false);
    };
    stage.onpointerup = e => {
        if (!start || e.pointerId !== pointerId)
            return;
        const b = between(start, point(e));
        start = null;
        if (b[2] >= .04 && b[3] >= .04) {
            boxes.push(b);
            update();
        }
        else {
            setDrawing(false);
            notice('请从猫的一侧拖向对角，框出可辨认的身体部分。');
        }
    };
    $('#undo').onclick = () => {
        boxes.pop();
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
                    const curRev = revision + 1;
                    useFrame(bitmapFrame(image, image.naturalWidth, image.naturalHeight));
                    await autoDetectAndIdentify(curRev);
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
        requestLocation();
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
        const curRev = revision + 1;
        useFrame(bitmapFrame(video, video.videoWidth, video.videoHeight));
        stopCamera();
        await autoDetectAndIdentify(curRev);
    };
    form.oninput = e => {
        if (e.target.name)
            requestId = newRequestId();
    };
    form.onsubmit = e => {
        e.preventDefault();
        if (lookupOnly) return;
        const submit = form.querySelector('[type=submit]');
        busy(submit, async () => {
            const observed = new Date(form.elements.observed.value);
            if (Number.isNaN(observed.valueOf()) || observed.getTime() > Date.now() + 60000)
                throw new Error('请选择已经发生的目击时间。');
            if (!form.elements.area.value.trim())
                throw new Error('请填写校园区域。');
            const payload = {
                photo, boxes: targets(), area: form.elements.area.value.trim(), note: form.elements.note.value.trim(), request_id: requestId, observed_at: observed.toISOString(),
                suggested_cat_ids: targets().map((_, i) => suggestions[i] ?? null),
                automatic: form.elements.automatic.checked,
                ...(gps ? { latitude: gps.latitude, longitude: gps.longitude, location_accuracy: gps.location_accuracy } : {})
            };
            const result = saveLocal ? await saveLocal(payload) : await api('/sightings', payload);
            if (!disposed)
                onSuccess(result);
        }, form);
    };
    if (draft) {
        const preview = new Image();
        preview.onload = () => {
            if (disposed) return;
            useFrame(bitmapFrame(preview, preview.naturalWidth, preview.naturalHeight));
            photo = draft.photo;
            boxes = draft.boxes.length === 1 && draft.boxes[0].every((n, i) => n === fullBox[i]) ? [] : draft.boxes.slice();
            update();
            form.elements.area.value = draft.area;
            form.elements.note.value = draft.note;
            const seen = new Date(draft.observed_at);
            form.elements.observed.value = new Date(seen - seen.getTimezoneOffset() * 60000).toISOString().slice(0,16);
            form.elements.automatic.checked = draft.automatic;
            requestId = draft.request_id;
        };
        preview.src = draft.photo;
    }
    return () => {
        disposed = true;
        stopCamera();
    };
}
