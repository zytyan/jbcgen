#include "json_reflect_internal.h"

#include <string.h>

bool JSON_REFLECT_ABI_SYMBOL(JSON_REFLECT_ABI_VERSION)(uint64_t signature)
{
    return signature == json_reflect_compile_abi_signature();
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
    if (json_reflect_decode_value(parser, type, NULL, out, NULL, NULL)) {
        return true;
    }
    json_reflect_release(parser->allocator, type, out);
    memset(out, 0, type->size);
    return false;
}
