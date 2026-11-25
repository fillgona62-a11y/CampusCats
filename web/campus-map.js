import { api, back, card, date, esc, head, icon } from './ui.js';

/**
 * 沈阳理工大学（浑南校区 · 南屏中路6号）内置校园猫交互地图
 * 方位依据：北临汇泉东路（北门，近地铁10号线理工大学站方向），南临南屏中路（南门正门），
 * 校内以琴园环路为核心，兵器博物馆与兵器广场位于校园中西部。
 */
export const SYLU_LANDMARKS = [
    {
        id: 'north-gate',
        lat: 41.7306, lng: 123.4936,
        name: '北门（汇泉东路）',
        short: '北门',
        x: 340, y: 66,
        keywords: ['北门', '汇泉', '地铁', '嘉华'],
        desc: '靠近汇泉东路与地铁 10 号线理工大学站方向。',
    },
    {
        id: 'dorm',
        lat: 41.7295, lng: 123.4962,
        name: '学生生活区（宿舍）',
        short: '生活区宿舍',
        x: 520, y: 148,
        keywords: ['宿舍', '公寓', '生活区', '寝室'],
        desc: '学生宿舍与生活区周边，早晚常有亲人猫咪出没。',
    },
    {
        id: 'canteen',
        lat: 41.7282, lng: 123.4963,
        name: '餐饮服务中心（食堂）',
        short: '食堂 / 餐饮中心',
        x: 525, y: 266,
        keywords: ['食堂', '餐饮', '餐厅', '一食堂', '二食堂', '三食堂'],
        desc: '沈阳理工大学餐饮服务中心及周边树荫长椅区。',
    },
    {
        id: 'stadium',
        lat: 41.7279, lng: 123.4910,
        name: '体育场 / 操场',
        short: '体育场',
        x: 152, y: 152,
        keywords: ['体育场', '操场', '体育馆', '运动场', '篮球场', '看台'],
        desc: '校内体育场与看台周边草坪。',
    },
    {
        id: 'armory',
        lat: 41.726883, lng: 123.491791,
        name: '兵器博物馆 / 兵器广场',
        short: '兵器博物馆',
        x: 175, y: 312,
        keywords: ['兵器', '博物馆', '广场', '坦克', '导弹'],
        desc: '沈理地标兵器博物馆室内展馆与室外兵器广场周边。',
    },
    {
        id: 'library',
        lat: 41.727829, lng: 123.493886,
        name: '图书馆（琴园环路）',
        short: '图书馆',
        x: 342, y: 214,
        keywords: ['图书馆', '图馆', '自习'],
        desc: '琴园环路核心地标，台阶与草坪常能偶遇晒太阳的猫。',
    },
    {
        id: 'zhixue',
        lat: 41.7272, lng: 123.4956,
        name: '志学堂',
        short: '志学堂',
        x: 342, y: 320,
        keywords: ['志学堂', '礼堂', '讲堂'],
        desc: '琴园环路沿线志学堂周边绿化带。',
    },
    {
        id: 'teaching',
        lat: 41.7264, lng: 123.4940,
        name: '教学楼区',
        short: '教学楼区',
        x: 256, y: 404,
        keywords: ['教学楼', '主楼', '信息楼', '机电', '文科', '实验楼', '阶梯'],
        desc: '校内核心教学楼与实验楼连廊、石阶周边。',
    },
    {
        id: 'qinyuan',
        lat: 41.7266, lng: 123.4926,
        name: '琴园绿地',
        short: '琴园绿地',
        x: 440, y: 382,
        keywords: ['琴园', '绿地', '草坪', '小树林', '花园'],
        desc: '琴园环路内侧树荫草地与休憩步道。',
    },
    {
        id: 'south-gate',
        lat: 41.7248, lng: 123.4939,
        name: '南门（南屏中路）',
        short: '南门正门',
        x: 342, y: 468,
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

function renderOfflineSvgMap(main, cats, onPickArea, onSwitchLive = null) {
    const byId = Object.fromEntries(SYLU_LANDMARKS.map(lm => [lm.id, []]));
    const others = [];
    for (const cat of cats) {
        const hit = matchLandmark(cat.area);
        if (hit) byId[hit].push(cat);
        else others.push(cat);
    }

    const initialId = (SYLU_LANDMARKS.find(lm => byId[lm.id].length > 0) || SYLU_LANDMARKS[5]).id;

    main.innerHTML = `<div class="sylu-map-page">
      ${back('#home', '返回首页')}
      ${head('沈理校园猫地图', '沈阳理工大学（浑南区南屏中路 6 号）校内测试版 · 点击地标查看常驻猫或直接在该处记录目击。')}
      <section class="surface map-stage-card">
        <div class="map-legend">
          <span><i class="dot has-cats"></i> 已有建档猫</span>
          <span><i class="dot empty-dot"></i> 暂未记录点位</span>
          <span class="map-addr">琴园环路 · 浑南校区</span>
        </div>
        <div class="sylu-svg-wrap">
          <svg class="sylu-svg" viewBox="0 0 680 520" role="img" aria-label="沈阳理工大学校园猫分布图">
            <rect x="24" y="34" width="632" height="452" rx="26" class="map-ground"/>
            <line x1="24" y1="34" x2="656" y2="34" class="map-road-outer"/>
            <text x="340" y="22" text-anchor="middle" class="map-road-label">汇泉东路（北 · 近地铁10号线理工大学站）</text>
            <line x1="24" y1="486" x2="656" y2="486" class="map-road-outer"/>
            <text x="340" y="508" text-anchor="middle" class="map-road-label">南屏中路 6 号（南 · 正门方向）</text>

            <rect x="64" y="96" width="176" height="114" rx="54" class="map-track"/>
            <ellipse cx="436" cy="378" rx="76" ry="44" class="map-lawn"/>
            <rect x="90" y="264" width="168" height="92" rx="18" class="map-plaza"/>

            <rect x="250" y="138" width="184" height="236" rx="72" class="map-ring"/>
            <line x1="342" y1="34" x2="342" y2="138" class="map-road"/>
            <line x1="342" y1="374" x2="342" y2="486" class="map-road"/>
            <line x1="250" y1="264" x2="590" y2="264" class="map-road"/>
            <line x1="175" y1="210" x2="175" y2="395" class="map-road"/>
            <text x="342" y="156" text-anchor="middle" class="map-sub-label">琴园环路</text>

            <g transform="translate(612, 82)" class="map-compass" aria-hidden="true">
              <circle r="20" class="compass-bg"/>
              <path d="M0 -12 L4 2 L0 -1 L-4 2 Z" fill="var(--ginger)"/>
              <text y="13" text-anchor="middle" font-size="10" font-weight="700" fill="var(--muted)">N</text>
            </g>

            ${SYLU_LANDMARKS.map(lm => {
                const count = byId[lm.id].length;
                const cls = count > 0 ? 'map-pin has-cats' : 'map-pin';
                return `<g class="${cls}" data-lm="${lm.id}" tabindex="0" role="button" aria-label="${esc(lm.name)}，${count}只猫" transform="translate(${lm.x}, ${lm.y})">
                  ${count > 0 ? '<circle r="24" class="pin-pulse"/>' : ''}
                  <circle r="15" class="pin-circle"/>
                  <text y="5" text-anchor="middle" class="pin-count">${count > 0 ? count : '·'}</text>
                  <g transform="translate(0, 29)">
                    <rect x="-48" y="-11" width="96" height="21" rx="10" class="pin-label-bg"/>
                    <text y="3" text-anchor="middle" class="pin-label">${esc(lm.short)}</text>
                  </g>
                </g>`;
            }).join('')}
          </svg>
        </div>
      </section>

      <section id="map-panel" class="surface map-panel" aria-live="polite"></section>
      ${others.length ? `<section class="surface"><h2>其他校内目击点位（${others.length} 只）</h2><div class="gallery">${others.map(card).join('')}</div></section>` : ''}
    </div>`;

    const panel = main.querySelector('#map-panel');
    const pins = [...main.querySelectorAll('.map-pin')];

    function select(id) {
        const lm = SYLU_LANDMARKS.find(item => item.id === id) || SYLU_LANDMARKS[0];
        const list = byId[lm.id] || [];
        pins.forEach(p => p.classList.toggle('active', p.dataset.lm === lm.id));
        panel.innerHTML = `<div class="map-panel-head">
          <div>
            <h2>${icon('pin')} ${esc(lm.name)}</h2>
            <p class="hint">${esc(lm.desc)}</p>
          </div>
          <button type="button" class="btn" id="map-record-here">${icon('camera')}在这里记录目击</button>
        </div>
        ${list.length
            ? `<p class="meta">该点位附近已记录 ${list.length} 只校园猫</p><div class="gallery">${list.map(card).join('')}</div>`
            : `<p class="hint">这个点位暂时还没有建档的校园猫，欢迎拍下你在这里遇见的第一只猫！</p>`}`;
        panel.querySelector('#map-record-here').onclick = () => onPickArea(lm.name);
    }

    pins.forEach(pin => {
        pin.onclick = () => select(pin.dataset.lm);
        pin.onkeydown = e => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                select(pin.dataset.lm);
            }
        };
    });
    select(initialId);
    if (onSwitchLive) {
        const bar = document.createElement('div');
        bar.className = 'actions';
        bar.style.marginBottom = '10px';
        bar.innerHTML = `<button type="button" class="btn light" id="switch-amap">${icon('pin')}切换回高德真实地图</button>`;
        const wrap = main.querySelector('.campus-map-wrap');
        if (wrap) wrap.parentNode.insertBefore(bar, wrap);
        bar.querySelector('#switch-amap').onclick = onSwitchLive;
    }
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


/* --- WGS-84 to GCJ-02 (China Mars Coordinate) conversion for accurate Amap pins --- */
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
        if (!cfg || !cfg.amap_key) return null;
        if (cfg.amap_service_host) {
            window._AMapSecurityConfig = { serviceHost: cfg.amap_service_host };
        } else if (cfg.amap_security_code) {
            window._AMapSecurityConfig = { securityJsCode: cfg.amap_security_code };
        }
        await new Promise((resolve, reject) => {
            const s = document.createElement('script');
            s.src = `https://webapi.amap.com/maps?v=2.0&key=${encodeURIComponent(cfg.amap_key)}&plugin=AMap.Geocoder,AMap.Scale`;
            s.async = true;
            s.onload = resolve;
            s.onerror = reject;
            document.head.appendChild(s);
        });
        return window.AMap || null;
    })().catch(() => {
        _amapPromise = null;
        return null;
    });
    return _amapPromise;
}

