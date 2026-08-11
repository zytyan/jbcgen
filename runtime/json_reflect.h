#ifndef JSON_REFLECT_H
#define JSON_REFLECT_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "json_key_dispatch.h"
#include "json_pull.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum json_reflect_kind {
    JSON_REFLECT_BOOL,
    JSON_REFLECT_INTEGER,
    JSON_REFLECT_FLOAT,
    JSON_REFLECT_ENUM,
    JSON_REFLECT_STRING,
    JSON_REFLECT_FIXED_ARRAY,
    JSON_REFLECT_DYNAMIC_ARRAY,
    JSON_REFLECT_RECORD,
    JSON_REFLECT_POINTER,
} json_reflect_kind;

typedef enum json_reflect_record_shape {
    JSON_REFLECT_OBJECT,
    JSON_REFLECT_ARRAY,
} json_reflect_record_shape;

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
} json_reflect_type;

extern const json_reflect_type json_reflect_type_bool;
extern const json_reflect_type json_reflect_type_i8;
extern const json_reflect_type json_reflect_type_i16;
extern const json_reflect_type json_reflect_type_i32;
extern const json_reflect_type json_reflect_type_i64;
extern const json_reflect_type json_reflect_type_u8;
extern const json_reflect_type json_reflect_type_u16;
extern const json_reflect_type json_reflect_type_u32;
extern const json_reflect_type json_reflect_type_u64;
extern const json_reflect_type json_reflect_type_f32;
extern const json_reflect_type json_reflect_type_f64;

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

/* Destination storage must be zero initialized. It is restored to zero on failure. */
bool json_reflect_decode(
    json_parser *parser,
    const json_reflect_type *type,
    void *out
);

/* Releasing an already-zero value is valid. */
void json_reflect_release(
    json_allocator *allocator,
    const json_reflect_type *type,
    void *value
);

#ifdef __cplusplus
}
#endif

#endif
