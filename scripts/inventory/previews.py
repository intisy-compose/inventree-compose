"""Renders the human partner's 3D-printed designs into product shots with Blender, from their exports only."""

import os
import subprocess

from .images import apply_model_images
from .settings import read_config
from .taxonomy import CatalogError, model_image_path

RENDER_SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "blender", "render_preview.py")


def design_folder(model, design_dirs):
    name = model["fields"]["Design source"]
    for root in design_dirs:
        candidate = os.path.join(root, name)
        if os.path.isdir(candidate):
            return candidate
    raise CatalogError(f"model '{model['name']}': design folder '{name}' is in none of DESIGN_DIRS ({'; '.join(design_dirs)})")


def export_paths(model, design_dirs):
    folder = design_folder(model, design_dirs)
    paths = [os.path.join(folder, relative) for relative in model["render"]]
    missing = [path for path in paths if not os.path.isfile(path)]
    if missing:
        raise CatalogError(f"model '{model['name']}': exports not found: {', '.join(missing)}")
    return paths


def render_model(blender, model, design_dirs):
    output = model_image_path(model)
    command = [blender, "-b", "--factory-startup", "-P", RENDER_SCRIPT, "--", output, *export_paths(model, design_dirs)]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0 or not os.path.isfile(output):
        raise CatalogError(f"model '{model['name']}': Blender failed:\n{result.stdout[-2000:]}{result.stderr[-2000:]}")


def render_previews(taxonomy, client, model_name=None):
    config = read_config()
    blender = config.get("BLENDER")
    design_dirs = [folder for folder in config.get("DESIGN_DIRS", "").split(";") if folder]
    if not blender or not design_dirs:
        raise CatalogError("set BLENDER and DESIGN_DIRS in config.env to render previews")
    models = [model for model in taxonomy["models"].values()
              if model.get("render") and (model_name is None or model["name"].lower() == model_name.lower())]
    if not models:
        raise CatalogError(f"no model with 'render' matches {model_name!r}" if model_name else "no model declares 'render'")
    for model in models:
        os.makedirs(os.path.dirname(model_image_path(model)), exist_ok=True)
        render_model(blender, model, design_dirs)
    rendered = {model["name"].lower(): model for model in models}
    return apply_model_images({**taxonomy, "models": rendered}, client, only_missing=False)

