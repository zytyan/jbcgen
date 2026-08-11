#ifndef JSON_REFLECT_INTERNAL_H
#define JSON_REFLECT_INTERNAL_H

#include "json_any_vec.h"
#include "json_reflect.h"

static inline unsigned char *json_reflect_at(void *base, size_t offset)
{
    return (unsigned char *)base + offset;
}

static inline const unsigned char *json_reflect_const_at(
    const void *base,
    size_t offset
)
{
    return (const unsigned char *)base + offset;
}

void json_reflect_context_error(
    json_parser *parser,
    json_error_code code,
    json_slice key,
    json_source_location location
);

void json_reflect_length_error(
    json_parser *parser,
    json_range_target target,
    size_t limit,
    json_source_location location
);

void json_reflect_number_error(
    json_parser *parser,
    json_source_location location,
    json_error_span value
);

void json_reflect_no_memory(json_parser *parser);

bool json_reflect_load_count(
    const json_reflect_type *type,
    const void *value,
    size_t *out
);

bool json_reflect_store_count(
    json_parser *parser,
    const json_reflect_type *type,
    void *value,
    size_t count,
    json_source_location location
);

size_t json_reflect_count_limit(const json_reflect_type *type);

bool json_reflect_check_length(
    json_parser *parser,
    const json_reflect_constraints *constraints,
    size_t length,
    json_range_target target,
    json_source_location location
);

bool json_reflect_decode_scalar(
    json_parser *parser,
    const json_reflect_type *type,
    const json_reflect_constraints *constraints,
    void *out
);

bool json_reflect_decode_string(
    json_parser *parser,
    const json_reflect_type *type,
    const json_reflect_constraints *constraints,
    void *out
);

bool json_reflect_decode_array(
    json_parser *parser,
    const json_reflect_type *type,
    const json_reflect_constraints *constraints,
    void *out,
    void *count_out,
    const json_reflect_type *count_type
);

bool json_reflect_decode_array_record(
    json_parser *parser,
    const json_reflect_type *type,
    void *out
);

bool json_reflect_decode_object(
    json_parser *parser,
    const json_reflect_type *type,
    void *out
);

bool json_reflect_decode_value(
    json_parser *parser,
    const json_reflect_type *type,
    const json_reflect_constraints *constraints,
    void *out,
    void *count_out,
    const json_reflect_type *count_type
);

#endif
