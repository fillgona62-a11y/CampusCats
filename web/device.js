import {back, btn, busy, date, empty, esc, head, img} from './ui.js';

async function records(mode, operation) {
    const db = await new Promise((resolve, reject) => {
        const req = indexedDB.open('campuscats-local-notes', 1);
        req.onupgradeneeded = () => req.result.createObjectStore('notes', {keyPath:'id', autoIncrement:true});
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
    });
    try {
        return await new Promise((resolve,reject) => {
            const tx = db.transaction('notes', mode);
            const req = operation(tx.objectStore('notes'));
            tx.oncomplete = () => resolve(req.result);
            tx.onabort = () => reject(tx.error || new Error('手机存储空间不足或不可用。'));
        });
    } finally { db.close(); }
}
export const saveNote = note => records('readwrite', store => store.add(note));
export const getNote = id => records('readonly', store => store.get(Number(id)));
export const removeNote = id => records('readwrite', store => store.delete(Number(id)));

export async function devicePage(main, current) {
    const keys = await records('readonly', store => store.getAllKeys());
    if (!current()) return;
    main.innerHTML = '<div class="narrow">' + back('#home','返回首页') +
        head('本机草稿','照片和目击信息保存在这台手机上。联网登录后可以选择提交到校园图鉴。',btn('#device-capture','拍照记一笔','camera')) +
        (keys.length ? '<div class="stack" id="device-list"></div>' : empty('book','还没有本机草稿','遇见一只猫时，可以先拍下它，记下地点。')) + '</div>';
    const list = main.querySelector('#device-list');
    for (const id of keys.reverse()) {
        const note = await getNote(id);
        if (!current()) return;
        if (!note) continue;
        const article = document.createElement('article');
        article.className = 'entry';
        article.innerHTML = img(note.photo,'本机目击照片','loading="lazy"') + '<div><h3>' + esc(note.area) + '</h3><p>' +
            esc(date(note.observed_at)) + '</p><p>' + esc(note.note) + '</p>' +
            btn('#capture/' + id,'核对并提交','book','light') +
            '<details><summary>删除草稿</summary><button class="btn light">确认删除</button></details></div>';
        article.querySelector('button').onclick = e => busy(e.currentTarget, async () => {
            await removeNote(id);
            if (current()) await devicePage(main, current);
        });
        list.append(article);
    }
}
