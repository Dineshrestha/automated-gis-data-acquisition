# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# Dinesh Shrestha
# GIS Automation & Spatial Analysis Consultant
# ArcGIS Pro • Python • ArcPy • Data Engineering
# email: dinesh.shrestha015@gmail.com
# Portfolio: dineshrestha.github.io
# -----------------------------------------------------------------------------
"""
FEMA Floodplain Downloader - ArcGIS Pro Python Toolbox

Downloads FEMA National Flood Hazard Layer (NFHL) Flood Hazard Zones
(layer 28) intersecting a user-provided study area, optionally buffers the
study area, filters flood hazards, clips the data exactly to the AOI, and
writes a local feature class plus an optional summary table.

Designed for ArcGIS Pro / Python 3 with ArcPy. Shared REST networking and
retry logic are provided by the Automated GIS Data Acquisition core package.
"""

import arcpy
import os
import sys
import json
import uuid
import urllib.error
from collections import defaultdict


# -----------------------------------------------------------------------------
# Local project package
# -----------------------------------------------------------------------------
# Toolbox location:
#   toolboxes/fema/FEMA_Floodplain_Downloader.pyt
#
# Shared package location:
#   src/automated_gis_data_acquisition/
#
# Add the repository's src folder to sys.path so ArcGIS Pro can import the
# reusable acquisition-engine modules without installing the package.
# -----------------------------------------------------------------------------

TOOLBOX_DIR = os.path.dirname(os.path.abspath(__file__))

PROJECT_SRC = os.path.abspath(
    os.path.join(
        TOOLBOX_DIR,
        "..",
        "..",
        "src",
    )
)

if PROJECT_SRC not in sys.path:
    sys.path.insert(0, PROJECT_SRC)


from automated_gis_data_acquisition.core.rest_client import (
    post_json as _request_json,
    format_arcgis_error as _arcgis_error_text,
)

from automated_gis_data_acquisition.core.aoi import (
    prepare_aoi,
)

from automated_gis_data_acquisition.core.projection import (
    project_feature_class,
)


FEMA_LAYER_URL = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28"
FEMA_QUERY_URL = FEMA_LAYER_URL + "/query"
FEMA_SR_WKID = 4269  # GCS NAD 1983
DEFAULT_BATCH_SIZE = 250
MIN_BATCH_SIZE = 10


class Toolbox(object):
    def __init__(self):
        self.label = "FEMA Flood Data"
        self.alias = "femaflood"
        self.tools = [DownloadFEMAFloodplain]


