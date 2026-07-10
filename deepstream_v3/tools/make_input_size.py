#!/usr/bin/env python3
"""
det_10g.onnx ni berilgan kirish o'lchamiga (masalan 1280) qayta eksport qiladi
va chiqishlarga batch o'lchami qo'shadi ([N,w] -> [1,N,w]).

add_batch_dim.py ning umumlashgan varianti: SCRFD to'liq konvolyutsion —
kirish kattalashsa chiqish anchor soni (sz/stride)^2*2 bo'lib o'zgaradi.
1920x1080 kadr 640 ga emas 1280 ga letterbox bo'lsa, orqa qatordagi kichik
yuzlar detektor ko'radigan o'lchamda qoladi.

Ishlatish (konteyner ichida):
  python3 make_input_size.py /in/det_10g.onnx /out/det_10g_1280_batched.onnx 1280
"""
import sys

import onnx
from onnx import TensorProto, helper

_STRIDES = [8, 16, 32]
_NUM_ANCHORS = 2

# chiqish nomi -> (stride, ustun soni); anchor soni kirish o'lchamidan hisoblanadi
_LAYER_MAP = {
    "448": (8, 1), "471": (16, 1), "494": (32, 1),
    "451": (8, 4), "474": (16, 4), "497": (32, 4),
    "454": (8, 10), "477": (16, 10), "500": (32, 10),
}


def main(src: str, dst: str, input_sz: int):
    m = onnx.load(src)
    g = m.graph

    # 1. Kirish o'lchamini qat'iy [1,3,sz,sz] qilish
    inp = g.input[0]
    dims = inp.type.tensor_type.shape.dim
    for i, v in enumerate((1, 3, input_sz, input_sz)):
        dims[i].ClearField("dim_param")
        dims[i].dim_value = v
    print(f"kirish {inp.name}: [1,3,{input_sz},{input_sz}]")

    # 2. Eski shape-inference izlarini tozalash (640 ga bog'langan bo'lishi mumkin)
    del g.value_info[:]

    opset = max((op.version for op in m.opset_import if op.domain in ("", "ai.onnx")), default=11)
    print(f"ONNX opset: {opset}")

    # 3. Chiqishlarga Unsqueeze(axis=0) — nvinfer TRT10 explicit-batch talabi
    new_outputs = []
    for out in list(g.output):
        name = out.name
        stride, w = _LAYER_MAP[name]
        n = (input_sz // stride) ** 2 * _NUM_ANCHORS
        new_name = name + "_b"
        if opset >= 13:
            axes_name = name + "_unsq_axes"
            g.initializer.append(
                helper.make_tensor(axes_name, TensorProto.INT64, [1], [0]))
            node = helper.make_node("Unsqueeze", [name, axes_name], [new_name],
                                    name="unsq_" + name)
        else:
            node = helper.make_node("Unsqueeze", [name], [new_name],
                                    name="unsq_" + name, axes=[0])
        g.node.append(node)
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
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]))
