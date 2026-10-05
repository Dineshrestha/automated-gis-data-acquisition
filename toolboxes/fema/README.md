# FEMA Floodplain Downloader

**Status:** Working baseline provider/toolbox  
**Version:** 1.1

This folder contains the tested ArcGIS Pro Python toolbox that initiated the broader Automated GIS Data Acquisition project.

## Files

- `FEMA_Floodplain_Downloader.pyt` — ArcGIS Pro Python toolbox.
- `FEMA_Floodplain_Downloader_README_v1_1.txt` — v1.1 installation and large-corridor notes.

## Why the code is preserved here

The FEMA toolbox currently works as a standalone implementation. During the next development phase, reusable AOI, REST, batching, projection, QA, and metadata logic will be extracted into the shared `src/` package while this working baseline is retained for regression testing.
