# -----------------------------------------------------------------------------
# Dinesh Shrestha
# GIS Automation & Spatial Analysis Consultant
# ArcGIS Pro • Python • ArcPy • Data Engineering
# email: dinesh.shrestha015@gmail.com
# Portfolio: dineshrestha.github.io
# -----------------------------------------------------------------------------

import arcpy


def field_lookup(feature_class):
    """
    Return a case-insensitive lookup of feature-class field names.
    """
    return {
        field.name.upper(): field.name
        for field in arcpy.ListFields(feature_class)
    }