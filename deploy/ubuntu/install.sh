#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
set -Eeuo pipefail
umask 077
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
SOURCE_DIR=$(cd -- "$SCRIPT_DIR/../.." && pwd)
BIND_IP=127.0.0.1
HTTP_PORT=8090
DATA_DIR=/srv/scm-manager
NAME=scm-manager-zh
IMAGE=scm-manager-zh:3.12.2-zh.1
INSTALL_DOCKER=0
SKIP_BUILD=0
DRY_RUN=0
die() { printf '错误：%s\n' "$*" >&2; exit 1; }
usage() {
  cat <<'HELP'
Ubuntu 26.04 SCM-Manager 中文版首次安装（也允许 22.04/24.04）
用法：sudo bash deploy/ubuntu/install.sh [选项]
  --bind-ip IP        监听的本机 IPv4 地址，默认 127.0.0.1
  --http-port PORT    Web 与 Git/SVN HTTP 共用端口，默认 8090
  --data-dir PATH     新的独立数据目录，默认 /srv/scm-manager
  --name NAME         容器名，默认 scm-manager-zh
  --image TAG         本地中文版镜像标签，默认 scm-manager-zh:3.12.2-zh.1
  --install-docker    仅在完全未安装 Docker 时安装官方 Docker Engine
  --skip-build        使用已有的同版本中文镜像（可配合 docker load）
  --dry-run           只检查参数并显示计划，不安装、不创建文件
  --help             显示帮助
已有容器或非空数据目录会拒绝覆盖。已有 Docker 会复用，不升级、不重启。
HELP
}
need_value() { [[ $# -ge 2 && -n $2 && $2 != --* ]] || die "$1 缺少参数"; }
while (($#)); do
  case $1 in
    --bind-ip) need_value "$@"; BIND_IP=$2; shift 2 ;;
    --http-port) need_value "$@"; HTTP_PORT=$2; shift 2 ;;
    --data-dir) need_value "$@"; DATA_DIR=$2; shift 2 ;;
    --name) need_value "$@"; NAME=$2; shift 2 ;;
    --image) need_value "$@"; IMAGE=$2; shift 2 ;;
    --install-docker) INSTALL_DOCKER=1; shift ;;
    --skip-build) SKIP_BUILD=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    --help|-h) usage; exit 0 ;;
    *) die "未知参数：$1" ;;
  esac
