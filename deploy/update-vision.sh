#!/usr/bin/env bash
# 更新已采用 /srv/campuscats/current 发布目录和 systemd 的琴园有猫业务机。
set -euo pipefail

base=/srv/campuscats
current="$base/current"
unit=campuscats.service
revision=a163d0c082c56c679a15f88046fe7869b7b34cb4
parent=d1775207f6a1bdc3111bafc536dcbc366ba82cf7
repo=https://github.com/fillgona62-a11y/CampusCats.git
api=${CAMPUS_CHECK_API:-http://127.0.0.1:8765}
site=${CAMPUS_CHECK_SITE:-https://thickearth.online}

die() { echo "$*" >&2; exit 1; }
[[ $EUID == 0 ]] || die "请用 sudo bash 执行。"
[[ -L "$current" && -d "$base/releases" ]] || die "找不到发布目录 $current 和 $base/releases。"
exec 9>"$base/.vision-deploy.lock"
flock -n 9 || die "已有部署正在运行。"
previous=$(readlink -e "$current")
working=$(systemctl show -p WorkingDirectory --value "$unit")
[[ -n "$working" && "$(readlink -e "$working")" == "$previous" ]] || die "请核对 $unit 的 WorkingDirectory 和 $current。"
tmp=$(mktemp -d "$base/releases/.vision-XXXXXXXX")
release="$base/releases/vision-${revision:0:12}-${tmp##*-}"
switched=0
switch_to() {
    ln -s "$1" "$tmp/next"
    mv -Tf "$tmp/next" "$current"
}
finish() {
    local code=$?
    trap - EXIT
    if (( code != 0 && switched )); then
        if [[ "$(readlink -f "$current")" == "$release" ]]; then
            echo "检查失败，正在恢复 $previous" >&2
            switch_to "$previous" && systemctl restart "$unit" || echo "恢复失败，请检查 $unit。" >&2
        fi
    fi
    rm -rf -- "$tmp"
    exit "$code"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

git -C "$tmp" init -q repo
git -C "$tmp/repo" fetch -q --depth=2 "$repo" "$revision"
[[ "$(git -C "$tmp/repo" rev-parse FETCH_HEAD^)" == "$parent" ]] || die "下载的提交与预期不符。"
git -C "$tmp/repo" diff --binary "$parent" "$revision" -- server web >"$tmp/update.patch"
[[ -s "$tmp/update.patch" ]] || die "未取得更新内容。"

health() {
    systemctl is-active --quiet "$unit" || return 1
    curl -fsS --max-time 5 "$api/api/agent/status" >"$tmp/status.json" || return 1
    python3 -c 'import json,sys; sys.exit(json.load(open(sys.argv[1])).get("photo_box_modes") is not True)' "$tmp/status.json" || return 1
    for file in capture.js ui.js; do
        curl -fsS --max-time 8 "${site%/}/$file?rev=$revision" >"$tmp/web.js" || return 1
        cmp -s "$tmp/web.js" "$current/web/$file" || return 1
    done
}

if git -C "$previous" apply --no-index --reverse --check "$tmp/update.patch" 2>/dev/null; then
    health || die "现有代码已更新，但服务或网站校验未通过。"
    echo "此版本已部署，接口和网页校验通过。"
    exit 0
fi
git -C "$previous" apply --no-index --check "$tmp/update.patch" || die "当前版本无法直接应用更新，请检查上述文件差异。"
mkdir "$tmp/stage"
cp -a --reflink=auto "$previous/." "$tmp/stage/"
git -C "$tmp/stage" apply --no-index "$tmp/update.patch"
chmod --reference="$previous" "$tmp/stage"
mv -T "$tmp/stage" "$release"
[[ "$(readlink -e "$current")" == "$previous" ]] || die "当前版本已被其他部署切换。"
switched=1
switch_to "$release"
systemctl restart "$unit"
for attempt in {1..12}; do
    if health; then
        echo "部署成功，识别接口和两个网页脚本均已验证。"
        python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print("游客视觉模式",d.get("vision_mode"),d.get("vision_model") or "")' "$tmp/status.json"
        echo "当前版本 $release"
        echo "上一版本 $previous"
        exit 0
    fi
    sleep 2
done
die "服务或网页未通过校验。日志可用 journalctl -u $unit -n 60 查看。"
