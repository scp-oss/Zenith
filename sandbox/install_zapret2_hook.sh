#!/usr/bin/env bash
# Ставит zapret2-exclude-sandbox.sh в custom.d боевого zapret2 (идемпотентно).
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
for d in /opt/zapret2/init.d/sysv/custom.d /opt/zapret2/init.d/openwrt/custom.d; do
  [ -d "$d" ] || continue
  install -m 644 "$SCRIPT_DIR/zapret2-exclude-sandbox.sh" "$d/95-zenith-sandbox-exclude.sh"
  echo "Установлен $d/95-zenith-sandbox-exclude.sh"
done
echo "Применится при следующем (пере)запуске zapret2."