class DownloadFEMAFloodplain(object):
    def __init__(self):
        self.label = "Download FEMA Floodplain"
        self.description = (
            "Downloads FEMA NFHL Flood Hazard Zones intersecting a study area, "
            "handles REST record limits by batching ObjectIDs, filters the desired "
            "hazard category, clips features to the AOI, and saves them locally."
        )
        self.canRunInBackground = False

    def getParameterInfo(self):
        p0 = arcpy.Parameter(
            displayName="Study Area",
            name="study_area",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input",
        )

        p1 = arcpy.Parameter(
            displayName="Buffer Distance",
            name="buffer_distance",
            datatype="GPLinearUnit",
            parameterType="Optional",
            direction="Input",
        )
        p1.value = "0 Miles"

        p2 = arcpy.Parameter(
            displayName="Flood Hazard Filter",
            name="flood_filter",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
        )
        p2.filter.type = "ValueList"
        p2.filter.list = [
            "All FEMA Flood Zones",
            "SFHA / 1% Annual Chance (100-year)",
            "0.2% Annual Chance (500-year)",
            "Regulatory Floodway",
            "Custom SQL",
        ]
        p2.value = "All FEMA Flood Zones"

        p3 = arcpy.Parameter(
            displayName="Custom SQL (FEMA fields)",
            name="custom_sql",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        p3.enabled = False
        p3.category = "Advanced"

        p4 = arcpy.Parameter(
            displayName="Output File Geodatabase",
            name="output_gdb",
            datatype="DEWorkspace",
            parameterType="Required",
            direction="Input",
        )
        p4.filter.list = ["Local Database"]

        p5 = arcpy.Parameter(
            displayName="Output Feature Class Name",
            name="output_name",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
        )
        p5.value = "FEMA_Floodplain"

        p6 = arcpy.Parameter(
            displayName="Create Summary Table",
            name="create_summary",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input",
        )
        p6.value = True

        p7 = arcpy.Parameter(
            displayName="Add Result to Current Map",
            name="add_to_map",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input",
        )
        p7.value = True

        p8 = arcpy.Parameter(
            displayName="Downloaded Floodplain",
            name="output_feature_class",
            datatype="DEFeatureClass",
            parameterType="Derived",
            direction="Output",
        )

        p9 = arcpy.Parameter(
            displayName="Summary Table",
            name="summary_table",
            datatype="DETable",
            parameterType="Derived",
            direction="Output",
        )

        return [p0, p1, p2, p3, p4, p5, p6, p7, p8, p9]

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        parameters[3].enabled = parameters[2].valueAsText == "Custom SQL"
        return

    def updateMessages(self, parameters):
        if parameters[0].altered and parameters[0].value:
            try:
                desc = arcpy.Describe(parameters[0].value)
                if desc.shapeType not in ("Polygon", "Polyline", "Point", "Multipoint"):
                    parameters[0].setErrorMessage("Study Area must be a feature layer.")
                sr = desc.spatialReference
                if not sr or sr.name == "Unknown":
                    parameters[0].setErrorMessage(
                        "Study Area has an unknown coordinate system. Define its projection before running."
                    )
            except Exception:
                pass

        if parameters[2].valueAsText == "Custom SQL" and not parameters[3].valueAsText:
            parameters[3].setErrorMessage("Enter a SQL expression when Flood Hazard Filter is Custom SQL.")

        if parameters[5].altered and parameters[5].valueAsText:
            cleaned = arcpy.ValidateTableName(parameters[5].valueAsText)
            if cleaned != parameters[5].valueAsText:
                parameters[5].setWarningMessage(
                    "Output name contains characters ArcGIS may replace. Suggested: {}".format(cleaned)
                )
        return

    def execute(self, parameters, messages):
        study_area = parameters[0].valueAsText
        buffer_distance = parameters[1].valueAsText or "0 Miles"
        flood_filter = parameters[2].valueAsText
        custom_sql = parameters[3].valueAsText
        output_gdb = parameters[4].valueAsText
        output_name = arcpy.ValidateTableName(parameters[5].valueAsText, output_gdb)
        create_summary = bool(parameters[6].value)
        add_to_map = bool(parameters[7].value)

        final_output = os.path.join(output_gdb, output_name)
        summary_output = os.path.join(output_gdb, output_name + "_Summary")

        arcpy.env.overwriteOutput = True
        arcpy.env.addOutputsToMap = False

        temp_items = []
        run_id = uuid.uuid4().hex[:8]
        scratch_gdb = arcpy.env.scratchGDB
        scratch_folder = arcpy.env.scratchFolder

        def tmp_fc(label):
            path = os.path.join(scratch_gdb, "{}_{}".format(label, run_id))
            temp_items.append(path)
            return path

        try:
            arcpy.AddMessage("FEMA Floodplain Downloader")
            arcpy.AddMessage("NFHL source: Flood Hazard Zones (Layer 28)")
            arcpy.AddMessage("Validating study area...")

            desc = arcpy.Describe(study_area)
            input_sr = desc.spatialReference
            if not input_sr or input_sr.name == "Unknown":
                raise arcpy.ExecuteError(
                    "Study Area has an unknown coordinate system. Define its projection first."
                )

            # Build one dissolved polygon AOI in the study area's native CRS
            # using the shared acquisition-engine AOI helper.
            aoi_native = tmp_fc("FEMA_AOI")
            arcpy.AddMessage(
                "Preparing study area AOI using shared core helper..."
            )

            prepare_aoi(
                study_area=study_area,
                buffer_distance=buffer_distance,
                output_fc=aoi_native,
            )

            # Project AOI to FEMA's native coordinate system for REST query
            # and exact clipping using the shared projection helper.
            fema_sr = arcpy.SpatialReference(FEMA_SR_WKID)
            aoi_fema = tmp_fc("FEMA_AOI_4269")

            if input_sr.factoryCode == FEMA_SR_WKID:
                arcpy.management.CopyFeatures(
                    aoi_native,
                    aoi_fema,
                )
            else:
                arcpy.AddMessage(
                    "Projecting query AOI to FEMA NAD83 geographic coordinates "
                    "using shared core helper..."
                )

                project_feature_class(
                    input_fc=aoi_native,
                    output_fc=aoi_fema,
                    target_sr=fema_sr,
                )

            extent = arcpy.Describe(aoi_fema).extent
            envelope = {
                "xmin": extent.XMin,
                "ymin": extent.YMin,
                "xmax": extent.XMax,
                "ymax": extent.YMax,
                "spatialReference": {"wkid": FEMA_SR_WKID},
            }

            # Confirm service availability and obtain layer metadata.
            arcpy.AddMessage("Connecting to FEMA NFHL service...")
            layer_info = _request_json(FEMA_LAYER_URL, {"f": "json"})
            if "error" in layer_info:
                raise RuntimeError(_arcgis_error_text(layer_info["error"]))
            service_max = int(layer_info.get("maxRecordCount") or 2000)
            batch_size = min(DEFAULT_BATCH_SIZE, service_max)
            arcpy.AddMessage(
                "Connected: {} | service max records/request: {}".format(
                    layer_info.get("name", "Flood Hazard Zones"), service_max
                )
            )

            # Query IDs first. Prefer the actual AOI polygon rather than its bounding
            # rectangle. This matters for long transmission corridors because a simple
            # envelope can include thousands of unrelated FEMA polygons.
            arcpy.AddMessage("Finding FEMA flood polygons intersecting the actual study area...")
            query_geometry = None
            try:
                with arcpy.da.SearchCursor(aoi_fema, ["SHAPE@JSON"]) as rows:
                    query_geometry = next(rows)[0]
            except Exception:
                query_geometry = None

            id_params = {
                "f": "json",
                "where": "1=1",
                "inSR": str(FEMA_SR_WKID),
                "spatialRel": "esriSpatialRelIntersects",
                "returnGeometry": "false",
                "returnIdsOnly": "true",
            }
            if query_geometry:
                id_params["geometry"] = query_geometry
                id_params["geometryType"] = "esriGeometryPolygon"
                id_response = _request_json(FEMA_QUERY_URL, id_params, timeout=180, retries=5)
            else:
                id_response = {"error": {"code": 500, "message": "AOI polygon could not be serialized"}}

            # Very complex polygons can occasionally be rejected by ArcGIS Server.
            # Fall back to the bounding envelope only when the polygon query fails.
            if "error" in id_response:
                arcpy.AddWarning(
                    "FEMA could not query the full AOI polygon directly. "
                    "Falling back to the AOI envelope; more candidate features may be downloaded."
                )
                id_response = _request_json(
                    FEMA_QUERY_URL,
                    {
                        "f": "json",
                        "where": "1=1",
                        "geometry": json.dumps(envelope, separators=(",", ":")),
                        "geometryType": "esriGeometryEnvelope",
                        "inSR": str(FEMA_SR_WKID),
                        "spatialRel": "esriSpatialRelIntersects",
                        "returnGeometry": "false",
                        "returnIdsOnly": "true",
                    },
                    timeout=180,
                    retries=5,
                )
            if "error" in id_response:
                raise RuntimeError(_arcgis_error_text(id_response["error"]))

            object_ids = id_response.get("objectIds") or []
            object_ids = sorted(object_ids)
            arcpy.AddMessage("{} FEMA polygons found in the query envelope.".format(len(object_ids)))

            if not object_ids:
                _create_empty_output(final_output, input_sr)
                arcpy.AddWarning("No FEMA Flood Hazard Zone features intersect the study area.")
                parameters[8].value = final_output
                if create_summary:
                    _create_summary_table(final_output, summary_output)
                    parameters[9].value = summary_output
                return

            # Download features in adaptive batches. Large or geometrically complex
            # FEMA records can make ArcGIS Server return a generic 500 even when the
            # record count is below maxRecordCount. Failed batches are automatically
            # split into smaller chunks until they succeed.
            batch_fcs = []
            initial_batches = [
                object_ids[i:i + batch_size]
                for i in range(0, len(object_ids), batch_size)
            ]
            arcpy.AddMessage(
                "Downloading {} candidate FEMA features in {} initial batches (up to {} IDs each)...".format(
                    len(object_ids), len(initial_batches), batch_size
                )
            )

            download_counter = [0]

            def download_ids(ids, label):
                if not ids:
                    return
                arcpy.AddMessage(
                    "Downloading {} ({} features)...".format(label, len(ids))
                )
                response = _request_json(
                    FEMA_QUERY_URL,
                    {
                        "f": "json",
                        "objectIds": ",".join(map(str, ids)),
                        "outFields": "*",
                        "returnGeometry": "true",
                        "outSR": str(FEMA_SR_WKID),
                        "returnTrueCurves": "false",
                        "returnZ": "false",
                        "returnM": "false",
                    },
                    timeout=240,
                    retries=5,
                )

                if "error" in response:
                    if len(ids) > MIN_BATCH_SIZE:
                        midpoint = len(ids) // 2
                        left = ids[:midpoint]
                        right = ids[midpoint:]
                        arcpy.AddWarning(
                            "FEMA rejected {} ({} IDs): {}. Retrying as {} + {} IDs.".format(
                                label, len(ids), _arcgis_error_text(response["error"]),
                                len(left), len(right)
                            )
                        )
                        download_ids(left, label + "A")
                        download_ids(right, label + "B")
                        return
                    raise RuntimeError(
                        "{} | ObjectIDs: {}".format(
                            _arcgis_error_text(response["error"]),
                            ",".join(map(str, ids))
                        )
                    )

                download_counter[0] += 1
                n = download_counter[0]
                json_path = os.path.join(
                    scratch_folder, "fema_{}_{:04d}.json".format(run_id, n)
                )
                temp_items.append(json_path)
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(response, f)

                batch_fc = tmp_fc("FEMA_Batch_{:04d}".format(n))
                arcpy.conversion.JSONToFeatures(json_path, batch_fc, "POLYGON")
                if int(arcpy.management.GetCount(batch_fc)[0]) > 0:
                    batch_fcs.append(batch_fc)

            for idx, ids in enumerate(initial_batches, 1):
                arcpy.SetProgressorLabel(
                    "Downloading FEMA initial batch {} of {}...".format(idx, len(initial_batches))
                )
                download_ids(ids, "batch {} of {}".format(idx, len(initial_batches)))

            arcpy.ResetProgressor()
            if not batch_fcs:
                raise RuntimeError("FEMA returned no downloadable features for the candidate ObjectIDs.")

            downloaded = tmp_fc("FEMA_Downloaded")
            arcpy.AddMessage("Combining downloaded FEMA batches...")
            if len(batch_fcs) == 1:
                arcpy.management.CopyFeatures(batch_fcs[0], downloaded)
            else:
                arcpy.management.Merge(batch_fcs, downloaded)

            downloaded_count = int(arcpy.management.GetCount(downloaded)[0])
            arcpy.AddMessage("{} FEMA features downloaded successfully.".format(downloaded_count))

            # Apply desired hazard filter locally after download.
            filtered = tmp_fc("FEMA_Filtered")
            _filter_flood_hazards(downloaded, filtered, flood_filter, custom_sql)
            filtered_count = int(arcpy.management.GetCount(filtered)[0])
            arcpy.AddMessage(
                "{} features remain after filter: {}.".format(filtered_count, flood_filter)
            )

            if filtered_count == 0:
                _create_empty_output(final_output, input_sr, template=downloaded)
                arcpy.AddWarning("The selected flood filter returned zero features in the study area.")
            else:
                # Exact spatial clip to the actual buffered/dissolved AOI.
                clipped_4269 = tmp_fc("FEMA_Clipped_4269")
                arcpy.AddMessage("Clipping FEMA flood zones to the exact study area...")
                arcpy.analysis.PairwiseClip(filtered, aoi_fema, clipped_4269)
                arcpy.management.RepairGeometry(clipped_4269, "DELETE_NULL")

                clip_count = int(arcpy.management.GetCount(clipped_4269)[0])
                if clip_count == 0:
                    _create_empty_output(final_output, input_sr, template=downloaded)
                else:
                    # Deliver output in the study area's coordinate system.
                    if input_sr.factoryCode == FEMA_SR_WKID:
                        arcpy.management.CopyFeatures(
                            clipped_4269,
                            final_output,
                        )
                    else:
                        arcpy.AddMessage(
                            "Projecting final floodplain to the Study Area coordinate "
                            "system using shared core helper..."
                        )

                        project_feature_class(
                            input_fc=clipped_4269,
                            output_fc=final_output,
                            target_sr=input_sr,
                        )

                    arcpy.management.RepairGeometry(
                        final_output,
                        "DELETE_NULL",
                    )

            final_count = int(arcpy.management.GetCount(final_output)[0])
            arcpy.AddMessage("Final clipped features: {:,}".format(final_count))

            if create_summary:
                arcpy.AddMessage("Creating flood-zone summary table...")
                _create_summary_table(final_output, summary_output)
                parameters[9].value = summary_output

            if add_to_map:
                try:
                    aprx = arcpy.mp.ArcGISProject("CURRENT")
                    active_map = aprx.activeMap
                    if active_map:
                        active_map.addDataFromPath(final_output)
                        arcpy.AddMessage("Result added to the current map.")
                except Exception as ex:
                    arcpy.AddWarning("Could not add output to current map: {}".format(ex))

            parameters[8].value = final_output

            arcpy.AddMessage("--------------------------------------------")
            arcpy.AddMessage("FEMA download completed successfully.")
            arcpy.AddMessage("Output: {}".format(final_output))
            if create_summary:
                arcpy.AddMessage("Summary: {}".format(summary_output))
            arcpy.AddMessage("Source: FEMA National Flood Hazard Layer (NFHL), Flood Hazard Zones")

        except urllib.error.URLError as ex:
            arcpy.AddError(
                "Unable to reach FEMA's NFHL web service. Check internet/proxy access and try again. "
                "Details: {}".format(ex)
            )
            raise
        except Exception as ex:
            arcpy.AddError("FEMA Floodplain Downloader failed: {}".format(ex))
            raise
        finally:
            arcpy.ResetProgressor()
            for item in reversed(temp_items):
                try:
                    if isinstance(item, str) and os.path.isfile(item):
                        os.remove(item)
                    elif arcpy.Exists(item):
                        arcpy.management.Delete(item)
                except Exception:
                    pass


def _field_lookup(feature_class):
    return {f.name.upper(): f.name for f in arcpy.ListFields(feature_class)}


def _filter_flood_hazards(in_fc, out_fc, filter_name, custom_sql=None):
    """Filter FEMA features locally, using robust FEMA attribute logic."""
    if filter_name == "All FEMA Flood Zones":
        arcpy.management.CopyFeatures(in_fc, out_fc)
        return

    fields = _field_lookup(in_fc)

    if filter_name == "Custom SQL":
        lyr = "fema_custom_{}".format(uuid.uuid4().hex[:8])
        try:
            arcpy.management.MakeFeatureLayer(in_fc, lyr, custom_sql)
            arcpy.management.CopyFeatures(lyr, out_fc)
        finally:
            if arcpy.Exists(lyr):
                arcpy.management.Delete(lyr)
        return

    # Use a temporary copy and delete nonmatching records. This avoids dependence
    # on DB-specific SQL functions/case behavior for FEMA's text attributes.
    arcpy.management.CopyFeatures(in_fc, out_fc)
    fld_zone = fields.get("FLD_ZONE")
    zone_subty = fields.get("ZONE_SUBTY")
    sfha_tf = fields.get("SFHA_TF")
    floodway = fields.get("FLOODWAY")

    required = {
        "SFHA / 1% Annual Chance (100-year)": [sfha_tf],
        "0.2% Annual Chance (500-year)": [zone_subty],
        "Regulatory Floodway": [zone_subty or floodway],
    }
    if filter_name in required and not all(required[filter_name]):
        raise RuntimeError(
            "FEMA service schema does not contain the field required for '{}' filtering.".format(
                filter_name
            )
        )

    cursor_fields = []
    for f in (fld_zone, zone_subty, sfha_tf, floodway):
        if f and f not in cursor_fields:
            cursor_fields.append(f)
    index = {name.upper(): i for i, name in enumerate(cursor_fields)}

    def value(row, logical_name):
        actual = fields.get(logical_name)
        if not actual:
            return ""
        v = row[index[actual.upper()]]
        return "" if v is None else str(v).strip().upper()

    with arcpy.da.UpdateCursor(out_fc, cursor_fields) as cur:
        for row in cur:
            z = value(row, "FLD_ZONE")
            sub = value(row, "ZONE_SUBTY")
            sfha = value(row, "SFHA_TF")
            fw = value(row, "FLOODWAY")

            keep = True
            if filter_name == "SFHA / 1% Annual Chance (100-year)":
                keep = sfha in ("T", "Y", "YES", "TRUE", "1")
            elif filter_name == "0.2% Annual Chance (500-year)":
                keep = (
                    "0.2 PCT" in sub
                    or "0.2%" in sub
                    or "0.2 PERCENT" in sub
                    or (z == "X" and "ANNUAL CHANCE" in sub and "0.2" in sub)
                )
            elif filter_name == "Regulatory Floodway":
                keep = (
                    "FLOODWAY" in sub
                    or fw in ("FLOODWAY", "REGULATORY FLOODWAY", "T", "Y", "YES", "TRUE", "1")
                )

            if not keep:
                cur.deleteRow()


def _create_empty_output(out_fc, spatial_reference, template=None):
    if arcpy.Exists(out_fc):
        arcpy.management.Delete(out_fc)
    out_path = os.path.dirname(out_fc)
    out_name = os.path.basename(out_fc)
    if template and arcpy.Exists(template):
        arcpy.management.CreateFeatureclass(
            out_path,
            out_name,
            "POLYGON",
            template=template,
            spatial_reference=spatial_reference,
        )
    else:
        arcpy.management.CreateFeatureclass(
            out_path,
            out_name,
            "POLYGON",
            spatial_reference=spatial_reference,
        )
        for name, length in (("FLD_ZONE", 20), ("ZONE_SUBTY", 100), ("SFHA_TF", 10)):
            arcpy.management.AddField(out_fc, name, "TEXT", field_length=length)


def _create_summary_table(feature_class, out_table):
    if arcpy.Exists(out_table):
        arcpy.management.Delete(out_table)

    out_gdb = os.path.dirname(out_table)
    out_name = os.path.basename(out_table)
    arcpy.management.CreateTable(out_gdb, out_name)
    arcpy.management.AddField(out_table, "FLD_ZONE", "TEXT", field_length=30)
    arcpy.management.AddField(out_table, "ZONE_SUBTY", "TEXT", field_length=120)
    arcpy.management.AddField(out_table, "FEATURE_COUNT", "LONG")
    arcpy.management.AddField(out_table, "AREA_ACRES", "DOUBLE")

    fields = _field_lookup(feature_class)
    fld = fields.get("FLD_ZONE")
    sub = fields.get("ZONE_SUBTY")
    if not fld:
        return

    cursor_fields = [fld]
    if sub:
        cursor_fields.append(sub)
    cursor_fields.append("SHAPE@")

    stats = defaultdict(lambda: [0, 0.0])
    with arcpy.da.SearchCursor(feature_class, cursor_fields) as cur:
        for row in cur:
            zone = "" if row[0] is None else str(row[0])
            subtype = ""
            geom_index = 1
            if sub:
                subtype = "" if row[1] is None else str(row[1])
                geom_index = 2
            geom = row[geom_index]
            acres = 0.0
            if geom:
                try:
                    acres = geom.getArea("GEODESIC", "ACRES")
                except Exception:
                    acres = 0.0
            stats[(zone, subtype)][0] += 1
            stats[(zone, subtype)][1] += acres

    with arcpy.da.InsertCursor(
        out_table, ["FLD_ZONE", "ZONE_SUBTY", "FEATURE_COUNT", "AREA_ACRES"]
    ) as icur:
        for (zone, subtype), (count, acres) in sorted(stats.items()):
            icur.insertRow((zone, subtype, count, acres))
