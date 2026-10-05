# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# Dinesh Shrestha
# GIS Automation & Spatial Analysis Consultant
# ArcGIS Pro • Python • ArcPy • Data Engineering
# email: dinesh.shrestha015@gmail.com
# Portfolio: dineshrestha.github.io
# -----------------------------------------------------------------------------

VERSION = "1.5.0"
"""
Automated GIS Data Acquisition
ArcGIS Pro Python Toolbox

Input:
    Study Area (point, line, or polygon)

Optional buffer:
    Used to convert point/line study areas to an area of interest and to expand
    polygon study areas.

Available datasets:
    - FEMA Floodplain
    - NWI Wetlands
    - NHD Hydrography
    - NLCD Land Cover
    - USGS 3DEP Elevation
    - USGS 3DEP DEM 10 m
    - Census Boundaries
    - USDA Cropland Data Layer (CDL)

Output:
    Project_Environmental_Data.gdb

Design goals:
    - One study area -> multiple authoritative public GIS datasets
    - Large-AOI-safe vector downloads using ObjectID batching
    - Exact AOI clipping
    - Output projection matching the study area
    - Failure isolation: one failed source does not stop the entire run
    - Automatic raster tiling + mosaic fallback for ImageServer size limits
    - NHD Flowline optimization: actual-AOI query + 125-ID starting batches
    - Acquisition log written to the output geodatabase
    - Dataset-level provenance and automated output QA metadata
    - Automatic HTML QA report and CSV acquisition manifest
"""

import arcpy
import csv
import datetime
import html
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


# -----------------------------------------------------------------------------
# Authoritative / public service endpoints
# -----------------------------------------------------------------------------

FEMA_FLOOD_URL = (
    "https://hazards.fema.gov/arcgis/rest/services/"
    "public/NFHL/MapServer/28"
)

NWI_WETLANDS_URL = (
    "https://fwspublicservices.wim.usgs.gov/"
    "wetlandsmapservice/rest/services/Wetlands/MapServer/0"
)

NHD_BASE = (
    "https://hydro.nationalmap.gov/arcgis/rest/services/"
    "nhd/MapServer"
)
NHD_FLOWLINE_URL = NHD_BASE + "/6"
NHD_WATERBODY_URL = NHD_BASE + "/12"

CENSUS_BASE = (
    "https://tigerweb.geo.census.gov/arcgis/rest/services/"
    "TIGERweb/State_County/MapServer"
)
# BAS 2026 layers
CENSUS_STATES_URL = CENSUS_BASE + "/18"
CENSUS_COUNTIES_URL = CENSUS_BASE + "/19"

NLCD_IMAGE_URL = (
    "https://di-nlcd.img.arcgis.com/arcgis/rest/services/"
    "USA_NLCD_Annual_LandCover/ImageServer"
)

USGS_3DEP_URL = (
    "https://elevation.nationalmap.gov/arcgis/rest/services/"
    "3DEPElevation/ImageServer"
)

USDA_CDL_URL = (
    "https://pdi.scinet.usda.gov/image/rest/services/"
    "CDL_WM/ImageServer"
)


VECTOR_BATCH_SIZE = 500
NHD_FLOWLINE_BATCH_SIZE = 125
MIN_VECTOR_BATCH_SIZE = 10
WEB_MERCATOR = 3857
FEMA_WKID = 4269


class Toolbox(object):
    def __init__(self):
        self.label = "Automated GIS Data Acquisition"
        self.alias = "automated_gis_data_acquisition"
        self.tools = [AutomatedGISDataAcquisition]


