# 猫迹 · 沈阳理工大学校园猫图鉴（v0.4.3-SYLU）

猫迹帮同学记录在校园里遇到的猫，当前面向**沈阳理工大学（浑南校区 · 南屏中路 6 号）**开展校内测试。同一只猫可以有多个别名和多条目击记录，图鉴只计一只。游客可以直接浏览图鉴、通过内置**沈理校园猫地图**按地标找猫、用「照片查查」比对查重与识别花色，或向「猫猫助手」查询校园猫动态；注册登录后可以提交目击、点亮个人猫册、参与校园定点观察、补充别名，以及生成带二维码的高清相遇卡与重遇卡。

在线访问：[**打开沈阳理工大学校园猫图鉴（thickearth.online）**](https://thickearth.online/)

## 手机下载与使用

* **安卓手机（Android 8.0 及以上）**

  * **下载源一（官网直连，国内推荐）**：[从官网下载 CampusCats-Android.apk](https://www.google.com/search?q=https://thickearth.online/downloads/CampusCats-Android.apk)

  * **下载源二（GitHub 仓库源）**：[从 GitHub 下载 CampusCats-Android.apk](https://www.google.com/search?q=https://github.com/fillgona62-a11y/CampusCats/raw/main/downloads/CampusCats-Android.apk)（仓库内路径：`downloads/CampusCats-Android.apk`）

  * **使用与升级说明**：安装后默认连接 `https://thickearth.online`（网页内容随线上 `v0.4.3-SYLU` 自动同步更新），首页点「拍照记录」即可拍照或选图；无网或未登录时可先存为**本机草稿**，联网登录后再提交。若学校后续更换域名，可在「我的手记」或离线重连页展开「切换校园站点地址」直接修改。*注：0.4.0 起改用持久化正式签名证书，若此前安装过早期 0.2.x / 0.3.0 测试包提示签名不一致，请先提交本机草稿并卸载旧包后安装一次，后续版本均可直接覆盖更新。*

* **iPhone / iPad（PWA 桌面版）** 用 Safari 打开 <https://thickearth.online/>，点底栏「分享」→「添加到主屏幕」，即可从桌面图标全屏进入。

* **iOS 工程源码下载** 仓库提供已预设 `https://thickearth.online` 地址的 Xcode 工程包（尚无直接安装的签名 IPA）。在 Mac 上解压后用 Xcode 打开 `CampusCats.xcodeproj`，在「Signing & Capabilities」选择自己的开发团队即可真机运行：[下载 iOS 工程 ZIP](https://www.google.com/search?q=https://github.com/fillgona62-a11y/CampusCats/raw/main/downloads/CampusCats-iOS-Xcode.zip)（仓库内路径：`downloads/CampusCats-iOS-Xcode.zip`）。

## 最新功能与近期更新（v0.4.1 \~ v0.4.3-SYLU）

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

* **生产部署加固（v0.4.1）**：补齐 Gunicorn 单进程多线程配置、Nginx `ETag` / `304` 透传、PWA 离线预缓存 `/device.js`、运维巡检脚本（`server/maintenance.py`）与 CI 前端语法校验。详见 [版本更新说明](https://www.google.com/search?q=FIX_NOTES.md)。

## 本地启动

需要 Python 3.10 或更新版本，以及 SQLite 3.35 或更新版本。在项目根目录创建并激活虚拟环境，再安装依赖并启动服务：

```
python -m pip install -r server/requirements.txt
python server/app.py --port 8765

```

初次启动时，主页已建档数量为 0，照片和账号数据保存在 `instance/`。Windows 上也可以在安装好依赖后直接双击 `start.cmd`。[打开本机图鉴](https://www.google.com/search?q=http://127.0.0.1:8765)

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

品种可根据多只已核验相似档案提供待核实线索，正式核验需由维护者登记可复查来源。跨日个体检索准确率与自动归档指标可通过本校照片离线评测，详见 [识别复测指南](https://www.google.com/search?q=evaluate/README.md)。

## 自行构建与部署

* **构建安卓安装包**：使用 `mobile/android/build-debug.ps1` 构建（需 Android SDK Platform 35+ 与 JDK）。默认使用本机 `%LOCALAPPDATA%\CampusCats\signing\campuscats-signing.jks` 持久化签名密钥以保证后续覆盖升级保留本机草稿；可通过 `-SchoolOrigin https://your-campus.example` 指定预设的学校 HTTPS 站点地址。

* **构建 iOS 客户端**：工程源码位于 `mobile/ios/`，可在 `App.swift` 的 `schoolOrigin` 中预设学校 HTTPS 地址。

* **服务端部署与运维**：单机与双机分离部署、Nginx 反向代理缓存、一致性备份恢复及并发压测方法见 [试点部署指南](https://www.google.com/search?q=deploy/README.md)。