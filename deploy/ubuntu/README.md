# SCM-Manager 简体中文版 · Ubuntu 部署

本分支基于上游稳定标签 **3.12.2**，中文镜像版本为 **3.12.2-zh.1**。
目标宿主系统为 Ubuntu 26.04 LTS（amd64 / arm64）。安装脚本也允许 22.04 和 24.04。
Gitea 继续保留：SCM-Manager 使用独立容器、端口和数据目录。

已完成资源校验、前端构建及本机中文页面检查；Docker 构建和 Ubuntu 实机部署仍需你验收，详见 [本次验证记录](VALIDATION.md)。

## 无需在服务器编译：导入预构建镜像

服务器连接 Docker Hub 超时时，推荐此方式。构建在 GitHub Actions 或另一台能联网的 Linux/Docker 机器完成，服务器只加载最终镜像。已有 Docker 时，无需下载 Node/Python 基础镜像或安装前端编译工具。

本分支的工作流是 `.github/workflows/scm-zh-image.yml`，名称 **Build Chinese SCM image**。
相关代码推送到 `zh-cn-ubuntu-26.04` 时自动构建 amd64 镜像，并在临时容器中检查健康状态和中文资源，然后导出镜像、对应源码及 SHA-256 校验文件。不会连接部署服务器，也不发布到 Docker Hub 或 GHCR。

1. 打开 fork 的 **Actions**，如 GitHub 提示 fork 的 Actions 未启用，先启用。进入最新的 **Build Chinese SCM image** 成功运行记录。
2. 在 **Artifacts** 下载 `scm-manager-zh-linux-amd64-提交号`，解压 ZIP，将里面的文件上传服务器。构建产物保留 7 天，请自行保存。
3. 在服务器用 `dpkg --print-architecture` 确认架构。自动构建默认为 amd64；arm64 需要在手动运行时选择对应架构。网页的 **Run workflow** 按钮要求工作流文件位于仓库默认分支；目前默认分支是上游 `develop` 时，不要为显示按钮直接把整条中文分支合入它。已有运行可通过 **Re-run all jobs** 重试；也可在另一台相同架构的机器按下文构建。
4. 在上传文件所在目录验证并导入（以下以 amd64 为例）：

```bash
sha256sum -c SHA256SUMS
sudo docker image load -i scm-manager-zh-3.12.2-zh.1-linux-amd64.image.tar.gz
```

5. 已有源码目录时，在该目录执行 `git pull --ff-only`。也可以在一个空目录解压产物里的 `scm-manager.source.tar.gz`，然后进入 `scm-manager`。
6. 将 IP 换成服务器实际内网地址，执行这一条单行命令：

```bash
sudo bash deploy/ubuntu/install.sh --skip-build --bind-ip 192.168.1.20 --http-port 8090
```

`--skip-build` 不访问镜像仓库，仅使用已导入的本地镜像，并检查版本和 CPU 架构。它仍按首次安装规则拒绝覆盖已有容器和非空数据目录。首次构建在下载基础镜像时失败的服务器，可直接采用此方式，无需重装 Docker。

如果使用另一台相同架构的 Linux/Docker 机器构建，在本仓库根目录执行：

```bash
docker build --pull -f deploy/ubuntu/Dockerfile -t scm-manager-zh:3.12.2-zh.1 .
docker image save scm-manager-zh:3.12.2-zh.1 | gzip > scm-manager-zh.image.tar.gz
sha256sum scm-manager-zh.image.tar.gz > scm-manager-zh.image.tar.gz.sha256
```

上传生成的镜像和校验文件后，先校验，再 `sudo docker image load -i scm-manager-zh.image.tar.gz`，最后使用上述 `--skip-build` 安装。

## 首次安装：在服务器构建

将**整个本分支源码**放到服务器，进入仓库根目录。不要只复制 `deploy` 文件夹。
安装需要访问 Docker Hub、Ubuntu/Docker 软件源、Yarn 包源和 GitHub。
构建前端需要额外内存与磁盘空间，建议至少预留 4 GB 可用内存和 10 GB 空间；构建完成后会释放构建进程。

先查看计划（不会安装软件或修改服务器）：

```bash
bash deploy/ubuntu/install.sh --dry-run --bind-ip 192.168.1.20
```

把示例 IP 换成服务器实际的内网或 VPN IPv4 地址，再安装：

```bash
sudo bash deploy/ubuntu/install.sh \
  --bind-ip 192.168.1.20 \
  --http-port 8090 \
  --data-dir /srv/scm-manager \
  --install-docker
```

