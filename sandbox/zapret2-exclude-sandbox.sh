# zapret2 custom.d hook (ставится как /opt/zapret2/init.d/sysv/custom.d/95-zenith-sandbox-exclude.sh,
# см. install_zapret2_hook.sh). Выводит трафик юзеров песочницы Zenith из-под
# БОЕВОГО zapret2 в обе стороны.
#
# Без этого пакет от zenith-sandbox сначала проходит песочный nfqws2 (mangle
# OUTPUT -> его NFQUEUE), а потом ещё и боевой (inet zapret2 postnat -> qnum
# 300): тест генома мерил «геном + боевая стратегия поверх», а ответы сервера
# дополнительно обрабатывал боевой профиль (in-range, wssize_ramp и т.п.).
# Исходящие узнаём по skuid, входящие -- по ct mark, проставленному на
# исходящем пакете. Бит 0x01000000 свободен (занятые: 0x40000000 desync,
# 0x20000000 postnat, 0x10000000, 0x08000000 supersweep, 0x04000000
# wssize_ramp, 0x00ff0000 client-scope).
ZENITH_SANDBOX_CTMARK="${ZENITH_SANDBOX_CTMARK:-0x01000000}"

_zenith_sandbox_uids() {
	local u ids=""
	for u in zenith-sandbox zenith-voice-bot; do
		id -u "$u" >/dev/null 2>&1 && ids="${ids:+$ids, }$(id -u "$u")"
	done
	echo "$ids"
}

zapret_custom_firewall_nft() {
	[ "$FWTYPE" = nftables ] || return 0
	local uids ch table="${ZAPRET_NFT_TABLE:-zapret2}"
	uids="$(_zenith_sandbox_uids)"
	[ -n "$uids" ] || return 0
	for ch in postrouting_hook postnat_hook; do
		nft list chain inet "$table" "$ch" >/dev/null 2>&1 || continue
		nft insert rule inet "$table" "$ch" ct mark \& "$ZENITH_SANDBOX_CTMARK" == "$ZENITH_SANDBOX_CTMARK" counter return comment \"zenith-sandbox-exclude\"
		nft insert rule inet "$table" "$ch" meta skuid "{ $uids }" ct mark set ct mark or "$ZENITH_SANDBOX_CTMARK" counter return comment \"zenith-sandbox-exclude\"
	done
	for ch in prerouting_hook prenat_hook; do
		nft list chain inet "$table" "$ch" >/dev/null 2>&1 || continue
		nft insert rule inet "$table" "$ch" ct mark \& "$ZENITH_SANDBOX_CTMARK" == "$ZENITH_SANDBOX_CTMARK" counter return comment \"zenith-sandbox-exclude\"
	done
}

zapret_custom_firewall_nft_flush() { return 0; }

zapret_custom_firewall() {
	# iptables-режим zapret2: боевые правила в mangle POSTROUTING/PREROUTING.
	local action="${1:-1}" uid
	[ "$FWTYPE" = iptables ] || return 0
	for uid in zenith-sandbox zenith-voice-bot; do
		id "$uid" >/dev/null 2>&1 || continue
		if [ "$action" = 1 ]; then
			iptables -t mangle -C POSTROUTING -m owner --uid-owner "$uid" -j RETURN 2>/dev/null || iptables -t mangle -I POSTROUTING 1 -m owner --uid-owner "$uid" -j RETURN
		else
			iptables -t mangle -D POSTROUTING -m owner --uid-owner "$uid" -j RETURN 2>/dev/null || true
		fi
	done
}
