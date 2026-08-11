#include "json_reflect_internal.h"

#include <string.h>

void json_reflect_context_error(
    json_parser *parser,
    json_error_code code,
    json_slice key,
    json_source_location location
)
{
    json_error_detail detail = {0};
    detail.other.context.begin = key.ptr;
    detail.other.context.end = key.ptr + key.len;
    json_set_error_at(parser, code, &detail, location);
}

void json_reflect_length_error(
    json_parser *parser,
    json_range_target target,
    size_t limit,
    json_source_location location
)
{
    json_error_detail detail = {0};
    detail.range.target = target;
    detail.range.limit = limit;
    const json_error_code code = target == JSON_RANGE_STRING_LENGTH
                                     ? JSON_ERROR_RANGE_STRING_LENGTH
                                     : JSON_ERROR_RANGE_ARRAY_LENGTH;
    json_set_error_at(parser, code, &detail, location);
}

void json_reflect_number_error(
    json_parser *parser,
    json_source_location location,
    json_error_span value
)
{
    json_error_detail detail = {0};
    detail.range.target = JSON_RANGE_NUMBER_VALUE;
    detail.range.value = value;
    json_set_error_at(parser, JSON_ERROR_RANGE_NUMBER, &detail, location);
}

void json_reflect_no_memory(json_parser *parser)
{
    json_set_error(parser, JSON_ERROR_OTHER_NO_MEMORY, NULL);
}

bool json_reflect_load_count(
    const json_reflect_type *type,
    const void *value,
    size_t *out
)
{
    uint64_t count;
    switch (type->bits) {
    case 8: {
        uint8_t item;
        memcpy(&item, value, sizeof(item));
        count = item;
        break;
    }
    case 16: {
        uint16_t item;
        memcpy(&item, value, sizeof(item));
        count = item;
        break;
    }
    case 32: {
        uint32_t item;
        memcpy(&item, value, sizeof(item));
        count = item;
        break;
    }
    case 64:
        memcpy(&count, value, sizeof(count));
        break;
    default:
        return false;
    }
#if SIZE_MAX < UINT64_MAX
    if (count > SIZE_MAX) return false;
#endif
    *out = (size_t)count;
    return true;
}

bool json_reflect_store_count(
    json_parser *parser,
    const json_reflect_type *type,
    void *value,
    size_t count,
    json_source_location location
)
{
    const size_t limit = json_reflect_count_limit(type);
    if (count > limit) {
        json_reflect_length_error(
            parser, JSON_RANGE_ARRAY_LENGTH, limit, location
        );
        return false;
    }
    switch (type->bits) {
    case 8: {
        const uint8_t item = (uint8_t)count;
        memcpy(value, &item, sizeof(item));
        return true;
    }
    case 16: {
        const uint16_t item = (uint16_t)count;
        memcpy(value, &item, sizeof(item));
        return true;
    }
    case 32: {
        const uint32_t item = (uint32_t)count;
        memcpy(value, &item, sizeof(item));
        return true;
    }
    case 64: {
        const uint64_t item = count;
        memcpy(value, &item, sizeof(item));
        return true;
    }
    default:
        json_set_error(parser, JSON_ERROR_OTHER_INVALID_STATE, NULL);
        return false;
    }
}

size_t json_reflect_count_limit(const json_reflect_type *type)
{
    if (type == NULL || type->bits >= sizeof(size_t) * 8) {
        return SIZE_MAX;
    }
    return ((size_t)1 << type->bits) - 1;
}

bool json_reflect_check_length(
    json_parser *parser,
    const json_reflect_constraints *constraints,
    size_t length,
    json_range_target target,
    json_source_location location
)
{
    if (constraints == NULL) {
        return true;
    }
    if ((constraints->flags & JSON_REFLECT_HAS_MIN_LENGTH) != 0 &&
        length < constraints->min_length) {
        json_reflect_length_error(
            parser, target, constraints->min_length, location
        );
        return false;
    }
    if ((constraints->flags & JSON_REFLECT_HAS_MAX_LENGTH) != 0 &&
        length > constraints->max_length) {
        json_reflect_length_error(
            parser, target, constraints->max_length, location
        );
        return false;
    }
    return true;
}
