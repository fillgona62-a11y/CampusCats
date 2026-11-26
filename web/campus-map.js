import { api, back, card, date, esc, head, icon, notice } from './ui.js';

/**
 * 沈阳理工大学（浑南校区 · 南屏中路 6 号）高德实景校园猫地图
 * 仅使用高德地图 JS API 2.0 实景/卫星底图展示校内常驻地标、精确 GPS 目击落点与猫咪时空轨迹。
 */
export const SYLU_LANDMARKS = [
    {
        id: 'north-gate',
        lat: 41.7306, lng: 123.4936,
        name: '北门（汇泉东路）',
        short: '北门',
        keywords: ['北门', '汇泉', '地铁', '嘉华'],
        desc: '靠近汇泉东路与地铁 10 号线理工大学站方向。',
    },
    {
        id: 'dorm',
        lat: 41.7295, lng: 123.4962,
        name: '学生生活区（宿舍）',
        short: '生活区宿舍',
        keywords: ['宿舍', '公寓', '生活区', '寝室'],
        desc: '学生宿舍与生活区周边，早晚常有亲人猫咪出没。',
    },
    {
        id: 'canteen',
        lat: 41.7282, lng: 123.4963,
        name: '餐饮服务中心（食堂）',
        short: '食堂 / 餐饮中心',
        keywords: ['食堂', '餐饮', '餐厅', '一食堂', '二食堂', '三食堂'],
        desc: '沈阳理工大学餐饮服务中心及周边树荫长椅区。',
    },
    {
        id: 'stadium',
        lat: 41.7279, lng: 123.4910,
        name: '体育场 / 操场',
        short: '体育场',
        keywords: ['体育场', '操场', '体育馆', '运动场', '篮球场', '看台'],
        desc: '校内体育场与看台周边草坪。',
    },
    {
        id: 'armory',
        lat: 41.726883, lng: 123.491791,
        name: '兵器博物馆 / 兵器广场',
        short: '兵器博物馆',
        keywords: ['兵器', '博物馆', '广场', '坦克', '导弹'],
        desc: '沈理地标兵器博物馆室内展馆与室外兵器广场周边。',
    },
    {
        id: 'library',
        lat: 41.727829, lng: 123.493886,
        name: '图书馆（琴园环路）',
        short: '图书馆',
        keywords: ['图书馆', '图馆', '自习'],
        desc: '琴园环路核心地标，台阶与草坪常能偶遇晒太阳的猫。',
    },
    {
        id: 'zhixue',
        lat: 41.7272, lng: 123.4956,
        name: '志学堂',
        short: '志学堂',
        keywords: ['志学堂', '礼堂', '讲堂'],
        desc: '琴园环路沿线志学堂周边绿化带。',
    },
    {
        id: 'teaching',
        lat: 41.7264, lng: 123.4940,
        name: '教学楼区',
        short: '教学楼区',
        keywords: ['教学楼', '主楼', '信息楼', '机电', '文科', '实验楼', '阶梯'],
        desc: '校内核心教学楼与实验楼连廊、石阶周边。',
    },
    {
        id: 'qinyuan',
        lat: 41.7266, lng: 123.4926,
        name: '琴园绿地',
        short: '琴园绿地',
        keywords: ['琴园', '绿地', '草坪', '小树林', '花园'],
        desc: '琴园环路内侧树荫草地与休憩步道。',
    },
    {
        id: 'south-gate',
        lat: 41.7248, lng: 123.4939,
        name: '南门（南屏中路）',
        short: '南门正门',
        keywords: ['南门', '正门', '南屏'],
        desc: '沈阳市浑南区南屏中路 6 号正门入口广场。',
    },
];

function matchLandmark(areaText) {
    const raw = String(areaText || '').trim();
    if (!raw) return null;
    const lower = raw.toLowerCase();
    for (const lm of SYLU_LANDMARKS) {
        if (raw === lm.name || lm.keywords.some(k => lower.includes(k))) {
            return lm.id;
        }
    }
    return null;
}

