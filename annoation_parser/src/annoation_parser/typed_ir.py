
class TypeIR:
    extra_info: dict


# Typed IR定义
class Int(TypeIR):
    bits: int
    signed: bool


class Float(TypeIR):
    bits: int


class String(TypeIR):
    min_len: int
    max_len: int


class Array(TypeIR):
    elems_type: TypeIR
    min_len: int
    max_len: int


class Bool(TypeIR):
    pass


class Null(TypeIR):
    pass


class Object(TypeIR):
    fields: dict[str, TypeIR]
    name: str
