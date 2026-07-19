# Reverse Baking
The Reverse Baker is a technical art tool that reverses the standard texture baking pipeline. Instead of baking materials into a single image texture, it scans an existing baked image (like an albedo or diffuse map), intelligently identifies the dominant base colors while ignoring baked-in shadows and highlights, and rebuilds them into discrete, editable Principled BSDF materials assigned precisely to the mesh geometry.

[![Watch the tutorial](https://img.youtube.com/vi/fqYN2J2Ns1I?si=V-s6JaGORumWz8rH/0.jpg)]([https://www.youtube.com/watch?v=YOUR_VIDEO_ID_HERE](https://youtu.be/fqYN2J2Ns1I?si=V-s6JaGORumWz8rH))
