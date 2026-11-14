# Field Shift: Adapting Farms with NASA Data

> A decision-support tool that combines NASA Earth observations with local soil information, crop traits, and farmer priorities to help farmers **explore** crop-rotation strategies that strengthen soil health and resilience to changing conditions.

**2026 NASA Space Apps Challenge** · Challenge: *Field Shift: Adapting Farms with NASA Data* · Subjects: Earth Science, Software

> **Field Shift supports farmer judgment. It does not replace it.** Every recommendation is a starting point for conversation with farmers and local agricultural experts.

---

## The Problem

Farmers face shifting temperatures, unpredictable rainfall, water shortages, extreme weather, erosion, and declining soil health. Choosing a new crop for a rotation is hard: a crop that improves soil in one place may use too much water, introduce disease, miss the local market, or not fit the growing season somewhere else.

## What Field Shift Does

Given a field location, the farmer's current rotation, and their priorities, Field Shift:

1. **Characterizes local conditions** from long-term NASA datasets (temperature, rainfall, soil moisture, evapotranspiration, vegetation stress, frost risk, water trends).
2. **Finds vulnerable periods**, such as when fields are typically bare or when the current crop shows stress.
3. **Compares at least three rotation strategies**, including the existing rotation.
4. **Explains each strategy**: why it was suggested, supporting evidence, expected benefits, information gaps, and risks that need local review.
5. **Adapts to farmer priorities**: water conservation, forage value, nitrogen fixation, erosion reduction, organic matter, supplemental income, market suitability.

## Data Sources

| Dataset | Used for |
|---|---|
| NASA POWER | Temperature, solar radiation, rainfall, frost risk |
| GPM | Precipitation and extreme-rainfall events |
| SMAP | Soil moisture and soil moisture anomalies |
| ECOSTRESS | Land-surface temperature, evapotranspiration, heat/water stress |
| Landsat / MODIS | NDVI and vegetation indices, bare-field periods |
| GRACE / GRACE-FO | Long-term groundwater and water-storage trends |
| SRTM (and other elevation products) | Slope, erosion risk, frost-prone low areas |
| GEDI (optional) | Biomass |
| Local soil data (e.g. SoilGrids / SSURGO) | Texture, organic matter, infiltration |

Datasets with different spatial and temporal resolutions are harmonized onto a common analysis grid (resampling and aggregation) so they can be combined into explainable features.

## Rotation Evaluation Criteria

- Nutrient cycling (nitrogen-fixing crops such as legumes)
- Erosion risk and ground cover (cover crops)
- Organic matter contribution
- Pest- and disease-cycle disruption
- Water use and drought tolerance (including deep-rooted crops that improve infiltration)
- Forage potential and income/market fit

## Planned Features

- Interactive map with overlays: long-term soil moisture, heat waves, water-storage decline, erosion and frost zones
- Timeline of bare-field periods and crop-stress seasons
- Farmer priority and constraint inputs (water availability, equipment, markets)
- Side-by-side rotation comparison with plain-language explanations
- Scenario sliders for rainfall and temperature changes
- Glossary: evapotranspiration, soil moisture anomaly, NDVI, frost risk, water balance
- Uncertainty display and clear flags for where local expertise must validate results

## Satellite vs. Ground Data

Satellites give consistent, long-term, wide coverage but at coarse resolution and with indirect measurements. Ground measurements (soil tests, field observations, farmer experience) are precise but local. Field Shift uses satellite data for patterns and trends, and asks users to supply local knowledge to ground-truth them.

## Limitations

- Outputs are pattern-based and probabilistic, not guarantees.
- Coarse satellite resolution may miss field-scale variation.
- Pest, disease, market, and equipment factors need local review.

## Getting Started

_Setup instructions coming soon._

## Team

_Add team members here._

## License

_To be decided._

## Acknowledgments

NASA Earth science data and the NASA Space Apps Challenge.
