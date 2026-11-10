"""Audit a finished round from its Antigravity (or Claude Code) transcripts: what it touched outside the project,
and what it cost.

    python audit_round.py <round folder> --root <project root> [--session <conversation-id>]
                          [--allow PATH ...] [--json out.json]

Searches Antigravity transcripts (~/.gemini/antigravity/brain/<id>/.system_generated/logs/transcript_full.jsonl)
for the builder subagent (matching --session or the round folder in its initial prompt) and any `research` critic
subagents spawned for the round's photo checks. Falls back to ~/.claude/projects if no Antigravity transcripts match.

Reports:
- Windows drive paths in tool calls outside the project root (configured Blender, Windows fonts, temp folders,
  and the harness skill dir are allowed); this is not a complete cross-platform filesystem audit,
- references to sibling round folders (another round's files),
- web tool calls (`search_web` / `read_url_content` / `Web*`),
- tokens: uncached input, cache writes, cache reads, output; wall and active minutes.
"""
import argparse
import glob
import json
import os
import re
import sys
import shutil
import tempfile
from collections import defaultdict
from datetime import datetime

AGY_BRAIN = os.path.expanduser(os.environ.get("PHOTOREAL_ANTIGRAVITY_LOGS", "~/.gemini/antigravity/brain"))
CLAUDE_BASE = os.path.expanduser(os.environ.get("PHOTOREAL_CLAUDE_LOGS", "~/.claude/projects"))
_blender_exe = shutil.which(os.environ.get("PHOTOREAL_BLENDER") or "blender")
ALLOW = [
    tempfile.gettempdir(),
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    AGY_BRAIN,
    os.path.expanduser("~/.gemini/antigravity/builtin"),
]
if _blender_exe:
    ALLOW.append(os.path.dirname(_blender_exe))
if os.name == "nt" and os.environ.get("WINDIR"):
    ALLOW.append(os.path.join(os.environ["WINDIR"], "Fonts"))
UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)


def mangle(path):
    return re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(path))


def norm(p):
    # "program files" keeps its space out of the path regex, so Blender's install path stays one token
    return re.sub(r"/+", "/", p.replace("\\", "/")).rstrip("/").lower().replace("program files", "program_files")


def agy_log_path(conv_id):
    logs = os.path.join(AGY_BRAIN, conv_id, ".system_generated", "logs")
    for name in ("transcript_full.jsonl", "transcript.jsonl"):
        p = os.path.join(logs, name)
        if os.path.exists(p):
            return p
    return None


