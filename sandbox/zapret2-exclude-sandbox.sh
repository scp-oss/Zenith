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

# ВАЖНО (2026-11-13, живой инцидент): zenith-voice-bot выводим из-под боевого
# zapret2 ТОЛЬКО по его голосовому UDP (его песочница -- это голос). Его TCP
# (логин в Discord, API, gateway) обязан идти через боевой обход: discord.com
# без него не открывается, и бот уходил в бесконечный рестарт с
# "Connection timeout to host https://discord.com/api/v10/users/@me".
VOICE_BOT_UDP_PORTS="443, 2053, 2083, 2087, 2096, 8443, 50000-50099, 1400, 3478-3481, 5349, 19294-19344"

_zenith_sandbox_uids() {
	id -u zenith-sandbox 2>/dev/null
}

_zenith_voicebot_uid() {
	id -u zenith-voice-bot 2>/dev/null
}

zapret_custom_firewall_nft() {
	[ "$FWTYPE" = nftables ] || return 0
	local sbuid vbuid ch table="${ZAPRET_NFT_TABLE:-zapret2}"
	sbuid="$(_zenith_sandbox_uids)"; vbuid="$(_zenith_voicebot_uid)"
	[ -n "$sbuid$vbuid" ] || return 0
	for ch in postrouting_hook postnat_hook; do
		nft list chain inet "$table" "$ch" >/dev/null 2>&1 || continue
		nft insert rule inet "$table" "$ch" ct mark \& "$ZENITH_SANDBOX_CTMARK" == "$ZENITH_SANDBOX_CTMARK" counter return comment \"zenith-sandbox-exclude\"
		[ -n "$vbuid" ] && nft insert rule inet "$table" "$ch" meta skuid "$vbuid" udp dport "{ $VOICE_BOT_UDP_PORTS }" ct mark set ct mark or "$ZENITH_SANDBOX_CTMARK" counter return comment \"zenith-sandbox-exclude\"
		[ -n "$sbuid" ] && nft insert rule inet "$table" "$ch" meta skuid "$sbuid" ct mark set ct mark or "$ZENITH_SANDBOX_CTMARK" counter return comment \"zenith-sandbox-exclude\"
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
	for uid in zenith-sandbox; do
		id "$uid" >/dev/null 2>&1 || continue
		if [ "$action" = 1 ]; then
			iptables -t mangle -C POSTROUTING -m owner --uid-owner "$uid" -j RETURN 2>/dev/null || iptables -t mangle -I POSTROUTING 1 -m owner --uid-owner "$uid" -j RETURN
		else
			iptables -t mangle -D POSTROUTING -m owner --uid-owner "$uid" -j RETURN 2>/dev/null || true
		fi
	done
	# zenith-voice-bot -- только голосовой UDP (TCP боту нужен боевой обход)
	if id zenith-voice-bot >/dev/null 2>&1; then
		local vb_ports="443,2053,2083,2087,2096,8443,50000:50099,1400,3478:3481,5349,19294:19344"
		if [ "$action" = 1 ]; then
			iptables -t mangle -C POSTROUTING -m owner --uid-owner zenith-voice-bot -p udp -m multiport --dports "$vb_ports" -j RETURN 2>/dev/null || \
				iptables -t mangle -I POSTROUTING 1 -m owner --uid-owner zenith-voice-bot -p udp -m multiport --dports "$vb_ports" -j RETURN
		else
			iptables -t mangle -D POSTROUTING -m owner --uid-owner zenith-voice-bot -p udp -m multiport --dports "$vb_ports" -j RETURN 2>/dev/null || true
		fi
	fi
}
