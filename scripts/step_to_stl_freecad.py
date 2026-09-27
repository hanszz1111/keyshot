"""Run with FreeCADCmd, not the web server's Python interpreter.

Inputs come from environment variables to avoid FreeCADCmd argv differences across
Windows distributions. The original STEP file is never modified.
"""

import os
import sys

import MeshPart
import Part


def main():
    source = os.environ["AI_RENDER_CAD_SOURCE"]
    output = os.environ["AI_RENDER_CAD_OUTPUT"]
    shape = Part.Shape()
    shape.read(source)
    if shape.isNull() or not shape.Faces:
        raise ValueError("STEP 文件没有可网格化的曲面；请检查文件是否为空或仅含曲线")
    mesh = MeshPart.meshFromShape(
        Shape=shape,
        LinearDeflection=0.1,
        AngularDeflection=0.261799,
        Relative=False,
    )
    if mesh.CountFacets == 0:
        raise ValueError("STEP 转换没有生成任何三角面")
    mesh.write(output)
    if not os.path.isfile(output) or os.path.getsize(output) == 0:
        raise ValueError("STEP 转换结果为空")
    print("CAD_CONVERT_OK facets=%s" % mesh.CountFacets, flush=True)


try:
    main()
except Exception as exc:
    print("CAD_CONVERT_ERROR %s" % exc, file=sys.stderr, flush=True)
    raise
