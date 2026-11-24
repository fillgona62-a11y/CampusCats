import { back, card, esc, head, icon } from './ui.js';

/**
 * 沈阳理工大学（浑南校区 · 南屏中路6号）内置校园猫交互地图
 * 方位依据：北临汇泉东路（北门，近地铁10号线理工大学站方向），南临南屏中路（南门正门），
 * 校内以琴园环路为核心，兵器博物馆与兵器广场位于校园中西部。
 */
export const SYLU_LANDMARKS = [
    {
        id: 'north-gate',
        name: '北门（汇泉东路）',
        short: '北门',
        x: 340, y: 66,
        keywords: ['北门', '汇泉', '地铁', '嘉华'],
        desc: '靠近汇泉东路与地铁 10 号线理工大学站方向。',
    },
    {
        id: 'dorm',
        name: '学生生活区（宿舍）',
        short: '生活区宿舍',
        x: 520, y: 148,
        keywords: ['宿舍', '公寓', '生活区', '寝室'],
        desc: '学生宿舍与生活区周边，早晚常有亲人猫咪出没。',
    },
    {
        id: 'canteen',
        name: '餐饮服务中心（食堂）',
        short: '食堂 / 餐饮中心',
        x: 525, y: 266,
        keywords: ['食堂', '餐饮', '餐厅', '一食堂', '二食堂', '三食堂'],
        desc: '沈阳理工大学餐饮服务中心及周边树荫长椅区。',
    },
    {
        id: 'stadium',
        name: '体育场 / 操场',
        short: '体育场',
        x: 152, y: 152,
        keywords: ['体育场', '操场', '体育馆', '运动场', '篮球场', '看台'],
        desc: '校内体育场与看台周边草坪。',
    },
    {
        id: 'armory',
        name: '兵器博物馆 / 兵器广场',
        short: '兵器博物馆',
        x: 175, y: 312,
        keywords: ['兵器', '博物馆', '广场', '坦克', '导弹'],
        desc: '沈理地标兵器博物馆室内展馆与室外兵器广场周边。',
    },
    {
        id: 'library',
        name: '图书馆（琴园环路）',
        short: '图书馆',
        x: 342, y: 214,
        keywords: ['图书馆', '图馆', '自习'],
        desc: '琴园环路核心地标，台阶与草坪常能偶遇晒太阳的猫。',
    },
    {
        id: 'zhixue',
        name: '志学堂',
        short: '志学堂',
        x: 342, y: 320,
        keywords: ['志学堂', '礼堂', '讲堂'],
        desc: '琴园环路沿线志学堂周边绿化带。',
    },
    {
        id: 'teaching',
        name: '教学楼区',
        short: '教学楼区',
        x: 256, y: 404,
        keywords: ['教学楼', '主楼', '信息楼', '机电', '文科', '实验楼', '阶梯'],
        desc: '校内核心教学楼与实验楼连廊、石阶周边。',
    },
    {
        id: 'qinyuan',
        name: '琴园绿地',
        short: '琴园绿地',
        x: 440, y: 382,
        keywords: ['琴园', '绿地', '草坪', '小树林', '花园'],
        desc: '琴园环路内侧树荫草地与休憩步道。',
    },
    {
        id: 'south-gate',
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

export function campusMapPage(main, cats, onPickArea) {
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
}
