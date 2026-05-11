from openpyxl import Workbook
from openpyxl.styles import Font
from pathlib import Path

wb = Workbook()
ws = wb.active
ws.title = "Password Import Template"

headers = [
    "name",
    "url",
    "username",
    "password",
    "notes"
]

for col, header in enumerate(headers, start=1):
    cell = ws.cell(row=1, column=col, value=header)
    cell.font = Font(bold=True)

example_rows = [
    ["Aldi", "https://new.aldi.us/", "", "", ""],
    ["Meijer", "https://www.meijer.com/", "", "", ""],
    ["Walmart", "https://www.walmart.com/", "", "", ""],
    ["Kroger", "https://www.kroger.com/", "", "", ""],
    ["Target", "https://www.target.com/", "", "", ""],
]

for row in example_rows:
    ws.append(row)

for column_cells in ws.columns:
    length = max(len(str(cell.value or "")) for cell in column_cells)
    ws.column_dimensions[column_cells[0].column_letter].width = min(length + 5, 50)

output_path = Path("/mnt/data/password_manager_import_template.xlsx")
wb.save(output_path)

print(f"Saved template to: {output_path}")
