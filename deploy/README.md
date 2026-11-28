# 在学校开放琴园有猫试点

业务机运行 Python、图像检索和 SQLite。将数据库固定在业务机本地磁盘。图片可以和数据库放在同一台机器，也可以放到第二台大带宽服务器。两台机器共用一个对外域名，手机始终连接同一服务。

## 先用现有服务器

在 Linux 业务机将项目放到 `/srv/campuscats`，准备服务账号 `campuscats`、该账号可写的数据和图片目录，以及已解析到公网入口的域名和 TLS 证书。在项目根目录创建环境。

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r server/requirements.txt
```

将 `env.example` 的内容复制到 `/etc/campuscats.env`。单机模式将 `CAMPUS_BIND` 改为 `127.0.0.1:8765`，保留 `CAMPUS_SECURE_COOKIE=1`。将 `campuscats.service.example` 安装为 `/etc/systemd/system/campuscats.service`。把 `nginx.conf.example` 用作 Nginx 站点配置，其中的域名、证书路径和 upstream 地址换成实际值。Nginx 账号需要读取网页、缩略图和原图目录的权限；媒体目录只能经配置中的 internal 路径读取。

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now campuscats
sudo nginx -t
sudo systemctl reload nginx
```

在手机上用 HTTPS 打开域名，依次检查游客浏览、注册、相机权限、上传和审核。服务账号需能写入配置的目录。配置中 `CAMPUS_ACCEL_MEDIA=1` 会让 Nginx 在业务服务核验权限后发送图片；直接调试 Python 服务时使用默认值 0。

## 增加 2 核 2 GB、200 Mbps 的图片入口

把 Nginx 和 `web/` 目录放到第二台机器，域名指向它。在两台机器间建立可达的私有网络或专用隧道。将业务机绑定到该私网地址，在 Nginx 配置的 upstream 中填入同一地址。业务端口仅供入口机访问。更新网页时要部署整套 `web/`，确保网页与 API 版本相配。

在入口机保存 `/srv/campuscats-media`，通过私网文件共享将它挂载到业务机的同名目录。设置一致的文件用户组，使业务进程能写，入口机的 Nginx 能读。迁移已有图鉴时先备份并暂停写入，将原图片和缩略图复制到新的媒体目录，再启动业务服务。SQLite 数据库始终在业务机本地。

手机提交的压缩照片经过入口机转交业务机处理。图片浏览由入口机直接发送，原图和待审核图仍通过业务服务验证访问权限。这套配置主要节省业务机的公网下行。若两机走公网且受 3 Mbps 限制，或大量用户同时上传，仍需分别测试传图耗时、CPU 和审核积压。

## 指定维护者和备份

先在界面注册维护者邮箱。在业务机用下面的命令指定审核角色，把示例邮箱换为实际值。新角色会在下次读取账号信息时生效。

```sh
cd /srv/campuscats
sudo -u campuscats .venv/bin/python server/app.py --data-dir /var/lib/campuscats --media-dir /srv/campuscats-media --promote reviewer@example.edu
```

备份要包括数据库和照片。以下命令将数据库一致性快照和快照引用的媒体文件写入一个新的 ZIP，并校验图片哈希。目标卷需支持硬链接；备份目录需预先创建并允许服务账号写入。备份同时包含用户数据和会话，宜保存在限制访问的私有位置。

```sh
sudo -u campuscats .venv/bin/python server/backup.py --data-dir /var/lib/campuscats --media-dir /srv/campuscats-media /srv/private-backups/campuscats-pilot-01.zip
```

恢复演练使用一个新的私有目录，将备份解压后的 `campus.sqlite3` 用作数据目录中的数据库，`media/` 用作媒体目录。先在本机试开图鉴和照片，再决定是否切换正式服务。

首次在 App 中保存 Agent 配置时，服务会在数据目录生成 `agent-key.fernet`，用于解密数据库中的服务商密钥。请单独备份这个文件。迁移或恢复已有配置时，把它放回数据目录，仅允许服务账号读写。

## 验证校园网络

首页读取和图片上传的负载不同。先模拟 1000 名访客在 30 秒内陆续打开首页，记录成功数、首批猫卡片出现的时间和图片出口峰值。同时试测常见手机照片大小下的并发上传和查图，观察候选返回时间、CPU 峰值和数据库写入等待。项目附带的 `server/benchmark_browse.py` 在独立临时数据库和本机回环接口演练浏览场景。校园的公网出口、真机以及混合读写需要在目标设备上复测。

本版在 Windows 本机以 24 个测试档案演练过该场景。1000 名访客按 30 秒分布进入，每人读取会话、图鉴和三张缩略图。最多 48 个客户端工作线程发出请求，5000 次 HTTP 请求均返回成功，响应正文共 159.6 MiB。该测试没有施加校园出口限速，也没有加入相机端渲染或上传负载。