class AutomatedGISDataAcquisition(object):
    def __init__(self):
        self.label = "Automated GIS Data Acquisition"
        self.description = (
            "Download and clip authoritative public GIS datasets to a study area."
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
            displayName="Output Folder",
            name="output_folder",
            datatype="DEFolder",
            parameterType="Required",
            direction="Input",
        )

        p3 = arcpy.Parameter(
            displayName="Output Geodatabase Name",
            name="output_gdb_name",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
        )
        p3.value = "Project_Environmental_Data.gdb"

        # Dataset checkboxes
        p4 = _bool_parameter("FEMA Floodplain", "fema_floodplain", True)
        p5 = _bool_parameter("NWI Wetlands", "nwi_wetlands", True)
        p6 = _bool_parameter("NHD Hydrography", "nhd_hydrography", True)
        p7 = _bool_parameter("NLCD Land Cover", "nlcd_land_cover", True)
        p8 = _bool_parameter("USGS Elevation (3DEP)", "usgs_elevation", True)
        p9 = _bool_parameter("USGS DEM 10 m", "usgs_dem_10m", True)
        p10 = _bool_parameter("Census Boundaries", "census_boundaries", True)
        p11 = _bool_parameter("USDA Agriculture (CDL)", "usda_agriculture", True)

        p12 = arcpy.Parameter(
            displayName="NLCD Year",
            name="nlcd_year",
            datatype="GPLong",
            parameterType="Optional",
            direction="Input",
        )
        p12.value = 2024

        p13 = arcpy.Parameter(
            displayName="USDA CDL Year",
            name="cdl_year",
            datatype="GPLong",
            parameterType="Optional",
            direction="Input",
        )
        p13.value = 2025

        p14 = arcpy.Parameter(
            displayName="Elevation Output Cell Size (map units)",
            name="elevation_cell_size",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input",
        )
        p14.value = 10

        p15 = _bool_parameter("Add Outputs to Current Map", "add_to_map", True)

        p16 = arcpy.Parameter(
            displayName="Output Geodatabase",
            name="output_geodatabase",
            datatype="DEWorkspace",
            parameterType="Derived",
            direction="Output",
        )

        return [
            p0, p1, p2, p3,
            p4, p5, p6, p7, p8, p9, p10, p11,
            p12, p13, p14, p15, p16,
        ]

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        return

    def updateMessages(self, parameters):
        study_area = parameters[0].valueAsText
        gdb_name = parameters[3].valueAsText

        if gdb_name and not gdb_name.lower().endswith(".gdb"):
            parameters[3].setWarningMessage(
                "'.gdb' will be appended automatically."
            )

        if study_area:
            try:
                desc = arcpy.Describe(study_area)
                if desc.shapeType not in ("Point", "Polyline", "Polygon"):
                    parameters[0].setErrorMessage(
                        "Study Area must be a point, polyline, or polygon layer."
                    )
            except Exception:
                pass

    def execute(self, parameters, messages):
        study_area = parameters[0].valueAsText
        buffer_distance = parameters[1].valueAsText or "0 Miles"
        output_folder = parameters[2].valueAsText
        gdb_name = parameters[3].valueAsText or "Project_Environmental_Data.gdb"

        get_fema = bool(parameters[4].value)
        get_nwi = bool(parameters[5].value)
        get_nhd = bool(parameters[6].value)
        get_nlcd = bool(parameters[7].value)
        get_elevation = bool(parameters[8].value)
        get_dem_10m = bool(parameters[9].value)
        get_census = bool(parameters[10].value)
        get_cdl = bool(parameters[11].value)

        nlcd_year = int(parameters[12].value or 2024)
        cdl_year = int(parameters[13].value or 2025)
        elevation_cell_size = float(parameters[14].value or 10)
        add_to_map = bool(parameters[15].value)

        if not gdb_name.lower().endswith(".gdb"):
            gdb_name += ".gdb"

        if not os.path.isdir(output_folder):
            raise arcpy.ExecuteError(
                "Output folder does not exist: {}".format(output_folder)
            )

        output_gdb = os.path.join(output_folder, gdb_name)

        if not arcpy.Exists(output_gdb):
            arcpy.AddMessage("Creating output geodatabase...")
            arcpy.management.CreateFileGDB(
                output_folder,
                os.path.splitext(gdb_name)[0],
            )

        parameters[16].value = output_gdb

        selected = [
            get_fema, get_nwi, get_nhd, get_nlcd,
            get_elevation, get_dem_10m, get_census, get_cdl,
        ]
        if not any(selected):
            raise arcpy.ExecuteError("Select at least one dataset.")

        run_id = uuid.uuid4().hex[:8]
        scratch_gdb = arcpy.env.scratchGDB
        temp_items = []
        outputs = []
        log_rows = []

        def tmp_fc(label):
            path = os.path.join(
                scratch_gdb,
                "{}_{}".format(label, run_id),
            )
            temp_items.append(path)
            return path

        try:
            arcpy.AddMessage("=" * 72)
            arcpy.AddMessage("AUTOMATED GIS DATA ACQUISITION")
            arcpy.AddMessage("=" * 72)

            # -----------------------------------------------------------------
            # AOI
            # -----------------------------------------------------------------
            desc = arcpy.Describe(study_area)
            input_sr = desc.spatialReference

            if not input_sr or input_sr.name == "Unknown":
                raise arcpy.ExecuteError(
                    "Study Area has an unknown coordinate system."
                )

            buffer_value = _linear_value(buffer_distance)

            if desc.shapeType != "Polygon" and buffer_value <= 0:
                raise arcpy.ExecuteError(
                    "Point/Polyline study areas require a positive buffer."
                )

            aoi_native = tmp_fc("AOI_NATIVE")

            if buffer_value > 0:
                arcpy.AddMessage(
                    "Preparing AOI with {} buffer...".format(buffer_distance)
                )
                arcpy.analysis.PairwiseBuffer(
                    study_area,
                    aoi_native,
                    buffer_distance,
                    dissolve_option="ALL",
                )
            else:
                arcpy.AddMessage("Preparing dissolved AOI...")
                arcpy.management.Dissolve(
                    study_area,
                    aoi_native,
                )

            if int(arcpy.management.GetCount(aoi_native)[0]) == 0:
                raise arcpy.ExecuteError("Prepared AOI is empty.")

            # -----------------------------------------------------------------
            # VECTOR DATASETS
            # -----------------------------------------------------------------
            if get_fema:
                _run_logged(
                    "FEMA Floodplain",
                    log_rows,
                    lambda: _download_vector_service(
                        label="FEMA Floodplain",
                        layer_url=FEMA_FLOOD_URL,
                        service_wkid=FEMA_WKID,
                        aoi_native=aoi_native,
                        input_sr=input_sr,
                        output_fc=os.path.join(output_gdb, "FEMA_Floodplain"),
                        tmp_fc=tmp_fc,
                        temp_items=temp_items,
                    ),
                    outputs,
                )

            if get_nwi:
                _run_logged(
                    "NWI Wetlands",
                    log_rows,
                    lambda: _download_vector_service(
                        label="NWI Wetlands",
                        layer_url=NWI_WETLANDS_URL,
                        service_wkid=WEB_MERCATOR,
                        aoi_native=aoi_native,
                        input_sr=input_sr,
                        output_fc=os.path.join(output_gdb, "NWI_Wetlands"),
                        tmp_fc=tmp_fc,
                        temp_items=temp_items,
                    ),
                    outputs,
                )

            if get_nhd:
                _run_logged(
                    "NHD Flowline",
                    log_rows,
                    lambda: _download_vector_service(
                        label="NHD Flowline",
                        layer_url=NHD_FLOWLINE_URL,
                        service_wkid=WEB_MERCATOR,
                        aoi_native=aoi_native,
                        input_sr=input_sr,
                        output_fc=os.path.join(output_gdb, "NHD_Flowline"),
                        tmp_fc=tmp_fc,
                        temp_items=temp_items,
                        initial_batch_size=NHD_FLOWLINE_BATCH_SIZE,
                        use_actual_aoi_query=True,
                    ),
                    outputs,
                )

                _run_logged(
                    "NHD Waterbody",
                    log_rows,
                    lambda: _download_vector_service(
                        label="NHD Waterbody",
                        layer_url=NHD_WATERBODY_URL,
                        service_wkid=WEB_MERCATOR,
                        aoi_native=aoi_native,
                        input_sr=input_sr,
                        output_fc=os.path.join(output_gdb, "NHD_Waterbody"),
                        tmp_fc=tmp_fc,
                        temp_items=temp_items,
                    ),
                    outputs,
                )

            if get_census:
                _run_logged(
                    "Census States",
                    log_rows,
                    lambda: _download_vector_service(
                        label="Census States",
                        layer_url=CENSUS_STATES_URL,
                        service_wkid=WEB_MERCATOR,
                        aoi_native=aoi_native,
                        input_sr=input_sr,
                        output_fc=os.path.join(output_gdb, "Census_States"),
                        tmp_fc=tmp_fc,
                        temp_items=temp_items,
                    ),
                    outputs,
                )

                _run_logged(
                    "Census Counties",
                    log_rows,
                    lambda: _download_vector_service(
                        label="Census Counties",
                        layer_url=CENSUS_COUNTIES_URL,
                        service_wkid=WEB_MERCATOR,
                        aoi_native=aoi_native,
                        input_sr=input_sr,
                        output_fc=os.path.join(output_gdb, "Census_Counties"),
                        tmp_fc=tmp_fc,
                        temp_items=temp_items,
                    ),
                    outputs,
                )

            # -----------------------------------------------------------------
            # RASTER DATASETS
            # -----------------------------------------------------------------
            if get_nlcd:
                _run_logged(
                    "NLCD Land Cover {}".format(nlcd_year),
                    log_rows,
                    lambda: _download_image_service(
                        label="NLCD Land Cover {}".format(nlcd_year),
                        image_url=NLCD_IMAGE_URL,
                        aoi_native=aoi_native,
                        input_sr=input_sr,
                        output_raster=os.path.join(
                            output_gdb,
                            "NLCD_LandCover_{}".format(nlcd_year),
                        ),
                        tmp_fc=tmp_fc,
                        where_clause="Year = {}".format(nlcd_year),
                        cell_size=None,
                        resampling="NEAREST",
                    ),
                    outputs,
                )

            if get_elevation:
                _run_logged(
                    "USGS 3DEP Elevation",
                    log_rows,
                    lambda: _download_image_service(
                        label="USGS 3DEP Elevation",
                        image_url=USGS_3DEP_URL,
                        aoi_native=aoi_native,
                        input_sr=input_sr,
                        output_raster=os.path.join(
                            output_gdb,
                            "USGS_3DEP_Elevation",
                        ),
                        tmp_fc=tmp_fc,
                        where_clause=None,
                        cell_size=elevation_cell_size,
                        resampling="BILINEAR",
                    ),
                    outputs,
                )

            if get_dem_10m:
                dem_10m_cell_size = _meters_to_map_units(input_sr, 10.0)

                _run_logged(
                    "USGS 3DEP DEM 10 m",
                    log_rows,
                    lambda: _download_image_service(
                        label="USGS 3DEP DEM 10 m",
                        image_url=USGS_3DEP_URL,
                        aoi_native=aoi_native,
                        input_sr=input_sr,
                        output_raster=os.path.join(
                            output_gdb,
                            "USGS_DEM_10m",
                        ),
                        tmp_fc=tmp_fc,
                        where_clause=None,
                        cell_size=dem_10m_cell_size,
                        resampling="BILINEAR",
                    ),
                    outputs,
                )

            if get_cdl:
                _run_logged(
                    "USDA CDL {}".format(cdl_year),
                    log_rows,
                    lambda: _download_image_service(
                        label="USDA CDL {}".format(cdl_year),
                        image_url=USDA_CDL_URL,
                        aoi_native=aoi_native,
                        input_sr=input_sr,
                        output_raster=os.path.join(
                            output_gdb,
                            "USDA_CDL_{}".format(cdl_year),
                        ),
                        tmp_fc=tmp_fc,
                        where_clause="Year = {}".format(cdl_year),
                        cell_size=None,
                        resampling="NEAREST",
                    ),
                    outputs,
                )

            # -----------------------------------------------------------------
            # LOG + MAP
            # -----------------------------------------------------------------
            log_table = os.path.join(
                output_gdb,
                "Data_Acquisition_Log",
            )
            _write_log(log_table, log_rows, run_id)

            report_html, manifest_csv = _write_run_reports(
                output_folder=output_folder,
                output_gdb=output_gdb,
                run_id=run_id,
                study_area=study_area,
                buffer_distance=buffer_distance,
                rows=log_rows,
            )

            if add_to_map:
                _add_outputs_to_map(outputs, log_table)

            success_count = sum(1 for r in log_rows if r["status"] == "SUCCESS")
            failed_count = sum(1 for r in log_rows if r["status"] == "FAILED")
            qa_warning_count = sum(1 for r in log_rows if r["qa_status"] == "WARN")
            qa_failed_count = sum(1 for r in log_rows if r["qa_status"] == "FAIL")

            arcpy.AddMessage("")
            arcpy.AddMessage("=" * 72)
            arcpy.AddMessage("DOWNLOAD COMPLETE")
            arcpy.AddMessage("Successful datasets: {}".format(success_count))
            arcpy.AddMessage("Failed datasets: {}".format(failed_count))
            arcpy.AddMessage("QA warnings: {}".format(qa_warning_count))
            arcpy.AddMessage("QA failures: {}".format(qa_failed_count))
            arcpy.AddMessage("Provenance/QA table: Data_Acquisition_Log")
            arcpy.AddMessage("QA report: {}".format(report_html))
            arcpy.AddMessage("Acquisition manifest: {}".format(manifest_csv))
            arcpy.AddMessage("Output: {}".format(output_gdb))
            arcpy.AddMessage("=" * 72)

            if failed_count:
                arcpy.AddWarning(
                    "{} dataset(s) failed. See Data_Acquisition_Log.".format(
                        failed_count
                    )
                )

        finally:
            for item in reversed(temp_items):
                try:
                    if arcpy.Exists(item):
                        arcpy.management.Delete(item)
                    elif os.path.isfile(item):
                        os.remove(item)
                except Exception:
                    pass


