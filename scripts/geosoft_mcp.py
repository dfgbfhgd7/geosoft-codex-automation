#!/usr/bin/env python3
"""Local, dependency-free MCP server for cautious Geosoft automation."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time
from typing import Any

from aeromag_auto_review import auto_review_survey_lines, self_test as auto_review_self_test

SERVER_NAME = "geosoft-automation"
SERVER_VERSION = "0.3.0"
PROTOCOL_VERSION = "2024-11-05"
GEOSOFT_EXTENSIONS = {
    ".gdb", ".grd", ".map", ".obs", ".gpf", ".gs", ".gx", ".gi",
    ".gm", ".omn", ".smn", ".agg", ".con", ".xyz", ".csv", ".dat",
}
PROTECTED_EXTENSIONS = {".gdb", ".grd", ".map", ".obs"}
_PLANS: dict[str, dict[str, Any]] = {}


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _version_tuple(value: str | None) -> tuple[int, ...]:
    if not value:
        return ()
    return tuple(int(part) for part in re.findall(r"\d+", value)[:4])


def _route_for_version(version: str | None) -> str:
    parsed = _version_tuple(version)
    if parsed and parsed < (9, 1):
        return "oms"
    if parsed >= (9, 1):
        return "probe_gxpy_then_oms_fallback"
    return "detect_version_before_selecting_route"


def _walk_registry(winreg: Any, hive: Any, key_name: str, max_depth: int = 4) -> list[tuple[str, dict[str, str]]]:
    """Read string values from a bounded registry subtree."""
    found: list[tuple[str, dict[str, str]]] = []

    def visit(name: str, depth: int) -> None:
        try:
            with winreg.OpenKey(hive, name) as key:
                sub_count, value_count, _ = winreg.QueryInfoKey(key)
                values: dict[str, str] = {}
                for index in range(value_count):
                    value_name, value, _ = winreg.EnumValue(key, index)
                    if isinstance(value, str):
                        values[value_name or "(Default)"] = value
                sub_names = [winreg.EnumKey(key, index) for index in range(sub_count)]
        except OSError:
            return
        found.append((name, values))
        if depth < max_depth:
            for sub_name in sub_names:
                visit(name + "\\" + sub_name, depth + 1)

    visit(key_name, 0)
    return found


def _registry_candidates() -> list[dict[str, str]]:
    if os.name != "nt":
        return []
    try:
        import winreg
    except ImportError:
        return []
    results: list[dict[str, str]] = []
    roots = (
        (winreg.HKEY_LOCAL_MACHINE, "HKEY_LOCAL_MACHINE"),
        (winreg.HKEY_CURRENT_USER, "HKEY_CURRENT_USER"),
    )
    keys = (
        r"SOFTWARE\Geosoft",
        r"SOFTWARE\WOW6432Node\Geosoft",
        r"SOFTWARE\Seequent",
        r"SOFTWARE\WOW6432Node\Seequent",
    )
    seen: set[tuple[str, str, str]] = set()
    for hive, hive_name in roots:
        for key_name in keys:
            for full_name, values in _walk_registry(winreg, hive, key_name):
                for name, value in values.items():
                    expanded = os.path.expandvars(value)
                    value_name = name.lower()
                    path_clue = (
                        value_name in {"geosoft", "geosoft2", "geotemp", "geosoft_resourcefiles"}
                        or any(token in value_name for token in ("path", "directory", "folder"))
                    )
                    try:
                        exists = Path(expanded).exists()
                    except OSError:
                        exists = False
                    if path_clue or exists:
                        item_key = (hive_name, full_name, name)
                        if item_key not in seen:
                            seen.add(item_key)
                            results.append({"hive": hive_name, "registry_key": full_name,
                                            "value_name": name, "value": expanded})
    return results


def _uninstall_records() -> list[dict[str, str | None]]:
    if os.name != "nt":
        return []
    try:
        import winreg
    except ImportError:
        return []
    locations = (
        (winreg.HKEY_LOCAL_MACHINE, "HKEY_LOCAL_MACHINE", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, "HKEY_LOCAL_MACHINE", r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, "HKEY_CURRENT_USER", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    )
    records: list[dict[str, str | None]] = []
    seen: set[tuple[str | None, str | None, str | None]] = set()
    for hive, hive_name, root_name in locations:
        try:
            with winreg.OpenKey(hive, root_name) as root:
                sub_names = [winreg.EnumKey(root, index) for index in range(winreg.QueryInfoKey(root)[0])]
        except OSError:
            continue
        for sub_name in sub_names:
            full_name = root_name + "\\" + sub_name
            try:
                with winreg.OpenKey(hive, full_name) as key:
                    values = {}
                    for index in range(winreg.QueryInfoKey(key)[1]):
                        name, value, _ = winreg.EnumValue(key, index)
                        values[name] = value
            except OSError:
                continue
            display_name = values.get("DisplayName")
            publisher = values.get("Publisher")
            identity = f"{display_name or ''} {publisher or ''}".lower()
            if not any(token in identity for token in ("geosoft", "oasis montaj", "seequent")):
                continue
            record = {
                "hive": hive_name,
                "registry_key": full_name,
                "display_name": str(display_name) if display_name else None,
                "display_version": str(values.get("DisplayVersion")) if values.get("DisplayVersion") else None,
                "install_location": os.path.expandvars(str(values.get("InstallLocation"))) if values.get("InstallLocation") else None,
                "publisher": str(publisher) if publisher else None,
            }
            record_key = (record["display_name"], record["display_version"], record["install_location"])
            if record_key not in seen:
                seen.add(record_key)
                records.append(record)
    return records


def _path_is_under(path: Path, root: Path) -> bool:
    try:
        common = os.path.normcase(os.path.commonpath((str(path), str(root))))
        return common == os.path.normcase(str(root))
    except (OSError, ValueError):
        return False


def _windows_version_strings(path: Path) -> dict[str, str | None]:
    """Read ProductVersion and FileVersion from a Windows executable resource."""
    if os.name != "nt":
        return {"product_version": None, "file_version": None}
    try:
        import ctypes
        from ctypes import wintypes

        version = ctypes.windll.version
        size = version.GetFileVersionInfoSizeW(str(path), None)
        if not size:
            return {"product_version": None, "file_version": None}
        buffer = ctypes.create_string_buffer(size)
        if not version.GetFileVersionInfoW(str(path), 0, size, buffer):
            return {"product_version": None, "file_version": None}

        translations_ptr = ctypes.c_void_p()
        translations_len = wintypes.UINT()
        translations: list[tuple[int, int]] = []
        if version.VerQueryValueW(buffer, r"\VarFileInfo\Translation",
                                  ctypes.byref(translations_ptr), ctypes.byref(translations_len)):
            count = translations_len.value // 4
            raw = ctypes.cast(translations_ptr, ctypes.POINTER(wintypes.WORD))
            translations = [(raw[index * 2], raw[index * 2 + 1]) for index in range(count)]
        translations.extend([(0x0409, 0x04B0), (0x0409, 0x04E4)])

        result: dict[str, str | None] = {"product_version": None, "file_version": None}
        for field, output_name in (("ProductVersion", "product_version"), ("FileVersion", "file_version")):
            for language, codepage in translations:
                value_ptr = ctypes.c_void_p()
                value_len = wintypes.UINT()
                query = f"\\StringFileInfo\\{language:04x}{codepage:04x}\\{field}"
                if version.VerQueryValueW(buffer, query, ctypes.byref(value_ptr), ctypes.byref(value_len)):
                    value = ctypes.wstring_at(value_ptr, value_len.value).rstrip("\x00").strip()
                    if value:
                        result[output_name] = value
                        break
        return result
    except (AttributeError, OSError, ValueError):
        return {"product_version": None, "file_version": None}


def detect_geosoft_installation(search_paths: list[str] | None = None) -> dict[str, Any]:
    registry = _registry_candidates()
    uninstall = _uninstall_records()
    candidates: dict[str, dict[str, Any]] = {}

    def add_candidate(value: str | Path, source: str) -> None:
        try:
            path = Path(os.path.expandvars(str(value))).expanduser()
            normalized = str(path.resolve()).lower() if path.exists() else str(path.absolute()).lower()
        except OSError:
            return
        entry = candidates.setdefault(normalized, {"path": path, "sources": []})
        if source not in entry["sources"]:
            entry["sources"].append(source)

    for name in ("GEOSOFT", "GXDIR", "GEOSOFT_BIN"):
        value = os.environ.get(name)
        if value:
            add_candidate(value, f"environment:{name}")
    for item in registry:
        value = Path(item["value"])
        add_candidate(value.parent if value.is_file() else value,
                      f"registry:{item['hive']}\\{item['registry_key']}:{item['value_name']}")
    for item in uninstall:
        if item["install_location"]:
            add_candidate(item["install_location"], f"uninstall:{item['registry_key']}")
    if search_paths:
        for item in search_paths:
            add_candidate(item, "explicit_search_path")
    if os.name == "nt":
        for base_name in ("ProgramFiles", "ProgramFiles(x86)"):
            base = os.environ.get(base_name)
            if base:
                for suffix in ("Geosoft", "Seequent"):
                    root = Path(base) / suffix
                    if root.exists():
                        add_candidate(root, f"standard_directory:{base_name}")
    located = shutil.which("OMS.EXE") or shutil.which("oms.exe")
    if located:
        add_candidate(Path(located).parent, "PATH")

    executables: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in sorted(candidates.values(), key=lambda item: str(item["path"]).lower()):
        root = candidate["path"]
        if not root.exists():
            continue
        probes = [root / "OMS.EXE", root / "bin" / "OMS.EXE"]
        if root.name.lower() == "oms.exe":
            probes.append(root)
        try:
            if root.is_dir() and root.name.lower() in {"geosoft", "seequent"}:
                probes.extend(root.glob("**/OMS.EXE"))
        except (OSError, PermissionError):
            pass
        for executable in probes:
            try:
                resolved = executable.resolve()
            except OSError:
                continue
            key = str(resolved).lower()
            if not resolved.is_file() or key in seen:
                continue
            seen.add(key)
            resource_versions = _windows_version_strings(resolved)
            matched_uninstall = None
            for record in uninstall:
                install_location = record.get("install_location")
                if install_location and _path_is_under(resolved, Path(install_location).resolve()):
                    matched_uninstall = record
                    break
            item_version = matched_uninstall.get("display_version") if matched_uninstall else None
            version_source = "uninstall_registry" if item_version else None
            if not item_version and resource_versions["product_version"]:
                product_match = re.search(r"(?<!\d)(\d+(?:\.\d+){1,3})(?!\d)", resource_versions["product_version"])
                item_version = product_match.group(1) if product_match else None
                version_source = "oms_product_version" if item_version else None
            if not item_version:
                path_match = re.search(r"(?<!\d)(\d+(?:\.\d+){1,3})(?!\d)", str(resolved))
                item_version = path_match.group(1) if path_match else None
                version_source = "path_hint" if item_version else None
            executables.append({
                "oms_exe": str(resolved),
                "install_root": str(root.resolve()),
                "detected_version": item_version,
                "version_source": version_source,
                **resource_versions,
                "discovery_sources": candidate["sources"],
                "size": resolved.stat().st_size,
                "modified_ns": resolved.stat().st_mtime_ns,
            })

    versions = [item["detected_version"] for item in executables if item["detected_version"]]
    detected_version = versions[0] if len(set(versions)) == 1 else None
    return {
        "host_windows": os.name == "nt",
        "platform": platform.platform(),
        "detected": bool(executables),
        "detected_version": detected_version,
        "recommended_route": _route_for_version(detected_version),
        "installations": executables,
        "registry_path_hints": registry,
        "uninstall_records": uninstall,
        "notes": [
            "Uninstall DisplayVersion and OMS product-version resources are stronger evidence than path-name hints.",
            "Verify the version against Oasis About before executing a production script.",
            "Do not install current gxpy for Oasis montaj 8.4.1.",
        ],
    }


def probe_gxpy(oasis_version: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "oasis_version": oasis_version,
        "route": _route_for_version(oasis_version),
        "geosoft_installed": False,
        "gxpy_importable": False,
        "compatible": False,
    }
    try:
        spec = importlib.util.find_spec("geosoft")
    except (ImportError, ValueError) as exc:
        result["error"] = f"geosoft discovery failed: {exc}"
        return result
    result["geosoft_installed"] = spec is not None
    if spec is None:
        result["guidance"] = "No geosoft package found. For 8.4.1, keep the OMS route; do not install latest gxpy."
        return result
    try:
        geosoft = importlib.import_module("geosoft")
        result["geosoft_version"] = getattr(geosoft, "__version__", None)
        result["geosoft_origin"] = getattr(spec, "origin", None)
        importlib.import_module("geosoft.gxpy")
        result["gxpy_importable"] = True
    except Exception as exc:
        result["error"] = f"gxpy import failed: {type(exc).__name__}: {exc}"
        return result
    if _version_tuple(oasis_version) >= (9, 1):
        result["compatible"] = True
        result["guidance"] = "Import passed; still verify licence/session initialization and read-only access on copied data."
    elif _version_tuple(oasis_version):
        result["guidance"] = "Oasis is older than 9.1. Treat this package as incompatible unless the vendor supplied it for this exact installation."
    else:
        result["guidance"] = "gxpy imports, but Oasis version is unknown. Detect and verify the desktop version before use."
    return result


def scan_geosoft_files(root: str, recursive: bool = True, include_checksums: bool = True,
                        max_files: int = 5000) -> dict[str, Any]:
    base = Path(root).expanduser().resolve()
    if not base.is_dir():
        raise ValueError(f"root is not a directory: {base}")
    iterator = base.rglob("*") if recursive else base.glob("*")
    files: list[dict[str, Any]] = []
    truncated = False
    for path in iterator:
        if not path.is_file() or path.suffix.lower() not in GEOSOFT_EXTENSIONS:
            continue
        if len(files) >= max_files:
            truncated = True
            break
        stat = path.stat()
        item = {
            "path": str(path),
            "relative_path": str(path.relative_to(base)),
            "extension": path.suffix.lower(),
            "size": stat.st_size,
            "modified_ns": stat.st_mtime_ns,
            "protected_source_type": path.suffix.lower() in PROTECTED_EXTENSIONS,
        }
        if include_checksums:
            item["sha256"] = _sha256(path)
        files.append(item)
    return {"root": str(base), "count": len(files), "truncated": truncated, "files": files}


def inspect_gdb_with_gxpy(path: str, oasis_version: str | None = None) -> dict[str, Any]:
    gdb_path = Path(path).expanduser().resolve()
    if not gdb_path.is_file() or gdb_path.suffix.lower() != ".gdb":
        raise ValueError("path must be an existing .gdb file")
    probe = probe_gxpy(oasis_version)
    result: dict[str, Any] = {"path": str(gdb_path), "sha256": _sha256(gdb_path), "probe": probe}
    if not probe["compatible"]:
        result["inspected"] = False
        result["reason"] = "gxpy compatibility was not established; proprietary contents were not opened"
        return result
    try:
        gx = importlib.import_module("geosoft.gxpy.gx")
        gxdb = importlib.import_module("geosoft.gxpy.gdb")
        if not hasattr(gxdb, "Geosoft_gdb"):
            raise RuntimeError("installed gxpy does not expose Geosoft_gdb")
        # External gxpy programs must initialize a GX context before opening a GDB.
        # The public API does not expose a read-only open flag, so this tool only
        # lists metadata and never calls commit or any write method.
        with gx.GXpy():
            with gxdb.Geosoft_gdb.open(str(gdb_path)) as database:
                result["database_repr"] = repr(database)
                result["lines"] = _json_safe(database.list_lines(select=False))
                result["channels"] = _json_safe(database.list_channels())
        result["inspected"] = True
    except Exception as exc:
        result["inspected"] = False
        result["error"] = f"read-only gxpy inspection failed: {type(exc).__name__}: {exc}"
    return result


def _command_display(command: list[str]) -> str:
    return subprocess.list2cmdline(command) if os.name == "nt" else " ".join(json.dumps(arg) for arg in command)


def plan_oms_command(oms_exe: str, script: str, output_dir: str,
                     arguments: list[str] | None = None, working_dir: str | None = None,
                     timeout_seconds: int = 3600) -> dict[str, Any]:
    oms = Path(oms_exe).expanduser().resolve()
    gs = Path(script).expanduser().resolve()
    output = Path(output_dir).expanduser().resolve()
    work = Path(working_dir).expanduser().resolve() if working_dir else gs.parent
    if not oms.is_file() or oms.name.lower() != "oms.exe":
        raise ValueError("oms_exe must be an existing OMS.EXE")
    if not gs.is_file() or gs.suffix.lower() != ".gs":
        raise ValueError("script must be an existing .gs file")
    if not work.is_dir():
        raise ValueError("working_dir must be an existing directory")
    if output.exists():
        raise ValueError("output_dir must not already exist; choose a new run directory")
    if timeout_seconds < 1 or timeout_seconds > 86400:
        raise ValueError("timeout_seconds must be between 1 and 86400")
    command = [str(oms), str(gs)] + [str(arg) for arg in (arguments or [])]
    material = {
        "command": command,
        "working_dir": str(work),
        "output_dir": str(output),
        "timeout_seconds": timeout_seconds,
        "oms_sha256": _sha256(oms),
        "script_sha256": _sha256(gs),
    }
    canonical = json.dumps(material, sort_keys=True, separators=(",", ":"))
    plan_id = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    plan = {**material, "plan_id": plan_id, "command_display": _command_display(command), "executed": False}
    _PLANS[plan_id] = plan
    return {
        **plan,
        "requires_confirmation": True,
        "warning": "Review the exact command and script output paths. Return code 0 will not validate geophysical correctness.",
    }


def run_oms_script(plan_id: str, confirmed: bool = False) -> dict[str, Any]:
    if not confirmed:
        raise PermissionError("explicit confirmation is required: confirmed must be true")
    plan = _PLANS.get(plan_id)
    if not plan:
        raise ValueError("unknown plan_id; call plan_oms_command in this server session")
    if plan["executed"]:
        raise ValueError("this plan has already been executed; create a new plan")
    oms = Path(plan["command"][0])
    gs = Path(plan["command"][1])
    output = Path(plan["output_dir"])
    if output.exists():
        raise ValueError("planned output_dir now exists; create and confirm a new plan")
    if _sha256(oms) != plan["oms_sha256"] or _sha256(gs) != plan["script_sha256"]:
        raise ValueError("OMS.EXE or script changed after planning; create and confirm a new plan")
    output.mkdir(parents=True, exist_ok=False)
    plan["executed"] = True
    env = os.environ.copy()
    env["CODEX_GEOSOFT_OUTPUT_DIR"] = str(output)
    started_wall = time.time()
    started = time.monotonic()
    timed_out = False
    try:
        completed = subprocess.run(
            plan["command"], cwd=plan["working_dir"], env=env,
            capture_output=True, text=True, errors="replace",
            timeout=plan["timeout_seconds"], check=False,
        )
        return_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        return_code = None
        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
    duration = time.monotonic() - started
    (output / "stdout.txt").write_text(stdout, encoding="utf-8")
    (output / "stderr.txt").write_text(stderr, encoding="utf-8")
    audit = {
        "server": SERVER_NAME,
        "server_version": SERVER_VERSION,
        "plan_id": plan_id,
        "command": plan["command"],
        "command_display": plan["command_display"],
        "working_dir": plan["working_dir"],
        "output_dir": str(output),
        "oms_sha256": plan["oms_sha256"],
        "script_sha256": plan["script_sha256"],
        "started_unix": started_wall,
        "duration_seconds": duration,
        "return_code": return_code,
        "timed_out": timed_out,
        "scientifically_validated": False,
    }
    (output / "run.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    output_files = []
    for path in sorted(output.rglob("*")):
        if path.is_file():
            output_files.append({"path": str(path.relative_to(output)), "size": path.stat().st_size, "sha256": _sha256(path)})
    manifest = {"files": output_files}
    (output / "checksums.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {**audit, "stdout_path": str(output / "stdout.txt"), "stderr_path": str(output / "stderr.txt"),
            "audit_path": str(output / "run.json"), "checksums_path": str(output / "checksums.json"),
            "process_succeeded": return_code == 0 and not timed_out}


TOOLS = [
    {"name": "detect_geosoft_installation", "description": "Detect OMS.EXE and Geosoft installation hints without changing the system.",
     "inputSchema": {"type": "object", "properties": {"search_paths": {"type": "array", "items": {"type": "string"}}}}},
    {"name": "probe_gxpy", "description": "Probe the current Python environment and route safely by Oasis version.",
     "inputSchema": {"type": "object", "properties": {"oasis_version": {"type": "string"}}}},
    {"name": "scan_geosoft_files", "description": "Inventory Geosoft project files with optional SHA-256 checksums.",
     "inputSchema": {"type": "object", "required": ["root"], "properties": {"root": {"type": "string"}, "recursive": {"type": "boolean", "default": True}, "include_checksums": {"type": "boolean", "default": True}, "max_files": {"type": "integer", "default": 5000}}}},
    {"name": "inspect_gdb_with_gxpy", "description": "Attempt read-only GDB metadata inspection only after gxpy compatibility is established.",
     "inputSchema": {"type": "object", "required": ["path"], "properties": {"path": {"type": "string"}, "oasis_version": {"type": "string"}}}},
    {"name": "auto_review_survey_lines",
     "description": "Infer a reusable survey-line review policy from each candidate table; preview by default or write a new audited review directory.",
     "inputSchema": {
         "type": "object", "required": ["candidate_table"], "properties": {
             "candidate_table": {"type": "string"},
             "output_dir": {"type": "string"},
             "mode": {"type": "string", "enum": ["strict", "assisted", "unattended"], "default": "assisted"},
             "intersection_table": {"type": "string"},
             "heading_tolerance_deg": {"type": "number", "default": 12.0},
             "confidence_threshold": {"type": "number", "default": 0.85},
             "minimum_length_m": {"type": "number"},
             "tie_keywords": {"type": "array", "items": {"type": "string"}},
             "calibration_keywords": {"type": "array", "items": {"type": "string"}},
             "column_map": {"type": "object", "additionalProperties": {"type": "string"}},
         },
     }},
    {"name": "plan_oms_command", "description": "Build and checksum an OMS.EXE command without running it.",
     "inputSchema": {"type": "object", "required": ["oms_exe", "script", "output_dir"], "properties": {"oms_exe": {"type": "string"}, "script": {"type": "string"}, "output_dir": {"type": "string"}, "arguments": {"type": "array", "items": {"type": "string"}}, "working_dir": {"type": "string"}, "timeout_seconds": {"type": "integer", "default": 3600}}}},
    {"name": "run_oms_script", "description": "Run one previously planned OMS command after explicit confirmation, with audit capture.",
     "inputSchema": {"type": "object", "required": ["plan_id", "confirmed"], "properties": {"plan_id": {"type": "string"}, "confirmed": {"type": "boolean"}}}},
]

FUNCTIONS = {
    "detect_geosoft_installation": detect_geosoft_installation,
    "probe_gxpy": probe_gxpy,
    "scan_geosoft_files": scan_geosoft_files,
    "inspect_gdb_with_gxpy": inspect_gdb_with_gxpy,
    "auto_review_survey_lines": auto_review_survey_lines,
    "plan_oms_command": plan_oms_command,
    "run_oms_script": run_oms_script,
}


def _tool_result(value: Any, is_error: bool = False) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(value, indent=2, ensure_ascii=False)}], "isError": is_error}


def _handle(request: dict[str, Any]) -> dict[str, Any] | None:
    method = request.get("method")
    request_id = request.get("id")
    if request_id is None:
        return None
    try:
        if method == "initialize":
            result = {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}},
                      "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION}}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            params = request.get("params") or {}
            name = params.get("name")
            if name not in FUNCTIONS:
                raise ValueError(f"unknown tool: {name}")
            result = _tool_result(FUNCTIONS[name](**(params.get("arguments") or {})))
        else:
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    except Exception as exc:
        return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result({"error": type(exc).__name__, "message": str(exc)}, True)}


def serve() -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
            response = _handle(request)
        except Exception as exc:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}}
        if response is not None:
            sys.stdout.write(json.dumps(response, separators=(",", ":"), ensure_ascii=False) + "\n")
            sys.stdout.flush()


def self_test() -> dict[str, Any]:
    review_test = auto_review_self_test()
    checks = {
        "seven_tools_registered": len(TOOLS) == 7 and set(FUNCTIONS) == {tool["name"] for tool in TOOLS},
        "legacy_route_is_oms": _route_for_version("8.4.1") == "oms",
        "modern_route_probes_gxpy": _route_for_version("9.1") == "probe_gxpy_then_oms_fallback",
        "unknown_route_detects_first": _route_for_version(None) == "detect_version_before_selecting_route",
        "full_legacy_build_routes_to_oms": _route_for_version("8.4.1.1156") == "oms",
        "generic_auto_review_passes": bool(review_test["ok"]),
    }
    return {"server": SERVER_NAME, "version": SERVER_VERSION, "host_windows": os.name == "nt",
            "python": platform.python_version(), "checks": checks, "ok": all(checks.values())}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--serve", action="store_true", help="run the MCP stdio server")
    group.add_argument("--self-test", action="store_true", help="run dependency-free checks")
    group.add_argument("--detect", action="store_true", help="print installation and gxpy detection JSON")
    parser.add_argument("--search-path", action="append", default=[],
                        help="additional installation root to inspect; may be repeated")
    args = parser.parse_args()
    if args.self_test:
        result = self_test()
        print(json.dumps(result, indent=2))
        return 0 if result["ok"] else 1
    if args.detect:
        detected = detect_geosoft_installation(args.search_path or None)
        detected["gxpy_probe"] = probe_gxpy(detected.get("detected_version"))
        print(json.dumps(detected, indent=2, ensure_ascii=False))
        return 0
    serve()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
