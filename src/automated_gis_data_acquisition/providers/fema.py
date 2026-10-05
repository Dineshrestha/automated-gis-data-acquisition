# -----------------------------------------------------------------------------
# Dinesh Shrestha
# GIS Automation & Spatial Analysis Consultant
# ArcGIS Pro • Python • ArcPy • Data Engineering
# email: dinesh.shrestha015@gmail.com
# Portfolio: dineshrestha.github.io
# -----------------------------------------------------------------------------

import os
import uuid
from collections import defaultdict

import arcpy

from automated_gis_data_acquisition.core.schema import field_lookup


FEMA_LAYER_URL = (
    "https://hazards.fema.gov/arcgis/rest/services/"
    "public/NFHL/MapServer/28"
)

FEMA_QUERY_URL = FEMA_LAYER_URL + "/query"

FEMA_SR_WKID = 4269  # GCS NAD 1983

DEFAULT_BATCH_SIZE = 250
MIN_BATCH_SIZE = 10


FLOOD_FILTERS = [
    "All FEMA Flood Zones",
    "SFHA / 1% Annual Chance (100-year)",
    "0.2% Annual Chance (500-year)",
    "Regulatory Floodway",
    "Custom SQL",
]


def filter_flood_hazards(
    input_fc,
    output_fc,
    filter_name,
    custom_sql=None,
):
    """
    Filter downloaded FEMA NFHL flood-hazard polygons.

    Filtering is performed locally after download so the workflow does
    not depend on database-specific SQL behavior in FEMA's REST service.
    """
    if filter_name == "All FEMA Flood Zones":
        arcpy.management.CopyFeatures(
            input_fc,
            output_fc,
        )
        return output_fc

    fields = field_lookup(input_fc)

    if filter_name == "Custom SQL":
        layer_name = "fema_custom_{}".format(
            uuid.uuid4().hex[:8]
        )

        try:
            arcpy.management.MakeFeatureLayer(
                input_fc,
                layer_name,
                custom_sql,
            )

            arcpy.management.CopyFeatures(
                layer_name,
                output_fc,
            )

        finally:
            if arcpy.Exists(layer_name):
                arcpy.management.Delete(layer_name)

        return output_fc

    # Copy first, then remove records that do not match.
    # This avoids reliance on server/database text SQL behavior.
    arcpy.management.CopyFeatures(
        input_fc,
        output_fc,
    )

    fld_zone = fields.get("FLD_ZONE")
    zone_subty = fields.get("ZONE_SUBTY")
    sfha_tf = fields.get("SFHA_TF")
    floodway = fields.get("FLOODWAY")

    required = {
        "SFHA / 1% Annual Chance (100-year)": [
            sfha_tf
        ],
        "0.2% Annual Chance (500-year)": [
            zone_subty
        ],
        "Regulatory Floodway": [
            zone_subty or floodway
        ],
    }

    if (
        filter_name in required
        and not all(required[filter_name])
    ):
        raise RuntimeError(
            "FEMA service schema does not contain the field "
            "required for '{}' filtering.".format(
                filter_name
            )
        )

    cursor_fields = []

    for field_name in (
        fld_zone,
        zone_subty,
        sfha_tf,
        floodway,
    ):
        if (
            field_name
            and field_name not in cursor_fields
        ):
            cursor_fields.append(field_name)

    index = {
        name.upper(): i
        for i, name in enumerate(cursor_fields)
    }

    def value(row, logical_name):
        actual = fields.get(logical_name)

        if not actual:
            return ""

        current_value = row[
            index[actual.upper()]
        ]

        if current_value is None:
            return ""

        return str(current_value).strip().upper()

    with arcpy.da.UpdateCursor(
        output_fc,
        cursor_fields,
    ) as cursor:

        for row in cursor:

            flood_zone = value(
                row,
                "FLD_ZONE",
            )

            zone_subtype = value(
                row,
                "ZONE_SUBTY",
            )

            sfha = value(
                row,
                "SFHA_TF",
            )

            floodway_value = value(
                row,
                "FLOODWAY",
            )

            keep = True

            if (
                filter_name
                == "SFHA / 1% Annual Chance (100-year)"
            ):
                keep = sfha in (
                    "T",
                    "Y",
                    "YES",
                    "TRUE",
                    "1",
                )

            elif (
                filter_name
                == "0.2% Annual Chance (500-year)"
            ):
                keep = (
                    "0.2 PCT" in zone_subtype
                    or "0.2%" in zone_subtype
                    or "0.2 PERCENT" in zone_subtype
                    or (
                        flood_zone == "X"
                        and "ANNUAL CHANCE"
                        in zone_subtype
                        and "0.2"
                        in zone_subtype
                    )
                )

            elif (
                filter_name
                == "Regulatory Floodway"
            ):
                keep = (
                    "FLOODWAY"
                    in zone_subtype
                    or floodway_value
                    in (
                        "FLOODWAY",
                        "REGULATORY FLOODWAY",
                        "T",
                        "Y",
                        "YES",
                        "TRUE",
                        "1",
                    )
                )

            if not keep:
                cursor.deleteRow()

    return output_fc