- 已有可用的 Docker：直接复用，不升级、不重启、不卸载任何包。
- 没有 Docker：只有指定 `--install-docker` 才通过官方软件源安装。
- 已有不完整或冲突的容器环境：停止并提示人工处理，不自动替换。
- 容器重名、端口占用、数据目录非空：停止，不覆盖数据。
- 不传 `--bind-ip` 时绑定 `127.0.0.1`，只供本机、SSH 隧道或反向代理访问。
- 通过固定的本机 Docker socket 操作，避免受远程 Docker context 影响。
- 不开放或更改 UFW，不配置 Nginx，不占用 Gitea 的 SSH 端口。
- 本脚本的 apt 调用临时设置 `NEEDRESTART_SUSPEND=1`，阻止这次 apt 钩子扫描后自动重启其他服务；不修改系统的长期更新策略。软件包自身的安装脚本仍由系统执行，首次安装 Docker 会启动新 Docker 服务。安装过依赖后，请在维护窗口运行 `sudo needrestart -r l` 检查待重启项。

打开 `http://服务器IP:8090/scm/`。Web 界面、Git HTTP 和 SVN HTTP 共用此端口；**不需要 3690 端口**。
仓库地址从界面复制，不要手动套用 `svn://` 地址。

Docker 发布端口可能绕过 UFW 规则，因此请绑定实际需要的内网/VPN 地址。若公网使用，请通过已有反向代理配置 HTTPS，并将本服务限制在可信网络。

若出现 `load metadata`、`registry-1.docker.io`、`i/o timeout`，说明下载基础镜像时发生网络错误，中文代码尚未编译。可以检查 DNS/代理与网络出口，或改用上面的离线镜像方式；不用重装 Docker，也不必为此重启 Docker 或 Gitea。
`aegis.service` 的失败属于另一项服务的问题，可用 `sudo systemctl status aegis.service --no-pager -l` 和 `sudo journalctl -u aegis.service -n 60 --no-pager` 单独检查；安装脚本不会禁用或卸载它。

## 初始化与中文

```bash
sudo docker logs scm-manager-zh 2>&1 | grep -A 3 'Startup token'
```

用日志中的初始化令牌在网页创建管理员账号和密码。没有预设的 `admin/admin` 密码。
初始化时可选择“不安装额外插件，直接开始”；Git、SVN、Mercurial 核心功能已包含。

界面跟随浏览器首选语言。将简体中文放在浏览器语言列表第一位，并刷新页面。
`zh`、`zh-CN`、`zh-Hans` 会使用此简体中文资源；其他语言继续使用上游翻译。
若网页仍显示英文，请检查浏览器实际首选语言、关闭浏览器翻译功能并完整刷新。

覆盖范围：登录、初始化、仓库/分支/标签/代码/差异、用户和用户组、权限、系统设置、插件管理、搜索、通知、核心错误提示，以及内置 Git/SVN/Mercurial 插件，共 **13 个源文件、1,342 个词条**。
相对时间也显示为中文，例如“5 分钟前”。

额外安装的第三方插件、插件中心远程介绍、操作日志和 Git/SVN 命令行原始输出可能仍是英文，需按实际安装的插件另补语言资源。
SCM-Manager 的 SVN 目录读取隔离限制仍与上游一致；此中文化不改变权限模型。

## 数据与日常管理

默认目录布局：

```text
/srv/scm-manager/
├── home/                 # 仓库、账号、权限、插件、应用配置，必须备份
├── cache/                # 工作缓存，可重新生成
├── deployment.json       # 容器名、地址、端口及实际镜像 ID
├── image-info.json       # 镜像信息
└── run-container.sh      # 用原镜像 ID 和参数重新创建容器
```

应用以官方镜像的非 root 用户（UID 1000）运行。默认 JVM 最大堆内存为 1 GB；大型 Unity 仓库可按实际资源调整保存的启动命令中的 `-Xmx`。
容器配置 `unless-stopped` 自动重启和日志轮换。

```bash
sudo docker logs --tail 100 scm-manager-zh
sudo docker inspect --format '{{.State.Health.Status}}' scm-manager-zh
sudo docker stop scm-manager-zh
sudo docker start scm-manager-zh
```

安装脚本只负责首次安装。已有数据时，不要反复运行安装脚本，也不要删除 `home` 来解决启动失败。

## 备份与恢复

先完成初始化，并确认无人提交，再运行：

```bash
sudo bash deploy/ubuntu/backup.sh scm-manager-zh /srv/scm-backups
sudo docker image save scm-manager-zh:3.12.2-zh.1 | gzip > scm-manager-zh-3.12.2-zh.1.image.tar.gz
```

备份脚本只停止指定的 SCM 容器，打包完成后恢复其原来的运行状态，不停止 Gitea。
这是一致性离线备份，停机时间随仓库体积增加。压缩包不包含缓存，失败时保留 `.partial` 文件供排查；只有完整备份生成 `.sha256`。
将数据备份、校验文件、镜像和本分支源码复制到另一台机器。应用自身的单库导出不能替代此整机数据备份。

恢复到新服务器时：

