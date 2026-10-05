import os
import uuid

import arcpy


class TempWorkspace:
    """
    Track temporary GIS datasets and files for one acquisition run.

    Temporary items are automatically named using a unique run ID.
    """

    def __init__(
        self,
        scratch_gdb=None,
        scratch_folder=None,
    ):
        self.run_id = uuid.uuid4().hex[:8]

        self.scratch_gdb = (
            scratch_gdb
            or arcpy.env.scratchGDB
        )

        self.scratch_folder = (
            scratch_folder
            or arcpy.env.scratchFolder
        )

        if not self.scratch_gdb:
            raise RuntimeError(
                "ArcGIS scratch geodatabase is unavailable."
            )

        if not self.scratch_folder:
            raise RuntimeError(
                "ArcGIS scratch folder is unavailable."
            )

        self._items = []

    def feature_class(self, label):
        """
        Return a unique temporary feature-class path in scratchGDB.
        """
        name = "{}_{}".format(
            label,
            self.run_id,
        )

        path = os.path.join(
            self.scratch_gdb,
            name,
        )

        self.track(path)

        return path

    def table(self, label):
        """
        Return a unique temporary table path in scratchGDB.
        """
        return self.feature_class(label)

    def file(self, label, extension):
        """
        Return a unique temporary file path in scratchFolder.

        Example
        -------
        workspace.file("fema_batch", ".json")
        """
        if extension and not extension.startswith("."):
            extension = "." + extension

        filename = "{}_{}{}".format(
            label,
            self.run_id,
            extension or "",
        )

        path = os.path.join(
            self.scratch_folder,
            filename,
        )

        self.track(path)

        return path

    def track(self, path):
        """
        Register an existing temporary path for later cleanup.
        """
        if path and path not in self._items:
            self._items.append(path)

        return path

    def cleanup(self):
        """
        Delete tracked temporary GIS datasets and files.

        Cleanup failures are ignored so they do not hide the original
        processing exception.
        """
        for item in reversed(self._items):
            try:
                if arcpy.Exists(item):
                    arcpy.management.Delete(item)

                elif os.path.exists(item):
                    os.remove(item)

            except Exception:
                pass

        self._items.clear()

    def __enter__(self):
        return self

    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ):
        self.cleanup()

        return False