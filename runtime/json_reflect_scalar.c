#include "json_reflect_internal.h"

#include <string.h>

typedef union json_reflect_integer_value {
    char char_value;
    signed char signed_char_value;
    unsigned char unsigned_char_value;
    short short_value;
    unsigned short unsigned_short_value;
    int int_value;
    unsigned int unsigned_int_value;
    long long_value;
    unsigned long unsigned_long_value;
    long long long_long_value;
    unsigned long long unsigned_long_long_value;
} json_reflect_integer_value;

static bool decode_integer(json_parser *parser, const json_reflect_type *type,
                           json_reflect_integer_value *value)
{
    switch (type->basic_id) {
    case JSON_REFLECT_BASIC_ID_CHAR:
        return json_decode_char(parser, &value->char_value);
    case JSON_REFLECT_BASIC_ID_SIGNED_CHAR:
        return json_decode_signed_char(parser, &value->signed_char_value);
    case JSON_REFLECT_BASIC_ID_UNSIGNED_CHAR:
        return json_decode_unsigned_char(parser, &value->unsigned_char_value);
    case JSON_REFLECT_BASIC_ID_SHORT:
        return json_decode_short(parser, &value->short_value);
    case JSON_REFLECT_BASIC_ID_UNSIGNED_SHORT:
        return json_decode_unsigned_short(parser, &value->unsigned_short_value);
    case JSON_REFLECT_BASIC_ID_INT:
        return json_decode_int(parser, &value->int_value);
    case JSON_REFLECT_BASIC_ID_UNSIGNED_INT:
        return json_decode_unsigned_int(parser, &value->unsigned_int_value);
    case JSON_REFLECT_BASIC_ID_LONG:
        return json_decode_long(parser, &value->long_value);
    case JSON_REFLECT_BASIC_ID_UNSIGNED_LONG:
        return json_decode_unsigned_long(parser, &value->unsigned_long_value);
    case JSON_REFLECT_BASIC_ID_LONG_LONG:
        return json_decode_long_long(parser, &value->long_long_value);
    case JSON_REFLECT_BASIC_ID_UNSIGNED_LONG_LONG:
        return json_decode_unsigned_long_long(parser, &value->unsigned_long_long_value);
    default:
        break;
    }
    json_set_error(parser, JSON_ERROR_OTHER_INVALID_STATE, NULL);
    return false;
}

static int64_t signed_value(const json_reflect_type *type, const json_reflect_integer_value *value)
{
    switch (type->basic_id) {
    case JSON_REFLECT_BASIC_ID_CHAR:
        return value->char_value;
    case JSON_REFLECT_BASIC_ID_SIGNED_CHAR:
        return value->signed_char_value;
    case JSON_REFLECT_BASIC_ID_SHORT:
        return value->short_value;
    case JSON_REFLECT_BASIC_ID_INT:
        return value->int_value;
    case JSON_REFLECT_BASIC_ID_LONG:
        return value->long_value;
    default:
        return value->long_long_value;
    }
}

static uint64_t unsigned_value(const json_reflect_type *type,
                               const json_reflect_integer_value *value)
{
    switch (type->basic_id) {
    case JSON_REFLECT_BASIC_ID_CHAR:
        return (unsigned char)value->char_value;
    case JSON_REFLECT_BASIC_ID_UNSIGNED_CHAR:
        return value->unsigned_char_value;
    case JSON_REFLECT_BASIC_ID_UNSIGNED_SHORT:
        return value->unsigned_short_value;
    case JSON_REFLECT_BASIC_ID_UNSIGNED_INT:
        return value->unsigned_int_value;
    case JSON_REFLECT_BASIC_ID_UNSIGNED_LONG:
        return value->unsigned_long_value;
    default:
        return value->unsigned_long_long_value;
    }
}

static bool integer_in_range(const json_reflect_type *type,
                             const json_reflect_constraints *constraints,
                             const json_reflect_integer_value *value)
{
    if (constraints == NULL) {
        return true;
    }
    const uint32_t flags = constraints->flags;
    if ((flags & (JSON_REFLECT_MIN_FAIL | JSON_REFLECT_MAX_FAIL)) != 0) {
        return false;
    }
    if ((type->flags & JSON_REFLECT_SIGNED) != 0) {
        const int64_t number = signed_value(type, value);
        return ((flags & JSON_REFLECT_HAS_MIN) == 0 ||
                number >= constraints->minimum.signed_value) &&
               ((flags & JSON_REFLECT_HAS_MAX) == 0 || number <= constraints->maximum.signed_value);
    }
    const uint64_t number = unsigned_value(type, value);
    return ((flags & JSON_REFLECT_HAS_MIN) == 0 || number >= constraints->minimum.unsigned_value) &&
           ((flags & JSON_REFLECT_HAS_MAX) == 0 || number <= constraints->maximum.unsigned_value);
}

