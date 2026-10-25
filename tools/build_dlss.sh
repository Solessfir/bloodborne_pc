#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
sdk=${DLSS_SDK_ROOT:?Set DLSS_SDK_ROOT to a checkout of https://github.com/NVIDIA/DLSS}
cmake -S gpu/dlss_bridge -B out/dlss-bridge-linux \
    -DCMAKE_BUILD_TYPE=Release -DDLSS_SDK_ROOT="$sdk"
cmake --build out/dlss-bridge-linux
install -m755 out/dlss-bridge-linux/libbbport_dlss.so out/libbbport_dlss.so
runtime=("$sdk"/lib/Linux_x86_64/rel/libnvidia-ngx-dlss.so.*)
[[ ${#runtime[@]} == 1 && -f ${runtime[0]} ]] || { echo 'Expected one Linux DLSS release runtime in the SDK.' >&2; exit 1; }
install -m755 "${runtime[0]}" "out/$(basename -- "${runtime[0]}")"
install -m644 "$sdk/LICENSE.txt" out/NVIDIA-DLSS-LICENSE.txt
echo 'DLSS Super Resolution / DLAA ready in out/ (Linux Frame Generation is disabled).'
