# Development Roadmap

## Phase 1 — Foundation

- Preserve FEMA Floodplain Downloader v1.1 as the baseline working implementation.
- Establish source-controlled repository structure.
- Extract shared AOI utilities.
- Extract reusable HTTP/REST retry and batching utilities.
- Define provider interface and common result/status model.
- Define provenance fields and `Data_Acquisition_Log` schema.

## Phase 2 — Core environmental providers

1. NWI Wetlands
2. NHD / hydrography
3. USGS Elevation

Each provider should be implemented, tested on a small AOI, then tested on a large corridor AOI before being marked working.

## Phase 3 — Land cover and administrative data

1. NLCD Land Cover
2. USDA Cropland Data Layer
3. Census boundaries

## Phase 4 — Unified ArcGIS Pro toolbox

Create a user-facing toolbox with:

- Study Area
- Optional buffer
- Output geodatabase
- Dataset selection
- Provider-specific advanced options
- Progress/status messages
- Acquisition log
- QA summary

## Phase 5 — Advanced acquisition

- EPA datasets
- State GIS portals
- County/local sources
- imagery metadata
- configuration-driven providers where practical

County parcel acquisition is intentionally later because availability, licensing, schemas, and service patterns vary widely by jurisdiction.
