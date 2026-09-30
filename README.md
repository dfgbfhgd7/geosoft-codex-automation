# Geosoft Codex Automation

A Codex Skill and local MCP server for cautious, reusable automation of Geosoft Oasis montaj and aeromagnetic projects. It detects Windows installations, reports Python/gxpy compatibility, inventories project files, reviews candidate survey lines using rules inferred from each dataset, and plans or runs Geosoft Scripts with `OMS.EXE`.

The target legacy environment is Oasis montaj 8.4.1. Public gxpy releases start at 9.1, so this project does **not** install or recommend current gxpy for 8.4.1. Unless the target computer already contains a vendor-supplied Python package matched to that installation, use Geosoft Script (`.gs`), `OMS.EXE`, ordinary file exchange, and independent Python processing.

## Safety model

- Detection, compatibility probing, file scanning, and command planning are read-only.
- `plan_oms_command` returns the complete argument vector and a plan ID without running it.
- `run_oms_script` requires both that plan ID and `confirmed: true`.
- A run uses a new output directory and records the command, script checksum, stdout, stderr, return code, duration, and output checksums.
- Source survey data, base-station data, GDB, GRD, MAP, OBS, and inversion products must remain unchanged. Work from copies and make scripts direct outputs to the planned output directory.
- A zero process return code means only that the program completed. It does not establish scientific validity.

## Windows setup

From PowerShell in the repository:

```powershell
.\scripts\install_windows.ps1
```

To install the reusable Skill under the current user's Codex home and register
its local MCP server, run:

```powershell
.\scripts\install_windows.ps1 -InstallForCodex
```

This copies only the Skill, references, and runtime scripts. It refuses to
overwrite an existing installation or MCP section and backs up an existing
`config.toml` before appending the registration. Restart Codex after installing.

Or run directly with an existing Python 3 installation:

```powershell
python .\scripts\geosoft_mcp.py --self-test
python .\scripts\geosoft_mcp.py --detect
python .\scripts\geosoft_mcp.py --serve
```

Legacy installations may live outside `Program Files`. The detector checks nested Geosoft/Seequent registry keys and Windows uninstall records. An installation root can also be supplied explicitly:

```powershell
python .\scripts\geosoft_mcp.py --detect --search-path D:\geosoft
```

The server uses JSON-RPC over stdio and has no required third-party Python dependency. Point the MCP client command to the absolute path of the selected Python executable and pass the absolute script path followed by `--serve`.

Example MCP configuration:

```json
{
  "mcpServers": {
    "geosoft-automation": {
      "command": "C:\\path\\to\\python.exe",
      "args": ["C:\\path\\to\\geosoft-codex-automation\\scripts\\geosoft_mcp.py", "--serve"]
    }
  }
}
```

## Recommended first run on the Oasis computer

Run the self-test and detector, then share the complete JSON output before creating an OMS workflow:

```powershell
python .\scripts\geosoft_mcp.py --self-test
python .\scripts\geosoft_mcp.py --detect
```

Do not install latest `geosoft`/gxpy to make the probe pass on Oasis montaj 8.4.1. See [references/compatibility.md](references/compatibility.md).

## Tools

- `detect_geosoft_installation`
- `probe_gxpy`
- `scan_geosoft_files`
- `inspect_gdb_with_gxpy`
- `auto_review_survey_lines`
- `plan_oms_command`
- `run_oms_script`

## Reuse on another survey

Do not copy this project's paths, flight names, line headings, length thresholds, units, CRS, or time offsets into another project. First inventory and profile the new dataset. The automatic reviewer recalculates its heading and length baseline from the new candidate table.

Preview a review without writing:

```powershell
python .\scripts\aeromag_auto_review.py C:\survey\candidate-lines.csv --mode assisted
```

Write the review to a new directory:

```powershell
python .\scripts\aeromag_auto_review.py C:\survey\candidate-lines.csv `
  --intersection-table C:\survey\intersections.csv `
  --output-dir C:\survey-output\line-review-001 `
  --mode assisted
```

The reviewer supports explicit `column_map` values through MCP when a project's field names are nonstandard. See [references/aeromagnetic-review.md](references/aeromagnetic-review.md).

Detection, automatic review, and OMS execution still require verification on the target computer and dataset. A completed process does not establish scientific validity.
