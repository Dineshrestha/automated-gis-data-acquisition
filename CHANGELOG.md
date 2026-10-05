# Changelog

All notable project changes will be documented here.

## [Unreleased]

### Added
- Standalone repository structure for Automated GIS Data Acquisition.
- Initial architecture, roadmap, examples, and testing placeholders.
- FEMA Floodplain Downloader v1.1 migrated as the first working provider/toolbox.

## [FEMA 1.1] - 2026-10-05

### Improved
- Query the actual AOI polygon before falling back to the AOI envelope.
- Reduced initial REST batch size from 500 to 250 features.
- Added retry handling for transient FEMA/ArcGIS Server failures.
- Added adaptive recursive batch splitting when FEMA rejects a batch.
- Increased feature-download timeout to 240 seconds.
- Suppressed Z/M geometry in REST responses to reduce payload size.
- Added automatic envelope fallback for unusually complex AOIs.

## v1.3

- Added actual-AOI spatial queries for NHD Flowlines
- Reduced NHD Flowline starting batch size from 500 to 125
- Added envelope-query fallback
- Eliminated repeated 504 timeout splitting in the tested 10-mile B2H run
- NHD test completed successfully in 3m 57s
