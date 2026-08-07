#!/usr/bin/env python3
"""Одноразовый тест Discord voice UDP-подключения -- запускается как
отдельный процесс от имени SANDBOX_USER (см. orchestrator/voice_tester.py),
чтобы его UDP-трафик попал в узкое iptables-правило песочницы. discord.py
живёт в своём event loop, поэтому не импортируется как модуль из main.py
-- вызывается subprocess'ом, результат печатает как JSON в stdout (ровно
одна строка) и завершается.

Логика подключения -- 1:1 то же, что делает channel.connect() в
z2r_test-voice-bot/bot.py (test_voice_connection): реальный voice gateway
handshake + UDP IP discovery, держим HOLD_SECONDS, проверяем
is_connected(). Не переизобретаем протокол, используем ту же discord.py.

Настройки -- ИЗ ОТДЕЛЬНОГО файла sandbox/voice.env (не .env — там же
MYSQL_PASSWORD, sandbox-юзеру незачем иметь к нему доступ). Формат тот
же простой KEY=VALUE, что и .env.

    ZENITH_DISCORD_TOKEN=...
    ZENITH_GUILD_ID=...
    ZENITH_VOICE_CHANNEL_ID=...      -- тот же канал, что у z2r_test-voice-bot
    ZENITH_VOICE_HOLD_SECONDS=5      -- опционально, по умолчанию 5
    ZENITH_VOICE_CONNECT_TIMEOUT=10  -- опционально, по умолчанию 10
"""
import asyncio
import json
import os
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VOICE_ENV_PATH = os.path.join(SCRIPT_DIR, "voice.env")


def _load_env(path):
    env = {}
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env


def main():
    cfg = _load_env(VOICE_ENV_PATH)
    result = {"success": False, "connect_ms": 0, "note": ""}

    token = cfg.get("ZENITH_DISCORD_TOKEN")
    guild_id = cfg.get("ZENITH_GUILD_ID")
    channel_id = cfg.get("ZENITH_VOICE_CHANNEL_ID")
    if not (token and guild_id and channel_id):
        result["note"] = f"{VOICE_ENV_PATH} не найден или неполный (нужны ZENITH_DISCORD_TOKEN/ZENITH_GUILD_ID/ZENITH_VOICE_CHANNEL_ID)"
        print(json.dumps(result))
        sys.exit(1)

    guild_id = int(guild_id)
    channel_id = int(channel_id)
    hold_seconds = int(cfg.get("ZENITH_VOICE_HOLD_SECONDS", "5"))
    connect_timeout = int(cfg.get("ZENITH_VOICE_CONNECT_TIMEOUT", "10"))

    try:
        import discord
    except ImportError:
        result["note"] = "discord.py не установлен в этом окружении (нужен discord.py[voice] в orchestrator/venv)"
        print(json.dumps(result))
        sys.exit(1)

    intents = discord.Intents.default()
    intents.guilds = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        try:
            guild = client.get_guild(guild_id)
            if guild is None:
                result["note"] = f"guild {guild_id} не найдена (бот не приглашён на сервер?)"
                return
            channel = guild.get_channel(channel_id)
            if channel is None:
                result["note"] = f"канал {channel_id} не найден на сервере {guild_id}"
                return

            t0 = time.time()
            vc = await channel.connect(timeout=connect_timeout, reconnect=False)
            result["connect_ms"] = int((time.time() - t0) * 1000)

            hold_ok = True
            start = time.time()
            try:
                while time.time() - start < hold_seconds:
                    if not vc.is_connected():
                        hold_ok = False
                        result["note"] = f"соединение разорвалось через {time.time() - start:.1f}s"
                        break
                    await asyncio.sleep(1)
            finally:
                try:
                    await vc.disconnect(force=True)
                except Exception:
                    pass

            result["success"] = hold_ok
        except Exception as e:
            result["note"] = f"connect() не удался: {e}"
        finally:
            await client.close()

    try:
        client.run(token, log_handler=None)
    except Exception as e:
        result["note"] = result["note"] or f"client.run() не удался: {e}"

    print(json.dumps(result))


if __name__ == "__main__":
    main()
