# Compatibility and routing

## Oasis montaj 8.4.1

The public `GeosoftInc/gxpy` repository's earliest public release tag is 9.1. Do not install the current PyPI/GitHub package into an Oasis montaj 8.4.1 environment as a compatibility experiment. A modern package may import partially while still being binary- or licence-incompatible with the installed desktop libraries.

For 8.4.1, prefer:

- Geosoft Script (`.gs`) recorded or authored for that installation;
- the installation's own `OMS.EXE` script processor;
- plain, documented interchange files;
- independent Python processing that does not open proprietary files directly.

Only use a Python package with 8.4.1 when it is already supplied by the vendor for that exact installation and the probe succeeds in the same interpreter and licence context.

## Oasis 9.1 and later

gxpy becomes a candidate at 9.1 or later, not an assumption. Confirm all of the following:

1. Oasis version and installation path were detected.
2. The Python interpreter can import both `geosoft` and the required `geosoft.gxpy` modules.
3. Package and desktop versions are compatible.
4. A Geosoft session can initialize under the available licence.
5. Read-only inspection succeeds before any write operation is considered.

## Public references

- Seequent, Command Line Interface (Script Processor): https://help.seequent.com/Oasismontaj/2023.2/Content/ss/process_data/apply_filters_gxs/r/command_line_interface.htm
- Seequent, Summary of Oasis montaj Components: https://help.seequent.com/Oasismontaj/2023.2/Content/ss/prepare_om/work_with_projects/r/summary_of_oasis__montaj_components.htm
- GeosoftInc/gxpy releases: https://github.com/GeosoftInc/gxpy/releases

These public pages document current or later releases. They do not prove behaviour on a specific 8.4.1 computer; collect the detector output and test only against copied data there.
