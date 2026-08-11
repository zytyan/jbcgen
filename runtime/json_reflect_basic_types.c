#include "json_reflect.h"

#include <limits.h>

#define BASIC_TYPE(name, type_kind, basic_kind, c_type, type_flags)                                \
    const json_reflect_type json_reflect_type_##name = {                                           \
        .kind = type_kind,                                                                         \
        .basic_id = basic_kind,                                                                    \
        .bits = sizeof(c_type) * CHAR_BIT,                                                         \
        .flags = type_flags,                                                                       \
        .size = sizeof(c_type),                                                                    \
        .capacity = 0,                                                                             \
        .target = NULL,                                                                            \
        .record = NULL,                                                                            \
    }

BASIC_TYPE(bool, JSON_REFLECT_BOOL, JSON_REFLECT_BASIC_ID_BOOL, _Bool, 0);
BASIC_TYPE(char, JSON_REFLECT_INTEGER, JSON_REFLECT_BASIC_ID_CHAR, char,
           CHAR_MIN < 0 ? JSON_REFLECT_SIGNED : 0);
BASIC_TYPE(signed_char, JSON_REFLECT_INTEGER, JSON_REFLECT_BASIC_ID_SIGNED_CHAR, signed char,
           JSON_REFLECT_SIGNED);
BASIC_TYPE(unsigned_char, JSON_REFLECT_INTEGER, JSON_REFLECT_BASIC_ID_UNSIGNED_CHAR, unsigned char,
           0);
BASIC_TYPE(short, JSON_REFLECT_INTEGER, JSON_REFLECT_BASIC_ID_SHORT, short, JSON_REFLECT_SIGNED);
BASIC_TYPE(unsigned_short, JSON_REFLECT_INTEGER, JSON_REFLECT_BASIC_ID_UNSIGNED_SHORT,
           unsigned short, 0);
BASIC_TYPE(int, JSON_REFLECT_INTEGER, JSON_REFLECT_BASIC_ID_INT, int, JSON_REFLECT_SIGNED);
BASIC_TYPE(unsigned_int, JSON_REFLECT_INTEGER, JSON_REFLECT_BASIC_ID_UNSIGNED_INT, unsigned int, 0);
BASIC_TYPE(long, JSON_REFLECT_INTEGER, JSON_REFLECT_BASIC_ID_LONG, long, JSON_REFLECT_SIGNED);
BASIC_TYPE(unsigned_long, JSON_REFLECT_INTEGER, JSON_REFLECT_BASIC_ID_UNSIGNED_LONG, unsigned long,
           0);
BASIC_TYPE(long_long, JSON_REFLECT_INTEGER, JSON_REFLECT_BASIC_ID_LONG_LONG, long long,
           JSON_REFLECT_SIGNED);
BASIC_TYPE(unsigned_long_long, JSON_REFLECT_INTEGER, JSON_REFLECT_BASIC_ID_UNSIGNED_LONG_LONG,
           unsigned long long, 0);
BASIC_TYPE(float, JSON_REFLECT_FLOAT, JSON_REFLECT_BASIC_ID_FLOAT, float, JSON_REFLECT_SIGNED);
BASIC_TYPE(double, JSON_REFLECT_FLOAT, JSON_REFLECT_BASIC_ID_DOUBLE, double, JSON_REFLECT_SIGNED);

#undef BASIC_TYPE
