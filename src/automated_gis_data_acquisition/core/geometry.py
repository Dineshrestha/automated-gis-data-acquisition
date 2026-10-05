import arcpy


def feature_count(feature_class):
    """
    Return the number of features in a feature class or layer.
    """
    if not arcpy.Exists(feature_class):
        raise ValueError(
            "Feature class does not exist: {}".format(feature_class)
        )

    return int(arcpy.management.GetCount(feature_class)[0])


def repair_geometry(
    feature_class,
    delete_null="DELETE_NULL",
):
    """
    Repair invalid geometries in-place.

    Parameters
    ----------
    feature_class : str
        Input feature class to repair.
    delete_null : str, optional
        ArcGIS Repair Geometry delete_null option.

    Returns
    -------
    str
        Same input feature class path.
    """
    if not arcpy.Exists(feature_class):
        raise ValueError(
            "Feature class does not exist: {}".format(feature_class)
        )

    arcpy.management.RepairGeometry(
        in_features=feature_class,
        delete_null=delete_null,
    )

    return feature_class


def clip_features(
    input_fc,
    clip_fc,
    output_fc,
):
    """
    Clip vector features to a polygon AOI.
    """
    if not arcpy.Exists(input_fc):
        raise ValueError(
            "Input feature class does not exist: {}".format(input_fc)
        )

    if not arcpy.Exists(clip_fc):
        raise ValueError(
            "Clip feature class does not exist: {}".format(clip_fc)
        )

    if arcpy.Exists(output_fc):
        arcpy.management.Delete(output_fc)

    arcpy.analysis.PairwiseClip(
        in_features=input_fc,
        clip_features=clip_fc,
        out_feature_class=output_fc,
    )

    return output_fc


def ensure_not_empty(
    feature_class,
    message=None,
):
    """
    Raise an error if a feature class contains no features.
    """
    count = feature_count(feature_class)

    if count == 0:
        raise RuntimeError(
            message
            or "Feature class contains no features: {}".format(
                feature_class
            )
        )

    return feature_class