FEMA Floodplain Downloader v1.1
================================

ArcGIS Pro Python Toolbox for downloading FEMA NFHL Flood Hazard Zones (Layer 28)
and clipping them to a study area.

v1.1 LARGE-CORRIDOR IMPROVEMENTS
---------------------------------
1. Queries FEMA with the actual AOI polygon first instead of the AOI bounding box.
   This can dramatically reduce irrelevant candidate polygons for long diagonal
   transmission corridors such as B2H.
2. Reduces the initial download batch size from 500 to 250 features.
3. Retries transient FEMA/ArcGIS Server errors up to 5 times.
4. If a batch still fails with a server error, automatically splits it into
   smaller batches (250 -> 125 -> 62 -> 31 -> 15 -> etc.) and continues.
5. Uses a 240-second timeout for feature downloads.
6. Suppresses Z/M geometry in REST responses to reduce payload size.
7. If FEMA rejects an unusually complex AOI polygon query, the tool falls back
   to the AOI envelope automatically.

INSTALL
-------
1. Extract the ZIP.
2. In ArcGIS Pro Catalog, right-click Toolboxes > Add Toolbox.
3. Select FEMA_Floodplain_Downloader.pyt.
4. Run Download FEMA Floodplain.

RECOMMENDED B2H TEST
--------------------
Use the same B2H study feature and 10-mile buffer that failed in v1.0. In the
Messages pane, v1.1 should report that it is querying the actual study area.
If FEMA rejects a particular batch, you should see a warning showing that the
batch is being split and retried rather than terminating the entire run.

NOTE
----
The final output is still clipped exactly to the buffered/dissolved AOI locally
in ArcGIS Pro. The REST spatial query is used only to determine/download candidate
FEMA polygons.
