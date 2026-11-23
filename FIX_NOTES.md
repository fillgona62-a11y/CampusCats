# CampusCats v0.3.1 修复与优化说明

基于仓库提交 `9107d3ce`（安卓 0.3.0）完成以下修复与体验优化，全部 14 项单元测试已通过：

1. **修复备份恢复与密钥损坏导致 503 的隐患**（`server/backup.py`、`server/providers.py`）
   - `backup.py` 生成快照时同步清理 `agent_providers` 表（与 `sessions` 一致），避免恢复到新环境缺少 `agent-key.fernet` 时解密报错。
   - `providers.effective()` 捕获密钥缺失或损坏异常，自动降级为本地模式，不再阻断 `/api/identify` 和 `/api/agent/status`。
2. **「照片查查」直连 `/api/identify`，消除多余 LLM 开销**（`server/app.py`、`web/capture.js`）
   - 开放 `/api/identify` 支持未登录请求（沿用按用户/IP 限流），游客与本机草稿模式查图不再绕道 `/api/agent/chat`。
3. **补齐视觉模型连通测试与推理模型兼容**（`server/providers.py`、`server/ai_vision.py`、`web/agent-settings.js`）
   - 在设置页点击「测试连接」时，若填写了 `vision_model`，会顺带发送极小测试图校验视觉模型是否支持图片输入。
   - 自配服务商调用视觉模型时与对话模型一致省略 `temperature` 参数，兼容 o1/o3 等推理模型。
4. **识图结果一键联动「猫猫助手」**（`web/capture.js`、`web/agent.js`）
   - 每张查图结果卡新增「问问猫猫助手」按钮，点击自动打开助手并带入本次查重与花色/品种结论。
