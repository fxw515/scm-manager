#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
# Consistent offline backup: stop only the selected SCM container, then restart.
set -Eeuo pipefail
umask 077
usage() { echo '用法：sudo bash backup.sh 容器名 /独立备份目录'; }
if [[ ${1:-} == --help ]]; then usage; exit 0; fi
[[ $# == 2 ]] || { usage >&2; exit 1; }
[[ $EUID == 0 ]] || { echo '请使用 sudo 执行' >&2; exit 1; }
NAME=$1
[[ $2 == /* ]] || { echo '备份目录必须为绝对路径' >&2; exit 1; }
DEST=$(realpath -m -- "$2")
docker_local() { docker --host unix:///var/run/docker.sock "$@"; }
[[ $(docker_local inspect --format '{{index .Config.Labels "io.scm-manager.zh.managed"}}' "$NAME") == true ]] || { echo '拒绝备份非本脚本管理的容器' >&2; exit 1; }
HOME_MOUNT=$(docker_local inspect --format '{{range .Mounts}}{{if eq .Destination "/var/lib/scm"}}{{.Source}}{{end}}{{end}}' "$NAME")
[[ $HOME_MOUNT == /*/home && -d $HOME_MOUNT ]] || { echo '数据挂载不符合安装布局' >&2; exit 1; }
ROOT=$(dirname -- "$HOME_MOUNT")
[[ -f $ROOT/deployment.json ]] || { echo '缺少部署记录' >&2; exit 1; }
case $DEST/ in "$ROOT/"*) echo '备份目录不能位于数据目录内' >&2; exit 1 ;; esac
install -d -m 0700 "$DEST"
exec 9>"$ROOT/.backup.lock"
flock -n 9 || { echo '已有备份正在运行' >&2; exit 1; }
TMP=$(mktemp "$DEST/scm-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX.tar.gz.partial")
WAS_RUNNING=$(docker_local inspect --format '{{.State.Running}}' "$NAME")
resume() {
  status=$?
  trap - EXIT
  if [[ $WAS_RUNNING == true ]]; then
    docker_local start "$NAME" >/dev/null || { echo '备份后启动 SCM 容器失败，请立即检查' >&2; exit 1; }
  fi
  exit "$status"
}
trap resume EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
if [[ $WAS_RUNNING == true ]]; then docker_local stop --time 60 "$NAME" >/dev/null; fi
tar --acls --xattrs --numeric-owner --exclude="$(basename "$ROOT")/cache" \
  --exclude="$(basename "$ROOT")/.backup.lock" -czf "$TMP" -C "$(dirname "$ROOT")" "$(basename "$ROOT")"
mv -- "$TMP" "${TMP%.partial}"
ARCHIVE=${TMP%.partial}
(cd -- "$DEST" && sha256sum "$(basename "$ARCHIVE")" > "$(basename "$ARCHIVE").sha256")
printf '备份完成：%s\n缓存不备份；账号、仓库、插件及部署信息均包含。请另行保存中文镜像并复制到其他设备。\n' "$ARCHIVE"
