# Changelog

## v1.5.0

- Added automatic HTML acquisition/QA report
- Added CSV acquisition manifest
- Added dataset-level provenance metadata
- Added output QA metadata for vectors and rasters
- Added QA summary counts to geoprocessing messages
- Preserved failure isolation across providers

## v1.4.0

- Added `Data_Acquisition_Log` provenance and QA fields
- Added source agency and service URL tracking
- Added requested year, CRS/WKID, feature count, raster dimensions, cell size, bands, and pixel type
- Added acquisition and QA status fields

## v1.3.0

- Added actual-AOI spatial queries for NHD Flowlines
- Reduced NHD Flowline starting batch size from 500 to 125
- Added envelope-query fallback
- Validated NHD Flowline performance on a 10-mile B2H-style test area

## v1.2.0

- Added automatic raster tiling when ImageServer export limits are exceeded
- Added automatic raster tile mosaicking
- Validated USGS 3DEP and USGS DEM 10 m on a 20-mile B2H-style study area

## v1.1.0

- Added dedicated USGS DEM 10 m option
- Added map-unit conversion for approximately 10-meter target output cells

## v1.0.0

- Initial multi-source ArcGIS Pro Python toolbox
- FEMA, NWI, NHD, NLCD, USGS 3DEP, Census, and USDA CDL support
- Vector batching, clipping, projection, raster acquisition, output geodatabase, and run logging
