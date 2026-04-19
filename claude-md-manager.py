#!/usr/bin/env python3
"""Local CLAUDE.md manager. Run: python3 claude-md-manager.py  →  http://localhost:9000"""
import argparse
import json
import os
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import parse_qs, urlparse

HOME = Path.home()
DEFAULT_CONFIG_PATH = HOME / ".config" / "claude-md-manager" / "config.json"
DEFAULT_CONFIG = {
    "user_global": str(HOME / ".claude" / "CLAUDE.md"),
    "project_roots": [],
}

_config_lock = Lock()
_state = {"config_path": DEFAULT_CONFIG_PATH, "config": dict(DEFAULT_CONFIG)}


def expand(p: str) -> Path:
    return Path(os.path.expanduser(os.path.expandvars(p))).resolve()


def load_config(path: Path) -> dict:
    if not path.exists():
        return dict(DEFAULT_CONFIG)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"warning: failed to read config at {path}: {e}; using defaults", file=sys.stderr)
        return dict(DEFAULT_CONFIG)
    merged = dict(DEFAULT_CONFIG)
    merged.update({k: v for k, v in data.items() if k in DEFAULT_CONFIG})
    return merged


def save_config(path: Path, config: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")


def get_config() -> dict:
    with _config_lock:
        return dict(_state["config"])


def set_config(new_config: dict) -> dict:
    with _config_lock:
        _state["config"] = new_config
        save_config(_state["config_path"], new_config)
        return dict(new_config)


def allowed_roots() -> list[Path]:
    cfg = get_config()
    roots = [expand(cfg["user_global"]).parent]
    roots.extend(expand(r) for r in cfg.get("project_roots", []))
    return roots


def is_path_allowed(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except Exception:
        return False
    if resolved.name != "CLAUDE.md":
        return False
    for root in allowed_roots():
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def discover_files() -> list[dict]:
    cfg = get_config()
    entries = []
    user_global = expand(cfg["user_global"])
    entries.append({
        "label": "User Global",
        "sublabel": str(user_global),
        "path": str(user_global),
        "group": "global",
        "project": None,
        "exists": user_global.exists(),
    })
    for root_str in cfg.get("project_roots", []):
        root = expand(root_str)
        if not root.exists() or not root.is_dir():
            continue
        try:
            children = sorted(root.iterdir(), key=lambda p: p.name.lower())
        except PermissionError:
            continue
        for project_dir in children:
            if not project_dir.is_dir() or project_dir.name.startswith("."):
                continue
            for location, candidate in [
                ("root", project_dir / "CLAUDE.md"),
                (".claude", project_dir / ".claude" / "CLAUDE.md"),
            ]:
                entries.append({
                    "label": f"{project_dir.name}",
                    "sublabel": location,
                    "path": str(candidate),
                    "group": root.name,
                    "project": project_dir.name,
                    "exists": candidate.exists(),
                })
    return entries


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>CLAUDE.md Manager</title>
<style>
  :root {
    --bg: #0f1115; --panel: #171a21; --panel-2: #1e222b; --border: #2a2f3a;
    --text: #e6e8ee; --muted: #8b93a5; --accent: #d97757; --accent-2: #8b5cf6;
    --ok: #3fb950; --warn: #d29922; --err: #f85149;
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", system-ui, sans-serif;
    background: var(--bg); color: var(--text); font-size: 14px;
    display: grid; grid-template-columns: 320px 1fr; grid-template-rows: 48px 1fr;
    grid-template-areas: "header header" "sidebar main"; height: 100vh;
  }
  header {
    grid-area: header; background: var(--panel); border-bottom: 1px solid var(--border);
    display: flex; align-items: center; padding: 0 16px; gap: 12px;
  }
  header h1 { font-size: 14px; margin: 0; font-weight: 600; letter-spacing: 0.2px; }
  header .accent { color: var(--accent); }
  header .meta { margin-left: auto; color: var(--muted); font-size: 12px; }
  .icon-btn {
    background: transparent; border: 1px solid var(--border); color: var(--muted);
    width: 30px; height: 30px; border-radius: 6px; cursor: pointer;
    display: inline-flex; align-items: center; justify-content: center;
  }
  .icon-btn:hover { color: var(--text); border-color: var(--accent); }
  aside {
    grid-area: sidebar; background: var(--panel); border-right: 1px solid var(--border);
    display: flex; flex-direction: column; min-height: 0;
  }
  .search { padding: 10px; border-bottom: 1px solid var(--border); }
  .search input {
    width: 100%; padding: 8px 10px; background: var(--panel-2); color: var(--text);
    border: 1px solid var(--border); border-radius: 6px; font-size: 13px; outline: none;
  }
  .search input:focus { border-color: var(--accent); }
  .filters { display: flex; gap: 6px; padding: 8px 10px; border-bottom: 1px solid var(--border); flex-wrap: wrap; }
  .chip {
    font-size: 11px; padding: 3px 8px; border: 1px solid var(--border); border-radius: 999px;
    color: var(--muted); cursor: pointer; user-select: none;
  }
  .chip:hover { color: var(--text); }
  .chip.active { color: var(--text); border-color: var(--accent); background: rgba(217, 119, 87, 0.08); }
  .list { overflow-y: auto; flex: 1; padding: 6px 0; }
  .group-label {
    font-size: 10px; text-transform: uppercase; letter-spacing: 0.8px; color: var(--muted);
    padding: 10px 14px 4px;
  }
  .item {
    padding: 6px 14px; cursor: pointer; border-left: 2px solid transparent;
    display: flex; align-items: center; gap: 8px;
  }
  .item:hover { background: var(--panel-2); }
  .item.active { background: var(--panel-2); border-left-color: var(--accent); }
  .item .dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
  .item .dot.exists { background: var(--ok); }
  .item .dot.missing { background: var(--border); }
  .item .name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
  .item .sub { font-size: 10px; color: var(--muted); margin-left: 6px; }
  .item.missing .name { color: var(--muted); }
  main { grid-area: main; display: flex; flex-direction: column; min-height: 0; }
  .toolbar {
    padding: 10px 16px; border-bottom: 1px solid var(--border); background: var(--panel);
    display: flex; align-items: center; gap: 10px;
  }
  .toolbar .path { font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 12px; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; }
  button {
    background: var(--panel-2); color: var(--text); border: 1px solid var(--border);
    padding: 6px 12px; border-radius: 6px; font-size: 13px; cursor: pointer;
  }
  button:hover { border-color: var(--accent); }
  button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
  button.primary:hover { filter: brightness(1.08); }
  button.danger { border-color: var(--border); color: var(--muted); }
  button.danger:hover { border-color: var(--err); color: var(--err); }
  button:disabled { opacity: 0.4; cursor: not-allowed; }
  .editor-wrap { flex: 1; display: flex; min-height: 0; }
  textarea {
    flex: 1; background: #0b0d12; color: var(--text); border: none; outline: none;
    padding: 16px 20px; resize: none; font-family: ui-monospace, "SF Mono", Menlo, monospace;
    font-size: 13px; line-height: 1.55; tab-size: 2;
  }
  .status {
    padding: 6px 16px; font-size: 12px; border-top: 1px solid var(--border);
    background: var(--panel); display: flex; gap: 14px; align-items: center;
  }
  .status .dirty { color: var(--warn); }
  .status .ok { color: var(--ok); }
  .toast {
    position: fixed; bottom: 20px; right: 20px; padding: 10px 14px; border-radius: 6px;
    background: var(--panel-2); border: 1px solid var(--border); font-size: 13px;
    opacity: 0; transform: translateY(6px); transition: all 0.2s; pointer-events: none;
    z-index: 100;
  }
  .toast.show { opacity: 1; transform: translateY(0); }
  .toast.ok { border-color: var(--ok); }
  .toast.err { border-color: var(--err); }
  .modal-backdrop {
    position: fixed; inset: 0; background: rgba(0,0,0,0.5); display: none;
    align-items: center; justify-content: center; z-index: 50;
  }
  .modal-backdrop.show { display: flex; }
  .modal {
    background: var(--panel); border: 1px solid var(--border); border-radius: 10px;
    width: min(560px, 92vw); max-height: 80vh; display: flex; flex-direction: column;
    box-shadow: 0 20px 60px rgba(0,0,0,0.6);
  }
  .modal h2 { margin: 0; padding: 16px 20px; border-bottom: 1px solid var(--border); font-size: 15px; }
  .modal .body { padding: 16px 20px; overflow-y: auto; }
  .modal .footer { padding: 12px 20px; border-top: 1px solid var(--border); display: flex; gap: 10px; justify-content: flex-end; }
  .field-label { font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.6px; margin-bottom: 6px; }
  .roots-list { display: flex; flex-direction: column; gap: 6px; margin-bottom: 10px; }
  .root-row { display: flex; gap: 8px; align-items: center; }
  .root-row input {
    flex: 1; padding: 6px 10px; background: var(--panel-2); color: var(--text);
    border: 1px solid var(--border); border-radius: 6px; font-size: 13px;
    font-family: ui-monospace, "SF Mono", Menlo, monospace; outline: none;
  }
  .root-row input:focus { border-color: var(--accent); }
  .root-row .status-mark { font-size: 11px; min-width: 56px; text-align: right; }
  .root-row .status-mark.ok { color: var(--ok); }
  .root-row .status-mark.bad { color: var(--err); }
  .add-row { display: flex; gap: 8px; }
  .help { font-size: 12px; color: var(--muted); margin-top: 12px; line-height: 1.5; }
  .help code, .welcome-hint code { background: var(--panel-2); padding: 1px 4px; border-radius: 3px; }
  .welcome-hint {
    background: rgba(217, 119, 87, 0.08); border: 1px solid rgba(217, 119, 87, 0.3);
    color: var(--text); padding: 10px 12px; border-radius: 6px; font-size: 13px;
    line-height: 1.5; margin-bottom: 16px;
  }
</style>
</head>
<body>
<header>
  <h1><span class="accent">CLAUDE.md</span> Manager</h1>
  <div class="meta" id="meta"></div>
  <button class="icon-btn" id="settings-btn" title="Settings" aria-label="Settings">
    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M9.671 4.136a2.34 2.34 0 0 1 4.659 0 2.34 2.34 0 0 0 3.319 1.915 2.34 2.34 0 0 1 2.33 4.033 2.34 2.34 0 0 0 0 3.831 2.34 2.34 0 0 1-2.33 4.033 2.34 2.34 0 0 0-3.319 1.915 2.34 2.34 0 0 1-4.659 0 2.34 2.34 0 0 0-3.32-1.915 2.34 2.34 0 0 1-2.33-4.033 2.34 2.34 0 0 0 0-3.831A2.34 2.34 0 0 1 6.35 6.051a2.34 2.34 0 0 0 3.319-1.915"/>
      <circle cx="12" cy="12" r="3"/>
    </svg>
  </button>
</header>
<aside>
  <div class="search"><input id="search" placeholder="Search projects…" autofocus></div>
  <div class="filters" id="filters"></div>
  <div class="list" id="list"></div>
</aside>
<main>
  <div class="toolbar">
    <div class="path" id="current-path">Select a file on the left</div>
    <button id="reload-btn" title="Reload from disk">Reload</button>
    <button id="save-btn" class="primary" disabled>Save</button>
  </div>
  <div class="editor-wrap">
    <textarea id="editor" placeholder="Select a CLAUDE.md file to edit…" spellcheck="false" disabled></textarea>
  </div>
  <div class="status">
    <span id="status-state">—</span>
    <span id="status-size" style="margin-left:auto; color: var(--muted);"></span>
  </div>
</main>

<div class="modal-backdrop" id="settings-modal">
  <div class="modal">
    <h2>Settings</h2>
    <div class="body">
      <div id="welcome-hint" class="welcome-hint" hidden>
        👋 Welcome — add at least one <strong>project root</strong> below to get started. A project root is a directory whose subfolders are your repos (e.g. <code>~/Documents/code</code>).
      </div>
      <div class="field-label">User-global CLAUDE.md</div>
      <div class="root-row" style="margin-bottom: 16px;">
        <input id="user-global-input" />
        <span class="status-mark" id="user-global-status"></span>
      </div>
      <div class="field-label">Project roots (directories containing project folders)</div>
      <div class="roots-list" id="roots-list"></div>
      <div class="add-row">
        <input id="new-root" placeholder="/absolute/path/to/projects or ~/code" />
        <button id="add-root-btn">Add</button>
      </div>
      <div class="help">
        Each project root is scanned one level deep — every subdirectory becomes a project, and its <code>CLAUDE.md</code> and <code>.claude/CLAUDE.md</code> are listed. Paths support <code>~</code> and <code>$VARS</code>.
      </div>
    </div>
    <div class="footer">
      <button id="settings-cancel">Cancel</button>
      <button id="settings-save" class="primary">Save settings</button>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>
<script>
const $ = sel => document.querySelector(sel);
const $$ = sel => Array.from(document.querySelectorAll(sel));
let files = [];
let config = null;
let groupFilter = "all";
let showEmpty = false;
let current = null;
let originalContent = "";
let dirty = false;

function toast(msg, kind="ok") {
  const t = $("#toast");
  t.textContent = msg;
  t.className = `toast show ${kind}`;
  setTimeout(() => t.className = "toast", 1800);
}

async function api(method, url, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(url, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `${res.status} error`);
  return data;
}

async function loadFiles() {
  files = await api("GET", "/api/files");
  renderFilters();
  renderList();
  const existing = files.filter(f => f.exists).length;
  $("#meta").textContent = `${existing} file${existing === 1 ? "" : "s"} · ${files.length - existing} empty slot${files.length - existing === 1 ? "" : "s"}`;
}

async function loadConfig() { config = await api("GET", "/api/config"); }

function renderFilters() {
  const groups = ["all", ...new Set(files.map(f => f.group))];
  const filterHtml = groups.map(g =>
    `<span class="chip ${g === groupFilter ? "active" : ""}" data-filter="${g}">${g}</span>`
  ).join("");
  const emptyToggle = `<span class="chip ${showEmpty ? "active" : ""}" id="toggle-empty" title="Toggle empty slots (projects without a CLAUDE.md)">${showEmpty ? "◉" : "○"} show empty</span>`;
  $("#filters").innerHTML = filterHtml + emptyToggle;
  $$("#filters .chip[data-filter]").forEach(c => {
    c.onclick = () => { groupFilter = c.dataset.filter; renderFilters(); renderList(); };
  });
  $("#toggle-empty").onclick = () => { showEmpty = !showEmpty; renderFilters(); renderList(); };
}

function renderList() {
  const q = $("#search").value.toLowerCase().trim();
  const filtered = files.filter(f => {
    if (groupFilter !== "all" && f.group !== groupFilter) return false;
    if (!showEmpty && !f.exists) return false;
    if (!q) return true;
    return (f.label + " " + (f.sublabel || "") + " " + (f.project || "")).toLowerCase().includes(q);
  });
  const byGroup = {};
  filtered.forEach(f => { (byGroup[f.group] ||= []).push(f); });
  let html = "";
  for (const [group, items] of Object.entries(byGroup)) {
    html += `<div class="group-label">${group} <span style="color:var(--muted); font-weight:normal;">· ${items.length}</span></div>`;
    items.forEach(f => {
      const activeCls = current && current.path === f.path ? "active" : "";
      const missingCls = f.exists ? "" : "missing";
      const dotCls = f.exists ? "exists" : "missing";
      html += `<div class="item ${activeCls} ${missingCls}" data-path="${encodeURIComponent(f.path)}">
        <span class="dot ${dotCls}"></span>
        <span class="name">${escapeHtml(f.label)}</span>
        <span class="sub">${escapeHtml(f.sublabel || "")}</span>
      </div>`;
    });
  }
  $("#list").innerHTML = html || `<div class="group-label" style="padding-top: 30px; text-align:center;">no matches</div>`;
  $$("#list .item").forEach(el => {
    el.onclick = () => selectFile(decodeURIComponent(el.dataset.path));
  });
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, ch => ({
    "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"
  })[ch]);
}

async function selectFile(path) {
  if (dirty && !confirm("Unsaved changes will be lost. Continue?")) return;
  const file = files.find(f => f.path === path);
  if (!file) return;
  current = file;
  const data = await api("GET", `/api/file?path=${encodeURIComponent(path)}`);
  originalContent = data.content || "";
  $("#editor").value = originalContent;
  $("#editor").disabled = false;
  $("#current-path").textContent = path;
  $("#save-btn").disabled = true;
  dirty = false;
  updateStatus();
  renderList();
}

function updateStatus() {
  const content = $("#editor").value;
  dirty = content !== originalContent;
  $("#save-btn").disabled = !dirty;
  $("#status-state").innerHTML = dirty
    ? `<span class="dirty">● unsaved changes</span>`
    : current ? (current.exists ? `<span class="ok">✓ saved</span>` : `<span style="color:var(--muted)">empty — type to create</span>`) : "—";
  $("#status-size").textContent = current
    ? `${content.length.toLocaleString()} chars · ${content.split("\n").length.toLocaleString()} lines`
    : "";
}

async function save() {
  if (!current) return;
  const content = $("#editor").value;
  try {
    await api("POST", "/api/file", { path: current.path, content });
  } catch (e) {
    toast(e.message, "err");
    return;
  }
  originalContent = content;
  current.exists = true;
  dirty = false;
  updateStatus();
  await loadFiles();
  toast("Saved");
}

function openSettings() {
  renderSettings();
  $("#settings-modal").classList.add("show");
}
function closeSettings() { $("#settings-modal").classList.remove("show"); }

function renderSettings() {
  $("#user-global-input").value = config.user_global;
  $("#welcome-hint").hidden = (config.project_roots || []).length !== 0;
  const list = $("#roots-list");
  list.innerHTML = "";
  (config.project_roots || []).forEach((root, idx) => {
    const row = document.createElement("div");
    row.className = "root-row";
    row.innerHTML = `
      <input value="${escapeHtml(root)}" data-idx="${idx}" />
      <button class="danger" data-remove="${idx}">Remove</button>
    `;
    list.appendChild(row);
  });
  list.querySelectorAll("input").forEach(inp => {
    inp.oninput = () => { config.project_roots[parseInt(inp.dataset.idx)] = inp.value; };
  });
  list.querySelectorAll("button[data-remove]").forEach(btn => {
    btn.onclick = () => {
      config.project_roots.splice(parseInt(btn.dataset.remove), 1);
      renderSettings();
    };
  });
}

async function saveSettings() {
  const payload = {
    user_global: $("#user-global-input").value.trim() || config.user_global,
    project_roots: config.project_roots.map(r => r.trim()).filter(Boolean),
  };
  try {
    config = await api("POST", "/api/config", payload);
  } catch (e) {
    toast(e.message, "err");
    return;
  }
  closeSettings();
  await loadFiles();
  toast("Settings saved");
}

$("#search").oninput = renderList;
$("#editor").oninput = updateStatus;
$("#save-btn").onclick = save;
$("#reload-btn").onclick = async () => {
  await loadFiles();
  if (current) await selectFile(current.path);
};
$("#settings-btn").onclick = openSettings;
$("#settings-cancel").onclick = async () => { await loadConfig(); closeSettings(); };
$("#settings-save").onclick = saveSettings;
$("#add-root-btn").onclick = () => {
  const val = $("#new-root").value.trim();
  if (!val) return;
  config.project_roots.push(val);
  $("#new-root").value = "";
  renderSettings();
};
$("#new-root").addEventListener("keydown", e => { if (e.key === "Enter") $("#add-root-btn").click(); });
$("#settings-modal").addEventListener("click", e => {
  if (e.target.id === "settings-modal") closeSettings();
});
document.addEventListener("keydown", e => {
  if ((e.metaKey || e.ctrlKey) && e.key === "s") {
    e.preventDefault();
    if (!$("#save-btn").disabled) save();
  }
  if (e.key === "Escape" && $("#settings-modal").classList.contains("show")) closeSettings();
});
window.addEventListener("beforeunload", e => {
  if (dirty) { e.preventDefault(); e.returnValue = ""; }
});
(async () => {
  await loadConfig();
  await loadFiles();
  if (!config.project_roots || config.project_roots.length === 0) openSettings();
})();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            body = INDEX_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/api/files":
            self._send_json(200, discover_files())
            return
        if parsed.path == "/api/config":
            self._send_json(200, get_config())
            return
        if parsed.path == "/api/file":
            qs = parse_qs(parsed.query)
            path_str = (qs.get("path") or [""])[0]
            path = Path(path_str)
            if not is_path_allowed(path):
                self._send_json(403, {"error": "path not allowed (must be CLAUDE.md under a configured root)"})
                return
            try:
                content = path.read_text(encoding="utf-8") if path.exists() else ""
            except Exception as e:
                self._send_json(500, {"error": str(e)})
                return
            self._send_json(200, {"path": str(path), "content": content, "exists": path.exists()})
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        try:
            data = json.loads(raw) if raw else {}
        except Exception:
            self._send_json(400, {"error": "invalid json"})
            return

        if parsed.path == "/api/file":
            path = Path(data.get("path", ""))
            content = data.get("content", "")
            if not isinstance(content, str):
                self._send_json(400, {"error": "content must be a string"})
                return
            if not is_path_allowed(path):
                self._send_json(403, {"error": "path not allowed"})
                return
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            except Exception as e:
                self._send_json(500, {"error": str(e)})
                return
            self._send_json(200, {"ok": True, "path": str(path)})
            return

        if parsed.path == "/api/config":
            user_global = str(data.get("user_global") or "").strip()
            project_roots = data.get("project_roots") or []
            if not user_global:
                self._send_json(400, {"error": "user_global is required"})
                return
            if not isinstance(project_roots, list):
                self._send_json(400, {"error": "project_roots must be a list"})
                return
            clean_roots = []
            for r in project_roots:
                if not isinstance(r, str):
                    continue
                r = r.strip()
                if r:
                    clean_roots.append(r)
            new_cfg = {"user_global": user_global, "project_roots": clean_roots}
            try:
                saved = set_config(new_cfg)
            except Exception as e:
                self._send_json(500, {"error": str(e)})
                return
            self._send_json(200, saved)
            return

        self._send_json(404, {"error": "not found"})


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Local CLAUDE.md manager.")
    p.add_argument("--host", default="127.0.0.1", help="bind address (default: 127.0.0.1)")
    p.add_argument("--port", type=int, default=9000, help="port (default: 9000)")
    p.add_argument("--config", default=str(DEFAULT_CONFIG_PATH),
                   help=f"config file path (default: {DEFAULT_CONFIG_PATH})")
    p.add_argument("--open", action="store_true", help="open browser on start")
    return p.parse_args(argv)


def main():
    args = parse_args()
    config_path = expand(args.config)
    _state["config_path"] = config_path
    _state["config"] = load_config(config_path)

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}"
    print(f"CLAUDE.md Manager → {url}")
    print(f"  config: {config_path}{' (new)' if not config_path.exists() else ''}")
    cfg = get_config()
    print(f"  user global: {expand(cfg['user_global'])}")
    for r in cfg.get("project_roots", []):
        exists = "" if expand(r).exists() else " [missing]"
        print(f"  project root: {expand(r)}{exists}")
    print("Ctrl-C to stop.")
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
