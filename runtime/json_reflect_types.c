#include "json_reflect.h"

#define JSON_REFLECT_BASIC_TYPE(name, type_kind, width, type_flags, c_type) \
    const json_reflect_type name = {                                    \
        .kind = type_kind,                                               \
        .bits = width,                                                   \
        .flags = type_flags,                                             \
        .size = sizeof(c_type),                                          \
    }

JSON_REFLECT_BASIC_TYPE(
    json_reflect_type_bool, JSON_REFLECT_BOOL, 8, 0, bool
);
JSON_REFLECT_BASIC_TYPE(
    json_reflect_type_i8, JSON_REFLECT_INTEGER, 8, JSON_REFLECT_SIGNED, int8_t
);
JSON_REFLECT_BASIC_TYPE(
    json_reflect_type_i16,
    JSON_REFLECT_INTEGER,
    16,
    JSON_REFLECT_SIGNED,
    int16_t
);
JSON_REFLECT_BASIC_TYPE(
    json_reflect_type_i32,
    JSON_REFLECT_INTEGER,
    32,
    JSON_REFLECT_SIGNED,
    int32_t
);
JSON_REFLECT_BASIC_TYPE(
    json_reflect_type_i64,
    JSON_REFLECT_INTEGER,
    64,
    JSON_REFLECT_SIGNED,
    int64_t
);
JSON_REFLECT_BASIC_TYPE(
    json_reflect_type_u8, JSON_REFLECT_INTEGER, 8, 0, uint8_t
);
JSON_REFLECT_BASIC_TYPE(
    json_reflect_type_u16, JSON_REFLECT_INTEGER, 16, 0, uint16_t
);
JSON_REFLECT_BASIC_TYPE(
    json_reflect_type_u32, JSON_REFLECT_INTEGER, 32, 0, uint32_t
);
JSON_REFLECT_BASIC_TYPE(
    json_reflect_type_u64, JSON_REFLECT_INTEGER, 64, 0, uint64_t
);
JSON_REFLECT_BASIC_TYPE(
    json_reflect_type_f32, JSON_REFLECT_FLOAT, 32, 0, float
);
JSON_REFLECT_BASIC_TYPE(
    json_reflect_type_f64, JSON_REFLECT_FLOAT, 64, 0, double
);

#undef JSON_REFLECT_BASIC_TYPE
