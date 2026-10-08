"""The label layout lives in the InvenTree printer plugin, so the server and this tool print the same
sheets. It is loaded by file path: importing the plugin package would pull in InvenTree itself."""

import importlib.util
import os

from .settings import ROOT

_PATH = os.path.join(ROOT, "plugins", "cd_label_sheet", "sheet.py")
_SPEC = importlib.util.spec_from_file_location("cd_label_sheet_layout", _PATH)
sheet = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(sheet)

Label = sheet.Label
write_sheets = sheet.write_sheets