# -----------------------------------------------------------------------------
# UI helpers
# -----------------------------------------------------------------------------

def _bool_parameter(display_name, name, default):
    p = arcpy.Parameter(
        displayName=display_name,
        name=name,
        datatype="GPBoolean",
        parameterType="Optional",
        direction="Input",
    )
    p.value = default
    return p


# -----------------------------------------------------------------------------
# Core request / geometry helpers
# -----------------------------------------------------------------------------

def _linear_value(text):
    if not text:
        return 0.0
    try:
        return float(str(text).strip().split()[0])
    except Exception:
        return 0.0


def _meters_to_map_units(spatial_reference, meters):
    """Convert meters to the map units of the target spatial reference."""
    try:
        meters_per_unit = float(spatial_reference.metersPerUnit)
        if meters_per_unit > 0:
            return float(meters) / meters_per_unit
    except Exception:
        pass
    return float(meters)


def _post_json(url, params, timeout=180, retries=4):
    data = urllib.parse.urlencode(params).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "User-Agent": "Automated-GIS-Data-Acquisition/1.0",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method="POST",
    )

    last_error = None

    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(
                request,
                timeout=timeout,
            ) as response:
                return json.loads(
                    response.read().decode("utf-8")
                )

        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            TimeoutError,
            json.JSONDecodeError,
        ) as exc:
            last_error = exc
            if attempt >= retries:
                raise
            time.sleep(2 ** attempt)

    raise last_error


def _project_feature(input_fc, output_fc, target_sr):
    source_sr = arcpy.Describe(input_fc).spatialReference

    if arcpy.Exists(output_fc):
        arcpy.management.Delete(output_fc)

    if source_sr.factoryCode == target_sr.factoryCode:
        arcpy.management.CopyFeatures(input_fc, output_fc)
        return output_fc

    transformation = ""
    try:
        transforms = arcpy.ListTransformations(source_sr, target_sr)
        if transforms:
            transformation = transforms[0]
    except Exception:
        pass

    arcpy.management.Project(
        input_fc,
        output_fc,
        target_sr,
        transformation,
    )
    return output_fc


def _extent_json(feature_class):
    extent = arcpy.Describe(feature_class).extent
    return json.dumps({
        "xmin": extent.XMin,
        "ymin": extent.YMin,
        "xmax": extent.XMax,
        "ymax": extent.YMax,
    })


def _arcgis_error(response):
    error = response.get("error", {})
    code = error.get("code", "Unknown")
    message = error.get("message", "ArcGIS REST error")
    details = error.get("details") or []
    text = "ArcGIS REST error {}: {}".format(code, message)
    if details:
        text += " | " + " | ".join(details)
    return text


# -----------------------------------------------------------------------------
# Generic ArcGIS REST vector downloader
# -----------------------------------------------------------------------------

