#!/usr/bin/env bash
# write_conf.sh — перезаписывает nfqws2_sandbox.conf содержимым из stdin.
# Существует ТОЛЬКО потому, что конфиг обычно создаётся/перезаписывается
# root'ом (Zenith orchestrator/main.py работает через sudo), а писать в
# него должны уметь и непривилегированные клиенты песочницы
# (z2r_test-voice-bot, юзер zenith-voice-bot) — см. sudoers для
# zenith-voice-bot в его README ("Песочница, не прод").
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cat > "$SCRIPT_DIR/nfqws2_sandbox.conf"
