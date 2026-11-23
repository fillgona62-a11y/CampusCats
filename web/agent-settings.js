import { api, back, head } from './ui.js';

export function agentSettings(main, settings, afterChange) {
    const admin = Object.hasOwn(settings, 'shared');
    main.innerHTML = `<div class="narrow">${back('#home','返回首页')}${head('接入 Agent','填写服务商提供的 OpenAI 兼容 Chat Completions 接口。')}
      <form class="surface" id="provider-form"><fieldset class="provider-fields">
        <label class="field"><span>配置范围</span><select name="scope"><option value="personal">我的 Agent</option>${admin ? '<option value="shared">校园共用 Agent</option>' : ''}</select></label>
        <p class="hint" id="provider-scope"></p>
        <label class="field"><span>接口类型</span><select name="protocol"><option value="tools">支持工具调用的模型</option><option value="chat">自建 Agent 或普通对话接口</option></select></label>
        <label class="field"><span>HTTPS 接口地址</span><input name="base_url" type="url" required maxlength="400" placeholder="https://api.example.com/v1" autocomplete="off" spellcheck="false"></label>
        <label class="field"><span>对话模型或 Agent ID</span><input name="chat_model" required maxlength="160" autocomplete="off" spellcheck="false"></label>
        <label class="field"><span>视觉模型（选填）</span><input name="vision_model" maxlength="160" autocomplete="off" spellcheck="false"></label>
        <label class="field"><span>API Key</span><input name="api_key" type="password" maxlength="2048" autocomplete="new-password" spellcheck="false"></label>
        <div class="actions"><button class="btn light" type="submit" value="test">测试连接</button><button class="btn" type="submit" value="save">保存并启用</button></div>
        <details id="provider-remove"><summary>移除当前配置</summary><button class="btn light" type="button">确认移除</button></details>
      </fieldset><p id="provider-feedback" role="status"></p></form></div>`;
    const form = main.querySelector('form'), fields = form.elements;
    const feedback = form.querySelector('#provider-feedback');
    const remove = form.querySelector('#provider-remove');
    function refresh() {
        const scope = fields.scope.value, row = settings[scope];
        fields.base_url.value = row?.base_url || '';
        fields.chat_model.value = row?.chat_model || '';
        fields.vision_model.value = row?.vision_model || '';
        fields.protocol.value = row?.protocol || 'tools';
        fields.api_key.value = '';
        fields.api_key.required = !row;
        fields.api_key.placeholder = row ? '已保存，留空沿用同一地址的密钥' : '输入服务商提供的密钥';
        remove.hidden = !row;
        remove.open = false;
        form.querySelector('#provider-scope').textContent = scope === 'shared'
            ? '游客和未设置个人 Agent 的同学使用此配置。' : row ? '你的账号正在使用此配置。移除后使用校园共用助手。' : '当前使用校园共用助手。保存后，仅你的账号使用这里的 Agent。';
        feedback.textContent = '';
    }
    fields.scope.onchange = refresh;
    async function apply(action) {
        const data = Object.fromEntries(new FormData(form));
        form.querySelector('fieldset').disabled = true;
        feedback.textContent = action === 'test' ? '正在请求所填接口…' : '正在保存…';
        try {
            const reply = await api('/agent/settings', action === 'remove' ? {scope:data.scope, action} : {...data, action});
            if (!form.isConnected) return;
            if (action === 'test') {
                feedback.textContent = reply?.vision_tested
                    ? '连接成功，对话模型与视觉模型均已响应。'
                    : '连接成功，所填对话模型已响应。';
                return;
            }
            settings[data.scope] = action === 'remove' ? null : {
                base_url:data.base_url, chat_model:data.chat_model, vision_model:data.vision_model, protocol:data.protocol
            };
            refresh();
            afterChange();
            feedback.innerHTML = (action === 'remove' ? '已移除配置。' : '已保存并启用。') +
                ' <button type="button" class="btn light" id="try-agent">打开猫猫助手</button>';
            feedback.querySelector('button').onclick = () => document.querySelector('#agent-fab').click();
        } catch (error) {
            feedback.textContent = error.message;
        } finally {
            form.querySelector('fieldset').disabled = false;
        }
    }
    form.onsubmit = event => {
        event.preventDefault();
        apply(event.submitter?.value || 'test');
    };
    remove.querySelector('button').onclick = () => apply('remove');
    refresh();
}
