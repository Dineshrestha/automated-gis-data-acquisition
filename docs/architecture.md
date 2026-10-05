# Architecture

## Objective

Build a reusable GIS data-acquisition framework in which each authoritative source is implemented as a provider while AOI processing, downloading, projection, QA, metadata, logging, and output packaging are shared.

## Target flow

```text
Study Area
    |
    v
AOI preparation
    |
    +--> dissolve / buffer / project / validate / subdivide
    |
    v
Provider selection
    |
    +--> FEMA
    +--> NWI
    +--> NHD
    +--> NLCD
    +--> USGS Elevation
    +--> Census
    `--> USDA CDL
    |
    v
Acquisition engine
    |
    +--> REST / API / download
    +--> batching
    +--> retries
    +--> service-specific limits
    |
    v
Spatial processing
    |
    +--> merge
    +--> deduplicate
    +--> clip
    +--> project
    +--> geometry repair
    |
    v
Standardization + QA + provenance
    |
    v
Project_Environmental_Data.gdb
```

## Core package

The future `src/automated_gis_data_acquisition/core/` package will contain reusable logic such as:

- `aoi.py` — AOI validation, dissolve, buffering, projection, extent, and subdivision.
- `download.py` — web request helpers, retries, backoff, batching, and temporary-file handling.
- `projection.py` — spatial-reference and transformation helpers.
- `metadata.py` — standardized provenance attributes and acquisition-log records.
- `qa.py` — output validation, geometry checks, counts, duplicates, and empty-output handling.
- `logging.py` — consistent ArcGIS messages and run logging.
- `exceptions.py` — provider/framework exception classes.

## Providers

Each provider should own only source-specific behavior: endpoint discovery, query parameters, source schema, source filters, and conversion into the common output model.

The first implementation is FEMA. It remains intact as a working `.pyt` while reusable portions are extracted gradually; this avoids breaking a tested production workflow merely to achieve a cleaner package structure.

## Failure isolation

The eventual multi-provider runner should record an individual status for every requested dataset. A failure from one provider should be captured and reported without automatically discarding successful outputs from other providers.

## Large AOIs

Large linear infrastructure projects are a first-class design case. The framework should support:

- polygon-first querying rather than extent-only querying where supported;
- adaptive request sizes;
- retry/backoff;
- AOI tiling/subdivision where needed;
- merge/deduplication after tiled acquisition;
- exact final clipping to the requested AOI.