1. 安装 Docker，加载保存的中文镜像：`sudo docker image load -i scm-manager-zh-3.12.2-zh.1.image.tar.gz`。
2. 在备份目录执行 `sha256sum -c 对应备份文件.tar.gz.sha256`，并用 `tar -tzf 对应备份文件.tar.gz` 检查内容。
3. 确认 `/srv/scm-manager` 不存在；如果已有数据，请先停服务并另行保留，不能直接覆盖。
4. 默认布局下执行 `sudo tar --acls --xattrs --numeric-owner -xzf 对应备份文件.tar.gz -C /srv`。自定义数据目录应解压到原目录的父目录。
5. 创建未备份的缓存目录：`sudo install -d -m 0750 -o 1000 -g 0 /srv/scm-manager/cache`。
6. 检查 `/srv/scm-manager/run-container.sh` 中的 IP 在新服务器存在、端口空闲、数据路径正确，再执行 `sudo bash /srv/scm-manager/run-container.sh`。
7. 等待健康状态变为 `healthy`，检查账号、Git/SVN 仓库、权限和插件。

启动脚本固定实际镜像 ID，因此需要先加载备份镜像。若只重启同一个容器，数据保留并不能证明恢复成功；应至少做一次在独立目录或另一台服务器的恢复演练。

## 更新与回退

不要直接切换到上游 `latest`：官方镜像不包含本分支中文资源。
也不要把任意新版本镜像传入当前打包脚本。脚本会校验上游版本和英文词条，版本不匹配时拒绝打包。

本次更新边界是 3.12.2 上的语言补丁。以后跟进上游版本时，需更新工作分支基线、镜像版本及 `localize.py`，补齐新增词条并重新验证。

更新已部署容器的步骤：

1. 先构建新标签的中文镜像，再做完整数据备份，并保存旧镜像及旧 `run-container.sh`。
2. 停止旧 SCM 容器，使用 `docker rename` 给它加上日期后缀，保留用于回退。
3. 复制原 `run-container.sh`，仅把最后的镜像 ID 改为新镜像 ID，核对容器名、端口和挂载路径后执行。
4. 验收健康状态、中文、账号和检出提交后再考虑移除旧容器。
5. 若新版本失败，停止新容器。发生过数据格式迁移时，必须恢复升级前的数据备份，再用旧镜像启动；不能盲目将旧程序指向已迁移的数据。

所有操作仅针对 SCM 容器。避免使用 `docker system prune`、全局停止容器或重启 Docker 来更新本服务。

## 部署验收

先运行只读检查：

```bash
python3 deploy/ubuntu/verify.py --url http://192.168.1.20:8090/scm
```

然后在界面新建一个专用 SVN 验收仓库和普通测试用户，授权此用户读写；以下操作只在该测试仓库进行。TortoiseSVN 也可以完成同样的验证。

```bash
svn checkout '从界面复制的测试仓库HTTP地址' scm-svn-check --username 测试用户名
cd scm-svn-check
printf '中文路径和内容验收\n' > '中文验收.txt'
svn add '中文验收.txt'
svn commit -m '中文提交验收'
svn propset svn:needs-lock '*' '中文验收.txt'
svn commit -m '启用文件锁提示'
svn lock '中文验收.txt' -m '文件锁验收'
svn unlock '中文验收.txt'
svn update
```

密码由 SVN 交互输入，不放在命令参数或脚本中。再用未授权用户确认无法读取测试仓库。
如需验证 Git，在另一个专用 Git 仓库完成 clone、commit、push、pull；不迁移现有 Gitea 仓库。
最后重启 SCM 容器，确认管理员密码、用户权限、提交历史和中文仍保留，并验证 Gitea 原地址及仓库操作正常。

## 开发与维护

中文源文件位于与上游 `en` 平级的 `zh` 目录。产品名、协议名、URL、代码示例和插值标记保留原样。
前端日期语言的改动位于 `scm-ui/ui-components/src/useDateFormatter.ts`。
浏览器语言识别继续采用上游机制，没有另加登录或权限逻辑。

```bash
python3 deploy/ubuntu/localize.py --check
python3 -m unittest discover -s deploy/ubuntu -p 'test_*.py' -v
bash -n deploy/ubuntu/install.sh
bash -n deploy/ubuntu/backup.sh
yarn install --frozen-lockfile --ignore-scripts
yarn build
```

镜像构建会编译前端，将语言 JSON 和前端资源放入官方 WAR，保留后端字节码和内置插件包内容。
插件翻译会合并到 WAR 的中文插件语言资源中，原始源码中的各插件目录也同时提供中文文件，便于未来向上游提交。
不需要在 Ubuntu 宿主机安装 Java、Node.js、PHP、Apache 或 SVN 服务。

程序及本分支修改遵循上游 AGPL-3.0-only。保留原版权和许可证；分发自定义镜像时也应提供对应可构建源码。

参考：[官方 Docker 部署](https://scm-manager.org/docs/latest/en/installation/docker/)、[官方版本下载](https://scm-manager.org/download/)、[Docker Ubuntu 安装](https://docs.docker.com/engine/install/ubuntu/)、[下载 GitHub 构建产物](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/download-workflow-artifacts)、[needrestart 环境变量](https://manpages.ubuntu.com/manpages/noble/man1/needrestart.1.html)。
