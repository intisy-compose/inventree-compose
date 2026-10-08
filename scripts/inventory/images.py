"""Gives every part its model's product shot, framed the same way so all parts look alike."""

import io
import os

from .sync import by_name
from .taxonomy import model_image_path

IMAGE_SIZE = 1200
IMAGE_MARGIN = 0.06


def product_image(path):
    """Flattened on white, trimmed to the item, centred in a square."""
    from PIL import Image, ImageChops, ImageOps

    with Image.open(path) as original:
        image = ImageOps.exif_transpose(original).convert("RGBA")
    flattened = Image.new("RGB", image.size, "white")
    flattened.paste(image, mask=image.getchannel("A"))
    whiten_background(flattened)
    difference = ImageChops.difference(flattened, Image.new("RGB", image.size, "white")).convert("L")
    content = difference.point(lambda level: 255 if level > 12 else 0).getbbox()
    if content:
        flattened = flattened.crop(content)
    side = int(max(flattened.size) * (1 + 2 * IMAGE_MARGIN))
    square = Image.new("RGB", (side, side), "white")
    square.paste(flattened, ((side - flattened.width) // 2, (side - flattened.height) // 2))
    return square.resize((IMAGE_SIZE, IMAGE_SIZE), Image.LANCZOS) if side > IMAGE_SIZE else square


def whiten_background(image):
    """Turns an off-white studio background pure white, filling from the corners so a white product stays intact."""
    from PIL import ImageDraw

    for corner in ((0, 0), (image.width - 1, 0), (0, image.height - 1), (image.width - 1, image.height - 1)):
        if min(image.getpixel(corner)) >= 225:
            ImageDraw.floodfill(image, corner, (255, 255, 255), thresh=16)


def jpeg_bytes(image):
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=90)
    return buffer.getvalue()


def apply_model_images(taxonomy, client, only_missing):
    parts = by_name(client.get("/api/part/"))
    lines = []
    for key, model in taxonomy["models"].items():
        part = parts.get(key)
        if part is None:
            continue
        path = model_image_path(model)
        if path is None:
            lines.append(f"! model without image: {model['name']}")
            continue
        if only_missing and part.get("image"):
            continue
        name = os.path.splitext(os.path.basename(path))[0] + ".jpg"
        client.upload(f"/api/part/{part['pk']}/", "image", name, jpeg_bytes(product_image(path)))
        lines.append(f"~ {model['name']}: image from data/{model['image']}")
    return lines
