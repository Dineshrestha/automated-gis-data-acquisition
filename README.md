# Automated GIS Data Acquisition

> Turn a project study area into a project-ready GIS data package by automating acquisition, clipping, projection, standardization, logging, and delivery of authoritative public GIS datasets.

[![ArcGIS Pro](https://img.shields.io/badge/ArcGIS%20Pro-Python%20Toolbox-blue)](https://www.esri.com/en-us/arcgis/products/arcgis-pro/overview)
[![Python](https://img.shields.io/badge/Python-3.x-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

## Overview

Environmental and infrastructure GIS projects repeatedly require analysts to visit multiple public-data portals, locate the correct dataset, download it, clip it to a study area, project it, organize the outputs, and document what was acquired.

**Automated GIS Data Acquisition** consolidates that workflow into a single ArcGIS Pro Python toolbox.

## Workflow at a glance

![Automated GIS Data Acquisition](docs/images/automated_gis_data_acquisition_banner.png)

```text
Study Area
    |
    v
Prepare / Buffer AOI
    |
    v
Connect to public GIS services
    |
    +--> FEMA Floodplain
    +--> NWI Wetlands
    +--> NHD Hydrography
    +--> NLCD Land Cover
    +--> USGS 3DEP Elevation
    +--> USGS DEM 10 m
    +--> Census Boundaries
    +--> USDA Cropland Data Layer
    |
    v
Clip / Project / Standardize
    |
    v
Project_Environmental_Data.gdb
    |
    `--> Data_Acquisition_Log
```

## Current toolbox

The master toolbox is:

```text
toolboxes/Automated_GIS_Data_Acquisition.pyt
```

The tool accepts a point, line, or polygon study area and allows the analyst to select which datasets to acquire.

### Available datasets

| Provider | Dataset | Toolbox support |
|---|---|---|
| FEMA | NFHL Flood Hazard Zones | ✅ Available |
| USFWS | National Wetlands Inventory (NWI) | ✅ Available |
| USGS | NHD Hydrography - Flowlines | ✅ Available |
| USGS | NHD Hydrography - Waterbodies | ✅ Available |
| USGS | NLCD Land Cover | ✅ Available |
| USGS | 3DEP Elevation | ✅ Available |
| USGS | 3DEP DEM 10 m | ✅ Available |
| U.S. Census Bureau | State boundaries | ✅ Available |
| U.S. Census Bureau | County boundaries | ✅ Available |
| USDA NASS | Cropland Data Layer (CDL) | ✅ Available |

> The project is actively being tested and refined. Dataset services can change over time, so provider-specific adjustments may be required as public endpoints evolve.

## Tool interface

<p align="center">
  <img src="docs/images/automated_gis_data_acquisition_tool_interface.png"
       alt="Automated GIS Data Acquisition toolbox interface in ArcGIS Pro"
       width="420">
</p>

The master tool is designed around a simple workflow:

```text
Study Area:
[ StudyArea.shp ]

Buffer Distance:
[ 0 Miles ]

Output Folder:
[ C:\Projects\Project01\Data ]

Output Geodatabase:
[ Project_Environmental_Data.gdb ]

Datasets:
[x] FEMA Floodplain
[x] NWI Wetlands
[x] NHD Hydrography
[x] NLCD Land Cover
[x] USGS Elevation
[x] USGS DEM 10 m
[x] Census Boundaries
[x] USDA Agriculture / CDL

[ RUN ]
```

## Output

A typical run produces:

```text
Project_Environmental_Data.gdb
|
|-- FEMA_Floodplain
|-- NWI_Wetlands
|-- NHD_Flowline
|-- NHD_Waterbody
|-- NLCD_LandCover_2024
|-- USGS_3DEP_Elevation
|-- USGS_DEM_10m
|-- Census_States
|-- Census_Counties
|-- USDA_CDL_2025
`-- Data_Acquisition_Log
```

## Core capabilities

- Point, polyline, or polygon study-area input
- Optional AOI buffering
- File geodatabase creation
- Multi-provider data acquisition
- ArcGIS REST vector querying
- ObjectID batching
- Adaptive batch splitting for large/complex requests
- Retry handling for transient web-service failures
- Exact AOI clipping
- Projection back to the study-area coordinate system
- Raster acquisition from ArcGIS ImageServer services
- DEM / raster clipping and reprojection
- Automatic raster tiling and mosaic fallback when ImageServer export limits are exceeded
- Dedicated 10 m DEM output
- Failure isolation between providers
- Optional add-to-map behavior
- Acquisition log with success/failure, output path, runtime, and message

## Large-AOI resilience

The original FEMA module was tested against a large transmission-corridor AOI after smaller-area workflows exposed REST-service limitations.

The toolbox includes adaptive batching:

```text
500 IDs
   |
   v
Request succeeds?
   |
   +-- Yes --> continue
   |
   `-- No
        |
        v
      Split
    250 + 250
        |
        v
      Retry
```

Failed batches are recursively subdivided until they succeed or reach the configured minimum batch size.

## Raster handling

Raster datasets are acquired from public ArcGIS ImageServer services.

For normal-sized requests, the workflow is:

```text
Image Service
     |
     v
Server-side source mosaic
     |
     v
Clip to AOI
     |
     v
Project to Study Area CRS
     |
     v
Single output raster
```

For large AOIs, the toolbox automatically switches to a tiled workflow when the ImageServer export-size limit is exceeded:

```text
Large raster request
        |
        v
ImageServer size limit
        |
        v
Automatic AOI subdivision
        |
        v
Download smaller raster tiles
        |
        v
Mosaic tiles
        |
        v
Project to Study Area CRS
        |
        v
Final raster
```

This large-raster fallback was successfully tested on a B2H-style study area with a 20-mile buffer. The USGS 3DEP request exceeded the service's 8000 × 8000 export limit, was automatically split into four tiles, mosaicked, projected, and completed successfully.

The dedicated **USGS DEM 10 m** option targets an approximately 10-meter output cell size and converts that distance into the study-area coordinate system's map units when necessary.

## FEMA module

The original FEMA-specific toolbox remains available under:

```text
toolboxes/fema/FEMA_Floodplain_Downloader.pyt
```

It includes:

- FEMA NFHL REST acquisition
- actual-AOI spatial querying
- ObjectID batching
- adaptive batch splitting
- retry handling
- flood-hazard filtering
- exact clipping
- output projection
- geometry repair
- optional summary table

The standalone FEMA module remains useful for FEMA-only workflows and as the first production provider used to build the broader acquisition framework.

## Repository structure

```text
automated-gis-data-acquisition/
|
|-- docs/
|   `-- images/
|       `-- automated_gis_data_acquisition_workflow.png
|
|-- toolboxes/
|   |-- Automated_GIS_Data_Acquisition.pyt
|   `-- fema/
|       |-- FEMA_Floodplain_Downloader.pyt
|       `-- FEMA_Floodplain_Downloader_README_v1_1.txt
|
|-- src/
|   `-- automated_gis_data_acquisition/
|       |-- core/
|       |   |-- aoi.py
|       |   |-- batching.py
|       |   |-- geometry.py
|       |   |-- projection.py
|       |   |-- rest_client.py
|       |   |-- schema.py
|       |   `-- temp.py
|       |
|       `-- providers/
|           `-- fema.py
|
|-- examples/
|-- tests/
|-- CHANGELOG.md
|-- LICENSE
`-- .gitignore
```

## Installation

1. Clone or download this repository.
2. Open **ArcGIS Pro**.
3. Open the **Catalog** pane.
4. Right-click **Toolboxes**.
5. Choose **Add Toolbox**.
6. Browse to:

```text
toolboxes/Automated_GIS_Data_Acquisition.pyt
```

7. Open **Automated GIS Data Acquisition**.
8. Select a study area.
9. Choose an optional buffer.
10. Select the datasets to download.
11. Choose an output folder and geodatabase name.
12. Run the tool.

## Recommended testing sequence

When testing a new environment or provider update, start with a small AOI.

### Vector test

```text
[x] FEMA Floodplain
[x] NWI Wetlands
[x] Census Boundaries
```

### Raster / hydrography test

```text
[x] NHD Hydrography
[x] NLCD Land Cover
[x] USGS DEM 10 m
[x] USDA Cropland Data Layer
```

Then test larger project areas after the small-AOI workflow succeeds.

## Development direction

Near-term priorities:

- [x] FEMA Floodplain
- [x] NWI Wetlands
- [x] NHD Hydrography
- [x] NLCD Land Cover
- [x] USGS 3DEP Elevation
- [x] USGS DEM 10 m
- [x] Census Boundaries
- [x] USDA Cropland Data Layer
- [x] Multi-provider ArcGIS Pro toolbox
- [x] Acquisition log
- [x] Provider failure isolation
- [ ] Expanded QA reporting
- [ ] Standardized provenance fields
- [ ] Large-raster tiling / local mosaic fallback
- [ ] Provider-specific options and filters
- [ ] Automated tests
- [ ] Additional EPA / state / county data providers

## Author

**Dinesh Shrestha**  
GIS Automation & Spatial Analysis Consultant  
ArcGIS Pro • Python • ArcPy • Data Engineering  
Email: dinesh.shrestha015@gmail.com  
Portfolio: dineshrestha.github.io

## License

Released under the [MIT License](LICENSE).
