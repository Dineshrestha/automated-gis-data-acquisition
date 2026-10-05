import arcpy


def linear_unit_value(distance_text):
    """
    Convert an ArcGIS linear-unit string into a numeric value.

    Examples
    --------
    "0 Miles" -> 0.0
    "5 Miles" -> 5.0
    "1000 Feet" -> 1000.0
    """
    if not distance_text:
        return 0.0

    try:
        return float(str(distance_text).split()[0])
    except (ValueError, TypeError, IndexError):
        raise ValueError(
            "Could not parse buffer distance: {!r}".format(distance_text)
        )


def prepare_aoi(
    study_area,
    buffer_distance,
    output_fc,
):
    """
    Prepare a dissolved polygon AOI from an input feature class.

    Polygon inputs may be used directly when the buffer distance is zero.
    Point and line inputs require a positive buffer distance.

    Parameters
    ----------
    study_area : str
        Input feature class or layer.
    buffer_distance : str
        ArcGIS linear-unit string, e.g. "5 Miles".
    output_fc : str
        Output temporary feature class.

    Returns
    -------
    str
        Path to the prepared AOI feature class.
    """
    if not arcpy.Exists(study_area):
        raise ValueError(
            "Study area does not exist: {}".format(study_area)
        )

    desc = arcpy.Describe(study_area)
    shape_type = desc.shapeType
    spatial_reference = desc.spatialReference

    if not spatial_reference or spatial_reference.name == "Unknown":
        raise ValueError(
            "Study area must have a defined coordinate system."
        )

    buffer_value = linear_unit_value(buffer_distance)

    if shape_type != "Polygon" and buffer_value <= 0:
        raise ValueError(
            "Point and line study areas require a positive buffer distance."
        )

    if arcpy.Exists(output_fc):
        arcpy.management.Delete(output_fc)

    if buffer_value > 0:
        arcpy.analysis.PairwiseBuffer(
            in_features=study_area,
            out_feature_class=output_fc,
            buffer_distance_or_field=buffer_distance,
            dissolve_option="ALL",
        )
    else:
        arcpy.management.Dissolve(
            in_features=study_area,
            out_feature_class=output_fc,
        )

    count = int(arcpy.management.GetCount(output_fc)[0])

    if count == 0:
        raise RuntimeError(
            "AOI preparation produced an empty feature class."
        )

    return output_fc