def first_user_input(log_file):
    try:
        with open(log_file, encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i > 15:
                    break
                o = json.loads(line)
                if o.get("type") == "USER_INPUT":
                    return o.get("content", "")
    except Exception:  # noqa: BLE001
        pass
    return ""


def spawned_subagent_ids(log_file):
    ids = set()
    try:
        pending = 0
        with open(log_file, encoding="utf-8") as f:
            for line in f:
                o = json.loads(line)
                if o.get("type") == "PLANNER_RESPONSE":
                    calls = [tc for tc in (o.get("tool_calls") or []) if tc.get("name") == "invoke_subagent"]
                    pending = len(calls)
                elif pending > 0 and o.get("type") == "GENERIC":
                    for m in UUID_RE.findall(o.get("content", "")):
                        ids.add(m.lower())
                    pending -= 1
    except Exception:  # noqa: BLE001
        pass
    return ids


def find_agy_transcripts(round_dir, session_ids):
    if not os.path.isdir(AGY_BRAIN):
        return {}
    round_n = norm(os.path.abspath(round_dir))
    found = defaultdict(list)
    builder_ids = {s.lower() for s in session_ids}
    all_logs = {}
    for conv in os.listdir(AGY_BRAIN):
        lp = agy_log_path(conv)
        if lp:
            all_logs[conv.lower()] = lp
    if not builder_ids:
        for cid, lp in all_logs.items():
            u = norm(first_user_input(lp))
            if not u or round_n not in u:
                continue
            if f"{round_n}/renders/check_" in u:
                found["critic"].append(lp)
            elif "task.md" in u or "working folder:" in u:
                builder_ids.add(cid)
    critic_ids = set()
    for cid in builder_ids:
        lp = all_logs.get(cid)
        if lp:
            found["builder"].append(lp)
            critic_ids |= spawned_subagent_ids(lp)
    for cid in sorted(critic_ids):
        lp = all_logs.get(cid)
        if lp and lp not in found["critic"]:
            found["critic"].append(lp)
    for cid, lp in all_logs.items():
        if lp in found["critic"] or cid in builder_ids:
            continue
        u = norm(first_user_input(lp))
        if f"{round_n}/renders/check_" in u:
            found["critic"].append(lp)
    return found


def find_claude_transcripts(round_dir):
    if not os.path.isdir(CLAUDE_BASE):
        return {}
    want = mangle(round_dir).lower()
    found = defaultdict(list)
    for d in os.listdir(CLAUDE_BASE):
        low = d.lower()
        if low in (want, want + "-critic-runs"):
            kind = "critic" if low.endswith("-critic-runs") else "builder"
            found[kind] += glob.glob(os.path.join(CLAUDE_BASE, d, "**", "*.jsonl"), recursive=True)
    return found


def check_paths(text, root_n, allow_n, rounds_parent, me, outside, siblings):
    s = norm(text).replace("file:///", "")
    for p in re.findall(r"(?<![a-z0-9/])[a-z]:/[^\"\s'`;|>)*?\\]{3,}", s):
        if p.startswith(rounds_parent + "/"):
            other = p[len(rounds_parent) + 1:].split("/")[0]
            if other and other != me:
                siblings[other] += 1
        if not p.startswith(root_n) and not any(p.startswith(x) for x in allow_n):
            outside.add(p[:120])


def scan(files, root, round_dir, allow):
    root_n, allow_n = norm(root), [norm(a) for a in allow]
    rounds_parent = norm(os.path.dirname(os.path.abspath(round_dir)))
    me = os.path.basename(os.path.normpath(round_dir)).lower()
    outside, siblings, web = set(), defaultdict(int), 0
    tot, models, msgs = defaultdict(int), defaultdict(int), 0
    t0 = t1 = None
    active = 0.0
    for f in files:
        seen_claude, st, en = {}, None, None
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                try:
                    o = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                ts = o.get("created_at") or o.get("timestamp")
                if ts:
                    t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    st, en = st or t, t
                # Antigravity format
                if o.get("type") == "PLANNER_RESPONSE":
                    msgs += 1
                    models["antigravity"] += 1
                    tot["input_tokens"] += o.get("input_tokens") or 0
                    tot["cache_read_input_tokens"] += o.get("cache_read_tokens") or 0
                    tot["output_tokens"] += o.get("output_tokens") or 0
                    for tc in o.get("tool_calls") or []:
                        name = tc.get("name", "")
                        if name in ("search_web", "read_url_content") or name.startswith("Web"):
                            web += 1
                        args_obj = tc.get("args") or {}
                        unwrapped = {}
                        for k, v in args_obj.items():
                            if isinstance(v, str):
                                try:
                                    unwrapped[k] = json.loads(v)
                                except Exception:  # noqa: BLE001
                                    unwrapped[k] = v
                            else:
                                unwrapped[k] = v
                        check_paths(json.dumps(unwrapped), root_n, allow_n, rounds_parent, me, outside, siblings)
                # Claude Code fallback format
                elif o.get("type") == "assistant":
                    m = o.get("message") or {}
                    if m.get("usage"):
                        seen_claude[m.get("id") or o.get("uuid")] = (m.get("model"), m["usage"])
                    for c in m.get("content") or []:
                        if not (isinstance(c, dict) and c.get("type") == "tool_use"):
                            continue
                        web += c.get("name", "").startswith("Web")
                        check_paths(json.dumps(c.get("input")), root_n, allow_n, rounds_parent, me, outside, siblings)
        for model, u in seen_claude.values():
            if model == "<synthetic>":
                continue
            models[model] += 1
            msgs += 1
            for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens"):
                tot[k] += u.get(k) or 0
        if st:
            t0, t1 = min(t0, st) if t0 else st, max(t1, en) if t1 else en
            active += (en - st).total_seconds()
    tin = sum(tot[k] for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
    return dict(sessions=len(files), messages=msgs, models=dict(models), outside=sorted(outside),
                other_rounds=dict(siblings), web_calls=web, tokens_in=tin, uncached=tot["input_tokens"],
                cache_write=tot["cache_creation_input_tokens"], cache_read=tot["cache_read_input_tokens"],
                tokens_out=tot["output_tokens"], wall_min=round((t1 - t0).total_seconds() / 60, 1) if t0 else 0,
                active_min=round(active / 60, 1))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("round")
    p.add_argument("--root", required=True, help="project root: paths under it are in bounds")
    p.add_argument("--session", nargs="*", default=[], help="explicit Antigravity builder conversationId(s)")
    p.add_argument("--allow", nargs="*", default=[])
    p.add_argument("--json")
    a = p.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    found = find_agy_transcripts(a.round, a.session) or find_claude_transcripts(a.round)
    if not found:
        print(f"no transcripts found for {a.round} in {AGY_BRAIN} or {CLAUDE_BASE}")
        return 1
    report = {k: scan(v, a.root, a.round, ALLOW + a.allow) for k, v in sorted(found.items())}
    for kind, r in report.items():
        print(f"== {kind}: {r['sessions']} session(s), {r['messages']} messages, models {r['models']}")
        print(f"   tokens in {r['tokens_in'] / 1e6:.2f} M (uncached {r['uncached']:,} + cache reads "
              f"{r['cache_read'] / 1e6:.2f} M + cache writes {r['cache_write'] / 1e6:.2f} M), "
              f"out {r['tokens_out'] / 1e3:.0f} k; wall {r['wall_min']} min, active {r['active_min']} min")
        print(f"   web tool calls: {r['web_calls']}; other rounds referenced: {r['other_rounds'] or 'none'}")
        print("   outside the project: " + ("none" if not r["outside"] else ""))
        for o in r["outside"]:
            print(f"     {o}")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