export function nearestSyluLandmark(lat, lng) {
    if (typeof lat !== 'number' || typeof lng !== 'number' || !Number.isFinite(lat) || !Number.isFinite(lng))
        return null;
    const toRad = d => d * Math.PI / 180;
    let best = null, bestDist = Infinity;
    for (const lm of SYLU_LANDMARKS) {
        if (typeof lm.lat !== 'number' || typeof lm.lng !== 'number') continue;
        const dLat = toRad(lm.lat - lat), dLng = toRad(lm.lng - lng);
        const a = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(lat)) * Math.cos(toRad(lm.lat)) * Math.sin(dLng / 2) ** 2;
        const dist = 6371000 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
        if (dist < bestDist) { bestDist = dist; best = lm; }
    }
    return best && bestDist <= 1800 ? { name: best.name, short: best.short, distanceMeters: Math.round(bestDist) } : null;
}

/* --- WGS-84 to GCJ-02 (China Mars Coordinate) conversion for accurate AMap pins --- */
export function wgs84ToGcj02(lat, lng) {
    const PI = Math.PI, a = 6378245.0, ee = 0.00669342162296594323;
    if (lng < 72.004 || lng > 137.8347 || lat < 0.8293 || lat > 55.8271) return [lng, lat];
    const transformLat = (x, y) => {
        let r = -100 + 2 * x + 3 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * Math.sqrt(Math.abs(x));
        r += (20 * Math.sin(6 * x * PI) + 20 * Math.sin(2 * x * PI)) * 2 / 3;
        r += (20 * Math.sin(y * PI) + 40 * Math.sin(y / 3 * PI)) * 2 / 3;
        r += (160 * Math.sin(y / 12 * PI) + 320 * Math.sin(y * PI / 30)) * 2 / 3;
        return r;
    };
    const transformLng = (x, y) => {
        let r = 300 + x + 2 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * Math.sqrt(Math.abs(x));
        r += (20 * Math.sin(6 * x * PI) + 20 * Math.sin(2 * x * PI)) * 2 / 3;
        r += (20 * Math.sin(x * PI) + 40 * Math.sin(x / 3 * PI)) * 2 / 3;
        r += (150 * Math.sin(x / 12 * PI) + 300 * Math.sin(x / 30 * PI)) * 2 / 3;
        return r;
    };
    let dLat = transformLat(lng - 105.0, lat - 35.0);
    let dLng = transformLng(lng - 105.0, lat - 35.0);
    const radLat = lat / 180.0 * PI;
    let magic = Math.sin(radLat);
    magic = 1 - ee * magic * magic;
    const sqrtMagic = Math.sqrt(magic);
    dLat = (dLat * 180.0) / ((a * (1 - ee)) / (magic * sqrtMagic) * PI);
    dLng = (dLng * 180.0) / (a / sqrtMagic * Math.cos(radLat) * PI);
    return [Number((lng + dLng).toFixed(6)), Number((lat + dLat).toFixed(6))];
}

let _amapPromise = null;
async function loadAmap() {
    if (window.AMap) return window.AMap;
    if (_amapPromise) return _amapPromise;
    _amapPromise = (async () => {
        const cfg = await api('/map/config').catch(() => null);
        if (!cfg || !cfg.amap_key) {
            throw new Error('服务端尚未配置高德地图密钥（AMAP_JS_KEY）。');
        }
        if (cfg.amap_service_host) {
            window._AMapSecurityConfig = { serviceHost: cfg.amap_service_host };
        } else if (cfg.amap_security_code) {
            window._AMapSecurityConfig = { securityJsCode: cfg.amap_security_code };
        }
        await new Promise((resolve, reject) => {
            document.querySelectorAll('script[data-amap-sdk]').forEach(el => el.remove());
            const s = document.createElement('script');
            s.dataset.amapSdk = '1';
            // Always send origin Referer so AMap domain whitelist succeeds under HTTPS
            s.referrerPolicy = 'origin';
            s.src = `https://webapi.amap.com/maps?v=2.0&key=${encodeURIComponent(cfg.amap_key)}&plugin=AMap.Geocoder,AMap.Scale`;
            s.async = true;
            s.onload = resolve;
            s.onerror = () => {
                s.remove();
                reject(new Error('高德地图脚本加载失败，请检查网络连接或高德控制台域名白名单。'));
            };
            document.head.appendChild(s);
        });
        if (!window.AMap) {
            throw new Error('高德地图初始化失败，请确认 Key 类型为「Web端(JS API)」且域名白名单包含当前站点域名。');
        }
        return window.AMap;
    })().catch(err => {
        _amapPromise = null;
        throw err;
    });
    return _amapPromise;
}

