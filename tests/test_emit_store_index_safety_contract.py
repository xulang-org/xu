"""Source contracts for type-directed indexed-store/drop safety.

These checks intentionally stay static: the Gen1 emitter is itself written in
Xu and is rebuilt by the hosted chain.  Keeping the assertions here free of a
compiler invocation makes the regression gate usable on every host while
still pinning the two safety invariants that are easy to regress during
lowering changes.
"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DROP = (ROOT / "src/cmd/compile/emit_drop.xu").read_text(encoding="utf-8")
INDEX = (ROOT / "src/cmd/compile/emit_instr_index_mem.xu").read_text(
    encoding="utf-8"
)


def _function_body(source: str, name: str) -> str:
    match = re.search(
        rf"^fn {re.escape(name)}\([^\n]*\)[^{{]*\{{(?P<body>.*?)^\}}",
        source,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match is not None, f"missing Xu function {name}"
    return match.group("body")


def test_nested_array_drop_routes_through_layout_aware_emitter() -> None:
    body = _function_body(DROP, "emit_array_drop_helper")
    branch = body[body.index("} else if types.is_array_type(ety) {") :]
    branch = branch[: branch.index("} else if types.is_throw_type(ety)")]

    # Metadata bounds are checked before any nested drop is emitted.
    assert "nfixed := m.arrays[nested].fixed_len" in branch
    assert "nbytes := m.arrays[nested].elem_bytes" in branch
    assert "nfixed >= 0" in branch
    assert "nbytes >= 0" in branch

    # Fixed arrays must use the inline path; descriptor loads/free belong only
    # to emit_drop_value's validated dynamic-array branch.
    assert "emit_drop_value(a, m, ety, 0, 1)" in branch
    assert "a.call(drop_array_name(nested))" not in branch
    assert "a.load(0, 9, 16)" not in branch


def test_store_index_shape_walks_nested_metadata_graph() -> None:
    graph = _function_body(INDEX, "emit_store_index_type_graph_ok")
    shape = _function_body(INDEX, "emit_store_index_shape_ok")
    layout = _function_body(INDEX, "emit_store_index_struct_layout_ok")
    enum_layout = _function_body(INDEX, "emit_store_index_enum_layout_ok")

    # The graph walk is bounded and distinguishes pointer cycles from inline
    # by-value cycles (recursive slices remain representable; malformed inline
    # layouts fail closed).
    assert "depth > emit_store_index_max_depth" in graph
    assert "path_len" in graph
    assert "if ptr_edge != 0" in graph
    assert "fixed_len * elem_bytes" in graph
    assert "m.type_size_bytes(elem_ty)" in graph
    assert "emit_store_index_type_graph_ok" in graph
    assert "vslots != 3" in graph
    assert "vstate != 0" in graph
    assert "emit_store_index_struct_layout_ok(nslots, size_bytes)" in graph
    assert "nslots == 0" in layout
    assert "size_bytes > lower" in layout
    assert "size_bytes <= upper" in layout
    assert "nslots == max_payload + 1" in enum_layout
    assert "emit_store_index_enum_layout_ok(nslots, max_payload)" in graph
    # Struct field metadata is byte-addressed; the ownership oracle must not
    # compare a byte offset against the word-count field.
    assert "CStruct.field.slot is a byte offset" in INDEX
    assert "fbytes > size_bytes - off" in INDEX

    # Every StoreIndex admission must invoke the nested graph check after the
    # existing ownership/width check.
    assert "emit_store_index_type_graph_root_ok(m, elem_ty)" in shape
