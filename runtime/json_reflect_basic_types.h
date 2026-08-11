#ifndef JSON_REFLECT_BASIC_TYPES_H
#define JSON_REFLECT_BASIC_TYPES_H

#include <limits.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef uint8_t json_reflect_basic_id;

enum {
    JSON_REFLECT_BASIC_ID_NONE,
    JSON_REFLECT_BASIC_ID_BOOL,
    JSON_REFLECT_BASIC_ID_CHAR,
    JSON_REFLECT_BASIC_ID_SIGNED_CHAR,
    JSON_REFLECT_BASIC_ID_UNSIGNED_CHAR,
    JSON_REFLECT_BASIC_ID_SHORT,
    JSON_REFLECT_BASIC_ID_UNSIGNED_SHORT,
    JSON_REFLECT_BASIC_ID_INT,
    JSON_REFLECT_BASIC_ID_UNSIGNED_INT,
    JSON_REFLECT_BASIC_ID_LONG,
    JSON_REFLECT_BASIC_ID_UNSIGNED_LONG,
    JSON_REFLECT_BASIC_ID_LONG_LONG,
    JSON_REFLECT_BASIC_ID_UNSIGNED_LONG_LONG,
    JSON_REFLECT_BASIC_ID_FLOAT,
    JSON_REFLECT_BASIC_ID_DOUBLE,
};

struct json_reflect_type;

extern const struct json_reflect_type json_reflect_type_bool;
extern const struct json_reflect_type json_reflect_type_char;
extern const struct json_reflect_type json_reflect_type_signed_char;
extern const struct json_reflect_type json_reflect_type_unsigned_char;
extern const struct json_reflect_type json_reflect_type_short;
extern const struct json_reflect_type json_reflect_type_unsigned_short;
extern const struct json_reflect_type json_reflect_type_int;
extern const struct json_reflect_type json_reflect_type_unsigned_int;
extern const struct json_reflect_type json_reflect_type_long;
extern const struct json_reflect_type json_reflect_type_unsigned_long;
extern const struct json_reflect_type json_reflect_type_long_long;
extern const struct json_reflect_type json_reflect_type_unsigned_long_long;
extern const struct json_reflect_type json_reflect_type_float;
extern const struct json_reflect_type json_reflect_type_double;

#define JSON_REFLECT_BASIC_ID(value)                                                               \
    _Generic((value),                                                                              \
        _Bool: JSON_REFLECT_BASIC_ID_BOOL,                                                         \
        char: JSON_REFLECT_BASIC_ID_CHAR,                                                          \
        signed char: JSON_REFLECT_BASIC_ID_SIGNED_CHAR,                                            \
        unsigned char: JSON_REFLECT_BASIC_ID_UNSIGNED_CHAR,                                        \
        short: JSON_REFLECT_BASIC_ID_SHORT,                                                        \
        unsigned short: JSON_REFLECT_BASIC_ID_UNSIGNED_SHORT,                                      \
        int: JSON_REFLECT_BASIC_ID_INT,                                                            \
        unsigned int: JSON_REFLECT_BASIC_ID_UNSIGNED_INT,                                          \
        long: JSON_REFLECT_BASIC_ID_LONG,                                                          \
        unsigned long: JSON_REFLECT_BASIC_ID_UNSIGNED_LONG,                                        \
        long long: JSON_REFLECT_BASIC_ID_LONG_LONG,                                                \
        unsigned long long: JSON_REFLECT_BASIC_ID_UNSIGNED_LONG_LONG,                              \
        float: JSON_REFLECT_BASIC_ID_FLOAT,                                                        \
        double: JSON_REFLECT_BASIC_ID_DOUBLE)

#define JSON_REFLECT_BASIC_SIGNED(value)                                                           \
    _Generic((value),                                                                              \
        _Bool: 0,                                                                                  \
        char: (CHAR_MIN < 0 ? JSON_REFLECT_SIGNED : 0),                                            \
        signed char: JSON_REFLECT_SIGNED,                                                          \
        unsigned char: 0,                                                                          \
        short: JSON_REFLECT_SIGNED,                                                                \
        unsigned short: 0,                                                                         \
        int: JSON_REFLECT_SIGNED,                                                                  \
        unsigned int: 0,                                                                           \
        long: JSON_REFLECT_SIGNED,                                                                 \
        unsigned long: 0,                                                                          \
        long long: JSON_REFLECT_SIGNED,                                                            \
        unsigned long long: 0,                                                                     \
        float: JSON_REFLECT_SIGNED,                                                                \
        double: JSON_REFLECT_SIGNED)

#define JSON_REFLECT_BASIC_TYPE(value)                                                             \
    _Generic((value),                                                                              \
        _Bool: &json_reflect_type_bool,                                                            \
        char: &json_reflect_type_char,                                                             \
        signed char: &json_reflect_type_signed_char,                                               \
        unsigned char: &json_reflect_type_unsigned_char,                                           \
        short: &json_reflect_type_short,                                                           \
        unsigned short: &json_reflect_type_unsigned_short,                                         \
        int: &json_reflect_type_int,                                                               \
        unsigned int: &json_reflect_type_unsigned_int,                                             \
        long: &json_reflect_type_long,                                                             \
        unsigned long: &json_reflect_type_unsigned_long,                                           \
        long long: &json_reflect_type_long_long,                                                   \
        unsigned long long: &json_reflect_type_unsigned_long_long,                                 \
        float: &json_reflect_type_float,                                                           \
        double: &json_reflect_type_double)

#ifdef __cplusplus
}
#endif

#endif
