import { api, back, esc, head } from './ui.js';

const PROVIDER_PRESETS = [
    {
        id: 'school-gpt',
        label: '学校 GPT 额度（gpt-6.2-sol / gpt-6.1-terra）',
        base_url: 'https://api.openai.com/v1',
        chat_model: 'gpt-6.1-terra',
        vision_model: 'gpt-6.2-sol',
        protocol: 'tools',
        tip: '专为「本地 0.5s 初筛 Top3 + 云端单张对比图精准拍板」双关架构优化！若学校提供了专属中转/网关地址，请将下方 HTTPS 接口地址改为学校给的 .../v1 地址，模型名按实际可用填入 gpt-6.2-sol 或 gpt-6.1-terra。',
    },
    {
        id: 'openai',
        label: 'OpenAI 官方（gpt-4o-mini）',
        base_url: 'https://api.openai.com/v1',
        chat_model: 'gpt-4o-mini',
        vision_model: 'gpt-4o-mini',
        protocol: 'tools',
        tip: 'OpenAI 官方标准接口与多模态模型 gpt-4o-mini（或 gpt-4o），支持工具调用与单张对比图拍板。',
    },
    {
        id: 'zhipu',
        label: '智谱 GLM（国内免费视觉+对话）',
        base_url: 'https://open.bigmodel.cn/api/paas/v4',
        chat_model: 'glm-4-flash',
        vision_model: 'glm-4v-flash',
        protocol: 'tools',
        tip: '智谱开放平台（open.bigmodel.cn）长期提供免费的 glm-4-flash（对话+工具）与 glm-4v-flash（免费多模态识图），国内直连无需代理。',
    },
    {
        id: 'siliconflow',
        label: '硅基流动（免费 Qwen2.5-VL）',
        base_url: 'https://api.siliconflow.cn/v1',
        chat_model: 'Qwen/Qwen2.5-7B-Instruct',
        vision_model: 'Qwen/Qwen2.5-VL-7B-Instruct',
        protocol: 'tools',
        tip: '硅基流动（siliconflow.cn）提供免费/赠送额度的通义千问 Qwen2.5-VL 视觉模型，中文猫品种与花色识别准确。',
    },
    {
        id: 'dashscope',
        label: '阿里云百炼（通义千问 VL）',
        base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        chat_model: 'qwen-plus',
        vision_model: 'qwen-vl-plus',
        protocol: 'tools',
        tip: '阿里云百炼兼容接口，新开通赠送免费额度，qwen-vl-plus 适合精细剪耳与品种判断。',
    },
    {
        id: 'deepseek',
        label: 'DeepSeek（对话+本地识图）',
        base_url: 'https://api.deepseek.com/v1',
        chat_model: 'deepseek-chat',
        vision_model: '',
        protocol: 'tools',
        tip: '注意 DeepSeek 标准模型名为 deepseek-chat（无图片输入接口，视觉留空即可自动搭配服务器本地 ONNX 模型完成识图与品种识别）。',
    },
];

export function agentSettings(main, settings, afterChange) {
    const admin = Object.hasOwn(settings, 'shared');
    main.innerHTML = `<div class="narrow">${back('#home','返回首页')}${head('接入 Agent 与视觉模型','支持一键填入 OpenAI GPT（学校额度）或国内免费多模态模型，驱动猫猫助手查库、品种识别与候选猫跨图复核。')}
      <form class="surface" id="provider-form"><fieldset class="provider-fields">
        <label class="field"><span>配置范围</span><select name="scope"><option value="personal">我的 Agent</option>${admin ? '<option value="shared">校园共用 Agent（全站游客与同学默认使用）</option>' : ''}</select></label>
        <p class="hint" id="provider-scope"></p>
        <div>
          <span style="font-weight:600;font-size:14px">一键填入服务商预设</span>
          <div class="preset-bar">${PROVIDER_PRESETS.map(p => `<button type="button" class="preset-chip" data-preset="${esc(p.id)}">${esc(p.label)}</button>`).join('')}</div>
          <p class="hint" id="preset-tip" hidden></p>
        </div>
        <label class="field"><span>接口类型</span><select name="protocol"><option value="tools">支持工具调用的模型（推荐：GPT / GLM / Qwen / DeepSeek）</option><option value="chat">自建 Agent 或仅支持普通对话的接口</option></select></label>
        <label class="field"><span>HTTPS 接口地址</span><input name="base_url" type="url" required maxlength="400" placeholder="https://api.openai.com/v1" autocomplete="off" spellcheck="false"><small>若使用学校提供的 GPT 转发/代理站，将此处改为学校给的 HTTPS Base URL（如 https://xxx/v1）即可。</small></label>
        <label class="field"><span>对话模型或 Agent ID</span><input name="chat_model" required maxlength="160" placeholder="例如 gpt-4o-mini / glm-4-flash / deepseek-chat" autocomplete="off" spellcheck="false"></label>
        <label class="field"><span>视觉模型（选填，用于云端品种识别与异猫对比）</span><input name="vision_model" maxlength="160" placeholder="例如 gpt-4o-mini / glm-4v-flash / qwen-vl-plus" autocomplete="off" spellcheck="false"></label>
        <label class="field"><span>API Key</span><input name="api_key" type="password" maxlength="2048" autocomplete="new-password" spellcheck="false"></label>
        <div class="actions"><button class="btn light" type="submit" value="test">测试连接</button><button class="btn" type="submit" value="save">保存并启用</button></div>
        <details id="provider-remove"><summary>移除当前配置</summary><button class="btn light" type="button">确认移除</button></details>
      </fieldset><p id="provider-feedback" role="status"></p></form></div>`;
    const form = main.querySelector('form'), fields = form.elements;
    const feedback = form.querySelector('#provider-feedback');
    const remove = form.querySelector('#provider-remove');
    const presetTip = form.querySelector('#preset-tip');

    function refresh() {
        const scope = fields.scope.value, row = settings[scope];
        fields.base_url.value = row?.base_url || '';
        fields.chat_model.value = row?.chat_model || '';
        fields.vision_model.value = row?.vision_model || '';
        fields.protocol.value = row?.protocol || 'tools';
        fields.api_key.value = '';
        fields.api_key.required = !row;
        fields.api_key.placeholder = row ? '已保存，留空沿用同一地址的密钥' : '输入服务商或学校提供的 API Key';
        remove.hidden = !row;
        remove.open = false;
        presetTip.hidden = true;
        form.querySelector('#provider-scope').textContent = scope === 'shared'
            ? '游客和未设置个人 Agent 的同学将默认使用此配置。' : row ? '你的账号正在使用此配置。移除后恢复使用校园共用助手。' : '当前使用校园共用助手。保存后，仅你的账号使用这里的 Agent。';
        feedback.textContent = '';
    }

    form.querySelectorAll('[data-preset]').forEach(btn => {
        btn.onclick = () => {
            const p = PROVIDER_PRESETS.find(item => item.id === btn.dataset.preset);
            if (!p) return;
            const prevUrl = settings[fields.scope.value]?.base_url || '';
            fields.base_url.value = p.base_url;
            fields.chat_model.value = p.chat_model;
            fields.vision_model.value = p.vision_model;
            fields.protocol.value = p.protocol;
            if (prevUrl !== p.base_url) {
                fields.api_key.required = true;
                fields.api_key.placeholder = '请输入该服务商的 API Key';
            }
            presetTip.textContent = p.tip;
            presetTip.hidden = false;
            fields.api_key.focus();
        };
    });

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
