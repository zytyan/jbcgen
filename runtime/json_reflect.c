#include "json_reflect_internal.h"

#include <string.h>

const unsigned char json_reflect_abi_v1 = 1;

_Static_assert(sizeof(json_reflect_type) <= UINT16_MAX, "json_reflect_type is too large");

bool json_reflect_abi_guard(const unsigned char *expected)
{
    return expected == &json_reflect_abi_v1;
}

bool json_reflect_type_abi_compatible(const json_reflect_type *type)
{
    return type != NULL && type->abi_version == JSON_REFLECT_ABI_VERSION &&
           type->struct_size == sizeof(json_reflect_type) &&
           type->abi_signature == JSON_REFLECT_ABI_SIGNATURE;
}

static bool check_pointer_target(
    json_parser *parser,
    const json_reflect_type *target
)
{
    if (target->kind != JSON_REFLECT_RECORD) {
        return true;
    }
    const bool is_array = target->record->shape == JSON_REFLECT_ARRAY;
    const json_token_kind expected =
        is_array ? JSON_TOKEN_LBRACKET : JSON_TOKEN_LBRACE;
    if (json_peek_token(parser)->kind == expected) {
        return true;
    }
    json_error_detail detail = {0};
    detail.type.expected = is_array ? JSON_EXPECTED_ARRAY : JSON_EXPECTED_OBJECT;
    detail.type.actual = json_peek_token(parser)->kind;
    json_set_error(parser, JSON_ERROR_TYPE_MISMATCH, &detail);
    return false;
}

static bool decode_pointer(
    json_parser *parser,
    const json_reflect_type *type,
    void *out
)
{
    if (json_peek_token(parser)->kind == JSON_TOKEN_NULL) {
        return json_decode_null(parser);
    }
    if (!check_pointer_target(parser, type->target)) {
        return false;
    }

    void *pointer = parser->allocator->malloc(type->target->size);
    if (pointer == NULL) {
        json_reflect_no_memory(parser);
        return false;
    }
    memset(pointer, 0, type->target->size);
    if (!json_reflect_decode_value(
            parser, type->target, NULL, pointer, NULL, NULL
        )) {
        json_reflect_release(parser->allocator, type->target, pointer);
        parser->allocator->free(pointer);
        return false;
    }
    memcpy(out, &pointer, sizeof(pointer));
    return true;
}

bool json_reflect_decode_value(
    json_parser *parser,
    const json_reflect_type *type,
    const json_reflect_constraints *constraints,
    void *out,
    void *count_out,
    const json_reflect_type *count_type
)
{
    switch (type->kind) {
    case JSON_REFLECT_BOOL:
    case JSON_REFLECT_INTEGER:
    case JSON_REFLECT_FLOAT:
    case JSON_REFLECT_ENUM:
        return json_reflect_decode_scalar(parser, type, constraints, out);
    case JSON_REFLECT_STRING:
        return json_reflect_decode_string(parser, type, constraints, out);
    case JSON_REFLECT_FIXED_ARRAY:
    case JSON_REFLECT_DYNAMIC_ARRAY:
        return json_reflect_decode_array(
            parser, type, constraints, out, count_out, count_type
        );
    case JSON_REFLECT_POINTER:
        return decode_pointer(parser, type, out);
    case JSON_REFLECT_RECORD:
        return type->record->shape == JSON_REFLECT_ARRAY
                   ? json_reflect_decode_array_record(parser, type, out)
                   : json_reflect_decode_object(parser, type, out);
    }
    json_set_error(parser, JSON_ERROR_OTHER_INVALID_STATE, NULL);
    return false;
}

bool json_reflect_decode(
    json_parser *parser,
    const json_reflect_type *type,
    void *out
)
{
    if (parser == NULL || type == NULL || out == NULL) {
        return false;
    }
    if (!json_reflect_type_abi_compatible(type)) {
        json_set_error(parser, JSON_ERROR_OTHER_ABI_MISMATCH, NULL);
        return false;
    }
    if (json_reflect_decode_value(parser, type, NULL, out, NULL, NULL)) {
        return true;
    }
    json_reflect_release(parser->allocator, type, out);
    memset(out, 0, type->size);
    return false;
}
