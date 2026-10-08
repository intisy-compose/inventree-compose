"""Renders exported STL files into one product shot on a transparent background, run inside Blender:
`blender -b --factory-startup -P render_preview.py -- <output.png> <part.stl> [<part.stl> ...]`.

Only the exports are imported, into an empty factory scene that is never saved, so the human partner's
model files stay untouched. Several parts are laid out side by side in the order given.
"""

import math
import sys

import bpy
from mathutils import Vector

RESOLUTION = 1024
GAP_FRACTION = 0.15
CAMERA_ELEVATION_DEGREES = 30
CAMERA_AZIMUTH_DEGREES = 35
PART_COLOUR = (0.30, 0.33, 0.37, 1.0)


def arguments():
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if len(values) < 2:
        raise SystemExit("usage: blender -b -P render_preview.py -- <output.png> <part.stl> [...]")
    return values[0], values[1:]


def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    return bpy.context.scene


def import_part(path):
    before = set(bpy.data.objects)
    bpy.ops.wm.stl_import(filepath=path)
    return [obj for obj in bpy.data.objects if obj not in before]


def world_bounds(objects):
    corners = [obj.matrix_world @ Vector(corner) for obj in objects for corner in obj.bound_box]
    low = Vector(tuple(min(corner[axis] for corner in corners) for axis in range(3)))
    high = Vector(tuple(max(corner[axis] for corner in corners) for axis in range(3)))
    return low, high


def lay_out_in_a_row(groups):
    """Each part rests on the floor, centred on its own depth, after the previous one along X."""
    widths = [world_bounds(group)[1].x - world_bounds(group)[0].x for group in groups]
    gap = GAP_FRACTION * max(widths)
    cursor = 0.0
    for group, width in zip(groups, widths):
        low, high = world_bounds(group)
        offset = Vector((cursor - low.x, -(low.y + high.y) / 2, -low.z))
        for obj in group:
            obj.location += offset
        bpy.context.view_layer.update()
        cursor += width + gap


def apply_material(objects):
    material = bpy.data.materials.new("Print")
    material.use_nodes = True
    shader = material.node_tree.nodes["Principled BSDF"]
    shader.inputs["Base Color"].default_value = PART_COLOUR
    shader.inputs["Roughness"].default_value = 0.55
    for obj in objects:
        obj.data.materials.clear()
        obj.data.materials.append(material)


def dim_world(scene):
    """The background is rendered transparent and flattened onto white by the catalog's image step; a white
    world would light the parts so evenly that their edges disappear."""
    world = bpy.data.worlds.new("Ambient")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (1, 1, 1, 1)
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.35
    scene.world = world
    scene.view_settings.view_transform = "Standard"


def add_lights(scene, centre, size):
    for name, energy, direction in (("Key", 2.5, (-0.6, -0.8, 1.0)), ("Fill", 0.8, (0.8, -0.3, 0.6))):
        light = bpy.data.lights.new(name, "SUN")
        light.energy = energy
        holder = bpy.data.objects.new(name, light)
        holder.location = centre + Vector(direction) * size
        holder.rotation_euler = (centre - holder.location).to_track_quat("-Z", "Y").to_euler()
        scene.collection.objects.link(holder)


def add_camera(scene, objects):
    """An orthographic camera at a fixed angle, framed to the parts so every preview looks alike."""
    low, high = world_bounds(objects)
    centre = (low + high) / 2
    size = (high - low).length
    elevation = math.radians(CAMERA_ELEVATION_DEGREES)
    azimuth = math.radians(CAMERA_AZIMUTH_DEGREES)
    direction = Vector((math.sin(azimuth) * math.cos(elevation), -math.cos(azimuth) * math.cos(elevation), math.sin(elevation)))
    camera = bpy.data.cameras.new("Camera")
    camera.type = "ORTHO"
    camera.ortho_scale = size * 1.1
    camera.clip_end = size * 10
    holder = bpy.data.objects.new("Camera", camera)
    holder.location = centre + direction * size * 2
    holder.rotation_euler = (centre - holder.location).to_track_quat("-Z", "Y").to_euler()
    scene.collection.objects.link(holder)
    scene.camera = holder
    add_lights(scene, centre, size)


def render(scene, output):
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = RESOLUTION
    scene.render.resolution_y = RESOLUTION
    scene.render.film_transparent = True
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = output
    bpy.ops.render.render(write_still=True)


def main():
    output, parts = arguments()
    scene = empty_scene()
    groups = [import_part(path) for path in parts]
    objects = [obj for group in groups for obj in group]
    lay_out_in_a_row(groups)
    apply_material(objects)
    dim_world(scene)
    add_camera(scene, objects)
    render(scene, output)


main()