def _download_vector_service(
    label,
    layer_url,
    service_wkid,
    aoi_native,
    input_sr,
    output_fc,
    tmp_fc,
    temp_items,
    initial_batch_size=VECTOR_BATCH_SIZE,
    use_actual_aoi_query=False,
):
    arcpy.AddMessage("")
    arcpy.AddMessage("[{}]".format(label))

    service_sr = arcpy.SpatialReference(service_wkid)
    aoi_service = tmp_fc(
        "{}_AOI".format(
            _safe_name(label)
        )
    )
    _project_feature(
        aoi_native,
        aoi_service,
        service_sr,
    )

    query_url = layer_url.rstrip("/") + "/query"

    ids_response = None

    if use_actual_aoi_query:
        try:
            with arcpy.da.SearchCursor(
                aoi_service,
                ["SHAPE@JSON"],
            ) as cursor:
                aoi_json = next(cursor)[0]

            arcpy.AddMessage(
                "{}: querying candidates with actual AOI geometry...".format(label)
            )

            ids_response = _post_json(
                query_url,
                {
                    "f": "json",
                    "where": "1=1",
                    "geometry": aoi_json,
                    "geometryType": "esriGeometryPolygon",
                    "inSR": str(service_wkid),
                    "spatialRel": "esriSpatialRelIntersects",
                    "returnIdsOnly": "true",
                },
                timeout=180,
                retries=5,
            )

            if "error" in ids_response:
                raise RuntimeError(_arcgis_error(ids_response))

        except Exception as exc:
            arcpy.AddWarning(
                "{} actual-AOI query failed. Falling back to envelope query. {}".format(
                    label,
                    exc,
                )
            )
            ids_response = None

    if ids_response is None:
        ids_response = _post_json(
            query_url,
            {
                "f": "json",
                "where": "1=1",
                "geometry": _extent_json(aoi_service),
                "geometryType": "esriGeometryEnvelope",
                "inSR": str(service_wkid),
                "spatialRel": "esriSpatialRelIntersects",
                "returnIdsOnly": "true",
            },
            timeout=180,
            retries=5,
        )

    if "error" in ids_response:
        raise RuntimeError(_arcgis_error(ids_response))

    object_ids = ids_response.get("objectIds") or []

    arcpy.AddMessage(
        "{} candidate feature(s) found.".format(len(object_ids))
    )

    if not object_ids:
        return _create_empty_output_from_service(
            layer_url,
            service_wkid,
            input_sr,
            output_fc,
        )

    batch_fcs = []
    batch_counter = [0]

    def download_batch(ids):
        response = _post_json(
            query_url,
            {
                "f": "json",
                "objectIds": ",".join(map(str, ids)),
                "outFields": "*",
                "returnGeometry": "true",
                "outSR": str(service_wkid),
                "returnTrueCurves": "false",
                "returnZ": "false",
                "returnM": "false",
            },
            timeout=300,
            retries=5,
        )

        if "error" in response:
            raise RuntimeError(_arcgis_error(response))

        batch_counter[0] += 1

        json_path = os.path.join(
            arcpy.env.scratchFolder,
            "{}_{}_{}.json".format(
                _safe_name(label),
                uuid.uuid4().hex[:6],
                batch_counter[0],
            ),
        )
        temp_items.append(json_path)

        with open(json_path, "w", encoding="utf-8") as stream:
            json.dump(response, stream)

        batch_fc = tmp_fc(
            "{}_B{}".format(
                _safe_name(label),
                batch_counter[0],
            )
        )

        arcpy.conversion.JSONToFeatures(
            json_path,
            batch_fc,
        )

        if int(arcpy.management.GetCount(batch_fc)[0]) > 0:
            batch_fcs.append(batch_fc)

        return batch_fc

    arcpy.AddMessage(
        "{} initial download batch size: {} IDs.".format(
            label,
            initial_batch_size,
        )
    )

    for initial in _chunks(object_ids, initial_batch_size):
        _adaptive_batch(
            initial,
            download_batch,
            MIN_VECTOR_BATCH_SIZE,
            label,
        )

    if not batch_fcs:
        return _create_empty_output_from_service(
            layer_url,
            service_wkid,
            input_sr,
            output_fc,
        )

    merged = tmp_fc(
        "{}_MERGED".format(_safe_name(label))
    )

    if len(batch_fcs) == 1:
        arcpy.management.CopyFeatures(
            batch_fcs[0],
            merged,
        )
    else:
        arcpy.management.Merge(
            batch_fcs,
            merged,
        )

    clipped_service = tmp_fc(
        "{}_CLIP".format(_safe_name(label))
    )

    arcpy.analysis.PairwiseClip(
        merged,
        aoi_service,
        clipped_service,
    )

    if arcpy.Exists(output_fc):
        arcpy.management.Delete(output_fc)

    _project_feature(
        clipped_service,
        output_fc,
        input_sr,
    )

    try:
        arcpy.management.RepairGeometry(
            output_fc,
            "DELETE_NULL",
        )
    except Exception:
        pass

    count = int(arcpy.management.GetCount(output_fc)[0])
    arcpy.AddMessage(
        "{} complete: {} feature(s).".format(
            label,
            count,
        )
    )

    return output_fc


def _adaptive_batch(ids, downloader, minimum_size, label):
    try:
        downloader(ids)
        return
    except Exception as exc:
        if len(ids) <= minimum_size:
            raise

        midpoint = len(ids) // 2
        left = ids[:midpoint]
        right = ids[midpoint:]

        if not left or not right:
            raise

        arcpy.AddWarning(
            "{} batch of {} IDs failed. Retrying as {} + {}. {}".format(
                label,
                len(ids),
                len(left),
                len(right),
                exc,
            )
        )

        _adaptive_batch(
            left,
            downloader,
            minimum_size,
            label,
        )
        _adaptive_batch(
            right,
            downloader,
            minimum_size,
            label,
        )


def _chunks(items, size):
    items = list(items)
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _create_empty_output_from_service(
    layer_url,
    service_wkid,
    input_sr,
    output_fc,
):
    if arcpy.Exists(output_fc):
        arcpy.management.Delete(output_fc)

    metadata = _post_json(
        layer_url,
        {"f": "json"},
        timeout=120,
        retries=3,
    )

    geometry_type = metadata.get(
        "geometryType",
        "esriGeometryPolygon",
    )

    gp_geometry = {
        "esriGeometryPoint": "POINT",
        "esriGeometryMultipoint": "MULTIPOINT",
        "esriGeometryPolyline": "POLYLINE",
        "esriGeometryPolygon": "POLYGON",
    }.get(geometry_type, "POLYGON")

    arcpy.management.CreateFeatureclass(
        os.path.dirname(output_fc),
        os.path.basename(output_fc),
        gp_geometry,
        spatial_reference=input_sr,
    )

    for field in metadata.get("fields") or []:
        name = field.get("name")
        field_type = field.get("type")

        if not name or field_type in (
            "esriFieldTypeOID",
            "esriFieldTypeGeometry",
        ):
            continue

        mapped = {
            "esriFieldTypeString": "TEXT",
            "esriFieldTypeSmallInteger": "SHORT",
            "esriFieldTypeInteger": "LONG",
            "esriFieldTypeSingle": "FLOAT",
            "esriFieldTypeDouble": "DOUBLE",
            "esriFieldTypeDate": "DATE",
            "esriFieldTypeGUID": "GUID",
        }.get(field_type)

        if not mapped:
            continue

        kwargs = {}
        if mapped == "TEXT":
            kwargs["field_length"] = min(
                int(field.get("length") or 255),
                2000,
            )

        try:
            arcpy.management.AddField(
                output_fc,
                name,
                mapped,
                **kwargs
            )
        except Exception:
            pass

    arcpy.AddMessage(
        "No intersecting features. Created empty output."
    )

    return output_fc


# -----------------------------------------------------------------------------
# Generic ArcGIS ImageServer downloader
# -----------------------------------------------------------------------------

