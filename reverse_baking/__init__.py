import bpy
import bmesh
import math
import random
import colorsys
from collections import Counter

# ------------------------------------------------------------------------
#    Math & Clustering Logic (Highly Optimized)
# ------------------------------------------------------------------------

def precompute_hsv(colors):
    """Converts RGB colors to cylindrical HSV coordinates once to save CPU time."""
    hsv_data = []
    for c in colors:
        h, s, v = colorsys.rgb_to_hsv(c[0], c[1], c[2])
        hx = s * math.cos(h * 2 * math.pi)
        hy = s * math.sin(h * 2 * math.pi)
        hsv_data.append((hx, hy, v, c))
    return hsv_data

def cluster_colors_hsv(hsv_data, k, shadow_tol, max_iterations=10):
    """Runs K-Means using a high-speed random sampling method."""
    original_colors = [data[3] for data in hsv_data]
    most_common_rgb = [c for c, count in Counter(original_colors).most_common(k)]
    
    centroids = []
    for c in most_common_rgb:
        h, s, v = colorsys.rgb_to_hsv(c[0], c[1], c[2])
        centroids.append((s * math.cos(h * 2 * math.pi), s * math.sin(h * 2 * math.pi), v))
        
    sample_size = min(len(hsv_data), 5000)
    training_data = random.sample(hsv_data, sample_size)
    
    for _ in range(max_iterations):
        clusters = [[] for _ in range(len(centroids))]
        for hx, hy, v, rgb in training_data:
            dists = [((hx - cx)**2 + (hy - cy)**2 + ((v - cv) * (1.0 - shadow_tol))**2) for cx, cy, cv in centroids]
            idx = dists.index(min(dists))
            clusters[idx].append((hx, hy, v, rgb))
            
        new_centroids = []
        for j, cl in enumerate(clusters):
            if not cl:
                new_centroids.append(centroids[j])
            else:
                new_centroids.append((
                    sum(item[0] for item in cl)/len(cl),
                    sum(item[1] for item in cl)/len(cl),
                    sum(item[2] for item in cl)/len(cl)
                ))
        if centroids == new_centroids: break
        centroids = new_centroids
        
    labels = []
    for hx, hy, v, rgb in hsv_data:
        dists = [((hx - cx)**2 + (hy - cy)**2 + ((v - cv) * (1.0 - shadow_tol))**2) for cx, cy, cv in centroids]
        labels.append(dists.index(min(dists)))
        
    final_rgb_centroids = []
    for j, cl in enumerate(clusters):
        if not cl:
            final_rgb_centroids.append(most_common_rgb[j])
        else:
            final_rgb_centroids.append((
                sum(item[3][0] for item in cl)/len(cl),
                sum(item[3][1] for item in cl)/len(cl),
                sum(item[3][2] for item in cl)/len(cl)
            ))
            
    return final_rgb_centroids, labels

# ------------------------------------------------------------------------
#    Core Logic Extraction
# ------------------------------------------------------------------------

def get_face_colors_from_active(obj):
    mat = obj.active_material
    if not mat or not mat.use_nodes: return None
        
    img_node = None
    principled = next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if principled and principled.inputs['Base Color'].links:
        linked_node = principled.inputs['Base Color'].links[0].from_node
        if linked_node.type == 'TEX_IMAGE': img_node = linked_node

    if not img_node:
        active_node = mat.node_tree.nodes.active
        if active_node and active_node.type == 'TEX_IMAGE': img_node = active_node

    if not img_node:
        img_node = next((node for node in mat.node_tree.nodes if node.type == 'TEX_IMAGE'), None)
        
    if not img_node or not img_node.image: return None
        
    image = img_node.image
    width, height = image.size
    pixels = image.pixels[:]
    
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    uv_layer = bm.loops.layers.uv.verify()
    face_colors = []
    
    for face in bm.faces:
        u_sum = sum(loop[uv_layer].uv.x for loop in face.loops) / len(face.loops)
        v_sum = sum(loop[uv_layer].uv.y for loop in face.loops) / len(face.loops)
        x = int((u_sum % 1.0) * width)
        y = int((v_sum % 1.0) * height)
        idx = (y * width + x) * 4
        if idx + 2 < len(pixels):
            face_colors.append((pixels[idx], pixels[idx+1], pixels[idx+2]))
        else:
            face_colors.append((0.0, 0.0, 0.0))
            
    bm.free()
    return face_colors

# ------------------------------------------------------------------------
#    Operators
# ------------------------------------------------------------------------

