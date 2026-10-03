#!/usr/bin/env python3
"""Слить .env.incoming с текущим VPS .env.

Идентичность бота (токен, username, образ) всегда с VPS.
Пустые строки с ноутбука не затирают ЮKassa / кассу / ADMINS.
Ключи, которых нет в incoming, остаются с сервера.
"""

from pathlib import Path
import sys

# Даже если локально другое непустое значение — на VPS побеждает сервер.
ALWAYS_VPS = ("BOT_TOKEN", "BOT_USERNAME", "DOCKER_IMAGE")


def kv(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value
    return out


def line_key(line: str) -> str | None:
    raw = line.split("\n", 1)[0]
    if not raw.strip() or raw.lstrip().startswith("#") or "=" not in raw:
        return None
    return raw.split("=", 1)[0].strip()


def keep_value(raw: str) -> bool:
    """[] и пусто не считаются заданными."""
    value = (raw or "").strip().strip('"').strip("'")
    return bool(value) and value not in ("[]", "{}", "null", "None")


def merge_env(incoming: str, existing: str) -> str:
    keep = kv(existing)
    lines: list[str] = []
    seen: set[str] = set()
    for line in incoming.splitlines(True):
        if line.startswith("TELEGRAM_PROXY="):
            lines.append("# TELEGRAM_PROXY=  # не нужен на этом VPS\n")
            seen.add("TELEGRAM_PROXY")
            continue
        key = line_key(line)
        incoming_val = ""
        if key is not None and "=" in line.split("\n", 1)[0]:
            incoming_val = line.split("\n", 1)[0].split("=", 1)[1]
        use_vps = False
        if key:
            vps_val = keep.get(key, "")
            if key in ALWAYS_VPS and keep_value(vps_val):
                use_vps = True
            elif keep_value(vps_val) and not keep_value(incoming_val):
                use_vps = True
        if use_vps and key:
            lines.append(f"{key}={keep[key].rstrip()}\n")
            seen.add(key)
            continue
        if key:
            seen.add(key)
        lines.append(line)
    for key, value in keep.items():
        if key in seen or not keep_value(value):
            continue
        if not lines or not lines[-1].endswith("\n"):
            lines.append("\n")
        lines.append(f"{key}={value.rstrip()}\n")
    return "".join(lines)


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    incoming_path = root / ".env.incoming"
    env_path = root / ".env"
    incoming = incoming_path.read_text(encoding="utf-8")
    existing = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    env_path.write_text(merge_env(incoming, existing), encoding="utf-8")
    env_path.chmod(0o600)
    incoming_path.unlink(missing_ok=True)
    print("env merged")


if __name__ == "__main__":
    main()