def _download_image_service(
    label,
    image_url,
    aoi_native,
    input_sr,
    output_raster,
    tmp_fc,
    where_clause=None,
    cell_size=None,
    resampling="NEAREST",
):
    """
    Download an ArcGIS ImageServer raster to the AOI.

    The function first attempts a single clip. If the image service rejects
    the request because its row/column export limit is exceeded, the AOI is
    automatically subdivided into smaller tiles. Each tile is downloaded
    separately, then mosaicked and projected to the Study Area CRS.

    This makes large-corridor projects resilient to ImageServer export limits
    such as USGS 3DEP's 8000 x 8000 maximum export size.
    """
    arcpy.AddMessage("")
    arcpy.AddMessage("[{}]".format(label))

    layer_name = "{}_{}".format(
        _safe_name(label),
        uuid.uuid4().hex[:6],
    )

    kwargs = {}

    if cell_size:
        kwargs["cell_size"] = cell_size

    if where_clause:
        kwargs["where_clause"] = where_clause

    arcpy.AddMessage("Connecting to image service...")

    try:
        arcpy.management.MakeImageServerLayer(
            image_url,
            layer_name,
            **kwargs
        )
    except TypeError:
        arcpy.management.MakeImageServerLayer(
            image_url,
            layer_name,
            "#",
            "#",
            "DEFAULT",
            "#",
            "#",
            "#",
            cell_size if cell_size else "#",
            where_clause if where_clause else "#",
        )

    local_temp_items = []

    def register(path):
        local_temp_items.append(path)
        return path

    def delete_if_exists(path):
        try:
            if arcpy.Exists(path):
                arcpy.management.Delete(path)
        except Exception:
            pass

    def is_size_limit_error(exc):
        message = str(exc).lower()
        return (
            "size limits of the image service" in message
            or "maximum number of rows and columns" in message
            or "8000 and 8000" in message
            or "exceeds the maximum" in message
        )

    def rectangle_fc(extent, spatial_reference, name):
        path = register(
            os.path.join(
                arcpy.env.scratchGDB,
                "{}_{}_{}".format(
                    _safe_name(label),
                    name,
                    uuid.uuid4().hex[:6],
                ),
            )
        )

        array = arcpy.Array([
            arcpy.Point(extent.XMin, extent.YMin),
            arcpy.Point(extent.XMin, extent.YMax),
            arcpy.Point(extent.XMax, extent.YMax),
            arcpy.Point(extent.XMax, extent.YMin),
            arcpy.Point(extent.XMin, extent.YMin),
        ])

        polygon = arcpy.Polygon(
            array,
            spatial_reference,
        )

        arcpy.management.CopyFeatures(
            [polygon],
            path,
        )

        return path

    def split_extent(extent):
        mid_x = (extent.XMin + extent.XMax) / 2.0
        mid_y = (extent.YMin + extent.YMax) / 2.0

        return [
            arcpy.Extent(
                extent.XMin,
                extent.YMin,
                mid_x,
                mid_y,
            ),
            arcpy.Extent(
                mid_x,
                extent.YMin,
                extent.XMax,
                mid_y,
            ),
            arcpy.Extent(
                extent.XMin,
                mid_y,
                mid_x,
                extent.YMax,
            ),
            arcpy.Extent(
                mid_x,
                mid_y,
                extent.XMax,
                extent.YMax,
            ),
        ]

    def clip_tile(extent, depth=0, max_depth=8):
        tile_rect = rectangle_fc(
            extent,
            input_sr,
            "RECT_D{}".format(depth),
        )

        tile_aoi = register(
            os.path.join(
                arcpy.env.scratchGDB,
                "{}_AOI_D{}_{}".format(
                    _safe_name(label),
                    depth,
                    uuid.uuid4().hex[:6],
                ),
            )
        )

        arcpy.analysis.PairwiseClip(
            aoi_native,
            tile_rect,
            tile_aoi,
        )

        if int(arcpy.management.GetCount(tile_aoi)[0]) == 0:
            return []

        tile_raster = register(
            os.path.join(
                arcpy.env.scratchGDB,
                "{}_TILE_D{}_{}".format(
                    _safe_name(label),
                    depth,
                    uuid.uuid4().hex[:6],
                ),
            )
        )

        try:
            arcpy.management.Clip(
                layer_name,
                "#",
                tile_raster,
                tile_aoi,
                "#",
                "ClippingGeometry",
                "NO_MAINTAIN_EXTENT",
            )

            arcpy.AddMessage(
                "{} tile downloaded (level {}).".format(
                    label,
                    depth,
                )
            )

            return [tile_raster]

        except Exception as exc:
            delete_if_exists(tile_raster)

            if not is_size_limit_error(exc) or depth >= max_depth:
                raise

            arcpy.AddWarning(
                "{} tile exceeded image-service size limits. "
                "Subdividing level {} tile into four smaller tiles...".format(
                    label,
                    depth,
                )
            )

            rasters = []

            for child_extent in split_extent(extent):
                rasters.extend(
                    clip_tile(
                        child_extent,
                        depth=depth + 1,
                        max_depth=max_depth,
                    )
                )

            return rasters

    temp_clip = register(
        os.path.join(
            arcpy.env.scratchGDB,
            "{}_CLIP_{}".format(
                _safe_name(label),
                uuid.uuid4().hex[:6],
            ),
        )
    )

    source_raster = None

    try:
        arcpy.AddMessage("Clipping image service to AOI...")

        try:
            arcpy.management.Clip(
                layer_name,
                "#",
                temp_clip,
                aoi_native,
                "#",
                "ClippingGeometry",
                "NO_MAINTAIN_EXTENT",
            )

            source_raster = temp_clip

        except Exception as exc:
            if not is_size_limit_error(exc):
                raise

            delete_if_exists(temp_clip)

            arcpy.AddWarning(
                "{} exceeds the image service export-size limit. "
                "Switching to automatic raster tiling + mosaic...".format(
                    label
                )
            )

            aoi_extent = arcpy.Describe(aoi_native).extent

            tile_rasters = clip_tile(
                aoi_extent,
                depth=0,
                max_depth=8,
            )

            if not tile_rasters:
                raise RuntimeError(
                    "{} produced no raster tiles.".format(label)
                )

            arcpy.AddMessage(
                "Mosaicking {} {} tile(s)...".format(
                    len(tile_rasters),
                    label,
                )
            )

            mosaic_raster = register(
                os.path.join(
                    arcpy.env.scratchGDB,
                    "{}_MOSAIC_{}".format(
                        _safe_name(label),
                        uuid.uuid4().hex[:6],
                    ),
                )
            )

            arcpy.management.CopyRaster(
                tile_rasters[0],
                mosaic_raster,
            )

            if len(tile_rasters) > 1:
                arcpy.management.Mosaic(
                    tile_rasters[1:],
                    mosaic_raster,
                )

            source_raster = mosaic_raster

        if arcpy.Exists(output_raster):
            arcpy.management.Delete(output_raster)

        source_sr = arcpy.Describe(
            source_raster
        ).spatialReference

        same_sr = (
            source_sr
            and input_sr
            and source_sr.factoryCode
            and input_sr.factoryCode
            and source_sr.factoryCode == input_sr.factoryCode
        )

        if same_sr:
            arcpy.management.CopyRaster(
                source_raster,
                output_raster,
            )

        else:
            arcpy.AddMessage(
                "Projecting raster to Study Area coordinate system..."
            )

            arcpy.management.ProjectRaster(
                source_raster,
                output_raster,
                input_sr,
                resampling,
                cell_size if cell_size else "#",
            )

        arcpy.AddMessage(
            "{} complete.".format(label)
        )

        return output_raster

    finally:
        try:
            if arcpy.Exists(layer_name):
                arcpy.management.Delete(layer_name)
        except Exception:
            pass

        for item in reversed(local_temp_items):
            delete_if_exists(item)