static bool decode_float(json_parser *parser, const json_reflect_type *type,
                         const json_reflect_constraints *constraints, void *out,
                         json_source_location location, json_error_span span)
{
    double number;
    if (type->basic_id == JSON_REFLECT_BASIC_ID_FLOAT) {
        float narrowed;
        if (!json_decode_float(parser, &narrowed)) {
            return false;
        }
        memcpy(out, &narrowed, sizeof(narrowed));
        number = narrowed;
    } else if (type->basic_id == JSON_REFLECT_BASIC_ID_DOUBLE) {
        if (!json_decode_double(parser, &number)) {
            return false;
        }
        memcpy(out, &number, sizeof(number));
    } else {
        json_set_error(parser, JSON_ERROR_OTHER_INVALID_STATE, NULL);
        return false;
    }
    if (constraints == NULL) {
        return true;
    }
    const uint32_t flags = constraints->flags;
    const bool invalid =
        (flags & (JSON_REFLECT_MIN_FAIL | JSON_REFLECT_MAX_FAIL)) != 0 ||
        ((flags & JSON_REFLECT_HAS_MIN) != 0 && number < constraints->minimum.float_value) ||
        ((flags & JSON_REFLECT_HAS_MAX) != 0 && number > constraints->maximum.float_value);
    if (invalid) {
        json_reflect_number_error(parser, location, span);
    }
    return !invalid;
}

bool json_reflect_decode_scalar(json_parser *parser, const json_reflect_type *type,
                                const json_reflect_constraints *constraints, void *out)
{
    if (type->kind == JSON_REFLECT_BOOL) {
        bool value = false;
        if (!json_decode_bool(parser, &value)) {
            return false;
        }
        memcpy(out, &value, sizeof(value));
        return true;
    }

    const json_token *token = json_peek_token(parser);
    const json_source_location location = token->location;
    const json_error_span span = {token->str.ptr, token->str.ptr + token->str.len};
    if (type->kind == JSON_REFLECT_FLOAT) {
        return decode_float(parser, type, constraints, out, location, span);
    }

    json_reflect_integer_value value = {0};
    if (!decode_integer(parser, type, &value)) {
        return false;
    }
    memcpy(out, &value, type->size);
    if (integer_in_range(type, constraints, &value)) {
        return true;
    }
    json_reflect_number_error(parser, location, span);
    return false;
}

bool json_reflect_decode_string(json_parser *parser, const json_reflect_type *type,
                                const json_reflect_constraints *constraints, void *out)
{
    if (type->capacity == 0 && json_peek_token(parser)->kind == JSON_TOKEN_NULL) {
        return json_decode_null(parser);
    }

    const json_source_location location = json_peek_token(parser)->location;
    json_cow_str string = {0};
    if (!json_decode_string(parser, &string)) {
        return false;
    }
    const json_slice slice = json_cow_str_as_slice(&string);
    if (memchr(slice.ptr, '\0', slice.len) != NULL) {
        json_free_cow_str(parser->allocator, &string);
        json_set_error_at(parser, JSON_ERROR_OTHER_EMBEDDED_NUL, NULL, location);
        return false;
    }
    if (!json_reflect_check_length(parser, constraints, slice.len, JSON_RANGE_STRING_LENGTH,
                                   location) ||
        (type->capacity != 0 && slice.len >= type->capacity)) {
        if (parser->error.code == JSON_ERROR_NONE) {
            json_reflect_length_error(parser, JSON_RANGE_STRING_LENGTH, type->capacity - 1,
                                      location);
        }
        json_free_cow_str(parser->allocator, &string);
        return false;
    }

    if (type->capacity != 0) {
        size_t written = 0;
        (void)json_slice_write_to_buf(&slice, (char *)out, type->capacity, &written);
        json_free_cow_str(parser->allocator, &string);
        return true;
    }

    char *owned = NULL;
    const json_error_code code = json_cow_str_into_owned_c_str(parser->allocator, &string, &owned);
    if (code != JSON_ERROR_NONE) {
        json_free_cow_str(parser->allocator, &string);
        json_set_error_at(parser, code, NULL, location);
        return false;
    }
    memcpy(out, &owned, sizeof(owned));
    return true;
}