export async function reverseGeocodeAmap(lat, lng) {
    const AMap = await loadAmap().catch(() => null);
    if (!AMap || !AMap.Geocoder) return null;
    const [gLng, gLat] = wgs84ToGcj02(lat, lng);
    return new Promise(resolve => {
        try {
            const geocoder = new AMap.Geocoder({ radius: 120, extensions: 'all' });
            geocoder.getAddress([gLng, gLat], (status, result) => {
                if (status === 'complete' && result?.regeocode) {
                    const rg = result.regeocode;
                    const poi = rg.pois?.[0]?.name;
                    const aois = rg.aois?.[0]?.name;
                    const addr = rg.formattedAddress || '';
                    const shortName = poi ? (aois && !poi.includes(aois) ? `${aois} · ${poi}` : poi) : addr.replace(/^辽宁省沈阳市浑南区/, '');
                    resolve(shortName ? shortName.slice(0, 56) : null);
                } else {
                    resolve(null);
                }
            });
        } catch {
            resolve(null);
        }
    });
}

export async function campusMapPage(main, cats, onPickArea, isCurrent = () => true) {
    const byLandmark = Object.fromEntries(SYLU_LANDMARKS.map(lm => [lm.id, []]));
    for (const cat of cats || []) {
        const hit = matchLandmark(cat.area);
        if (hit) byLandmark[hit].push(cat);
    }

    main.innerHTML = back('#home', '返回首页')
        + head('沈理猫地图（高德实景）', '沈阳理工大学（浑南区南屏中路 6 号）· 展示校内地标常驻猫、精确 GPS 目击落点与时空轨迹。')
        + `<section class="surface map-card">
            <div class="map-toolbar">
              <div class="map-toolbar-pills">
                <button type="button" class="btn light map-tool-btn" id="amap-layer-toggle">卫星图</button>
                <button type="button" class="btn light map-tool-btn" id="amap-landmarks-toggle">隐藏地标</button>
                <button type="button" class="btn light map-tool-btn" id="amap-locate">${icon('pin')}定位</button>
              </div>
              <select id="amap-cat-filter" class="map-cat-filter" aria-label="按猫查看时空轨迹">
                <option value="">正在加载目击点…</option>
              </select>
            </div>
            <div id="amap-container" class="amap-stage">
              <div class="amap-loading" id="amap-loading"><span class="skeleton-dot"></span><span>正在加载高德实景地图…</span></div>
            </div>
            <p class="hint" id="amap-hint" style="margin-top:8px"></p>
          </section>
          <section class="surface" id="amap-detail" style="margin-top:12px">
            <div class="map-panel-head">
              <div>
                <h2 id="amap-detail-title">沈阳理工大学（浑南校区）</h2>
                <p class="hint" id="amap-detail-desc">点击地图上的校内地标或猫咪足迹图钉查看详情，或直接记录新目击。</p>
              </div>
              <button type="button" class="btn" id="amap-record-now">${icon('camera')}拍照记录目击</button>
            </div>
            <div id="amap-detail-cats" style="margin-top:12px"></div>
          </section>`;

    let selectedArea = '';
    main.querySelector('#amap-record-now').onclick = () => onPickArea(selectedArea);

    let AMap, geoData;
    try {
        [AMap, geoData] = await Promise.all([
            loadAmap(),
            api('/map/sightings').catch(() => ({ sightings: [] })),
        ]);
    } catch (err) {
        if (!isCurrent()) return () => {};
        const filterEl = main.querySelector('#amap-cat-filter');
        if (filterEl) {
            filterEl.innerHTML = '<option value="">地图暂未就绪</option>';
            filterEl.disabled = true;
        }
        main.querySelectorAll('.map-tool-btn').forEach(b => { b.disabled = true; });
        const box = main.querySelector('#amap-container');
        if (box) {
            box.innerHTML = `<div class="amap-error"><strong>高德实景地图暂未就绪</strong><p class="hint">${esc(err.message || '请检查网络与高德密钥配置。')}</p><button type="button" class="btn light" id="amap-retry">重新加载地图</button></div>`;
            box.querySelector('#amap-retry').onclick = () => campusMapPage(main, cats, onPickArea, isCurrent);
        }
        return () => {};
    }

    const container = main.querySelector('#amap-container');
    if (!isCurrent() || !container || !container.isConnected) return () => {};
    container.innerHTML = '';

    const sightings = geoData?.sightings || [];
    const uniqueCats = [...new Map(sightings.filter(s => s.cat_id).map(s => [s.cat_id, s.cat_name || `猫 #${s.cat_id}`])).entries()];
    const filterEl = main.querySelector('#amap-cat-filter');
    filterEl.innerHTML = `<option value="">全部精确目击（${sightings.length} 条）</option>`
        + uniqueCats.map(([id, name]) => `<option value="${id}">${esc(name)} · 时空轨迹</option>`).join('');
    main.querySelector('#amap-hint').textContent = sightings.length
        ? `已加载 ${sightings.length} 条带精确 GPS 的目击记录与 ${SYLU_LANDMARKS.length} 个沈理地标，点击标点查看猫咪详情。`
        : `已加载 ${SYLU_LANDMARKS.length} 个沈理校内地标；拍照授权定位后，每次目击将自动以精确坐标落点在实景地图上。`;

    const centerGcj = wgs84ToGcj02(41.727829, 123.493886);
    const map = new AMap.Map('amap-container', {
        zoom: window.innerWidth <= 520 ? 15.5 : 16.3,
        center: centerGcj,
        viewMode: '2D',
    });
    if (AMap.Scale) map.addControl(new AMap.Scale());

    const satLayer = new AMap.TileLayer.Satellite();
    const roadNet = new AMap.TileLayer.RoadNet();
    let isSat = false;
    main.querySelector('#amap-layer-toggle').onclick = e => {
        isSat = !isSat;
        if (isSat) { map.add([satLayer, roadNet]); e.target.textContent = '标准图'; }
        else { map.remove([satLayer, roadNet]); e.target.textContent = '卫星图'; }
    };

    const infoWindow = new AMap.InfoWindow({ offset: new AMap.Pixel(0, -28) });
    let sightingOverlays = [];
    let landmarkOverlays = [];
    let showLandmarks = true;

    function showLandmarkDetail(lm) {
        selectedArea = lm.name;
        const list = byLandmark[lm.id] || [];
        main.querySelector('#amap-detail-title').textContent = lm.name;
        main.querySelector('#amap-detail-desc').textContent = lm.desc;
        main.querySelector('#amap-record-now').innerHTML = `${icon('camera')}在「${esc(lm.short)}」记录目击`;
        main.querySelector('#amap-detail-cats').innerHTML = list.length
            ? `<p class="meta">该区域常驻 ${list.length} 只已建档校园猫</p><div class="gallery">${list.map(card).join('')}</div>`
            : `<p class="hint">该地标暂未建档常驻猫，欢迎拍下你在这里遇见的第一只猫。</p>`;
    }

    function renderLandmarks() {
        if (landmarkOverlays.length) { map.remove(landmarkOverlays); landmarkOverlays = []; }
        if (!showLandmarks) return;
        for (const lm of SYLU_LANDMARKS) {
            const [gLng, gLat] = wgs84ToGcj02(lm.lat, lm.lng);
            const count = (byLandmark[lm.id] || []).length;
            const bg = count > 0 ? '#163f37' : '#526a60';
            const badge = count > 0 ? `<span style="background:#d9822b;color:#fff;border-radius:999px;padding:0 5px;margin-left:4px;font-size:11px">${count}</span>` : '';
            const marker = new AMap.Marker({
                position: [gLng, gLat],
                title: lm.name,
                zIndex: 90,
                content: `<div style="background:${bg};color:#fff;border:1.5px solid #fff;border-radius:999px;padding:3px 9px;white-space:nowrap;font-size:12px;font-weight:600;box-shadow:0 2px 6px rgba(0,0,0,.22);display:inline-flex;align-items:center">${esc(lm.short)}${badge}</div>`,
                offset: new AMap.Pixel(-32, -14),
            });
            marker.on('click', () => {
                showLandmarkDetail(lm);
                map.panTo([gLng, gLat]);
            });
            landmarkOverlays.push(marker);
        }
        if (landmarkOverlays.length) map.add(landmarkOverlays);
    }

    main.querySelector('#amap-landmarks-toggle').onclick = e => {
        showLandmarks = !showLandmarks;
        e.target.textContent = showLandmarks ? '隐藏地标' : '显示地标';
        renderLandmarks();
    };

    function renderPins(filterCatId = '') {
        if (sightingOverlays.length) { map.remove(sightingOverlays); sightingOverlays = []; }
        const list = filterCatId ? sightings.filter(s => String(s.cat_id) === String(filterCatId)) : sightings;
        const path = [];
        const ordered = [...list].reverse();
        ordered.forEach((s, idx) => {
            const [gLng, gLat] = wgs84ToGcj02(Number(s.latitude), Number(s.longitude));
            path.push([gLng, gLat]);
            const label = filterCatId ? String(idx + 1) : '🐾';
            const marker = new AMap.Marker({
                position: [gLng, gLat],
                title: s.cat_name || s.area || '校园猫目击',
                zIndex: 120,
                content: `<div style="background:#d9822b;color:#fff;border:2px solid #fff;border-radius:999px;min-width:26px;height:26px;padding:0 6px;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;box-shadow:0 2px 6px rgba(0,0,0,.28)">${label}</div>`,
                offset: new AMap.Pixel(-13, -13),
            });
            marker.on('click', () => {
                const title = s.cat_name ? esc(s.cat_name) : `待辨认目击 #${s.id}`;
                const link = s.cat_id ? `<a href="#cat/${Number(s.cat_id)}" style="color:#1c4d3e;font-weight:600">查看档案 →</a>` : '<span style="color:#666">待审核建档</span>';
                const accTxt = s.location_accuracy ? ` · 精度约 ${Math.round(s.location_accuracy)}m` : '';
                infoWindow.setContent(
                    `<div style="min-width:190px;font-size:13px;line-height:1.5;color:#1f2e28">`
                    + `<img src="${esc(s.thumbnail_url)}" alt="${title}" style="width:100%;height:110px;object-fit:cover;border-radius:8px;margin-bottom:6px">`
                    + `<div><strong>${title}</strong>${s.coat ? ` · ${esc(s.coat)}` : ''}</div>`
                    + `<div style="color:#555">${esc(s.area || '沈理校内')}${accTxt}</div>`
                    + `<div style="color:#777;font-size:12px">${esc(date(s.observed_at))}</div>`
                    + `<div style="margin-top:6px">${link}</div></div>`
                );
                infoWindow.open(map, [gLng, gLat]);
            });
            sightingOverlays.push(marker);
        });
        if (filterCatId && path.length >= 2) {
            const line = new AMap.Polyline({
                path,
                strokeColor: '#d9822b',
                strokeWeight: 4,
                strokeStyle: 'dashed',
                showDir: true,
            });
            sightingOverlays.push(line);
        }
        if (sightingOverlays.length) {
            map.add(sightingOverlays);
            if (filterCatId) {
                if (path.length === 1) map.setZoomAndCenter(17.2, path[0]);
                else map.setFitView(sightingOverlays, false, [48, 48, 48, 48]);
            }
        }
    }

    renderLandmarks();
    renderPins('');
    filterEl.onchange = e => renderPins(e.target.value);

    let meMarker = null;
    main.querySelector('#amap-locate').onclick = () => {
        if (!navigator.geolocation) {
            notice('当前浏览器不支持定位。');
            return;
        }
        notice('正在定位当前位置…');
        navigator.geolocation.getCurrentPosition(pos => {
            const [gLng, gLat] = wgs84ToGcj02(pos.coords.latitude, pos.coords.longitude);
            map.setZoomAndCenter(17.5, [gLng, gLat]);
            if (meMarker) map.remove(meMarker);
            meMarker = new AMap.CircleMarker({
                center: [gLng, gLat], radius: 8, strokeColor: '#fff', strokeWeight: 2, fillColor: '#2563eb', fillOpacity: 0.9,
            });
            map.add(meMarker);
        }, err => {
            notice(err?.code === 1 ? '未授予位置权限，请在系统设置中开启定位。' : '定位超时或信号较弱，请稍后重试。');
        }, { enableHighAccuracy: true, timeout: 8000 });
    };

    return () => {
        try { map.destroy(); } catch {}
    };
}
