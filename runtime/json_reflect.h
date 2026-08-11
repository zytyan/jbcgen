#ifndef JSON_REFLECT_H
#define JSON_REFLECT_H

#include <stdbool.h>
#include <limits.h>
#include <stddef.h>
#include <stdint.h>

#include "json_key_dispatch.h"
#include "json_pull.h"
#include "json_reflect_basic_types.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef uint8_t json_reflect_kind;

enum {
    JSON_REFLECT_BOOL,
    JSON_REFLECT_INTEGER,
    JSON_REFLECT_FLOAT,
    JSON_REFLECT_ENUM,
    JSON_REFLECT_STRING,
    JSON_REFLECT_FIXED_ARRAY,
    JSON_REFLECT_DYNAMIC_ARRAY,
    JSON_REFLECT_RECORD,
    JSON_REFLECT_POINTER,
};

typedef uint8_t json_reflect_record_shape;

enum {
    JSON_REFLECT_OBJECT,
    JSON_REFLECT_ARRAY,
};

enum {
    JSON_REFLECT_SIGNED = 1u << 0,
    JSON_REFLECT_REQUIRED = 1u << 1,
    JSON_REFLECT_HAS_MIN = 1u << 2,
    JSON_REFLECT_HAS_MAX = 1u << 3,
    JSON_REFLECT_MIN_FAIL = 1u << 4,
    JSON_REFLECT_MAX_FAIL = 1u << 5,
    JSON_REFLECT_HAS_MIN_LENGTH = 1u << 6,
    JSON_REFLECT_HAS_MAX_LENGTH = 1u << 7,
};

typedef union json_reflect_number {
    int64_t signed_value;
    uint64_t unsigned_value;
    double float_value;
} json_reflect_number;

typedef struct json_reflect_constraints {
    uint32_t flags;
    json_reflect_number minimum;
    json_reflect_number maximum;
    size_t min_length;
    size_t max_length;
} json_reflect_constraints;

struct json_reflect_record;

typedef struct json_reflect_type {
    json_reflect_kind kind;
    uint8_t bits;
    uint8_t flags;
    size_t size;
    size_t capacity;
    const struct json_reflect_type *target;
    const struct json_reflect_record *record;
    json_reflect_basic_id basic_id;
} json_reflect_type;

typedef struct json_reflect_field {
    json_slice primary_key;
    size_t offset;
    const json_reflect_type *type;
    const json_reflect_constraints *constraints;
    size_t count_offset;
    const json_reflect_type *count_type;
    uint32_t flags;
} json_reflect_field;

typedef struct json_reflect_storage {
    size_t offset;
    const json_reflect_type *type;
    size_t count_offset;
    const json_reflect_type *count_type;
} json_reflect_storage;

typedef struct json_reflect_array_layout {
    size_t elems_offset;
    const json_reflect_type *element_type;
    size_t length_offset;
    const json_reflect_type *length_type;
    size_t capacity_offset;
    const json_reflect_type *capacity_type;
} json_reflect_array_layout;

typedef struct json_reflect_record {
    json_reflect_record_shape shape;
    size_t size;
    json_key_map keys;
    const json_reflect_field *fields;
    size_t field_count;
    const json_reflect_storage *storage;
    size_t storage_count;
    const json_reflect_array_layout *array;
} json_reflect_record;

#define JSON_REFLECT_ABI_VERSION 1

#define JSON_REFLECT_ABI_SYMBOL_IMPL(version) json_reflect_check_abi_v##version
#define JSON_REFLECT_ABI_SYMBOL(version) JSON_REFLECT_ABI_SYMBOL_IMPL(version)

bool JSON_REFLECT_ABI_SYMBOL(JSON_REFLECT_ABI_VERSION)(uint64_t signature);

