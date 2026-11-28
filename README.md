# 琴园有猫 · 沈阳理工大学校园猫图鉴（v0.6.3-SYLU）

琴园有猫帮同学记录在校园里遇到的猫，当前面向**沈阳理工大学（浑南校区 · 南屏中路 6 号）**开展校内测试。同一只猫可以有多个别名和多条目击记录，图鉴只计一只。游客可以直接浏览图鉴、通过**高德实景校园猫地图**查看校内地标与猫猫时空轨迹、用「照片查查」完成多猫查重与品种花色识别，或向「猫猫助手」查询校园猫动态；注册登录后可以提交目击、点亮个人猫册、参与校园定点观察、补充别名，以及生成带二维码的高清相遇卡与重遇卡。

在线访问：[**打开沈阳理工大学校园猫图鉴（thickearth.online）**](https://thickearth.online/)

## 手机下载与使用

* **安卓手机（Android 8.0 及以上）**

  * **下载源一（官网直连，国内推荐）**：[从官网下载 CampusCats-Android.apk](https://thickearth.online/downloads/CampusCats-Android.apk)

  * **下载源二（GitHub 仓库源）**：[从 GitHub 下载 CampusCats-Android.apk](https://github.com/fillgona62-a11y/CampusCats/raw/main/downloads/CampusCats-Android.apk)（仓库内路径：`downloads/CampusCats-Android.apk`）

  * **使用与升级说明**：安装后默认连接 `https://thickearth.online`（网页内容随线上 `v0.6.3-SYLU` 热更新，App 内亦可一键检查并下载更新安装包），首页点「拍照记录」即可拍照或选图；无网或未登录时可先存为**本机草稿**，联网登录后再提交。若学校后续更换域名，可在「我的手记」或离线重连页展开「切换校园站点地址」直接修改。*注：0.4.0 起改用持久化正式签名证书，若此前安装过早期 0.2.x / 0.3.0 测试包提示签名不一致，请先提交本机草稿并卸载旧包后安装一次，后续版本均可直接覆盖更新。*

* **iPhone / iPad（PWA 桌面版）** 用 Safari 打开 <https://thickearth.online/>，点底栏「分享」→「添加到主屏幕」，即可从桌面图标全屏进入。

* **iOS 工程源码下载** 仓库提供已预设 `https://thickearth.online` 地址的 Xcode 工程包（尚无直接安装的签名 IPA）。在 Mac 上解压后用 Xcode 打开 `CampusCats.xcodeproj`，在「Signing & Capabilities」选择自己的开发团队即可真机运行：[下载 iOS 工程 ZIP](https://github.com/fillgona62-a11y/CampusCats/raw/main/downloads/CampusCats-iOS-Xcode.zip)（仓库内路径：`downloads/CampusCats-iOS-Xcode.zip`）。

## 最新功能与近期更新（v0.4.0 ~ v0.6.3-SYLU）

### v0.6.3-SYLU（基于 v0.6.2-SYLU：云端主导识猫 + 暗光防误杀 + 稳定性与安全性全面优化）
- **云端视觉模型占主导权重 + 消除重复 ONNX 推理**：`server/clip_classifier.py`、`server/ai_vision.py` 与 `server/catalog.py` 重构为单次前向复用的 `analyze_crop_once(crop)`，本地 CLIP 不再抢判纯种猫品种（统一作为 `local_assist` 毛色与物种辅助），开启云端视觉模型时跳过本地花色互斥预过滤并将同猫/异猫对比置信阈值校至 `0.55`；全图与裁剪框不再重复跑 YOLO 与 CLIP。
- **修复暗光/长毛猫误杀**：`server/detector.py` 禁止对紧贴子裁剪框再次运行 `YOLOv8n`（彻底解决双猫拼图或暗光黑猫被子框误判为犬类的问题），并增加低照度（`luma < 90`）提亮二次召回。
- **弱网稳定性、安全与体验优化**：`server/providers.py` 强制公网 IPv4 优先建连并放宽超时至 `35s`；`web/ui.js` 对只读及 `/api/detect`、`/api/identify` 瞬断自动静默重试 1 次；`web/capture.js` 按 `800px` / `1024px` 轻量化发送查重图适配 3 Mbps 带宽；`server/accounts.py` 移除源码明文默认管理员密码改由环境变量显式配置；`server/agent.py` 统一输出北京时间（UTC+8）；`web/review.js` 自动预填 `coat_hint`。

### v0.6.1 ~ v0.6.2-SYLU（高德精准融合定位 + 移动端体验 + 前端热更新与 App 一键更新）
- **高德精准融合定位与沈理地标校准**：新增 `locateAccurate()` 融合定位逻辑与 WGS84/GCJ02 坐标校准，修复安卓端高德地图拦截并优化移动端动效与局部特征/温度缩放（`logit_scale` 上限 `35.0`、`local_heuristic` 豁免、花纹惩罚平滑）。
- **前端联网热更新 & App 内一键更新**：新增 `GET /api/app/version`、`AndroidManifest.xml` `REQUEST_INSTALL_PACKAGES` 权限及 `CaptureFile.java` APK 授权安装分发，支持应用内一键下载更新与 GitHub Actions 自动同步仓库安装包。

### v0.6.0-SYLU（高德实景全量地图 + 三模型防误识视觉栈 + 猫猫助手全面升级）
- **纯高德实景校园猫地图（移除旧版离线 SVG 地图）**：全面启用高德地图 JS API 2.0 实景与卫星图，修复 HTTPS 下 `Referrer-Policy` 导致的 `ERR_BLOCKED_BY_ORB` 拦截与安卓 WebView WebGL 矢量瓦片兼容；10 个沈理核心地标、精确 GPS 猫咪足迹弹窗与时空轨迹折线同屏呈现。
- **全链路防把人/狗识别成猫**：`server/detector.py` 升级 80 类全类别对比抑制（拦截人像 `person` 与犬类 `dog` 锚框）+ 本地 `CLIP-ViT-B/32` 物种门控 + 云端 VLM `is_cat` 校验，在「照片查查」「记录目击提交（422 拦截）」与「猫猫助手」三条链路彻底杜绝人像误判为猫。
- **多猫拥挤同框高斯 Soft-NMS + 分块高清辅助检测**：升级 `YOLOv8s` + Gaussian Soft-NMS 与大图多尺度分块扫描，解决多只幼猫依偎重叠时被硬阈值误删的问题，「猫猫助手」传图同样支持自动多猫逐只识别。
- **修复异猫误匹配（DINOv2 空间局部特征池化 + 距离校准）**：`server/encoder.py` 从仅取全局 CLS 向量升级为 **CLS + 前景 GeM 空间块 + 头部/耳尖分区 + 胸腹/四肢分区** 四路融合（`v6`），收紧相似度外缘阈值并引入 `weak_candidate` 弱相似警示、双正脸零内点惩罚与花色互斥过滤。
- **本地零成本 16 品种识别 + 云端免费/GPT 一键预设**：新增 `server/clip_classifier.py`（`CLIP-ViT-B/32 INT8` 离线识别 16 类猫品种与 11 类花色），并在「接入 Agent」新增 **OpenAI GPT（学校/官方额度）、智谱 `glm-4v-flash`（免费）、硅基流动 `Qwen2.5-VL`（免费）、阿里云千问、DeepSeek** 一键预设。
- **猫猫助手全面重构**：补齐 `media_dir` 局部特征重排、自动修复 `deepseek-flash` 模型名笔误与 `tools` 协议降级重试、升级中文无空格地标/猫名/属性分词检索与气泡安全 Markdown 排版。

### v0.5.0 ~ v0.5.1-SYLU（自动多猫检测 + 高德精确地图与时空轨迹版）
- **12.2 MB `YOLOv8n` 自动多猫检测 + 23.3 MB `DINOv2-small` 两阶段识别**：新增 `server/detector.py` 与 `POST /api/detect`，拍照或选图后自动框出画面中的全部猫咪（支持一图多猫，单张 ~120 ms），紧贴猫身裁去背景后再逐只送入三视角 `DINOv2-small` 查重；云端 8 猫 25 图跨天实测 Top-1 从 84.0% 提升至 **96.0%**。
- **拍照询问位置权限 & 猫猫时空关联**：拍照/选图自动请求定位权限，数据库记录每条目击的精确 `latitude`、`longitude`、`location_accuracy` 与 `observed_at` 时刻，并在猫档案时间线展示；安卓客户端（`AndroidManifest.xml` / `MainActivity.java`）同步补齐定位授权回调。
- **高德地图 JS API 2.0 实景地图与轨迹**：配置 `AMAP_JS_KEY` / `AMAP_SECURITY_CODE` 后，自动启用沈阳理工大学高德真实底图与卫星图切换、WGS84→GCJ02 坐标纠偏、精确猫猫图钉弹窗、单只猫按时间顺序的时空轨迹折线以及拍照逆地理编码精确地址回填；未配置或离线时自动兜底回退至内置沈理 SVG 地图。

### v0.4.5-SYLU（DINOv2 三视角 TTA 与多模型融合识别版）
- **三视角多尺度 TTA + `DINOv2-small INT8` 最优方案**：经云端跨天多角度实测对比（92.9% Top-1 准确率、分离间隔 +0.230、单张仅 207 ms），`server/encoder.py` 升级为 **原图 + 水平镜像 + 78% 中心聚焦裁切** 三视角融合，校准生产距离阈值至 `0.45`，自动削弱边缘草地/地砖背景干扰。
- **支持多模型逗号拼接融合**：`CAMPUSCATS_ENCODER` 原生支持单模型或 `model1.onnx,model2.onnx` 多模型特征融合，方便后续无缝叠加沈阳理工本校微调模型。
- **免 PyTorch 一键安装 23 MB 量化模型**：`deploy/install_reid_model.py` 支持直接从国内镜像下载 `dinov2-small` 量化 ONNX，无需安装 2 GB PyTorch 即可在 4 GB CPU 服务器上跑满深度识猫引擎。

### v0.4.4-SYLU（四层融合个体识别升级版）
- **光照与镜像鲁棒局部特征（`coat-texture-2`）**：新增轻度 Gray-World 白平衡与亮度拉伸抑制逆光/阴影偏色，升级椭圆前景加权 5 分区 HSV + LBP + HOG 梯度方向特征，并支持水平镜像不变检索、多参考照共识融合与校园区域微弱先验。
- **倾角正脸与全身花纹 SIFT+RANSAC 重排**：正脸检测新增 ±12° 歪头容错与 CLAHE 暗毛对比度增强；侧身/背影照新增全身花纹 SIFT+RANSAC 候选重排，同时保持双日正脸自动归档的严格防误判阈值。
- **多图拼图 VLM 跨图复核**：配置视觉大模型后，「照片查查」自动将新照与候选参考照拼接成带编号对照图，逐项比对额头纹、鼻梁白斑、剪耳与四肢花纹，直接输出核对理由并重排候选。
- **ONNX 深度 Re-ID TTA 与国内一键安装脚本**：`server/encoder.py` 升级水平镜像双视角 TTA 特征融合；新增 `deploy/install_reid_model.py`（默认国内 `hf-mirror.com` 镜像，支持一键导出 `MegaDescriptor-T-224` 动物个体识别 ONNX 模型）与 `server/maintenance.py --reindex-vision` 一键特征索引重建。

### v0.4.3-SYLU（沈阳理工大学校内测试版）

* **内置沈理交互式校园猫地图（`#map` / `web/campus-map.js`）**：基于沈阳理工大学浑南校区真实方位（北临汇泉东路、南临南屏中路、中西部兵器博物馆/兵器广场、中心琴园环路）绘制交互式 SVG 校园地图，无需外网地图密钥即可离线秒开。

* **10 个沈理核心地标与猫点联动**：预设 **北门（汇泉东路）、学生生活区（宿舍）、餐饮服务中心（食堂）、体育场 / 操场、兵器博物馆 / 兵器广场、图书馆（琴园环路）、志学堂、教学楼区、琴园绿地、南门（南屏中路）** 10 个地标。橘色标点实时显示各点位已建档猫数量，点按地标可直接查看该区域常驻猫卡片，并支持「在这里记录目击」一键带入地点。

* **沈理标准区域字典与智能问答适配**：`/api/areas` 预置 10 个沈理标准区域供记录目击与定点观察下拉补全；「猫猫助手」新增「兵器广场找猫」等校内快捷提问；Service Worker 升级至 `campuscats-shell-v12` 预缓存地图脚本。

### v0.4.2（视觉与移动端体验升级）

* **全新视觉语言与深墨绿夜间模式**：统一暖橘点缀色（`#d9822b`）、三档字重与 1080px 响应式外壳，新增 SVG 猫爪标识与自然户外校园猫头图，全面适配浅色与深墨绿护眼夜间模式（含地图、图鉴与手记页）。

* **照片优先的猫猫卡片与引导优化**：重构图鉴卡片突出猫咪主体照片与状态徽标，优化键盘/触控焦点圆角样式，新增冷启动空库欢迎引导，并对普通同学隐藏底层模型名称保持界面清爽。

### v0.4.0 \~ v0.4.1（核心档案、AI 识别与生产加固）

* **校园猫档案与维护工具**：支持登记性别、绝育状态（剪耳等）、在校状态（在校活跃 / 需关注健康 / 已领养毕业 / 喵星纪念）与相处提示；支持按区域、关键词与状态联合筛选，以及维护者精选封面照与原子合并重复档案。

* **「照片查查」与「猫猫助手」联动**：游客与登录用户均可拍照查重与识别花色特征，并一键带入「猫猫助手」追问出没规律；支持接入 OpenAI 兼容对话模型与视觉模型（`Vision Model`）。

* **高清二维码重遇卡与定点观察**：跨日重遇自动解锁「重遇卡片」，支持 2x 高清渲染与扫码直达猫档案；支持 10 分钟定点观察计时与防公式注入的周报 CSV 导出。

* **生产部署加固（v0.4.1）**：补齐 Gunicorn 单进程多线程配置、Nginx `ETag` / `304` 透传、PWA 离线预缓存 `/device.js`、运维巡检脚本（`server/maintenance.py`）与 CI 前端语法校验。详见 [版本更新说明](FIX_NOTES.md)。

## 本地启动

需要 Python 3.10 或更新版本，以及 SQLite 3.35 或更新版本。在项目根目录创建并激活虚拟环境，再安装依赖并启动服务：

```
python -m pip install -r server/requirements.txt
python server/app.py --port 8765

```

初次启动时，主页已建档数量为 0，照片和账号数据保存在 `instance/`。Windows 上也可以在安装好依赖后直接双击 `start.cmd`。[打开本机图鉴](http://127.0.0.1:8765)

## 从第一张照片开始

1. **地图找猫、查重或记录目击**：游客可在首页进入「沈理猫地图」按地标查看常驻猫，或点「照片查查」直接比对图鉴；注册账号并保存恢复码后，可在「记录目击」拍照或从相册选图。同框有多只猫时，分别框选每只猫的位置。

2. **填写沈理区域并提交**：选择或输入校园区域（自动下拉提示 10 个沈理标准地标）并提交后，系统保存本次记录。

3. **审核建档与日常维护**：维护者在「维护」工作台中核对身份——新猫建立档案（可同步登记性别、绝育与性格提示），已建档的猫累计目击记录，重复建档的猫可在档案页合并。

要为已注册账号开通维护者审核权限，在项目根目录执行以下命令（替换为目标账号邮箱），刷新页面后即可看到「维护」入口：

```
python server/app.py --promote reviewer@example.edu

```

## 识别与自动归档

系统默认按框内毛色、明暗分布和局部二值纹理检索，最多展示三只候选猫并附上实际命中的历史参考照；画面过暗、过曝、模糊或主体像素不足时会提示补拍。

服务端安装可选的 OpenCV 后，当新照片与同一档案**两个不同日期的人工核实照**在正脸局部特征（SIFT + RANSAC 几何一致性）上充分吻合时，会自动归档关联到该猫档案；其余目击保留待辨认。若人工参考照后续被重审撤回，依赖它的自动归档记录会自动退回待辨认队列：

```
python -m pip install "opencv-python-headless>=4.11,<5"

```

品种可根据多只已核验相似档案提供待核实线索，正式核验需由维护者登记可复查来源。跨日个体检索准确率与自动归档指标可通过本校照片离线评测，详见 [识别复测指南](evaluate/README.md)。

## 自行构建与部署

* **构建安卓安装包**：使用 `mobile/android/build-debug.ps1` 构建（需 Android SDK Platform 35+ 与 JDK）。默认使用本机 `%LOCALAPPDATA%\CampusCats\signing\campuscats-signing.jks` 持久化签名密钥以保证后续覆盖升级保留本机草稿；可通过 `-SchoolOrigin https://your-campus.example` 指定预设的学校 HTTPS 站点地址。

* **构建 iOS 客户端**：工程源码位于 `mobile/ios/`，可在 `App.swift` 的 `schoolOrigin` 中预设学校 HTTPS 地址。

* **服务端部署与运维**：单机与双机分离部署、Nginx 反向代理缓存、一致性备份恢复及并发压测方法见 [试点部署指南](deploy/README.md)。