# -----------------------------------------------------------------------------
# Logging / output handling
# -----------------------------------------------------------------------------

def _source_metadata(dataset):
    """Return authoritative source provenance for a dataset label."""
    if dataset == "FEMA Floodplain":
        return (
            "Federal Emergency Management Agency (FEMA)",
            FEMA_FLOOD_URL,
            None,
        )

    if dataset == "NWI Wetlands":
        return (
            "U.S. Fish & Wildlife Service (USFWS)",
            NWI_WETLANDS_URL,
            None,
        )

    if dataset == "NHD Flowline":
        return (
            "U.S. Geological Survey (USGS)",
            NHD_FLOWLINE_URL,
            None,
        )

    if dataset == "NHD Waterbody":
        return (
            "U.S. Geological Survey (USGS)",
            NHD_WATERBODY_URL,
            None,
        )

    if dataset == "Census States":
        return (
            "U.S. Census Bureau",
            CENSUS_STATES_URL,
            None,
        )

    if dataset == "Census Counties":
        return (
            "U.S. Census Bureau",
            CENSUS_COUNTIES_URL,
            None,
        )

    if dataset.startswith("NLCD Land Cover "):
        year = _trailing_year(dataset)
        return (
            "U.S. Geological Survey (USGS)",
            NLCD_IMAGE_URL,
            year,
        )

    if dataset == "USGS 3DEP Elevation":
        return (
            "U.S. Geological Survey (USGS)",
            USGS_3DEP_URL,
            None,
        )

    if dataset == "USGS 3DEP DEM 10 m":
        return (
            "U.S. Geological Survey (USGS)",
            USGS_3DEP_URL,
            None,
        )

    if dataset.startswith("USDA CDL "):
        year = _trailing_year(dataset)
        return (
            "USDA National Agricultural Statistics Service (NASS)",
            USDA_CDL_URL,
            year,
        )

    return ("", "", None)


def _trailing_year(text):
    try:
        value = str(text).strip().split()[-1]
        year = int(value)
        if 1900 <= year <= 2200:
            return year
    except Exception:
        pass

    return None


def _qa_defaults():
    return {
        "qa_status": "PASS",
        "qa_message": "",
        "output_type": "",
        "count": "",
        "feature_count": None,
        "raster_rows": None,
        "raster_cols": None,
        "cell_size_x": None,
        "cell_size_y": None,
        "band_count": None,
        "pixel_type": "",
        "spatial_ref": "",
        "wkid": None,
    }


def _append_qa_message(meta, message):
    if not message:
        return

    if meta["qa_message"]:
        meta["qa_message"] += " | "

    meta["qa_message"] += message


def _set_qa_warning(meta, message):
    if meta["qa_status"] == "PASS":
        meta["qa_status"] = "WARN"

    _append_qa_message(meta, message)


def _inspect_output(result):
    """Inspect a completed output and return standardized QA metadata."""
    meta = _qa_defaults()

    if not result or not arcpy.Exists(result):
        meta["qa_status"] = "FAIL"
        meta["qa_message"] = "Expected output does not exist."
        return meta

    try:
        desc = arcpy.Describe(result)
    except Exception as exc:
        meta["qa_status"] = "WARN"
        meta["qa_message"] = "Could not describe output: {}".format(exc)
        return meta

    # Spatial reference QA
    try:
        sr = desc.spatialReference
        if sr:
            meta["spatial_ref"] = sr.name or ""
            factory_code = int(sr.factoryCode or 0)
            meta["wkid"] = factory_code if factory_code > 0 else None

            if not sr.name or sr.name == "Unknown":
                _set_qa_warning(
                    meta,
                    "Output coordinate system is unknown.",
                )
        else:
            _set_qa_warning(
                meta,
                "Output coordinate system could not be read.",
            )
    except Exception as exc:
        _set_qa_warning(
            meta,
            "Spatial reference QA could not be completed: {}".format(exc),
        )

    # Vector QA
    if hasattr(desc, "shapeType"):
        meta["output_type"] = "FeatureClass ({})".format(
            desc.shapeType
        )

        try:
            feature_count = int(
                arcpy.management.GetCount(result)[0]
            )
            meta["feature_count"] = feature_count
            meta["count"] = str(feature_count)

            if feature_count == 0:
                _set_qa_warning(
                    meta,
                    "Output contains 0 features.",
                )
        except Exception as exc:
            _set_qa_warning(
                meta,
                "Feature count could not be read: {}".format(exc),
            )

        return meta

    # Raster QA
    meta["output_type"] = "Raster"
    meta["count"] = "Raster"

    try:
        raster = arcpy.Raster(result)

        meta["raster_rows"] = int(raster.height)
        meta["raster_cols"] = int(raster.width)
        meta["cell_size_x"] = float(raster.meanCellWidth)
        meta["cell_size_y"] = float(raster.meanCellHeight)
        meta["band_count"] = int(raster.bandCount)
        meta["pixel_type"] = str(raster.pixelType or "")

        if meta["raster_rows"] <= 0 or meta["raster_cols"] <= 0:
            meta["qa_status"] = "FAIL"
            _append_qa_message(
                meta,
                "Raster has invalid row/column dimensions.",
            )

        if meta["cell_size_x"] <= 0 or meta["cell_size_y"] <= 0:
            meta["qa_status"] = "FAIL"
            _append_qa_message(
                meta,
                "Raster has invalid cell size.",
            )

    except Exception as exc:
        _set_qa_warning(
            meta,
            "Raster properties could not be fully inspected: {}".format(exc),
        )

    return meta


def _run_logged(dataset, log_rows, operation, outputs):
    start = datetime.datetime.now()

    source_agency, source_url, requested_year = _source_metadata(dataset)

    try:
        result = operation()

        end = datetime.datetime.now()
        elapsed = (end - start).total_seconds()

        qa = _inspect_output(result)

        if qa["qa_status"] in ("WARN", "FAIL"):
            arcpy.AddWarning(
                "{} QA {}: {}".format(
                    dataset,
                    qa["qa_status"],
                    qa["qa_message"] or "Review output metadata.",
                )
            )

        log_rows.append({
            "dataset": dataset,
            "status": "SUCCESS",
            "qa_status": qa["qa_status"],
            "source_agency": source_agency,
            "source_url": source_url,
            "requested_year": requested_year,
            "output": result or "",
            "output_type": qa["output_type"],
            "count": qa["count"],
            "feature_count": qa["feature_count"],
            "raster_rows": qa["raster_rows"],
            "raster_cols": qa["raster_cols"],
            "cell_size_x": qa["cell_size_x"],
            "cell_size_y": qa["cell_size_y"],
            "band_count": qa["band_count"],
            "pixel_type": qa["pixel_type"],
            "spatial_ref": qa["spatial_ref"],
            "wkid": qa["wkid"],
            "seconds": elapsed,
            "message": "",
            "qa_message": qa["qa_message"],
            "acquired_utc": datetime.datetime.utcnow(),
        })

        if result:
            outputs.append(result)

    except Exception as exc:
        elapsed = (
            datetime.datetime.now() - start
        ).total_seconds()

        message = str(exc)

        arcpy.AddWarning(
            "{} FAILED: {}".format(
                dataset,
                message,
            )
        )

        log_rows.append({
            "dataset": dataset,
            "status": "FAILED",
            "qa_status": "NOT_RUN",
            "source_agency": source_agency,
            "source_url": source_url,
            "requested_year": requested_year,
            "output": "",
            "output_type": "",
            "count": "",
            "feature_count": None,
            "raster_rows": None,
            "raster_cols": None,
            "cell_size_x": None,
            "cell_size_y": None,
            "band_count": None,
            "pixel_type": "",
            "spatial_ref": "",
            "wkid": None,
            "seconds": elapsed,
            "message": message[:2000],
            "qa_message": "Output QA was not run because acquisition failed.",
            "acquired_utc": datetime.datetime.utcnow(),
        })