static inline uint64_t json_reflect_compile_abi_signature(void)
{
    uint64_t hash = UINT64_C(1469598103934665603);

#define JSON_REFLECT_ABI_MIX(value)                                            \
    do {                                                                       \
        hash ^= (uint64_t)(value);                                             \
        hash *= UINT64_C(1099511628211);                                       \
    } while (0)

#ifdef __cplusplus
#define JSON_REFLECT_ABI_ALIGNOF(type) alignof(type)
#else
#define JSON_REFLECT_ABI_ALIGNOF(type) _Alignof(type)
#endif

    JSON_REFLECT_ABI_MIX(CHAR_MIN < 0);
    JSON_REFLECT_ABI_MIX(CHAR_BIT);
    JSON_REFLECT_ABI_MIX(sizeof(short));
    JSON_REFLECT_ABI_MIX(JSON_REFLECT_ABI_ALIGNOF(short));
    JSON_REFLECT_ABI_MIX(sizeof(int));
    JSON_REFLECT_ABI_MIX(JSON_REFLECT_ABI_ALIGNOF(int));
    JSON_REFLECT_ABI_MIX(sizeof(long));
    JSON_REFLECT_ABI_MIX(JSON_REFLECT_ABI_ALIGNOF(long));
    JSON_REFLECT_ABI_MIX(sizeof(long long));
    JSON_REFLECT_ABI_MIX(JSON_REFLECT_ABI_ALIGNOF(long long));
    JSON_REFLECT_ABI_MIX(sizeof(float));
    JSON_REFLECT_ABI_MIX(JSON_REFLECT_ABI_ALIGNOF(float));
    JSON_REFLECT_ABI_MIX(sizeof(double));
    JSON_REFLECT_ABI_MIX(JSON_REFLECT_ABI_ALIGNOF(double));
    JSON_REFLECT_ABI_MIX(sizeof(void *));
    JSON_REFLECT_ABI_MIX(JSON_REFLECT_ABI_ALIGNOF(void *));
    JSON_REFLECT_ABI_MIX(sizeof(size_t));
    JSON_REFLECT_ABI_MIX(JSON_REFLECT_ABI_ALIGNOF(size_t));
    JSON_REFLECT_ABI_MIX(sizeof(json_reflect_type));
    JSON_REFLECT_ABI_MIX(JSON_REFLECT_ABI_ALIGNOF(json_reflect_type));
    JSON_REFLECT_ABI_MIX(offsetof(json_reflect_type, size));
    JSON_REFLECT_ABI_MIX(offsetof(json_reflect_type, target));
    JSON_REFLECT_ABI_MIX(offsetof(json_reflect_type, basic_id));
    JSON_REFLECT_ABI_MIX(sizeof(json_reflect_record));
    JSON_REFLECT_ABI_MIX(JSON_REFLECT_ABI_ALIGNOF(json_reflect_record));
    JSON_REFLECT_ABI_MIX(offsetof(json_reflect_record, keys));
    JSON_REFLECT_ABI_MIX(offsetof(json_reflect_record, fields));
    JSON_REFLECT_ABI_MIX(offsetof(json_reflect_record, array));
    JSON_REFLECT_ABI_MIX(sizeof(json_reflect_field));
    JSON_REFLECT_ABI_MIX(JSON_REFLECT_ABI_ALIGNOF(json_reflect_field));
    JSON_REFLECT_ABI_MIX(offsetof(json_reflect_field, type));
    JSON_REFLECT_ABI_MIX(offsetof(json_reflect_field, flags));
    JSON_REFLECT_ABI_MIX(sizeof(json_parser));
    JSON_REFLECT_ABI_MIX(JSON_REFLECT_ABI_ALIGNOF(json_parser));
    JSON_REFLECT_ABI_MIX(offsetof(json_parser, current_token));
    JSON_REFLECT_ABI_MIX(offsetof(json_parser, error));
    JSON_REFLECT_ABI_MIX(offsetof(json_parser, valid));
    JSON_REFLECT_ABI_MIX(sizeof(json_error));
    JSON_REFLECT_ABI_MIX(JSON_REFLECT_ABI_ALIGNOF(json_error));
    JSON_REFLECT_ABI_MIX(offsetof(json_error, detail));
    JSON_REFLECT_ABI_MIX(sizeof(json_cow_str));
    JSON_REFLECT_ABI_MIX(JSON_REFLECT_ABI_ALIGNOF(json_cow_str));
    JSON_REFLECT_ABI_MIX(offsetof(json_cow_str, kind));
    JSON_REFLECT_ABI_MIX(sizeof(json_key_entry));
    JSON_REFLECT_ABI_MIX(JSON_REFLECT_ABI_ALIGNOF(json_key_entry));
    JSON_REFLECT_ABI_MIX(offsetof(json_key_entry, id));

#undef JSON_REFLECT_ABI_ALIGNOF
#undef JSON_REFLECT_ABI_MIX

    return hash;
}

#define JSON_REFLECT_ABI_CHECK()                                               \
    JSON_REFLECT_ABI_SYMBOL(JSON_REFLECT_ABI_VERSION)(                         \
        json_reflect_compile_abi_signature())

/* Destination storage must be zero initialized. It is restored to zero on
 * failure. */
bool json_reflect_decode(json_parser *parser, const json_reflect_type *type, void *out);

/* Releasing an already-zero value is valid. */
void json_reflect_release(json_allocator *allocator, const json_reflect_type *type, void *value);

#ifdef __cplusplus
}
#endif

#endif
