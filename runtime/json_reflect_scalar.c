#include "json_reflect_internal.h"

#include <float.h>
#include <string.h>

typedef union json_reflect_integer_value {
    int8_t i8;
    int16_t i16;
    int32_t i32;
    int64_t i64;
    uint8_t u8;
    uint16_t u16;
    uint32_t u32;
    uint64_t u64;
} json_reflect_integer_value;

static bool decode_integer(
    json_parser *parser,
    const json_reflect_type *type,
    json_reflect_integer_value *value
)
{
    const bool is_signed = (type->flags & JSON_REFLECT_SIGNED) != 0;
    if (is_signed) {
        switch (type->bits) {
        case 8:
            return json_decode_i8(parser, &value->i8);
        case 16:
            return json_decode_i16(parser, &value->i16);
        case 32:
            return json_decode_i32(parser, &value->i32);
        case 64:
            return json_decode_i64(parser, &value->i64);
        }
    } else {
        switch (type->bits) {
        case 8:
            return json_decode_u8(parser, &value->u8);
        case 16:
            return json_decode_u16(parser, &value->u16);
        case 32:
            return json_decode_u32(parser, &value->u32);
        case 64:
            return json_decode_u64(parser, &value->u64);
        }
    }
    json_set_error(parser, JSON_ERROR_OTHER_INVALID_STATE, NULL);
    return false;
}

static int64_t signed_value(
    const json_reflect_type *type,
    const json_reflect_integer_value *value
)
{
    switch (type->bits) {
    case 8:
        return value->i8;
    case 16:
        return value->i16;
    case 32:
        return value->i32;
    default:
        return value->i64;
    }
}

static uint64_t unsigned_value(
    const json_reflect_type *type,
    const json_reflect_integer_value *value
)
{
    switch (type->bits) {
    case 8:
        return value->u8;
    case 16:
        return value->u16;
    case 32:
        return value->u32;
    default:
        return value->u64;
    }
}

static bool integer_in_range(
    const json_reflect_type *type,
    const json_reflect_constraints *constraints,
    const json_reflect_integer_value *value
)
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
               ((flags & JSON_REFLECT_HAS_MAX) == 0 ||
                number <= constraints->maximum.signed_value);
    }
    const uint64_t number = unsigned_value(type, value);
    return ((flags & JSON_REFLECT_HAS_MIN) == 0 ||
            number >= constraints->minimum.unsigned_value) &&
           ((flags & JSON_REFLECT_HAS_MAX) == 0 ||
            number <= constraints->maximum.unsigned_value);
}

static bool decode_float(
    json_parser *parser,
    const json_reflect_type *type,
    const json_reflect_constraints *constraints,
    void *out,
    json_source_location location,
    json_error_span span
)
{
    double number = 0.0;
    if (!json_decode_f64(parser, &number)) {
        return false;
    }
    if (type->bits == 32) {
        if (number < -FLT_MAX || number > FLT_MAX) {
            json_reflect_number_error(parser, location, span);
            return false;
        }
        const float narrowed = (float)number;
        memcpy(out, &narrowed, sizeof(narrowed));
        number = narrowed;
    } else {
        memcpy(out, &number, sizeof(number));
    }
    if (constraints == NULL) {
        return true;
    }
    const uint32_t flags = constraints->flags;
    const bool invalid =
        (flags & (JSON_REFLECT_MIN_FAIL | JSON_REFLECT_MAX_FAIL)) != 0 ||
        ((flags & JSON_REFLECT_HAS_MIN) != 0 &&
         number < constraints->minimum.float_value) ||
        ((flags & JSON_REFLECT_HAS_MAX) != 0 &&
         number > constraints->maximum.float_value);
    if (invalid) {
        json_reflect_number_error(parser, location, span);
    }
    return !invalid;
}

bool json_reflect_decode_scalar(
    json_parser *parser,
    const json_reflect_type *type,
    const json_reflect_constraints *constraints,
    void *out
)
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
    const json_error_span span = {
        token->str.ptr, token->str.ptr + token->str.len};
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

bool json_reflect_decode_string(
    json_parser *parser,
    const json_reflect_type *type,
    const json_reflect_constraints *constraints,
    void *out
)
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
        json_set_error_at(
            parser, JSON_ERROR_OTHER_EMBEDDED_NUL, NULL, location
        );
        return false;
    }
    if (!json_reflect_check_length(
            parser,
            constraints,
            slice.len,
            JSON_RANGE_STRING_LENGTH,
            location
        ) ||
        (type->capacity != 0 && slice.len >= type->capacity)) {
        if (parser->error.code == JSON_ERROR_NONE) {
            json_reflect_length_error(
                parser,
                JSON_RANGE_STRING_LENGTH,
                type->capacity - 1,
                location
            );
        }
        json_free_cow_str(parser->allocator, &string);
        return false;
    }

    if (type->capacity != 0) {
        size_t written = 0;
        (void)json_slice_write_to_buf(
            &slice, (char *)out, type->capacity, &written
        );
        json_free_cow_str(parser->allocator, &string);
        return true;
    }

    char *owned = NULL;
    const json_error_code code = json_cow_str_into_owned_c_str(
        parser->allocator, &string, &owned
    );
    if (code != JSON_ERROR_NONE) {
        json_free_cow_str(parser->allocator, &string);
        json_set_error_at(parser, code, NULL, location);
        return false;
    }
    memcpy(out, &owned, sizeof(owned));
    return true;
}
