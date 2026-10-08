"""Loads data/catalog.toml and checks it is self-consistent before anything touches InvenTree."""

import os
import tomllib

from .settings import CATALOG_PATH, DATA_DIR

FIELD_TYPES = {"TEXT", "NUMBER", "OPTION", "BOOLEAN"}
LABEL_SIZES = ("large", "standard", "small", "none")
KINDS = ("categories", "fields", "tags", "locations", "models")


class CatalogError(Exception):
    pass


def load_toml(path):
    try:
        with open(path, "rb") as handle:
            return tomllib.load(handle)
    except FileNotFoundError:
        raise CatalogError(f"{path} not found")
    except tomllib.TOMLDecodeError as error:
        raise CatalogError(f"{path}: {error}")


def load_catalog(path=CATALOG_PATH):
    raw = load_toml(path)
    taxonomy = {kind: {entry["name"].lower(): entry for entry in raw.get(kind, [])} for kind in KINDS}
    validate_categories(taxonomy)
    validate_fields(taxonomy)
    validate_locations(taxonomy)
    for model in taxonomy["models"].values():
        validate_model(taxonomy, model)
    return taxonomy


def require(taxonomy, kind, name, context):
    entry = taxonomy[kind].get(str(name).lower())
    if entry is None:
        raise CatalogError(f"{context}: '{name}' is not declared under [[{kind}]] in data/catalog.toml")
    return entry


def validate_label(label, context):
    if label is not None and label not in LABEL_SIZES:
        raise CatalogError(f"{context}: label must be one of {', '.join(LABEL_SIZES)}, not '{label}'")


def validate_categories(taxonomy):
    for category in taxonomy["categories"].values():
        validate_label(category.get("label"), f"category '{category['name']}'")


def validate_fields(taxonomy):
    for field in taxonomy["fields"].values():
        context = f"field '{field['name']}'"
        if field.get("type", "TEXT") not in FIELD_TYPES:
            raise CatalogError(f"{context}: unknown type {field.get('type')}")
        if field.get("type") == "OPTION" and not field.get("options"):
            raise CatalogError(f"{context}: OPTION fields need options")
        if any("," in option for option in field.get("options", [])):
            raise CatalogError(f"{context}: options cannot contain commas")
        for category in field.get("categories", []):
            require(taxonomy, "categories", category, context)


def validate_locations(taxonomy):
    for location in taxonomy["locations"].values():
        if location.get("parent"):
            require(taxonomy, "locations", location["parent"], f"location '{location['name']}'")


def validate_model(taxonomy, model):
    context = f"model '{model['name']}'"
    category = require(taxonomy, "categories", model["category"], context)
    if model.get("image") and not os.path.isfile(model_image_path(model)):
        raise CatalogError(f"{context}: image data/{model['image']} not found")
    validate_label(model.get("label"), context)
    for tag in model.get("tags", []):
        require(taxonomy, "tags", tag, context)
    values = model.get("fields", {})
    for name, value in values.items():
        validate_field_value(taxonomy, category, name, value, context)
    for field in fields_of(taxonomy, category):
        if field.get("required") and field["name"] not in values:
            raise CatalogError(f"{context}: required field '{field['name']}' is missing")


def fields_of(taxonomy, category):
    return [field for field in taxonomy["fields"].values()
            if category["name"].lower() in (name.lower() for name in field.get("categories", []))]


def validate_field_value(taxonomy, category, name, value, context):
    field = require(taxonomy, "fields", name, context)
    if field not in fields_of(taxonomy, category):
        raise CatalogError(f"{context}: field '{name}' does not apply to category '{category['name']}'")
    kind = field.get("type", "TEXT")
    if kind == "NUMBER" and (isinstance(value, bool) or not isinstance(value, (int, float))):
        raise CatalogError(f"{context}: '{name}' must be a number, not {value!r}")
    if kind == "BOOLEAN" and not isinstance(value, bool):
        raise CatalogError(f"{context}: '{name}' must be true or false, not {value!r}")
    if kind == "OPTION" and value not in field["options"]:
        raise CatalogError(f"{context}: '{name}' must be one of {field['options']}, not {value!r}")
    if kind == "TEXT" and not isinstance(value, str):
        raise CatalogError(f"{context}: '{name}' must be text, not {value!r}")


def model_image_path(model):
    return os.path.join(DATA_DIR, model["image"]) if model.get("image") else None


def label_size(taxonomy, model, override=None):
    """An asset's own label, else its model's, else none for soldered parts, else its category's."""
    if override:
        return override
    if model.get("label"):
        return model["label"]
    if model.get("fields", {}).get("Soldered") is True:
        return "none"
    category = require(taxonomy, "categories", model["category"], f"model '{model['name']}'")
    return category.get("label", "standard")