class REVERSEBAKE_OT_preview(bpy.types.Operator):
    bl_idname = "object.reverse_bake_preview"
    bl_label = "Preview Clusters (Fast)"
    bl_description = "Calculates colors and displays them in the viewport without creating materials"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'MESH'

    def execute(self, context):
        obj = context.active_object
        detail_level = context.scene.reverse_bake_detail
        shadow_tol = context.scene.reverse_bake_shadow_tol / 100.0
        
        face_colors = get_face_colors_from_active(obj)
        if not face_colors:
            self.report({'WARNING'}, "Valid material and image texture required.")
            return {'CANCELLED'}
            
        hsv_data = precompute_hsv(face_colors)
        rgb_centroids, labels = cluster_colors_hsv(hsv_data, detail_level, shadow_tol)
        
        # --- VIEWPORT FIX: FORCE CORNER DOMAIN ---
        attr_name = "ReverseBake_Preview"
        
        # Remove existing attribute to avoid FACE/CORNER domain clashes
        if attr_name in obj.data.color_attributes:
            obj.data.color_attributes.remove(obj.data.color_attributes[attr_name])
            
        # CORNER domain is strictly required for reliable Viewport display
        color_attr = obj.data.color_attributes.new(name=attr_name, type='FLOAT_COLOR', domain='CORNER')
        
        # Assign colors to corners (loops)
        for poly in obj.data.polygons:
            color = (*rgb_centroids[labels[poly.index]], 1.0)
            for loop_idx in poly.loop_indices:
                color_attr.data[loop_idx].color = color
                
        # Set as the active rendering and display attribute
        obj.data.attributes.active_color = color_attr
            
        # Force the 3D Viewport to Solid Mode and read the Attribute
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                for space in area.spaces:
                    if space.type == 'VIEW_3D':
                        space.shading.type = 'SOLID'
                        try:
                            space.shading.color_type = 'ATTRIBUTE'
                        except TypeError:
                            space.shading.color_type = 'VERTEX'
                        
        obj.data.update()
        
        # Bulletproof viewport cache refresh toggle
        if context.object.mode == 'OBJECT':
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.object.mode_set(mode='OBJECT')
            
        self.report({'INFO'}, "Preview generated successfully.")
        return {'FINISHED'}


class REVERSEBAKE_OT_extract(bpy.types.Operator):
    bl_idname = "object.reverse_bake_extract"
    bl_label = "Generate Materials"
    bl_description = "Permanently creates materials and assigns them to faces based on current settings"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'MESH'

    def execute(self, context):
        obj = context.active_object
        detail_level = context.scene.reverse_bake_detail
        shadow_tol = context.scene.reverse_bake_shadow_tol / 100.0
        
        face_colors = get_face_colors_from_active(obj)
        if not face_colors:
            return {'CANCELLED'}
            
        hsv_data = precompute_hsv(face_colors)
        rgb_centroids, labels = cluster_colors_hsv(hsv_data, detail_level, shadow_tol)
        
        obj.data.materials.clear()
        for i, centroid in enumerate(rgb_centroids):
            mat = bpy.data.materials.new(name=f"Extracted_Cluster_{i+1}")
            mat.use_nodes = True
            mat.node_tree.nodes.clear()
            out = mat.node_tree.nodes.new('ShaderNodeOutputMaterial')
            out.location = (400, 0)
            bsdf = mat.node_tree.nodes.new('ShaderNodeBsdfPrincipled')
            bsdf.location = (0, 0)
            bsdf.inputs['Base Color'].default_value = (*centroid, 1.0)
            mat.node_tree.links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
            mat.preview_ensure()
            obj.data.materials.append(mat)
            
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        for i, face in enumerate(bm.faces):
            face.material_index = labels[i]
        bm.to_mesh(obj.data)
        bm.free()
        
        # Switch Viewport back to Material view so you can see the final result
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                for space in area.spaces:
                    if space.type == 'VIEW_3D':
                        space.shading.type = 'MATERIAL'
                        
        obj.data.update()
        return {'FINISHED'}

# ------------------------------------------------------------------------
#    UI Panel
# ------------------------------------------------------------------------

class REVERSEBAKE_PT_panel(bpy.types.Panel):
    bl_label = "Reverse Baker"
    bl_idname = "REVERSEBAKE_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Reverse Baker"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        layout.label(text="Scanner Settings:")
        row = layout.row()
        row.prop(scene, "reverse_bake_detail", text="Detail Grade")
        row = layout.row()
        row.prop(scene, "reverse_bake_shadow_tol", text="Shadow Tolerance %")
        
        layout.separator()
        layout.operator("object.reverse_bake_preview", icon='COLOR')
        layout.operator("object.reverse_bake_extract", icon='MATERIAL')

# ------------------------------------------------------------------------
#    Registration
# ------------------------------------------------------------------------

classes = (
    REVERSEBAKE_OT_preview,
    REVERSEBAKE_OT_extract,
    REVERSEBAKE_PT_panel,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
        
    bpy.types.Scene.reverse_bake_detail = bpy.props.IntProperty(
        name="Detail Grade",
        default=5,
        min=1,
        max=30
    )
    bpy.types.Scene.reverse_bake_shadow_tol = bpy.props.IntProperty(
        name="Shadow Tolerance",
        default=80,
        min=0,
        max=100
    )

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
        
    del bpy.types.Scene.reverse_bake_detail
    del bpy.types.Scene.reverse_bake_shadow_tol

if __name__ == "__main__":
    register()