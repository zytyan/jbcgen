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
    uint16_t abi_version;
    uint16_t struct_size;
    uint64_t abi_signature;
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

#define JSON_REFLECT_ABI_VERSION UINT16_C(1)
#define JSON_REFLECT_ABI_MIX(seed, value)                                      \
    (((seed) ^ (uint64_t)(value)) * UINT64_C(1099511628211))
#define JSON_REFLECT_ABI_HASH_0 UINT64_C(1469598103934665603)
#define JSON_REFLECT_ABI_HASH_1                                                \
    JSON_REFLECT_ABI_MIX(JSON_REFLECT_ABI_HASH_0, CHAR_MIN < 0)
#define JSON_REFLECT_ABI_HASH_2                                                \
    JSON_REFLECT_ABI_MIX(JSON_REFLECT_ABI_HASH_1, sizeof(json_reflect_type))
#define JSON_REFLECT_ABI_HASH_3                                                \
    JSON_REFLECT_ABI_MIX(JSON_REFLECT_ABI_HASH_2, offsetof(json_reflect_type, size))
#define JSON_REFLECT_ABI_HASH_4                                                \
    JSON_REFLECT_ABI_MIX(JSON_REFLECT_ABI_HASH_3, offsetof(json_reflect_type, target))
#define JSON_REFLECT_ABI_HASH_5                                                \
    JSON_REFLECT_ABI_MIX(JSON_REFLECT_ABI_HASH_4, offsetof(json_reflect_type, basic_id))
#define JSON_REFLECT_ABI_HASH_6                                                \
    JSON_REFLECT_ABI_MIX(JSON_REFLECT_ABI_HASH_5, sizeof(json_reflect_record))
#define JSON_REFLECT_ABI_HASH_7                                                \
    JSON_REFLECT_ABI_MIX(JSON_REFLECT_ABI_HASH_6, offsetof(json_reflect_record, keys))
#define JSON_REFLECT_ABI_HASH_8                                                \
    JSON_REFLECT_ABI_MIX(JSON_REFLECT_ABI_HASH_7, offsetof(json_reflect_record, fields))
#define JSON_REFLECT_ABI_HASH_9                                                \
    JSON_REFLECT_ABI_MIX(JSON_REFLECT_ABI_HASH_8, offsetof(json_reflect_record, array))
#define JSON_REFLECT_ABI_HASH_10                                               \
    JSON_REFLECT_ABI_MIX(JSON_REFLECT_ABI_HASH_9, sizeof(json_reflect_field))
#define JSON_REFLECT_ABI_HASH_11                                               \
    JSON_REFLECT_ABI_MIX(JSON_REFLECT_ABI_HASH_10, offsetof(json_reflect_field, type))
#define JSON_REFLECT_ABI_HASH_12                                               \
    JSON_REFLECT_ABI_MIX(JSON_REFLECT_ABI_HASH_11, offsetof(json_reflect_field, flags))
#define JSON_REFLECT_ABI_HASH_13                                               \
    JSON_REFLECT_ABI_MIX(JSON_REFLECT_ABI_HASH_12, sizeof(json_parser))
#define JSON_REFLECT_ABI_HASH_14                                               \
    JSON_REFLECT_ABI_MIX(JSON_REFLECT_ABI_HASH_13, offsetof(json_parser, current_token))
#define JSON_REFLECT_ABI_HASH_15                                               \
    JSON_REFLECT_ABI_MIX(JSON_REFLECT_ABI_HASH_14, offsetof(json_parser, error))
#define JSON_REFLECT_ABI_HASH_16                                               \
    JSON_REFLECT_ABI_MIX(JSON_REFLECT_ABI_HASH_15, offsetof(json_parser, valid))
#define JSON_REFLECT_ABI_HASH_17                                               \
    JSON_REFLECT_ABI_MIX(JSON_REFLECT_ABI_HASH_16, sizeof(json_error))
#define JSON_REFLECT_ABI_HASH_18                                               \
    JSON_REFLECT_ABI_MIX(JSON_REFLECT_ABI_HASH_17, offsetof(json_error, detail))
#define JSON_REFLECT_ABI_HASH_19                                               \
    JSON_REFLECT_ABI_MIX(JSON_REFLECT_ABI_HASH_18, sizeof(json_cow_str))
#define JSON_REFLECT_ABI_HASH_20                                               \
    JSON_REFLECT_ABI_MIX(JSON_REFLECT_ABI_HASH_19, offsetof(json_cow_str, kind))
#define JSON_REFLECT_ABI_HASH_21                                               \
    JSON_REFLECT_ABI_MIX(JSON_REFLECT_ABI_HASH_20, sizeof(json_key_entry))
#define JSON_REFLECT_ABI_SIGNATURE                                             \
    JSON_REFLECT_ABI_MIX(JSON_REFLECT_ABI_HASH_21, offsetof(json_key_entry, id))

#define JSON_REFLECT_TYPE_ABI_INIT                                             \
    .abi_version = JSON_REFLECT_ABI_VERSION,                                   \
    .struct_size = sizeof(json_reflect_type),                                  \
    .abi_signature = JSON_REFLECT_ABI_SIGNATURE

extern const unsigned char json_reflect_abi_v1;

bool json_reflect_abi_guard(const unsigned char *expected);

bool json_reflect_type_abi_compatible(const json_reflect_type *type);

/* Destination storage must be zero initialized. It is restored to zero on
 * failure. */
bool json_reflect_decode(json_parser *parser, const json_reflect_type *type, void *out);

/* Releasing an already-zero value is valid. */
void json_reflect_release(json_allocator *allocator, const json_reflect_type *type, void *value);

#ifdef __cplusplus
}
#endif

#endif
