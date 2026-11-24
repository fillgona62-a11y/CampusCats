# CampusCats v0.4.0 优化与升级说明

## v0.4.0 全方位架构、安全与校园运营升级

1. **反向代理真实 IP 识别与注册/登录双维限流**（`server/accounts.py`、`server/app.py`、`deploy/env.example`）
   - 新增 `CAMPUS_TRUSTED_PROXIES` 可信代理网段支持（兼容 `CAMPUS_TRUST_LOCAL_PROXY=1`），在单机与双机 Nginx 反代下准确提取客户端真实 IP，消除全校游客共用同一限流桶导致的误伤 `429`。
   - 为注册、登录和找回密码接口补齐来源 IP 维度限流，防范批量刷号与密码喷洒。
2. **并发隔离、无锁媒体落盘与分级 HTTP 图像缓存**（`server/agent.py`、`server/catalog.py`、`server/media.py`、`server/app.py`、`deploy/nginx.conf.example`）
   - 为外部大模型调用增加并发信号量隔离并在等待网络前提交/释放 SQLite 读事务，防止慢速 LLM 请求占满全部工作线程拖垮主站。
   - 将内容寻址的媒体文件落盘（`save_media` + `fsync`）移出 SQLite `BEGIN IMMEDIATE` 写锁并在异常回滚时安全清理未引用文件，显著缩短写锁持有时间。
   - 对已审核公开缩略图与裁剪图启用 `Cache-Control: public, max-age=3600` 与 `ETag` / `304 Not Modified` 校验，待审核与原图保持 `private, no-store`，大幅节省校园出口带宽。
3. **校园猫核心档案字段、精选封面、重复档案合并与标准区域字典**（`server/schema.sql`、`server/catalog.py`、`web/app.js`、`web/review.js`、`web/capture.js`）
   - 支持老库在线平滑迁移，新增性别、绝育状态、在校状态与性格相处提示字段，图鉴与猫猫助手同步支持检索与状态筛选。
   - 支持维护者指定精选封面照（照片重审退回或删除时由触发器自动回退），支持重复档案原子合并（自动迁移目击与别名、拦截同框冲突）。
   - 支持维护校园标准区域字典，并在记录目击页提供区域自动补全与空白符规范化。
4. **视觉编码长宽比保留、NumPy 向量化检索与离线复测对齐**（`server/encoder.py`、`server/vision.py`、`evaluate/run.py`）
   - ONNX 编码器改为 224×224 长宽比保留 Letterbox 缩放（ImageNet 均值填充），避免横向侧身猫被裁掉头尾辨识特征。
   - 利用 NumPy 矩阵运算加速候选距离排序，并增加进程内版本化参考向量缓存。
   - 离线复测工具默认对齐线上 2048px JPEG 重编码管线，并新增自动归档准确率/误判率统计指标。
5. **高清带二维码分享卡、Android 站点切换与工程化自动化**（`web/qrcode.js`、`web/album.js`、`web/app.js`、`mobile/android/`、`.github/workflows/ci.yml`）
   - 内置零依赖 ISO 标准二维码生成模块，重遇卡与相遇卡升级为 2x 高清渲染、长文本自适应截断并附带扫码直达档案二维码。
   - Android 客户端升级至 0.4.0，支持在应用内动态切换校园 HTTPS 站点地址，打包脚本默认使用本地持久化签名证书以保障覆盖升级不丢失本机草稿；新增 GitHub Actions 双环境自动化单测流水线。

---

## v0.3.1 修复与优化说明

1. **修复备份恢复与密钥损坏导致 503 的隐患**（`server/backup.py`、`server/providers.py`）
2. **「照片查查」直连 `/api/identify`，消除多余 LLM 开销**（`server/app.py`、`web/capture.js`）
3. **补齐视觉模型连通测试与推理模型兼容**（`server/providers.py`、`server/ai_vision.py`、`web/agent-settings.js`）
4. **识图结果一键联动「猫猫助手」**（`web/capture.js`、`web/agent.js`）
---

# CampusCats v0.4.1 工程与运维细节优化

基于提交 `80d0710` 完成以下工程与运维优化（保留原功能与测试全部通过，新增维护巡检测试）：

1. **Nginx `X-Accel-Redirect` 透传 `ETag`**（`deploy/nginx.conf.example`）
   - 增加 `map $upstream_http_etag $campus_media_etag`，并在 `location /_campus_media/` 关闭 Nginx 默认 `etag` 并输出上游 `ETag`，确保公开图片 1 小时后 `If-None-Match` 协商缓存真正命中 304。
2. **补全 PWA 离线预缓存清单**（`web/sw.js`）
   - 将 `/device.js` 加入 `shell` 预缓存数组并将缓存版本升至 `campuscats-shell-v10`，避免未访问过草稿页的用户断网时无法打开离线草稿。
3. **4GB 内存单机 Gunicorn 默认配置优化**（`deploy/campuscats.service.example`）
   - 调整为 `--workers 1 --threads 8`，避免开启 ONNX 编码器时多进程重复占用内存，并让进程内参考照缓存 `_REF_CACHE` 与 LLM 并发信号量 `_LLM_SLOTS` 全局共享。
4. **CI 增加前端 JS 语法检查**（`.github/workflows/ci.yml`）
   - 新增 `web-syntax` 任务，使用 Node.js 校验所有 `web/*.js` 语法。
5. **自动化运维清理与孤儿媒体巡检**（新增 `server/maintenance.py`，更新 `server/backup.py`、`server/test_optimizations.py`）
   - `maintenance.py` 默认只读巡检过期的 `sessions`/`throttle` 记录及超过宽限期的未引用图片，传 `--apply` 安全清理；`backup.py` 快照同步清理 `throttle` 表。
6. **GitHub Releases 自动发布工作流**（新增 `.github/workflows/release.yml`）
   - 推送 `v*` 标签（如 `git tag v0.4.1 && git push origin v0.4.1`）自动创建 GitHub Release 并附带安装包，后续可将 APK/iOS 压缩包从 Git 主干移出以减小仓库体积。
---

# CampusCats v0.4.2 视觉与交互审美升级

基于 UI/UX 评审建议完成全站审美与体验重构：

1. **焦点与弹窗交互优化**：将 `:focus-visible` 改为跟随元素圆角的柔和外发光（消除鼠标点击出现的突兀直角方框）；打开「猫猫助手」弹窗时自动将焦点定位到输入框。
2. **全新户外校园猫封面图**：将 `web/assets/field-cat.jpg` 替换为自然光下树荫草地与石阶上的自由校园猫摄影，整体绿/棕/暖灰色调与站内设计统一。
3. **首页冷启动与信息架构**：全 0 冷启动时隐藏三连 0 统计，改为温暖引导横幅；桌面端快捷入口改为三列一行（安卓端 2×2）；合并并列「照片查查」与「猫猫助手」，顶栏改用统一风格的圆形图标按钮；将「接入 Agent」收进「我的手记」设置区，对话副标题不再对普通学生暴露底层模型名。
4. **字体、字重与样式系统规范**：统一间距/圆角/阴影/三档字重（400/600/700）变量，统一页面最大宽度至 1080px，小字号禁用衬线防 Windows 退化发虚；引入低用量橘猫暖色 `#d9822b` 点缀；新增统一风格线描空状态 SVG 插画。
5. **品牌标志、相册式卡片与深色模式**：重画矢量 SVG 猫爪标志；图鉴卡片升级为照片铺满 + 底部渐变文字遮罩的相册风；基于 CSS 变量新增深墨绿夜间模式（跟随系统暗色主题）。
