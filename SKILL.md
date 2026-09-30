---
name: geosoft-automation
description: Inspect and automate Geosoft Oasis montaj and aeromagnetic workflows safely, including installation detection, project inventory, dataset-specific survey-line review, and confirmed OMS.EXE script runs. Use for reusable Geosoft or airborne magnetic processing across new projects; preserve originals and treat 8.4.1 as an OMS-based legacy environment.
---

# Geosoft Automation

Use the local `geosoft-automation` MCP server for environment discovery and controlled execution.

## Route by detected version

1. Call `detect_geosoft_installation` before choosing an integration route.
2. Call `probe_gxpy` using the detected Oasis version.
3. For Oasis montaj 8.4.1, do not install current gxpy. Use `.gs` scripts, `OMS.EXE`, ordinary files, and standalone Python unless the installed vendor distribution already supplies a package explicitly matched to 8.4.1.
4. Consider gxpy only for Oasis 9.1 or later after the probe succeeds in the exact Python environment that will run the task.

If automatic detection returns no installation, do not infer that Oasis is absent. Inspect legacy Geosoft registry `Environment` subkeys and Windows uninstall metadata, then retry with an explicit installation root. The CLI form is `--detect --search-path D:\path\to\geosoft`.

Read [references/compatibility.md](references/compatibility.md) when deciding between gxpy and OMS or diagnosing an installation.

## Inspect before changing

Use `scan_geosoft_files` to inventory relevant files and capture sizes, timestamps, and checksums. Use `inspect_gdb_with_gxpy` only when compatibility has been established. Never claim a GDB was inspected if gxpy was unavailable or initialization failed.

Keep original survey, base-station, GDB, GRD, MAP, OBS, inversion, and derived scientific products unchanged. Work from explicit copies and place all generated material in a new output directory. Preserve units, coordinate reference information, dummy values, channel names, line structure, and processing parameters in any interchange format.

## Generalize to each new survey

Do not reuse paths, sortie numbers, line lengths, headings, units, CRS, time offsets, dummy values, or file-name conventions from an earlier project. Inventory the new input, inspect headers and representative rows, and establish an explicit import profile before transforming data. Stop for unresolved units, coordinate systems, or clock interpretation.

For candidate-line review, call `auto_review_survey_lines` without an output directory first. The tool recomputes the dominant traverse direction and length baseline from the supplied table. Use `assisted` by default: accept high-confidence ordinary lines and leave conflicts, short lines, ambiguous headings, and disconnected controls as `待审核`. Supply an intersection table when available so isolated controls are detected.

Use `strict` when every line must remain pending. Use `unattended` only when the user explicitly chooses automatic decisions and the returned summary has no unresolved rows. Treat semantic keywords as configurable hints, never as the only scientific evidence. Flag magnetic anomalies for review; do not delete or alter values merely because their amplitude is unusual.

Read [references/aeromagnetic-review.md](references/aeromagnetic-review.md) when adapting the workflow to a new input format or configuring automatic review.

## Run OMS only after review

1. Create or inspect the `.gs` script and verify that its output paths point to the new output directory.
2. Call `plan_oms_command`. Show the returned `command_display`, input checksums, working directory, and output directory to the user.
3. Obtain explicit confirmation for that exact command.
4. Call `run_oms_script` with the returned `plan_id` and `confirmed: true`.
5. Review the audit files and output checksums. Treat return code 0 as process success only; validate the geophysical result separately.

Do not reconstruct or guess an OMS command after confirmation. If any executable, script, arguments, working directory, or output path changes, create and confirm a new plan.
