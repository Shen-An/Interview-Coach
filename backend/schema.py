"""JSON Schema 校验（draft 2020-12 的常用子集），零依赖。

为什么不用 jsonschema 库：这个后端要被 PyInstaller 打成单文件 exe，
而 jsonschema 会拖进 rpds-py 这个 Rust 编译扩展，给桌面打包平添一份平台风险。
这里要校验的对象只有一种形状（kb/schema/intel.schema.json），
支持这些关键字就够了，且 schema 文件是真的被读进来解释、不是摆设：

  type / enum / const / required / properties / additionalProperties
  items / minItems / maxItems / minLength / maxLength / minimum / maximum

不支持的关键字（$ref、oneOf、pattern 等）会被静默忽略——schema 里也不许用，
用了就等于没校验，这一点比"假装支持"重要。
"""
from __future__ import annotations

import json
from pathlib import Path

_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "null": type(None),
}


def _type_ok(value, name: str) -> bool:
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "boolean":
        return isinstance(value, bool)
    expect = _TYPES.get(name)
    if expect is None:
        return True                      # 未知类型名不当错误，交给 schema 作者
    return isinstance(value, expect) and not (expect is not bool and isinstance(value, bool))


def _kind(value) -> str:
    for name, py in (("boolean", bool), ("integer", int), ("string", str),
                     ("array", list), ("object", dict), ("null", type(None))):
        if isinstance(value, py):
            return name
    return type(value).__name__


def validate(value, schema: dict, path: str = "") -> list[str]:
    """返回人类可读的错误清单，空列表 = 通过。错误信息会被喂回给 LLM 重试，
    所以写成中文、带路径、说清楚期望值。"""
    errs: list[str] = []
    here = path or "根对象"

    types = schema.get("type")
    if types:
        names = [types] if isinstance(types, str) else list(types)
        if not any(_type_ok(value, n) for n in names):
            errs.append(f"{here}：期望 {'/'.join(names)}，实际是 {_kind(value)}")
            return errs                  # 类型都不对，再往下查只会刷屏

    if "const" in schema and value != schema["const"]:
        errs.append(f"{here}：只能是 {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        allowed = "、".join(repr(x) for x in schema["enum"])
        errs.append(f"{here}：只能取 {allowed}，实际是 {value!r}")

    if isinstance(value, str):
        n = len(value)
        if "minLength" in schema and n < schema["minLength"]:
            errs.append(f"{here}：至少 {schema['minLength']} 个字符，实际 {n}")
        if "maxLength" in schema and n > schema["maxLength"]:
            errs.append(f"{here}：最多 {schema['maxLength']} 个字符，实际 {n}，请压缩")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errs.append(f"{here}：不得小于 {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errs.append(f"{here}：不得大于 {schema['maximum']}")

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errs.append(f"{here}：至少 {schema['minItems']} 项，实际 {len(value)}")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errs.append(f"{here}：最多 {schema['maxItems']} 项，实际 {len(value)}，只留最有价值的")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for i, item in enumerate(value):
                errs += validate(item, item_schema, f"{path or ''}[{i}]")

    if isinstance(value, dict):
        props = schema.get("properties") or {}
        for key in schema.get("required") or []:
            if key not in value:
                errs.append(f"{here}：缺少必填字段 {key!r}")
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in props:
                    errs.append(f"{here}：不认识的字段 {key!r}，契约里没有这一项")
        for key, sub in props.items():
            if key in value and isinstance(sub, dict):
                errs += validate(value[key], sub, f"{path}.{key}" if path else key)

    return errs


def load(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ---------------- 由 schema 反推出的字段骨架（拼进提示词，防止契约与提示词走岔）----------------
def _leaf(schema: dict) -> str:
    if "enum" in schema:
        return "|".join(f'"{x}"' for x in schema["enum"])
    t = schema.get("type", "any")
    if isinstance(t, list):
        t = "/".join(t)
    lim = ""
    if "maxLength" in schema:
        lim = f" ≤{schema['maxLength']}字"
    elif "maximum" in schema:
        lim = f" ≤{schema['maximum']}"
    return f"{t}{lim}"


def _sketch(schema: dict, indent: int = 2) -> str:
    pad = " " * indent
    t = schema.get("type")
    if t == "array":
        item = schema.get("items") or {}
        count = ""
        if "maxItems" in schema:
            count = f"   // 最多 {schema['maxItems']} 项"
        if schema.get("minItems"):
            count = f"   // {schema['minItems']}-{schema.get('maxItems', '∞')} 项"
        if item.get("type") == "object":
            return f"[\n{pad}  {_sketch(item, indent + 4)}\n{pad}]{count}"
        return f"[{_leaf(item)}, ...]{count.replace('   // ', '，共 ')}"
    if t != "object":
        return _leaf(schema)
    req = set(schema.get("required") or [])
    lines = []
    for key, sub in (schema.get("properties") or {}).items():
        body = _sketch(sub, indent + 2)
        mark = "  ← 必填" if key in req else ""
        desc = sub.get("description", "")
        if desc and "\n" in body:              # 多行的值：注释单独一行放在键前面，读起来才顺
            lines.append(f"{pad}// {desc}")
            lines.append(f'{pad}"{key}": {body}{mark}')
        else:
            note = f"   // {desc}" if desc else ""
            lines.append(f'{pad}"{key}": {body}{mark}{note}')
    return "{\n" + "\n".join(lines) + f"\n{' ' * (indent - 2)}}}"


def outline(schema: dict, skip: tuple[str, ...] = ()) -> str:
    """把 schema 渲染成给 LLM 看的字段骨架。skip 里的顶层字段不出现在骨架里
    （meta 由代码填，不该让模型产出）。"""
    trimmed = dict(schema)
    trimmed["properties"] = {
        k: v for k, v in (schema.get("properties") or {}).items() if k not in skip
    }
    trimmed["required"] = [k for k in (schema.get("required") or []) if k not in skip]
    return _sketch(trimmed)
