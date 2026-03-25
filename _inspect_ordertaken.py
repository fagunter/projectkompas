"""One-off script to parse and inspect Ordertaken.csv."""
import pandas as pd

COLS = [
    "Geo", "Afdeling", "Werkorder", "Operatie", "Gebied", "Station",
    "Equipmentnummer", "Equipment omschrijving", "Taak omschrijving",
    "TESI code", "Kostensoort", "ProjectID", "Projectomschrijving",
    "Uitvoeringsjaar", "Deelreeks", "Alle jaren", "Alle voorgaande jaren",
    "2025", "N+1", "N+2", "N+3", "N+4", "N+5", "N+6", "N+7", "N+8",
    "N+9", "N+10", "N+11", "N+12", "N+13", "N+14", "N+15",
    "Taak in PMF", "Taak in PMF1", "Budget toegewezen door MT AM",
    "Gebruikersstatus",
]

DQ = '""'  # double-double-quote delimiter for string fields


def parse_line(line: str) -> list[str]:
    line = line.strip()
    # Strip outer wrapping quote and trailing semicolons
    if line.startswith('"') and ';;;' in line:
        line = line[1:]
        idx = line.rfind(';;;')
        line = line[:idx]
        if line.endswith('"'):
            line = line[:-1]

    parts: list[str] = []
    i = 0
    n = len(line)
    while i < n:
        if line[i:i+2] == DQ:
            # Quoted field: find closing ""
            close = line.find(DQ, i + 2)
            if close == -1:
                parts.append(line[i+2:])
                break
            parts.append(line[i+2:close])
            i = close + 2
            if i < n and line[i] == '.':
                i += 1
        else:
            dot = line.find('.', i)
            if dot == -1:
                parts.append(line[i:])
                break
            parts.append(line[i:dot])
            i = dot + 1
    return parts


rows = []
bad = 0
with open(r"data\Ordertaken.csv", "r", encoding="utf-8-sig") as f:
    f.readline()  # skip header
    for line in f:
        parts = parse_line(line)
        if len(parts) >= len(COLS):
            rows.append(parts[:len(COLS)])
        else:
            bad += 1

df = pd.DataFrame(rows, columns=COLS)
print(f"Parsed: {len(df)} rows, {bad} skipped\n")

for c in COLS:
    vals = df[c][df[c] != ""]
    print(f"{c}: nunique={vals.nunique()}, empty={(df[c]=='').sum()}, sample={vals.unique()[:5].tolist()}")

print("\n=== KEY COLUMNS ===")
print("\nGeo unique:", sorted(df["Geo"][df["Geo"] != ""].unique())[:20])
print("\nTESI code unique:", sorted(df["TESI code"][df["TESI code"] != ""].unique())[:30])
print("\nProjectID unique (sample):", sorted(df["ProjectID"][df["ProjectID"] != ""].unique())[:20])
print("ProjectID count (non-empty):", (df["ProjectID"] != "").sum())
print("\nGebied unique:", sorted(df["Gebied"][df["Gebied"] != ""].unique())[:20])
print("\nKostensoort unique:", sorted(df["Kostensoort"][df["Kostensoort"] != ""].unique())[:20])
print("\nUitvoeringsjaar unique:", sorted(df["Uitvoeringsjaar"][df["Uitvoeringsjaar"] != ""].unique()))

# Budget columns
for bc in ["Alle jaren", "Alle voorgaande jaren", "2025", "N+1"]:
    vals = df[bc][df[bc] != ""]
    print(f"\n{bc}: sample={vals.head(10).tolist()}")
