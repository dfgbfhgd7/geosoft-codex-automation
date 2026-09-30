# Reusable Aeromagnetic Review

## Candidate table contract

`auto_review_survey_lines` accepts CSV, TSV, or semicolon-delimited text. It automatically recognizes common English and Chinese column names. At minimum each row needs:

- a unique line identifier;
- line length in metres;
- median heading or azimuth in degrees.

A source file or sortie column and a provisional line type improve classification. Use `column_map` when names are project-specific:

```json
{
  "line_id": "segment",
  "source": "flight_file",
  "line_type": "provisional_class",
  "length_m": "distance_metres",
  "heading_deg": "median_bearing"
}
```

Do not invent units. Normalize length to metres and heading to degrees before review.

## How decisions are inferred

The reviewer finds the densest length-weighted angular neighbourhood in the current candidate table, then calculates its axial mean. It treats that dominant direction as the traverse direction and the perpendicular direction as the control-line direction. The length threshold defaults to 35 percent of the current table's median positive length and can be overridden.

File or source names can provide configurable hints for control, calibration, attitude, or compensation flights. A hint that conflicts with geometry lowers confidence and creates an exception. If an intersection table is supplied, a proposed control that never appears in it also becomes an exception.

The output records the suggestion, applied decision, confidence, reasons, and exceptions for every line. Preview mode writes nothing. A requested output directory must not already exist.

## Modes

- `strict`: calculate suggestions but leave every decision pending.
- `assisted`: automatically apply only high-confidence decisions with no exception. This is the default.
- `unattended`: apply every available suggestion; structurally invalid rows remain pending.

Automatic line review does not validate geology. Keep amplitude anomalies, leveling-network warnings, missing base coverage, and other scientific QC as separate findings.

## New dataset checklist

Before preprocessing a new survey, establish:

- flight and base-station file roles;
- column mapping and dummy values;
- coordinate units and CRS;
- altitude and magnetic units;
- flight and base clock interpretation;
- expected traverse and control layout;
- an unused output directory.

Save the profile, input checksums, auto-review summary, chosen policy, and output checksums with the run.
