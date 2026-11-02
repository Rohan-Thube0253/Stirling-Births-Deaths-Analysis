"""
Age-standardised death rates: Stirling vs Scotland, 1991 to 2024

Method
- Directly age-standardised rates (DSR) per 100,000 using the 2013 European
  Standard Population (ESP 2013), collapsed to the 10-year age groups NRS
  publishes for council areas (Table DT.07).
- 95% confidence intervals by the Dobson method with exact Poisson limits.
- Denominators: NRS mid-year population estimates by single year of age.

Quality checks (printed when the script runs)
1. Crude rates are compared with NRS Table DT.09 (should match).
2. The Stirling / Scotland DSR ratio is compared with NRS standardised
   mortality ratios in Table DT.11 (a different, indirect method).
3. Scotland's DSR on 10-year groups is compared with the full 5-year ESP
   (Table DT.04a) to measure the effect of the coarser age groups.

Run from the repository root:  python age_standardised_death_rates.py
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.stats import chi2

DEATHS_FILE = "Data/deaths-time-series-24-corrected.xlsx"
POP_FILE = "Data/09ebfefb-33f4-4f6a-8312-2d14e2b02ace.csv"
OUT_CSV = "Data/age_standardised_death_rates.csv"
OUT_PNG = "Screenshots/age_standardised_death_rates.png"

AREAS = {"S92000003": "Scotland", "S12000030": "Stirling"}

# ESP 2013 weights summed into the 10-year groups used in Table DT.07
ESP10 = {
    "0 to 9": 10500, "10 to 19": 11000, "20 to 29": 12000, "30 to 39": 13500,
    "40 to 49": 14000, "50 to 59": 13500, "60 to 69": 11500, "70 to 79": 9000,
    "80 to 89": 4000, "90 and over": 1000,
}
# Full ESP 2013 5-year weights (for check 3)
ESP5 = {
    "0": 1000, "1 to 4": 4000, "5 to 9": 5500, "10 to 14": 5500, "15 to 19": 5500,
    "20 to 24": 6000, "25 to 29": 6000, "30 to 34": 6500, "35 to 39": 7000,
    "40 to 44": 7000, "45 to 49": 7000, "50 to 54": 7000, "55 to 59": 6500,
    "60 to 64": 6000, "65 to 69": 5500, "70 to 74": 5000, "75 to 79": 4000,
    "80 to 84": 2500, "85 to 89": 1500, "90 and over": 1000,
}
assert sum(ESP10.values()) == sum(ESP5.values()) == 100000


def ages_in(band):
    """Single years of age covered by a band label, or None for 90 and over."""
    if band == "90 and over":
        return None
    if band == "0":
        return [0]
    lo, hi = band.split(" to ")
    return range(int(lo), int(hi) + 1)


def band_population(row, band):
    ages = ages_in(band)
    if ages is None:
        return row["Age90plus"]
    return sum(row[f"Age{a}"] for a in ages)


def dsr_with_ci(deaths, pops, weights):
    """Direct standardisation per 100,000 with Dobson 95% limits."""
    d, n, w = (np.asarray(x, float) for x in (deaths, pops, weights))
    W = w.sum()
    dsr = (w * d / n).sum() / W * 1e5
    var = ((w / n) ** 2 * d).sum() / W ** 2 * 1e10
    o = d.sum()
    lo = chi2.ppf(0.025, 2 * o) / 2
    hi = chi2.ppf(0.975, 2 * (o + 1)) / 2
    k = np.sqrt(var / o)
    return dsr, dsr + k * (lo - o), dsr + k * (hi - o)


# Load data
deaths = pd.read_excel(DEATHS_FILE, sheet_name="Table_DT.07", header=3)
deaths["Area name"] = deaths["Area name"].astype(str).str.strip()
deaths = deaths[deaths["Area name"].isin(AREAS.values())]

pop = pd.read_csv(POP_FILE)
pop = pop[(pop["Sex"] == "All") & pop["CA"].isin(AREAS) & (pop["Year"] >= 1991)].copy()
pop["Area"] = pop["CA"].map(AREAS)

not_stated = int(deaths["Not Stated"].sum())

# Calculate rates
rows = []
for _, dr in deaths.iterrows():
    area, year = dr["Area name"], int(dr["Year"])
    pr = pop[(pop["Area"] == area) & (pop["Year"] == year)].iloc[0]
    bands = list(ESP10)
    d = [dr[b] for b in bands]
    n = [band_population(pr, b) for b in bands]
    assert sum(n) == pr["AllAges"], f"Population bands do not add up: {area} {year}"
    dsr, lcl, ucl = dsr_with_ci(d, n, [ESP10[b] for b in bands])
    rows.append({
        "Area": area, "Year": year, "Deaths": int(sum(d)),
        "Population": int(pr["AllAges"]),
        "CrudeRatePer100k": sum(d) / pr["AllAges"] * 1e5,
        "ASRPer100k": dsr, "LowerCI95": lcl, "UpperCI95": ucl,
    })

res = pd.DataFrame(rows).sort_values(["Area", "Year"]).reset_index(drop=True)
asr = res.pivot(index="Year", columns="Area", values="ASRPer100k")
crude = res.pivot(index="Year", columns="Area", values="CrudeRatePer100k")
stir = res[res["Area"] == "Stirling"].set_index("Year")
res["SignificantlyDifferentFromScotland"] = res.apply(
    lambda r: r["Area"] == "Stirling"
    and not (stir.loc[r["Year"], "LowerCI95"] <= asr.loc[r["Year"], "Scotland"]
             <= stir.loc[r["Year"], "UpperCI95"]),
    axis=1,
)
res.round(1).to_csv(OUT_CSV, index=False)

# Quality checks
print(f"Deaths with age not stated (excluded): {not_stated}")

t9 = pd.read_excel(DEATHS_FILE, sheet_name="Table_DT.09", header=5)
t9["Area name"] = t9["Area name"].astype(str).str.strip()
chk = res.merge(t9, left_on=["Area", "Year"], right_on=["Area name", "Year"])
diff = ((chk["CrudeRatePer100k"] / 100).round(1) - chk["Overall death rates"]).abs().max()
print(f"Check 1, crude rate vs NRS DT.09, max difference per 1,000: {diff}")

t11 = pd.read_excel(DEATHS_FILE, sheet_name="Table_DT.11", header=6)
t11 = t11[(t11["Area name"].astype(str).str.strip() == "Stirling")
          & (t11["Cause"] == "All deaths")]
ratio = asr["Stirling"] / asr["Scotland"] * 100
smr = pd.to_numeric(t11.set_index("Year")["Ratio"], errors="coerce")
gap = (ratio.reindex(smr.index.astype(int)).values - smr.values)
print(f"Check 2, DSR ratio vs NRS SMR (2000 to 2024), max gap: {np.nanmax(np.abs(gap)):.1f} points")

t4 = pd.read_excel(DEATHS_FILE, sheet_name="Table_DT.04a", header=6)
t4 = t4[(t4["Sex"] == "Persons") & (t4["Year"] >= 1991)]
scot_pop = pop[pop["Area"] == "Scotland"].set_index("Year")
five = {}
for _, r in t4.iterrows():
    pr = scot_pop.loc[r["Year"]]
    five[int(r["Year"])] = dsr_with_ci(
        [r[b] for b in ESP5], [band_population(pr, b) for b in ESP5], list(ESP5.values())
    )[0]
five = pd.Series(five)
print(f"Check 3, 10-year vs 5-year ESP for Scotland, max difference: "
      f"{((asr['Scotland'] / five - 1).abs().max() * 100):.1f}%")

# Headline findings
for a in ["Scotland", "Stirling"]:
    print(f"{a}: crude rate change 1991 to 2024 {crude[a].iloc[-1] / crude[a].iloc[0] - 1:+.1%}, "
          f"age-standardised change {asr[a].iloc[-1] / asr[a].iloc[0] - 1:+.1%}")
sig = res[res["SignificantlyDifferentFromScotland"]]
print(f"Stirling significantly below Scotland in {len(sig)} of {len(stir)} years")
print(f"2024: Stirling {asr.loc[2024, 'Stirling']:.0f} vs Scotland {asr.loc[2024, 'Scotland']:.0f} per 100,000")

# Chart
fig, ax = plt.subplots(1, 2, figsize=(13, 4.8), sharey=True)
for i, (title, data) in enumerate([("Crude death rate", crude), ("Age-standardised death rate (ESP 2013)", asr)]):
    ax[i].plot(data.index, data["Scotland"], color="#1f4e79", lw=2, label="Scotland")
    ax[i].plot(data.index, data["Stirling"], color="#c55a11", lw=2, label="Stirling")
    if i == 1:
        ax[i].fill_between(stir.index, stir["LowerCI95"], stir["UpperCI95"],
                           color="#c55a11", alpha=0.18, label="Stirling 95% CI")
    ax[i].set_title(title)
    ax[i].grid(alpha=0.3)
    ax[i].set_xlabel("Year of registration")
ax[0].set_ylabel("Deaths per 100,000")
ax[1].legend(frameon=False)
fig.suptitle("Stirling vs Scotland: crude and age-standardised death rates, 1991 to 2024", fontweight="bold")
fig.text(0.01, 0.005, "Source: National Records of Scotland, deaths time series (DT.07) and mid-year population estimates.",
         fontsize=8, color="#555")
fig.tight_layout(rect=(0, 0.03, 1, 1))
fig.savefig(OUT_PNG, dpi=150)
print(f"Saved {OUT_CSV} and {OUT_PNG}")