done
[[ $HTTP_PORT =~ ^[0-9]{1,5}$ ]] || die '端口必须为数字'
HTTP_PORT=$((10#$HTTP_PORT))
((HTTP_PORT >= 1024 && HTTP_PORT <= 65535)) || die '端口必须在 1024–65535 之间'
[[ $NAME =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ ]] || die '容器名无效'
[[ $IMAGE =~ ^[a-z0-9][a-z0-9._/:-]*$ && $IMAGE == *:* ]] || die '镜像必须带版本标签'
[[ $DATA_DIR =~ ^/([a-zA-Z0-9_-]+/)+[a-zA-Z0-9_-]+$ ]] || die '数据目录需为至少两级的绝对路径，仅允许字母、数字、下划线和连字符'
case $DATA_DIR in /etc/*|/usr/*|/bin/*|/sbin/*|/lib/*|/lib64/*|/boot/*|/dev/*|/proc/*|/sys/*|/run/*|/var/lib/docker*|/var/lib/containerd*) die '不能使用系统或容器引擎目录' ;; esac
[[ $BIND_IP =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || die '需要具体的 IPv4 地址'
IFS=. read -r a b c d <<< "$BIND_IP"
for octet in "$a" "$b" "$c" "$d"; do ((10#$octet <= 255)) || die 'IPv4 地址无效'; done
BIND_IP="$((10#$a)).$((10#$b)).$((10#$c)).$((10#$d))"
[[ $BIND_IP != 0.0.0.0 ]] || die '请指定本机内网、VPN 或回环地址，避免监听所有网卡'
printf '版本：3.12.2-zh.1\n地址：http://%s:%s/scm/\n数据：%s\n容器：%s\n镜像：%s\n' "$BIND_IP" "$HTTP_PORT" "$DATA_DIR" "$NAME" "$IMAGE"
printf 'Gitea：保留，使用独立容器和数据目录。\n'
((DRY_RUN)) && exit 0
[[ $EUID == 0 ]] || die '请使用 sudo 执行'
[[ -r /etc/os-release ]] || die '无法识别操作系统'
. /etc/os-release
[[ $ID == ubuntu && $VERSION_ID =~ ^(22\.04|24\.04|26\.04)$ ]] || die '支持 Ubuntu 22.04、24.04、26.04 LTS'
ARCH=$(dpkg --print-architecture)
[[ $ARCH == amd64 || $ARCH == arm64 ]] || die '仅支持 amd64/arm64'
[[ ! -L $DATA_DIR ]] || die '数据目录不能是符号链接'
[[ $(realpath -m -- "$DATA_DIR") == "$DATA_DIR" ]] || die '数据路径含符号链接，拒绝使用'
if [[ -e $DATA_DIR ]]; then
  [[ -d $DATA_DIR && -z $(find "$DATA_DIR" -mindepth 1 -maxdepth 1 -print -quit) ]] || die '数据目录不是空目录，请查看维护文档；不会覆盖已有数据'
fi
# Scope this to our apt calls. Ubuntu's apt hook may explicitly select automatic
# restarts, which overrides NEEDRESTART_MODE; SUSPEND skips only this hook run.
# Do not change global needrestart settings or stop existing services.
apt_local() { NEEDRESTART_SUSPEND=1 apt-get "$@"; }
command -v python3 >/dev/null || { apt_local update; apt_local install -y --no-upgrade python3; }
python3 - "$BIND_IP" "$HTTP_PORT" <<'PY'
import socket, sys
try:
    with socket.socket() as s:
        s.bind((sys.argv[1], int(sys.argv[2])))
except OSError as e:
    sys.exit(f'监听地址不存在或端口已占用：{e}')
PY
docker_local() { docker --host unix:///var/run/docker.sock "$@"; }
if command -v docker >/dev/null; then
  docker_local info >/dev/null 2>&1 || die '已有 Docker 不可用；为保护现有服务，不自动启动或重启它'
else
  ((INSTALL_DOCKER)) || die '未安装 Docker。安装引擎后重试，或使用 --install-docker'
  for pkg in docker.io docker-ce docker-ce-cli docker-compose docker-compose-v2 docker-doc docker-buildx podman-docker containerd containerd.io runc; do
    status=$(dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null || true)
    [[ $status != 'install ok installed' ]] || die "已存在 $pkg；不自动卸载或替换，请先人工检查现有容器服务"
  done
  apt_local update
  apt_local install -y --no-upgrade ca-certificates curl
  if ! grep -Rq 'download.docker.com/linux/ubuntu' /etc/apt/sources.list.d /etc/apt/sources.list 2>/dev/null; then
    [[ ! -e /etc/apt/sources.list.d/docker.sources ]] || die 'docker.sources 已存在，请人工检查'
    install -d -m 0755 /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    cat > /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: ${UBUNTU_CODENAME:-$VERSION_CODENAME}
Components: stable
Architectures: $ARCH
Signed-By: /etc/apt/keyrings/docker.asc
EOF
  fi
  apt_local update
  apt_local install -y --no-upgrade docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
  docker_local info >/dev/null
fi
docker_local container inspect "$NAME" >/dev/null 2>&1 && die '同名容器已存在；不会替换'
# Docker can publish ports without a userspace listener, so also inspect NAT bindings.
IDS=$(docker_local ps -q)
if [[ -n $IDS ]]; then
  # shellcheck disable=SC2086 # Docker IDs intentionally become separate arguments.
  docker_local inspect $IDS | python3 -c '
import json, sys
ip, port = sys.argv[1:]
for c in json.load(sys.stdin):
    for bindings in (c.get("NetworkSettings", {}).get("Ports") or {}).values():
        for b in bindings or []:
            if b["HostPort"] == port and b["HostIp"] in (ip, "0.0.0.0", "::", ""):
                sys.exit("端口已由容器占用：" + c["Name"])
' "$BIND_IP" "$HTTP_PORT"
fi
if ((SKIP_BUILD)); then
  docker_local image inspect "$IMAGE" >/dev/null || die '请先 docker load 中文镜像，或去掉 --skip-build'
else
  python3 "$SCRIPT_DIR/localize.py" --check
  if ! docker_local build --pull -f "$SCRIPT_DIR/Dockerfile" -t "$IMAGE" "$SOURCE_DIR"; then
    die '镜像构建失败。若 Docker Hub 超时，可在其他机器或 GitHub Actions 构建，docker load 后使用 --skip-build；见 deploy/ubuntu/README.md。尚未创建 SCM 容器和数据目录。'
  fi
fi
LABEL=$(docker_local image inspect --format '{{index .Config.Labels "io.scm-manager.zh.version"}}' "$IMAGE")
[[ $LABEL == 3.12.2-zh.1 ]] || die '镜像不是本版本的 SCM-Manager 中文版'
IMAGE_PLATFORM=$(docker_local image inspect --format '{{.Os}}/{{.Architecture}}' "$IMAGE")
[[ $IMAGE_PLATFORM == "linux/$ARCH" ]] || die "镜像平台 $IMAGE_PLATFORM 与服务器 linux/$ARCH 不匹配，请导入对应架构的镜像"
IMAGE_ID=$(docker_local image inspect --format '{{.Id}}' "$IMAGE")
# Recheck after the potentially long image build; never adopt new files that
# another process may have placed in the directory in the meantime.
[[ ! -L $DATA_DIR && $(realpath -m -- "$DATA_DIR") == "$DATA_DIR" ]] || die '数据路径在构建期间发生变化'
if [[ -e $DATA_DIR ]]; then
  [[ -d $DATA_DIR && -z $(find "$DATA_DIR" -mindepth 1 -maxdepth 1 -print -quit) ]] || die '数据目录在构建期间不再为空'
fi
install -d -m 0750 "$DATA_DIR"
install -d -m 0750 -o 1000 -g 0 "$DATA_DIR/home" "$DATA_DIR/cache"
RUN_ARGS=(--detach --name "$NAME" --restart unless-stopped --stop-timeout 60
  --label io.scm-manager.zh.managed=true
  --log-driver json-file --log-opt max-size=10m --log-opt max-file=3
  --publish "$BIND_IP:$HTTP_PORT:8080"
  --mount "type=bind,src=$DATA_DIR/home,dst=/var/lib/scm"
  --mount "type=bind,src=$DATA_DIR/cache,dst=/var/cache/scm/work"
  --env TZ=Asia/Shanghai --env 'JAVA_OPTS=-Xms128m -Xmx1024m' "$IMAGE_ID")
{
  printf '#!/usr/bin/env bash\nset -euo pipefail\n'
  printf 'docker --host unix:///var/run/docker.sock run'
  printf ' %q' "${RUN_ARGS[@]}"
  printf '\n'
} > "$DATA_DIR/run-container.sh"
chmod 0700 "$DATA_DIR/run-container.sh"
docker_local image inspect "$IMAGE_ID" > "$DATA_DIR/image-info.json"
python3 - "$DATA_DIR" "$NAME" "$BIND_IP" "$HTTP_PORT" "$IMAGE_ID" <<'PY'
import json, pathlib, sys
directory, name, ip, port, image = sys.argv[1:]
(pathlib.Path(directory)/'deployment.json').write_text(json.dumps({
    'version': '3.12.2-zh.1', 'name': name, 'bind_ip': ip,
    'http_port': int(port), 'image': image,
}, indent=2)+'\n')
PY
docker_local run "${RUN_ARGS[@]}" >/dev/null
printf '等待服务启动（首次启动可能需要几分钟）…\n'
for ((i=0; i<120; i++)); do
  state=$(docker_local inspect --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' "$NAME")
  [[ $state == 'running healthy' ]] && break
  [[ $state != exited* && $state != dead* ]] || die "容器已退出。查看：sudo docker logs $NAME"
  sleep 2
done
[[ $state == 'running healthy' ]] || die "服务未在等待时间内就绪，保留容器和数据供排查。查看：sudo docker logs $NAME"
printf '\n安装完成：http://%s:%s/scm/\n' "$BIND_IP" "$HTTP_PORT"
printf '用中文浏览器访问。首次管理员账号由你在初始化页面创建。\n'
printf '查看初始化令牌：sudo docker logs %q 2>&1 | grep -A 3 "Startup token"\n' "$NAME"
printf '备份：sudo bash %q %q /srv/scm-backups\n' "$SCRIPT_DIR/backup.sh" "$NAME"
printf '重建命令已保存：%s/run-container.sh（固定镜像 ID）\n' "$DATA_DIR"
[[ $BIND_IP != 127.* ]] || printf '当前仅本机可访问；远程可通过 SSH 隧道或反向代理访问。\n'
systemctl is-enabled docker >/dev/null 2>&1 || printf '提示：已有 Docker 未设置开机启动，请按现有服务策略自行管理。\n'
printf '本脚本的 apt 操作不运行 needrestart 自动重启；如安装了软件包，请在维护窗口检查待重启服务。\n'
