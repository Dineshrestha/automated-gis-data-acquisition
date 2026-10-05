# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# Dinesh Shrestha
# GIS Automation & Spatial Analysis Consultant
# ArcGIS Pro • Python • ArcPy • Data Engineering
# email: dinesh.shrestha015@gmail.com
# Portfolio: dineshrestha.github.io
# -----------------------------------------------------------------------------
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
    - Acquisition log written to the output geodatabase
"""

import arcpy
import datetime
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
            _write_log(log_table, log_rows)

            if add_to_map:
                _add_outputs_to_map(outputs, log_table)

            success_count = sum(1 for r in log_rows if r["status"] == "SUCCESS")
            failed_count = sum(1 for r in log_rows if r["status"] == "FAILED")

            arcpy.AddMessage("")
            arcpy.AddMessage("=" * 72)
            arcpy.AddMessage("DOWNLOAD COMPLETE")
            arcpy.AddMessage("Successful datasets: {}".format(success_count))
            arcpy.AddMessage("Failed datasets: {}".format(failed_count))
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

    for initial in _chunks(object_ids, VECTOR_BATCH_SIZE):
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

    arcpy.AddMessage(
        "Connecting to image service..."
    )

    try:
        arcpy.management.MakeImageServerLayer(
            image_url,
            layer_name,
            **kwargs
        )
    except TypeError:
        # Compatibility fallback for ArcGIS Pro builds that do not accept
        # keyword arguments for all optional MakeImageServerLayer parameters.
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

    temp_clip = os.path.join(
        arcpy.env.scratchGDB,
        "{}_CLIP_{}".format(
            _safe_name(label),
            uuid.uuid4().hex[:6],
        ),
    )

    try:
        arcpy.AddMessage(
            "Clipping image service to AOI..."
        )

        arcpy.management.Clip(
            layer_name,
            "#",
            temp_clip,
            aoi_native,
            "#",
            "ClippingGeometry",
            "NO_MAINTAIN_EXTENT",
        )

        if arcpy.Exists(output_raster):
            arcpy.management.Delete(output_raster)

        source_sr = arcpy.Describe(temp_clip).spatialReference

        same_sr = (
            source_sr
            and input_sr
            and source_sr.factoryCode
            and input_sr.factoryCode
            and source_sr.factoryCode == input_sr.factoryCode
        )

        if same_sr:
            arcpy.management.CopyRaster(
                temp_clip,
                output_raster,
            )
        else:
            arcpy.AddMessage(
                "Projecting raster to Study Area coordinate system..."
            )
            arcpy.management.ProjectRaster(
                temp_clip,
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

        try:
            if arcpy.Exists(temp_clip):
                arcpy.management.Delete(temp_clip)
        except Exception:
            pass


# -----------------------------------------------------------------------------
# Logging / output handling
# -----------------------------------------------------------------------------

def _run_logged(dataset, log_rows, operation, outputs):
    start = datetime.datetime.now()

    try:
        result = operation()

        elapsed = (
            datetime.datetime.now() - start
        ).total_seconds()

        count_text = ""

        try:
            desc = arcpy.Describe(result)
            if hasattr(desc, "shapeType"):
                count_text = str(
                    int(arcpy.management.GetCount(result)[0])
                )
            else:
                count_text = "Raster"
        except Exception:
            count_text = ""

        log_rows.append({
            "dataset": dataset,
            "status": "SUCCESS",
            "output": result or "",
            "count": count_text,
            "seconds": elapsed,
            "message": "",
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
            "output": "",
            "count": "",
            "seconds": elapsed,
            "message": message[:2000],
        })


def _write_log(output_table, rows):
    if arcpy.Exists(output_table):
        arcpy.management.Delete(output_table)

    arcpy.management.CreateTable(
        os.path.dirname(output_table),
        os.path.basename(output_table),
    )

    fields = [
        ("DATASET", "TEXT", 100),
        ("STATUS", "TEXT", 20),
        ("OUTPUT", "TEXT", 500),
        ("COUNT", "TEXT", 50),
        ("RUNTIME_SEC", "DOUBLE", None),
        ("MESSAGE", "TEXT", 2000),
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

    with arcpy.da.InsertCursor(
        output_table,
        [
            "DATASET",
            "STATUS",
            "OUTPUT",
            "COUNT",
            "RUNTIME_SEC",
            "MESSAGE",
            "RUN_DATE",
        ],
    ) as cursor:
        for row in rows:
            cursor.insertRow([
                row["dataset"],
                row["status"],
                row["output"],
                row["count"],
                row["seconds"],
                row["message"],
                datetime.datetime.now(),
            ])


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
