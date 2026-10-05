# Automated GIS Data Acquisition

> Turn a project study area into a project-ready GIS data package by automating data discovery, acquisition, clipping, standardization, QA, and documentation.

[![ArcGIS Pro](https://img.shields.io/badge/ArcGIS%20Pro-Python%20Toolbox-blue)](https://www.esri.com/en-us/arcgis/products/arcgis-pro/overview)
[![Python](https://img.shields.io/badge/Python-3.x-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

## Why this project exists

Environmental and infrastructure GIS projects repeatedly require analysts to visit multiple public-data portals, identify the correct dataset, download it, extract it, project it, clip it to a study area, clean the output, and document where it came from.

That workflow is manageable once. Repeating it across dozens or hundreds of projects is slow, inconsistent, and difficult to audit.

**Automated GIS Data Acquisition** is being built as a modular ArcGIS Pro/Python framework that reduces that workflow to a study area plus a set of requested datasets.

```text
Study Area
    |
    v
Determine geography / AOI
    |
    v
Connect to authoritative public sources
    |
    v
Download relevant GIS data
    |
    v
Clip / project / standardize
    |
    v
QA + provenance metadata
    |
    v
Project_Environmental_Data.gdb
```

## Project status

The project is being developed incrementally. The first production module is the existing **FEMA Floodplain Downloader v1.1**, which has already been tested against both small study areas and a much larger transmission-corridor AOI.

| Provider | Dataset | Status |
|---|---|---|
| FEMA | National Flood Hazard Layer / Flood Hazard Zones | **Working — v1.1** |
| USFWS | National Wetlands Inventory (NWI) | Planned |
| USGS | National Hydrography / hydrography | Planned |
| USGS | NLCD Land Cover | Planned |
| USGS | Elevation / DEM | Planned |
| U.S. Census Bureau | Administrative boundaries | Planned |
| USDA | Cropland Data Layer (CDL) | Planned |
| EPA | Environmental datasets | Future |
| State GIS portals | State-specific datasets | Future |
| County sources | Parcels and local data | Future / advanced |

## Current working module: FEMA Floodplain Downloader v1.1

The FEMA module downloads FEMA National Flood Hazard Layer (NFHL) Flood Hazard Zones that intersect a user-supplied study area.

Current capabilities include:

- Polygon, polyline, point, or multipoint study-area input
- Optional AOI buffer
- FEMA NFHL REST-service acquisition
- Actual-AOI spatial query before falling back to an envelope
- ObjectID batching to handle REST record limits
- Adaptive batch splitting for server failures
- Retry handling for transient FEMA/ArcGIS Server errors
- Flood-hazard filtering
- Exact local clipping to the AOI
- Output projection back to the study-area coordinate system
- Geometry repair
- Optional flood-zone summary table
- Optional add-to-map behavior in ArcGIS Pro

The large-corridor improvements in v1.1 were added after a smaller-area workflow succeeded but a much larger corridor AOI exposed REST/server limitations. The solution now queries the actual AOI where possible, reduces batch size, retries transient failures, and recursively splits rejected batches.

## Target product

The long-term ArcGIS Pro tool will use one study area and allow the analyst to choose the datasets required for the project.

```text
Input:
    StudyArea.shp

Datasets:
    [x] FEMA Floodplain
    [ ] NWI Wetlands
    [ ] NHD Hydrography
    [ ] NLCD Land Cover
    [ ] USGS Elevation
    [ ] Census Boundaries
    [ ] USDA Agriculture

Output:
    Project_Environmental_Data.gdb
```

A future project geodatabase may contain outputs such as:

```text
Project_Environmental_Data.gdb
|
|-- FEMA_Flood_Hazard
|-- NWI_Wetlands
|-- NHD_Flowline
|-- NHD_Waterbody
|-- NLCD_LandCover
|-- USDA_CDL
|-- USGS_DEM
|-- Census_Counties
`-- Data_Acquisition_Log
```

## Design goals

The framework is intended to be more than a collection of download scripts. The core design goals are:

1. **Modular providers** — each public data source is implemented independently.
2. **Reusable AOI processing** — dissolve, buffer, project, subdivide, and validate once.
3. **Large-AOI resilience** — batching, retry logic, tiling/subdivision, and graceful recovery.
4. **Consistent outputs** — predictable names, coordinate systems, schemas, and geodatabase organization.
5. **Data provenance** — preserve the source, acquisition date, dataset vintage, processing steps, and tool version.
6. **QA before delivery** — detect empty outputs, invalid geometry, spatial-reference issues, duplicates, and failed downloads.
7. **Failure isolation** — one unavailable provider should not necessarily terminate an entire multi-dataset run.

## Repository architecture

```text
automated-gis-data-acquisition/
|
|-- toolboxes/
|   `-- fema/
|       |-- FEMA_Floodplain_Downloader.pyt
|       `-- FEMA_Floodplain_Downloader_README_v1_1.txt
|
|-- src/
|   `-- automated_gis_data_acquisition/
|       |-- core/
|       `-- providers/
|
|-- docs/
|-- examples/
|-- tests/
|-- CHANGELOG.md
|-- LICENSE
`-- .gitignore
```

The current working FEMA toolbox remains intact under `toolboxes/fema/` while its reusable acquisition logic is progressively refactored into `src/`.

## Standardized provenance attributes — planned

Where appropriate, vector outputs will eventually carry standardized acquisition metadata such as:

| Field | Purpose |
|---|---|
| `DATASET` | Standard dataset name |
| `SOURCE` | Source/provider name |
| `AGENCY` | Publishing agency |
| `SOURCE_URL` | Source service or download location |
| `DOWNLOAD_DT` | Acquisition date |
| `SOURCE_DT` | Dataset vintage/date where available |
| `AOI_NAME` | Project/study-area identifier |
| `ORIG_CRS` | Original coordinate system |
| `OUTPUT_CRS` | Delivered coordinate system |
| `PROCESSING` | Clip/project/mosaic/etc. |
| `TOOL_VER` | Tool version used |

A `Data_Acquisition_Log` table is also planned so a project package can document successes, failures, source information, feature counts, processing, and runtime.

## Roadmap

### Phase 1 — Foundation

- [x] FEMA Floodplain Downloader v1.1
- [x] Large-corridor FEMA query/batching improvements
- [x] Establish standalone GitHub repository
- [ ] Refactor shared AOI/download logic into reusable core modules
- [ ] Add standardized logging and provenance model

### Phase 2 — Core environmental providers

- [ ] NWI Wetlands
- [ ] NHD / hydrography
- [ ] USGS Elevation

### Phase 3 — Land cover and administrative data

- [ ] NLCD Land Cover
- [ ] USDA Cropland Data Layer
- [ ] Census boundaries

### Phase 4 — Production framework

- [ ] Multi-provider ArcGIS Pro toolbox UI
- [ ] Dataset checkboxes and provider-specific options
- [ ] Acquisition log
- [ ] Standard metadata fields
- [ ] QA report
- [ ] Failure isolation and provider status summary
- [ ] Large-AOI subdivision/tiling engine

## Requirements

The current FEMA toolbox is designed for:

- ArcGIS Pro
- Python 3 / ArcPy
- Internet access to the FEMA NFHL ArcGIS REST service

The FEMA module uses Python's standard library for web requests and does not currently require a third-party HTTP package.

## Install the current FEMA module

1. Download or clone this repository.
2. In ArcGIS Pro, open the Catalog pane.
3. Right-click **Toolboxes** and choose **Add Toolbox**.
4. Browse to `toolboxes/fema/FEMA_Floodplain_Downloader.pyt`.
5. Open **Download FEMA Floodplain**.
6. Select the study area, optional buffer, flood-hazard filter, and output geodatabase.
7. Run the tool.

## Repository direction

This repository is intentionally being built in public as a GIS-development portfolio project. Working provider modules will be added incrementally rather than marking planned datasets as complete before they are implemented and tested.

## License

Released under the [MIT License](LICENSE).
