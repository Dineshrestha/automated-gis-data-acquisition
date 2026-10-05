import arcpy


def best_transformation(source_sr, target_sr):
    """
    Return the first ArcGIS geographic transformation recommended
    between two spatial references.

    Returns None when no transformation is required or available.
    """
    if not source_sr or not target_sr:
        return None

    if source_sr.factoryCode == target_sr.factoryCode:
        return None

    transformations = arcpy.ListTransformations(
        source_sr,
        target_sr,
    )

    return transformations[0] if transformations else None


def project_feature_class(
    input_fc,
    output_fc,
    target_sr,
):
    """
    Project a feature class using ArcGIS' preferred geographic
    transformation when one is available.

    Parameters
    ----------
    input_fc : str
        Input feature class.
    output_fc : str
        Output projected feature class.
    target_sr : arcpy.SpatialReference | int
        Target spatial reference or WKID.

    Returns
    -------
    str
        Path to the projected output.
    """
    if isinstance(target_sr, int):
        target_sr = arcpy.SpatialReference(target_sr)

    source_sr = arcpy.Describe(input_fc).spatialReference

    if not source_sr or source_sr.name == "Unknown":
        raise ValueError(
            "Input feature class must have a defined coordinate system."
        )

    if arcpy.Exists(output_fc):
        arcpy.management.Delete(output_fc)

    transformation = best_transformation(
        source_sr,
        target_sr,
    )

    kwargs = {
        "in_dataset": input_fc,
        "out_dataset": output_fc,
        "out_coor_system": target_sr,
    }

    if transformation:
        kwargs["transform_method"] = transformation

    arcpy.management.Project(**kwargs)

    return output_fc