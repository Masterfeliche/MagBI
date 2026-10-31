# Map boundaries

## tanzania-regions.json

Tanzania's 31 regions (ADM1), as they stood in 2018, including Songwe.

- **Source**: Tanzania National Bureau of Statistics, published by UN OCHA ROSA on the Humanitarian Data Exchange (https://data.humdata.org/dataset/cod-ab-tza), packaged by geoBoundaries (gbHumanitarian TZA ADM1, build of 12 Dec 2023, file `geoBoundaries-TZA-ADM1_simplified.geojson`, commit 9469f09 of https://github.com/wmgeolab/geoBoundaries).
- **Licence**: Creative Commons Attribution 3.0 IGO (CC BY 3.0 IGO), https://creativecommons.org/licenses/by/3.0/igo/. MagBI credits the source on every map that draws these boundaries.
- **Changes made for MagBI** (31 Oct 2026):
  - coordinates rounded to 0.001 degrees (about 110 m), with repeated points removed, bringing the file from 1.2 MB to about 580 KB;
  - each feature keeps only `name` (from geoBoundaries' `shapeName`) and `iso` (from `shapeISO`).

Region names are the official ones, so Zanzibar's regions are Kaskazini Unguja, Kusini Unguja, Mjini Magharibi, Kaskazini Pemba and Kusini Pemba. MagBI matches data to them ignoring case, spaces, hyphens and the word "Region".