def _write_log(output_table, rows, run_id):
    """Create a dataset-level provenance and QA table for the current run."""
    if arcpy.Exists(output_table):
        arcpy.management.Delete(output_table)

    arcpy.management.CreateTable(
        os.path.dirname(output_table),
        os.path.basename(output_table),
    )

    fields = [
        ("RUN_ID", "TEXT", 16),
        ("DATASET", "TEXT", 100),
        ("STATUS", "TEXT", 20),
        ("QA_STATUS", "TEXT", 20),
        ("SOURCE_AGENCY", "TEXT", 150),
        ("SOURCE_URL", "TEXT", 1000),
        ("REQUEST_YEAR", "LONG", None),
        ("OUTPUT", "TEXT", 500),
        ("OUTPUT_TYPE", "TEXT", 50),
        ("COUNT", "TEXT", 50),
        ("FEATURE_COUNT", "LONG", None),
        ("RASTER_ROWS", "LONG", None),
        ("RASTER_COLS", "LONG", None),
        ("CELL_SIZE_X", "DOUBLE", None),
        ("CELL_SIZE_Y", "DOUBLE", None),
        ("BAND_COUNT", "LONG", None),
        ("PIXEL_TYPE", "TEXT", 50),
        ("SPATIAL_REF", "TEXT", 255),
        ("WKID", "LONG", None),
        ("RUNTIME_SEC", "DOUBLE", None),
        ("MESSAGE", "TEXT", 2000),
        ("QA_MESSAGE", "TEXT", 1000),
        ("ACQUIRED_UTC", "DATE", None),
        ("RUN_DATE", "DATE", None),
    ]

    for name, field_type, length in fields:
        kwargs = {}

        if length:
            kwargs["field_length"] = length

        arcpy.management.AddField(
            output_table,
            name,
            field_type,
            **kwargs
        )

    insert_fields = [
        "RUN_ID",
        "DATASET",
        "STATUS",
        "QA_STATUS",
        "SOURCE_AGENCY",
        "SOURCE_URL",
        "REQUEST_YEAR",
        "OUTPUT",
        "OUTPUT_TYPE",
        "COUNT",
        "FEATURE_COUNT",
        "RASTER_ROWS",
        "RASTER_COLS",
        "CELL_SIZE_X",
        "CELL_SIZE_Y",
        "BAND_COUNT",
        "PIXEL_TYPE",
        "SPATIAL_REF",
        "WKID",
        "RUNTIME_SEC",
        "MESSAGE",
        "QA_MESSAGE",
        "ACQUIRED_UTC",
        "RUN_DATE",
    ]

    with arcpy.da.InsertCursor(
        output_table,
        insert_fields,
    ) as cursor:
        for row in rows:
            cursor.insertRow([
                run_id,
                row["dataset"],
                row["status"],
                row["qa_status"],
                row["source_agency"],
                row["source_url"],
                row["requested_year"],
                row["output"],
                row["output_type"],
                row["count"],
                row["feature_count"],
                row["raster_rows"],
                row["raster_cols"],
                row["cell_size_x"],
                row["cell_size_y"],
                row["band_count"],
                row["pixel_type"],
                row["spatial_ref"],
                row["wkid"],
                row["seconds"],
                row["message"],
                row["qa_message"],
                row["acquired_utc"],
                datetime.datetime.now(),
            ])



def _report_value(value):
    if value is None:
        return ""
    return str(value)


def _report_count_detail(row):
    if row.get("feature_count") is not None:
        return "{:,} features".format(int(row["feature_count"]))

    if (
        row.get("raster_rows") is not None
        and row.get("raster_cols") is not None
    ):
        detail = "{:,} x {:,} cells".format(
            int(row["raster_cols"]),
            int(row["raster_rows"]),
        )

        if (
            row.get("cell_size_x") is not None
            and row.get("cell_size_y") is not None
        ):
            detail += " | cell {:.4g} x {:.4g}".format(
                float(row["cell_size_x"]),
                float(row["cell_size_y"]),
            )

        return detail

    return row.get("count") or ""