export async function reverseGeocodeAmap(lat, lng) {
    const AMap = await loadAmap();
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

export async function campusMapPage(main, cats, onPickArea) {
    const [AMap, geoData] = await Promise.all([
        loadAmap(),
        api('/map/sightings').catch(() => ({ sightings: [] })),
    ]);
    if (!AMap) {
        renderOfflineSvgMap(main, cats, onPickArea);
        return;
    }

    const sightings = geoData?.sightings || [];
    const uniqueCats = [...new Map(sightings.filter(s => s.cat_id).map(s => [s.cat_id, s.cat_name || `猫 #${s.cat_id}`])).entries()];

    main.innerHTML = back('#home', '返回首页')
        + head('沈理猫地图（高德实景）', '基于高德地图精确落点展示猫咪出现位置与时间轨迹。')
        + `<section class="surface" style="padding:14px">
            <div class="actions" style="flex-wrap:wrap;gap:8px;margin-bottom:10px">
              <button type="button" class="btn light" id="amap-layer-toggle">切换卫星图</button>
              <button type="button" class="btn light" id="amap-locate">${icon('pin')}定位到我</button>
              <select id="amap-cat-filter" aria-label="按猫查看时空轨迹" style="max-width:190px">
                <option value="">全部精确目击（${sightings.length} 条）</option>
                ${uniqueCats.map(([id, name]) => `<option value="${id}">${esc(name)} · 时空轨迹</option>`).join('')}
              </select>
              <button type="button" class="btn ghost" id="amap-offline">离线示意图</button>
            </div>
            <div id="amap-container" style="width:100%;height:440px;border-radius:12px;overflow:hidden;border:1px solid var(--border)"></div>
            <p class="hint" id="amap-hint" style="margin-top:8px">${sightings.length ? `已加载 ${sightings.length} 条带精确 GPS 的目击记录，点击橘色图钉查看照片与时间。` : '当前暂无带精确 GPS 的目击记录，拍照授权定位后将自动精确落点在此地图上。'}</p>
          </section>
          <section class="surface" id="amap-detail" style="margin-top:12px">
            <div class="map-panel-head">
              <div><h2>沈阳理工大学（浑南校区）</h2><p class="hint">可点击地图任意图钉查看对应猫咪，或直接在这里记录新目击。</p></div>
              <button type="button" class="btn" id="amap-record-now">${icon('camera')}拍照记录目击</button>
            </div>
          </section>`;

    const map = new AMap.Map('amap-container', {
        zoom: 16.2,
        center: [123.493886, 41.727829],
        viewMode: '2D',
    });
    if (AMap.Scale) map.addControl(new AMap.Scale());

    const satLayer = new AMap.TileLayer.Satellite();
    const roadNet = new AMap.TileLayer.RoadNet();
    let isSat = false;
    main.querySelector('#amap-layer-toggle').onclick = e => {
        isSat = !isSat;
        if (isSat) { map.add([satLayer, roadNet]); e.target.textContent = '切换标准图'; }
        else { map.remove([satLayer, roadNet]); e.target.textContent = '切换卫星图'; }
    };
    main.querySelector('#amap-offline').onclick = () => {
        map.destroy();
        renderOfflineSvgMap(main, cats, onPickArea, () => campusMapPage(main, cats, onPickArea));
    };
    main.querySelector('#amap-record-now').onclick = () => onPickArea('');

    const infoWindow = new AMap.InfoWindow({ offset: new AMap.Pixel(0, -28) });
    let overlays = [];

    function renderPins(filterCatId = '') {
        if (overlays.length) { map.remove(overlays); overlays = []; }
        const list = filterCatId ? sightings.filter(s => String(s.cat_id) === String(filterCatId)) : sightings;
        const path = [];
        // Chronological order for trajectory polyline
        const ordered = [...list].reverse();
        ordered.forEach((s, idx) => {
            const [gLng, gLat] = wgs84ToGcj02(Number(s.latitude), Number(s.longitude));
            path.push([gLng, gLat]);
            const label = filterCatId ? String(idx + 1) : '🐾';
            const marker = new AMap.Marker({
                position: [gLng, gLat],
                title: s.cat_name || s.area || '校园猫目击',
                content: `<div style="background:#d9822b;color:#fff;border:2px solid #fff;border-radius:999px;min-width:26px;height:26px;padding:0 6px;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;box-shadow:0 2px 6px rgba(0,0,0,.28)">${label}</div>`,
                offset: new AMap.Pixel(-13, -13),
            });
            marker.on('click', () => {
                const title = s.cat_name ? esc(s.cat_name) : `待辨认目击 #${s.id}`;
                const link = s.cat_id ? `<a href="#cat/${Number(s.cat_id)}" style="color:#1c4d3e;font-weight:600">查看档案 →</a>` : '<span style="color:#666">待审核建档</span>';
                const accTxt = s.location_accuracy ? ` · 精度约 ${Math.round(s.location_accuracy)}m` : '';
                infoWindow.setContent(
                    `<div style="min-width:190px;font-size:13px;line-height:1.5">`
                    + `<img src="${esc(s.thumbnail_url)}" alt="${title}" style="width:100%;height:110px;object-fit:cover;border-radius:8px;margin-bottom:6px">`
                    + `<div><strong>${title}</strong>${s.coat ? ` · ${esc(s.coat)}` : ''}</div>`
                    + `<div style="color:#555">${esc(s.area || '沈理校内')}${accTxt}</div>`
                    + `<div style="color:#777;font-size:12px">${esc(date(s.observed_at))}</div>`
                    + `<div style="margin-top:6px">${link}</div></div>`
                );
                infoWindow.open(map, [gLng, gLat]);
            });
            overlays.push(marker);
        });
        if (filterCatId && path.length >= 2) {
            const line = new AMap.Polyline({
                path,
                strokeColor: '#d9822b',
                strokeWeight: 4,
                strokeStyle: 'dashed',
                showDir: true,
            });
            overlays.push(line);
        }
        if (overlays.length) {
            map.add(overlays);
            if (path.length === 1) map.setZoomAndCenter(17.2, path[0]);
            else map.setFitView(overlays, false, [48, 48, 48, 48]);
        }
    }

    renderPins('');
    main.querySelector('#amap-cat-filter').onchange = e => renderPins(e.target.value);
    main.querySelector('#amap-locate').onclick = () => {
        if (!navigator.geolocation) return;
        navigator.geolocation.getCurrentPosition(pos => {
            const [gLng, gLat] = wgs84ToGcj02(pos.coords.latitude, pos.coords.longitude);
            map.setZoomAndCenter(17.5, [gLng, gLat]);
            const meMarker = new AMap.CircleMarker({
                center: [gLng, gLat], radius: 8, strokeColor: '#fff', strokeWeight: 2, fillColor: '#2563eb', fillOpacity: 0.9,
            });
            map.add(meMarker);
        }, () => {}, { enableHighAccuracy: true, timeout: 8000 });
    };
}
