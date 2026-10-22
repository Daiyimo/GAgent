#!/usr/bin/env bash
# 构建 tsbridge.aar (tsnet 嵌入; gomobile bind -> app/libs/)
# 依赖: Go >= 1.27.3, Android SDK+NDK (ANDROID_HOME / ANDROID_NDK_HOME), 网络可达 proxy.golang.org
set -euo pipefail
cd "$(dirname "$0")/.."

export PATH="$PATH:$(go env GOPATH)/bin"
mkdir -p app/libs
cd tsbridge
mobile_version=$(go list -m -f '{{.Version}}' golang.org/x/mobile)
go install "golang.org/x/mobile/cmd/gomobile@$mobile_version"
go install "golang.org/x/mobile/cmd/gobind@$mobile_version"
gomobile init
gomobile bind -target=android/arm64 -androidapi 24 -ldflags="-s -w" \
    -o ../app/libs/tsbridge.aar .
python3 ../tools/collect_go_notices.py