def _write_run_reports(
    output_folder,
    output_gdb,
    run_id,
    study_area,
    buffer_distance,
    rows,
):
    """
    Write a human-readable HTML QA report and machine-readable CSV manifest.

    Both files summarize the same dataset-level provenance and QA information
    stored in Data_Acquisition_Log.
    """
    report_html = os.path.join(
        output_folder,
        "Data_Acquisition_Report.html",
    )
    manifest_csv = os.path.join(
        output_folder,
        "Data_Acquisition_Manifest.csv",
    )

    csv_fields = [
        "RUN_ID",
        "DATASET",
        "STATUS",
        "QA_STATUS",
        "SOURCE_AGENCY",
        "SOURCE_URL",
        "REQUEST_YEAR",
        "OUTPUT",
        "OUTPUT_TYPE",
        "COUNT_DETAIL",
        "FEATURE_COUNT",
        "RASTER_ROWS",
        "RASTER_COLS",
        "CELL_SIZE_X",
        "CELL_SIZE_Y",
        "BAND_COUNT",
        "PIXEL_TYPE",
        "SPATIAL_REF",
        "WKID",
        "RUNTIME_SEC",
        "MESSAGE",
        "QA_MESSAGE",
        "ACQUIRED_UTC",
    ]

    with open(
        manifest_csv,
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=csv_fields,
        )
        writer.writeheader()

        for row in rows:
            writer.writerow({
                "RUN_ID": run_id,
                "DATASET": row.get("dataset", ""),
                "STATUS": row.get("status", ""),
                "QA_STATUS": row.get("qa_status", ""),
                "SOURCE_AGENCY": row.get("source_agency", ""),
                "SOURCE_URL": row.get("source_url", ""),
                "REQUEST_YEAR": _report_value(row.get("requested_year")),
                "OUTPUT": row.get("output", ""),
                "OUTPUT_TYPE": row.get("output_type", ""),
                "COUNT_DETAIL": _report_count_detail(row),
                "FEATURE_COUNT": _report_value(row.get("feature_count")),
                "RASTER_ROWS": _report_value(row.get("raster_rows")),
                "RASTER_COLS": _report_value(row.get("raster_cols")),
                "CELL_SIZE_X": _report_value(row.get("cell_size_x")),
                "CELL_SIZE_Y": _report_value(row.get("cell_size_y")),
                "BAND_COUNT": _report_value(row.get("band_count")),
                "PIXEL_TYPE": row.get("pixel_type", ""),
                "SPATIAL_REF": row.get("spatial_ref", ""),
                "WKID": _report_value(row.get("wkid")),
                "RUNTIME_SEC": "{:.2f}".format(
                    float(row.get("seconds") or 0)
                ),
                "MESSAGE": row.get("message", ""),
                "QA_MESSAGE": row.get("qa_message", ""),
                "ACQUIRED_UTC": (
                    row["acquired_utc"].isoformat(sep=" ")
                    if row.get("acquired_utc")
                    else ""
                ),
            })

    success_count = sum(
        1 for row in rows
        if row.get("status") == "SUCCESS"
    )
    failed_count = sum(
        1 for row in rows
        if row.get("status") == "FAILED"
    )
    qa_warn_count = sum(
        1 for row in rows
        if row.get("qa_status") == "WARN"
    )
    qa_fail_count = sum(
        1 for row in rows
        if row.get("qa_status") == "FAIL"
    )

    generated = datetime.datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    html_rows = []

    for row in rows:
        status = row.get("status", "")
        qa_status = row.get("qa_status", "")

        status_class = (
            "success" if status == "SUCCESS" else "failed"
        )

        if qa_status == "PASS":
            qa_class = "success"
        elif qa_status == "WARN":
            qa_class = "warning"
        elif qa_status == "FAIL":
            qa_class = "failed"
        else:
            qa_class = "neutral"

        source_url = row.get("source_url", "")
        source_cell = html.escape(
            row.get("source_agency", "") or ""
        )

        if source_url:
            source_cell += (
                '<br><a href="{0}">Service</a>'.format(
                    html.escape(
                        source_url,
                        quote=True,
                    )
                )
            )

        note = row.get("message", "") or row.get(
            "qa_message",
            "",
        )

        html_rows.append(
            """
            <tr>
              <td>{dataset}</td>
              <td><span class="badge {status_class}">{status}</span></td>
              <td><span class="badge {qa_class}">{qa}</span></td>
              <td>{source}</td>
              <td>{year}</td>
              <td>{output_type}</td>
              <td>{detail}</td>
              <td>{crs}</td>
              <td>{runtime}</td>
              <td>{note}</td>
            </tr>
            """.format(
                dataset=html.escape(
                    row.get("dataset", "") or ""
                ),
                status_class=status_class,
                status=html.escape(status),
                qa_class=qa_class,
                qa=html.escape(qa_status),
                source=source_cell,
                year=html.escape(
                    _report_value(
                        row.get("requested_year")
                    )
                ),
                output_type=html.escape(
                    row.get("output_type", "") or ""
                ),
                detail=html.escape(
                    _report_count_detail(row)
                ),
                crs=html.escape(
                    row.get("spatial_ref", "") or ""
                ),
                runtime="{:.1f}s".format(
                    float(row.get("seconds") or 0)
                ),
                note=html.escape(note or ""),
            )
        )

    page = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Automated GIS Data Acquisition Report</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body {{
    font-family: Arial, Helvetica, sans-serif;
    margin: 32px;
    color: #1f2937;
    background: #ffffff;
}}
h1 {{
    margin-bottom: 4px;
}}
.subtitle {{
    color: #4b5563;
    margin-top: 0;
}}
.meta {{
    background: #f8fafc;
    border: 1px solid #e5e7eb;
    padding: 14px 18px;
    border-radius: 8px;
    margin: 20px 0;
}}
.cards {{
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    margin: 18px 0 24px;
}}
.card {{
    min-width: 150px;
    padding: 14px 18px;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
}}
.card strong {{
    display: block;
    font-size: 24px;
}}
table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
}}
th, td {{
    border: 1px solid #e5e7eb;
    padding: 8px;
    text-align: left;
    vertical-align: top;
}}
th {{
    background: #f3f4f6;
}}
.badge {{
    display: inline-block;
    padding: 3px 7px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 700;
}}
.success {{
    background: #dcfce7;
    color: #166534;
}}
.warning {{
    background: #fef3c7;
    color: #92400e;
}}
.failed {{
    background: #fee2e2;
    color: #991b1b;
}}
.neutral {{
    background: #e5e7eb;
    color: #374151;
}}
.footer {{
    color: #6b7280;
    font-size: 12px;
    margin-top: 24px;
}}
a {{
    color: #2563eb;
}}
</style>
</head>
<body>

<h1>Automated GIS Data Acquisition</h1>
<p class="subtitle">Acquisition, provenance, and QA report</p>

<div class="meta">
<strong>Run ID:</strong> {run_id}<br>
<strong>Generated:</strong> {generated}<br>
<strong>Study Area:</strong> {study_area}<br>
<strong>Buffer:</strong> {buffer_distance}<br>
<strong>Output Geodatabase:</strong> {output_gdb}
</div>

<div class="cards">
<div class="card"><strong>{success}</strong>Successful</div>
<div class="card"><strong>{failed}</strong>Failed</div>
<div class="card"><strong>{warn}</strong>QA Warnings</div>
<div class="card"><strong>{qa_fail}</strong>QA Failures</div>
</div>

<table>
<thead>
<tr>
<th>Dataset</th>
<th>Status</th>
<th>QA</th>
<th>Source</th>
<th>Year</th>
<th>Output Type</th>
<th>Feature/Raster Detail</th>
<th>CRS</th>
<th>Runtime</th>
<th>Message</th>
</tr>
</thead>
<tbody>
{rows}
</tbody>
</table>

<p class="footer">
Dinesh Shrestha — GIS Automation &amp; Spatial Analysis Consultant |
ArcGIS Pro • Python • ArcPy • Data Engineering<br>
dinesh.shrestha015@gmail.com |
dineshrestha.github.io
</p>

</body>
</html>
""".format(
        run_id=html.escape(run_id),
        generated=html.escape(generated),
        study_area=html.escape(
            study_area or ""
        ),
        buffer_distance=html.escape(
            buffer_distance or ""
        ),
        output_gdb=html.escape(
            output_gdb or ""
        ),
        success=success_count,
        failed=failed_count,
        warn=qa_warn_count,
        qa_fail=qa_fail_count,
        rows="\n".join(html_rows),
    )

    with open(
        report_html,
        "w",
        encoding="utf-8",
    ) as handle:
        handle.write(page)

    arcpy.AddMessage(
        "HTML QA report created: {}".format(
            report_html
        )
    )
    arcpy.AddMessage(
        "CSV acquisition manifest created: {}".format(
            manifest_csv
        )
    )

    return report_html, manifest_csv


def _add_outputs_to_map(outputs, log_table):
    try:
        project = arcpy.mp.ArcGISProject("CURRENT")
        active_map = project.activeMap

        if not active_map:
            return

        for output in outputs:
            try:
                if arcpy.Exists(output):
                    active_map.addDataFromPath(output)
            except Exception:
                pass

        try:
            if arcpy.Exists(log_table):
                active_map.addTable(
                    arcpy.mp.Table(log_table)
                )
        except Exception:
            pass

    except Exception:
        pass


def _safe_name(text):
    cleaned = []
    for char in str(text):
        if char.isalnum() or char == "_":
            cleaned.append(char)
        else:
            cleaned.append("_")

    name = "".join(cleaned).strip("_")

    while "__" in name:
        name = name.replace("__", "_")

    return name[:45] or "dataset"