def create_empty_fema_output(
    output_fc,
    spatial_reference,
    template=None,
):
    """
    Create an empty FEMA-compatible polygon feature class.
    """
    if arcpy.Exists(output_fc):
        arcpy.management.Delete(output_fc)

    output_path = os.path.dirname(
        output_fc
    )

    output_name = os.path.basename(
        output_fc
    )

    if template and arcpy.Exists(template):

        arcpy.management.CreateFeatureclass(
            output_path,
            output_name,
            "POLYGON",
            template=template,
            spatial_reference=spatial_reference,
        )

    else:

        arcpy.management.CreateFeatureclass(
            output_path,
            output_name,
            "POLYGON",
            spatial_reference=spatial_reference,
        )

        for name, length in (
            ("FLD_ZONE", 20),
            ("ZONE_SUBTY", 100),
            ("SFHA_TF", 10),
        ):
            arcpy.management.AddField(
                output_fc,
                name,
                "TEXT",
                field_length=length,
            )

    return output_fc


def create_flood_summary(
    feature_class,
    output_table,
):
    """
    Create a FEMA flood-zone summary table containing feature counts
    and geodesic acreage by flood zone and zone subtype.
    """
    if arcpy.Exists(output_table):
        arcpy.management.Delete(
            output_table
        )

    output_gdb = os.path.dirname(
        output_table
    )

    output_name = os.path.basename(
        output_table
    )

    arcpy.management.CreateTable(
        output_gdb,
        output_name,
    )

    arcpy.management.AddField(
        output_table,
        "FLD_ZONE",
        "TEXT",
        field_length=30,
    )

    arcpy.management.AddField(
        output_table,
        "ZONE_SUBTY",
        "TEXT",
        field_length=120,
    )

    arcpy.management.AddField(
        output_table,
        "FEATURE_COUNT",
        "LONG",
    )

    arcpy.management.AddField(
        output_table,
        "AREA_ACRES",
        "DOUBLE",
    )

    fields = field_lookup(
        feature_class
    )

    fld_zone = fields.get(
        "FLD_ZONE"
    )

    zone_subty = fields.get(
        "ZONE_SUBTY"
    )

    if not fld_zone:
        return output_table

    cursor_fields = [
        fld_zone
    ]

    if zone_subty:
        cursor_fields.append(
            zone_subty
        )

    cursor_fields.append(
        "SHAPE@"
    )

    stats = defaultdict(
        lambda: [0, 0.0]
    )

    with arcpy.da.SearchCursor(
        feature_class,
        cursor_fields,
    ) as cursor:

        for row in cursor:

            zone = (
                ""
                if row[0] is None
                else str(row[0])
            )

            subtype = ""
            geometry_index = 1

            if zone_subty:
                subtype = (
                    ""
                    if row[1] is None
                    else str(row[1])
                )

                geometry_index = 2

            geometry = row[
                geometry_index
            ]

            acres = 0.0

            if geometry:
                try:
                    acres = geometry.getArea(
                        "GEODESIC",
                        "ACRES",
                    )

                except Exception:
                    acres = 0.0

            stats[
                (zone, subtype)
            ][0] += 1

            stats[
                (zone, subtype)
            ][1] += acres

    with arcpy.da.InsertCursor(
        output_table,
        [
            "FLD_ZONE",
            "ZONE_SUBTY",
            "FEATURE_COUNT",
            "AREA_ACRES",
        ],
    ) as cursor:

        for (
            zone,
            subtype,
        ), (
            count,
            acres,
        ) in sorted(
            stats.items()
        ):

            cursor.insertRow(
                (
                    zone,
                    subtype,
                    count,
                    acres,
                )
            )

    return output_table