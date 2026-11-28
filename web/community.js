import {api, back, busy, esc, head, icon, img} from './ui.js';

export function badgeList(badges = []) {
    return badges.length ? '<ul class="community-badges">' + badges.map(badge =>
        '<li><span class="badge-mark">' + icon(badge.icon) + '</span><div><strong>' +
        esc(badge.title) + ' · ' + Number(badge.count) + '</strong><p>' +
        esc(badge.description) + '</p></div></li>').join('') + '</ul>' :
        '<p class="hint">发现新猫、完成命名和参与有效辨认都可以获得徽章。</p>';
}

function estimate(topic) {
    const values = topic.distribution;
    const rows = Object.entries(values).map(([key, value]) => {
        const label = topic.options.find(option => option.key === key)?.label || (key === 'unclear' ? '证据不足' : '候选档案');
        return '<li>' + esc(label) + ' <strong>' + Math.round(value * 100) + '%</strong></li>';
    });
    return '<details><summary>' + (topic.calibrated ? '模型概率分布' : '初步判定权重（待校准）') +
        '</summary><ul>' + rows.join('') + '</ul></details>';
}

function ballot(topic, id) {
    if (topic.voted) return '<p class="hint">已投票。截止后可查看票数和结果。</p>';
    return '<form data-vote="' + id + '"><fieldset><legend>这只猫属于哪个档案？</legend>' +
        topic.options.map(option => '<label class="community-option"><input type="radio" name="choice" required value="' +
            esc(option.key) + '"' + (option.available ? '' : ' disabled') + '>' +
            (option.photo_id ? img('/media/thumb/' + Number(option.photo_id) + '.jpg', '', 'loading="lazy"') : '') +
            '<span>' + esc(option.label) + '</span></label>').join('') +
        '</fieldset><p class="form-error" role="alert"></p><button class="btn" type="submit">提交选票</button></form>';
}

export function communityPage(main, data, page, refresh) {
    main.innerHTML = '<div class="narrow">' + back('#home','返回首页') + head('校园猫论坛','辨认照片里的猫，或给新猫取一个名字。') +
        '<div class="stack">' + (data.topics.length ? data.topics.map(topic => {
            const id = Number(topic.id);
            const naming = ['private_name','public_name'].includes(topic.state);
            const polling = topic.state === 'poll';
            const headline = polling ? '帮忙辨认这只猫' : naming ? '为新猫命名' : '辨认结果';
            const end = topic.closes ? new Date(topic.closes * 1000).toLocaleString('zh-CN', {timeZone:'Asia/Shanghai',hour12:false}) : '';
            const winner = topic.options.find(option => option.key === topic.result);
            const outcome = topic.state === 'cancelled' ? '此条记录已变更' :
                topic.result === 'no_votes' ? '截至结束时无人投票，保留待辨认。' :
                topic.result === 'unclear' ? '证据不足，保留待辨认。' :
                topic.result === 'new' ? '辨认为新猫。' : winner ? '已关联「' + winner.label + '」。' : '';
            const counts = !polling && topic.closes !== null && topic.result ? '<ul>' + topic.options.map(option =>
                '<li>' + esc(option.label) + ' · ' + Number(option.votes) + ' 票</li>').join('') + '</ul>' : '';
            const name = naming ? '<form data-name="' + id + '"><p class="hint">' +
                (topic.state === 'private_name' ? '这是你首发的校园新猫，命名权由你的账号保留。' :
                    '投票确认是新猫。第一个成功提交猫名的账号获得命名权。') +
                '</p><label class="field"><span>猫名</span><input name="name" required maxlength="40"></label><p class="form-error" role="alert"></p><button class="btn" type="submit">确认命名</button></form>' : '';
            return '<article class="surface community-topic" id="community-' + id + '"><h2>' + headline + '</h2><p class="hint">' +
                esc(topic.area) + (end ? ' · 北京时间 ' + esc(end) + ' 截止' : '') + '</p>' +
                (polling || topic.cat_id ? img('/media/crop/' + id + '.jpg','本条目击照片','class="community-photo" loading="lazy"') : '') +
                (polling ? ballot(topic, id) : '<p>' + esc(outcome) + '</p>' + counts + name) +
                (topic.cat_id ? '<a class="link" href="#cat/' + Number(topic.cat_id) + '">' + esc(topic.name) + '</a>' : '') +
                estimate(topic) + '</article>';
        }).join('') : '<section class="surface"><p>当前还没有需要辨认或命名的照片。</p></section>') +
        '</div><div class="actions community-pages">' +
        (page ? '<a class="btn light" href="#community/' + (page - 1) + '">上一页</a>' : '') +
        (data.more ? '<a class="btn light" href="#community/' + (page + 1) + '">下一页</a>' : '') + '</div></div>';
    main.querySelectorAll('[data-vote],[data-name]').forEach(form => {
        form.onsubmit = event => {
            event.preventDefault();
            const voting = Boolean(form.dataset.vote);
            const id = Number(form.dataset.vote || form.dataset.name);
            const payload = Object.fromEntries(new FormData(form));
            busy(form.querySelector('button'), async () => {
                await api('/community/' + id + (voting ? '/vote' : '/name'), payload);
                await refresh();
                requestAnimationFrame(() => document.getElementById('community-' + id)?.scrollIntoView({block:'nearest'}));
            }, form);
        };
    });
}
