# External Workbook Verification

Use this reference when creating spreadsheets that another person will rely on: budgets, grant/funder packets, Form 1023 financials, legal/accounting workbooks, or any Google Sheet uploaded from `.xlsx`.

## Lessons captured

Two spreadsheet defects can survive local construction and only show up once a user opens the artifact:

1. **Formula-cache blanks**
   - `openpyxl` can write formulas but not cached calculated values (`<f>...</f><v/>`).
   - Excel may recalculate on open, but Quick Look, Numbers previews, and some Drive/Sheets imports may display `$0` or blank.
   - For external deliverables, prefer static computed values for totals unless the user explicitly needs live formulas.

2. **Template row-label drift**
   - When filling a provided template (IRS Form 1023, budget formats, legal schedules), values can land one row off while totals still manually tie out.
   - Always verify label/value alignment in the actual imported Google Sheet before returning the link.

## Recommended pattern

### Local workbook check

```bash
uv run --with openpyxl python - <<'PY'
from openpyxl import load_workbook
p='workbook.xlsx'
wb=load_workbook(p, data_only=False)
formulas=[]
for ws in wb.worksheets:
    for row in ws.iter_rows():
        for c in row:
            if isinstance(c.value, str) and c.value.startswith('='):
                formulas.append((ws.title, c.coordinate, c.value))
print('formula_count', len(formulas), formulas[:5])

wb=load_workbook(p, data_only=True)
# Print the exact rows/labels that matter, not just totals.
# Example:
# ws=wb['Income Statement']
# for r in [8, 20, 41]:
#     print(r, [ws.cell(r,c).value for c in range(1,7)])
PY
```

### Live Google Sheet check

After upload/convert to a native Sheet, read back the exact rows the user/counsel/funder will inspect:

```bash
gog sheets get "$SID" "Income Statement!A8:F8" --json --no-input
gog sheets get "$SID" "Income Statement!A20:F20" --json --no-input
gog sheets get "$SID" "Income Statement!A41:F41" --json --no-input
```

If the uploaded file is wrong, delete or rename the flawed Drive artifact before returning the folder link. Do not leave stale bad versions where the user might share them.
