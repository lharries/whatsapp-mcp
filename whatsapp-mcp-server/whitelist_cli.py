"""Manage the WhatsApp MCP whitelist from the command line.

    uv run python whitelist_cli.py chats [query]   # list chats, mark whitelisted
    uv run python whitelist_cli.py add <name>      # search by name, add to whitelist
    uv run python whitelist_cli.py remove <name>   # remove from whitelist
    uv run python whitelist_cli.py list            # show current whitelist

Changes are written to whitelist.json (see whitelist.example.json). The server
re-reads the file on every request, so changes take effect immediately.
"""
import argparse
import sys
from typing import List, Optional

import admin
import whitelist

RELOAD_HINT = "→ Change takes effect on the next request; no restart needed."


def _kind(jid: str) -> str:
    return "group" if jid.endswith("@g.us") else "dm"


def _name_map() -> dict:
    # Key by normalized JID so lookups from the (normalized) whitelist match
    # regardless of how the raw JID was cased in the database.
    return {whitelist.normalize_jid(jid): name for jid, name, _ in admin.all_chats()}


def _print_candidates(rows) -> None:
    for i, (jid, name, _) in enumerate(rows, 1):
        print(f"  [{i}] {name}  {jid}  ({_kind(jid)})")


def _cmd_add(query: str, yes: bool) -> int:
    rows = admin.find_chats(query)
    if not rows:
        print(f"No chat matches '{query}'.")
        return 1
    if len(rows) > 1:
        if yes or not sys.stdin.isatty():
            print(f"Multiple chats match '{query}':")
            _print_candidates(rows)
            print("Narrow the query so it matches exactly one chat.")
            return 2
        print(f"Multiple chats match '{query}':")
        _print_candidates(rows)
        try:
            choice = int(input(f"Pick one [1-{len(rows)}], 0 to cancel: "))
        except (ValueError, EOFError):
            choice = 0
        if not (1 <= choice <= len(rows)):
            print("Cancelled.")
            return 1
        rows = [rows[choice - 1]]

    jid, name, _ = rows[0]
    if not yes and sys.stdin.isatty():
        if input(f"Add {name} ({jid}) to whitelist? [y/N] ").strip().lower() != "y":
            print("Cancelled.")
            return 1
    elif not yes:
        print("Refusing to add without confirmation; pass -y.")
        return 1
    whitelist.add_jid(jid)
    print(f"✓ added {name} ({jid})")
    print(RELOAD_HINT)
    return 0


def _cmd_remove(query: str, yes: bool) -> int:
    current = whitelist.load_whitelist()
    if not current:
        print("Whitelist is already empty.")
        return 1
    names = _name_map()
    q = query.lower()
    matches = [j for j in current if q in (names.get(j, "") or "").lower() or q in j.lower()]
    if not matches:
        print(f"No whitelisted chat matches '{query}'.")
        return 1
    if len(matches) > 1:
        print(f"Multiple whitelisted chats match '{query}':")
        for j in matches:
            print(f"  {names.get(j, '?')}  {j}")
        print("Narrow the query.")
        return 2
    jid = matches[0]
    name = names.get(jid, "?")
    if not yes and sys.stdin.isatty() and input(f"Remove {name} ({jid})? [y/N] ").strip().lower() != "y":
        print("Cancelled.")
        return 1
    whitelist.remove_jid(jid)
    print(f"✓ removed {name} ({jid})")
    print(RELOAD_HINT)
    return 0


def _cmd_list() -> int:
    current = whitelist.load_whitelist()
    if not current:
        print("Whitelist is empty — nothing is exposed (fail closed).")
        return 0
    names = _name_map()
    print(f"{len(current)} chat(s) whitelisted:")
    for jid in sorted(current):
        print(f"  {jid}  {names.get(jid, '?')}  ({_kind(jid)})")
    return 0


def _cmd_chats(query: Optional[str]) -> int:
    rows = admin.find_chats(query)
    if not rows:
        print("No chats found." if query is None else f"No chat matches '{query}'.")
        return 0
    current = whitelist.load_whitelist()
    for jid, name, last in rows:
        mark = "[✓]" if whitelist.normalize_jid(jid) in current else "[ ]"
        print(f"{mark} {jid:40}  {name[:28]:28}  {last}  ({_kind(jid)})")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="whitelist_cli", description="Manage the WhatsApp MCP whitelist.")
    sub = p.add_subparsers(dest="cmd", required=True)

    pa = sub.add_parser("add", help="search chats by name and add one to the whitelist")
    pa.add_argument("query")
    pa.add_argument("-y", "--yes", action="store_true", help="skip confirmation")

    pr = sub.add_parser("remove", help="remove a whitelisted chat by name/JID")
    pr.add_argument("query")
    pr.add_argument("-y", "--yes", action="store_true", help="skip confirmation")

    sub.add_parser("list", help="show the current whitelist")

    pc = sub.add_parser("chats", help="list chats, marking whitelisted ones")
    pc.add_argument("query", nargs="?")

    args = p.parse_args(argv)
    if args.cmd == "add":
        return _cmd_add(args.query, args.yes)
    if args.cmd == "remove":
        return _cmd_remove(args.query, args.yes)
    if args.cmd == "list":
        return _cmd_list()
    if args.cmd == "chats":
        return _cmd_chats(args.query)
    return 1


if __name__ == "__main__":
    sys.exit(main())
