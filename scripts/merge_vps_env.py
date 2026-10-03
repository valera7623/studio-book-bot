#!/usr/bin/env python3
"""Слить .env.incoming с текущим VPS .env: токен бота на сервере важнее локального."""

from pathlib import Path
import sys

KEEP = ("BOT_TOKEN", "BOT_USERNAME", "DOCKER_IMAGE", "ADMINS", "SUPERADMINS")


def kv(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value
    return out


def keep_value(raw: str) -> bool:
    """[] не считается заданным — иначе пустой ADMINS с VPS навсегда затирает новый список."""
    value = raw.strip().strip('"').strip("'")
    return bool(value) and value not in ("[]", "{}", "null", "None")


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    incoming_path = root / ".env.incoming"
    env_path = root / ".env"
    incoming = incoming_path.read_text(encoding="utf-8")
    existing = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    keep = kv(existing)
    lines: list[str] = []
    for line in incoming.splitlines(True):
        if line.startswith("TELEGRAM_PROXY="):
            lines.append("# TELEGRAM_PROXY=  # не нужен на этом VPS\n")
            continue
        kept = False
        for key in KEEP:
            if line.startswith(f"{key}=") and keep_value(keep.get(key, "")):
                lines.append(f"{key}={keep[key].rstrip()}\n")
                kept = True
                break
        if not kept:
            lines.append(line)
    env_path.write_text("".join(lines), encoding="utf-8")
    env_path.chmod(0o600)
    incoming_path.unlink(missing_ok=True)
    print("env merged")


if __name__ == "__main__":
    main()
