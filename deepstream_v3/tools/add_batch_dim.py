#!/usr/bin/env python3
"""
det_10g.onnx chiqishlariga batch o'lchami qo'shadi: [N,w] -> [1,N,w].

Sabab: TRT10/nvinfer explicit-batch rejimida chiqishning birinchi
o'lchamini batch deb oladi ([12800,1] -> batch=12800, dims=[1]) va
host buffer'ni 1 element qilib ajratadi. Unsqueeze(axis=0) bilan
to'g'ri batch=1 hosil qilinadi — nvinfer to'liq [12800,1] ni ko'radi.

Ishlatish (konteyner ichida):
  python3 add_batch_dim.py /in/det_10g.onnx /out/det_10g_batched.onnx
"""
import sys

import onnx
from onnx import TensorProto, helper

# 640x640 kirish uchun chiqish shakllari (SCRFD det_10g, stride 8/16/32)
_SHAPES = {
    "448": (12800, 1), "471": (3200, 1), "494": (800, 1),
    "451": (12800, 4), "474": (3200, 4), "497": (800, 4),
    "454": (12800, 10), "477": (3200, 10), "500": (800, 10),
}


def main(src: str, dst: str):
    m = onnx.load(src)
    g = m.graph

    opset = max((op.version for op in m.opset_import if op.domain in ("", "ai.onnx")), default=11)
    print(f"ONNX opset: {opset}")

    new_outputs = []
    for out in list(g.output):
        name = out.name
        new_name = name + "_b"
        if opset >= 13:
            axes_name = name + "_unsq_axes"
            g.initializer.append(
                helper.make_tensor(axes_name, TensorProto.INT64, [1], [0]))
            node = helper.make_node("Unsqueeze", [name, axes_name], [new_name],
                                    name="unsq_" + name)
        else:
            # opset <13: axes atribut sifatida
            node = helper.make_node("Unsqueeze", [name], [new_name],
                                    name="unsq_" + name, axes=[0])
        g.node.append(node)
        n, w = _SHAPES[name]
        vi = helper.make_tensor_value_info(
            new_name, out.type.tensor_type.elem_type, [1, n, w])
        new_outputs.append(vi)
        print(f"  {name} -> {new_name} [1,{n},{w}]")

    del g.output[:]
    g.output.extend(new_outputs)

    onnx.checker.check_model(m)
    onnx.save(m, dst)
    print(f"Saqlandi: {dst}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
