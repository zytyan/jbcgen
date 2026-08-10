#include <errno.h>
#include <stdlib.h>
#include "json_pull.h"
#include "json_str_slice.h"
#include "json_tokenizer.h"
void json_free_nullable(const json_allocator *allocator, void *ptr)
{
    if (ptr) {
        allocator->free(ptr);
    }
}
void json_parser_init(json_parser *parser, json_allocator *allocator, json_slice input)
{
    parser->allocator = allocator;
    parser->begin = input.ptr;
    parser->cursor = input.ptr;
    parser->end = input.ptr + input.len;
    parser->cursor_location = (json_source_location){0, 1, 1};
    parser->current_token = (json_token){0};
    parser->depth = 0;
    parser->max_depth = 1024;
    parser->max_number_len = 0;
    parser->error = (json_error){0};
    parser->valid = true;
    json_advance_token(parser);
}

static bool json_expect_token(json_parser *parser, json_token_kind kind)
{
    json_token *token = json_peek_token(parser);
    if (token->kind == kind) {
        return true;
    }
    json_error_detail detail = {0};
    detail.syntax.expected = kind;
    detail.syntax.actual = token->kind;
    json_set_error(parser, JSON_ERROR_SYNTAX_EXPECTED_TOKEN, &detail);
    return false;
}

static bool json_expect_type(json_parser *parser, json_token_kind kind, json_expected_type expected)
{
    json_token *token = json_peek_token(parser);
    if (token->kind == kind) {
        return true;
    }
    json_error_detail detail = {0};
    detail.type.expected = expected;
    detail.type.actual = token->kind;
    json_set_error(parser, JSON_ERROR_TYPE_MISMATCH, &detail);
    return false;
}

static void json_set_type_mismatch(json_parser *parser, json_expected_type expected)
{
    json_error_detail detail = {0};
    detail.type.expected = expected;
    detail.type.actual = json_peek_token(parser)->kind;
    json_set_error(parser, JSON_ERROR_TYPE_MISMATCH, &detail);
}

static bool json_consume_token(json_parser *parser, json_token_kind kind)
{
    if (json_expect_token(parser, kind)) {
        json_advance_token(parser);
        return true;
    }
    return false;
}

static bool json_try_consume_token(json_parser *parser, json_token_kind kind)
{
    if (!parser->valid) {
        return false;
    }
    if (json_peek_token(parser)->kind == kind) {
        json_advance_token(parser);
        return true;
    }
    return false;
}

static bool inc_depth_checked(json_parser *parser)
{
    if (parser->max_depth > 0 && parser->depth >= parser->max_depth) {
        json_error_detail detail = {0};
        detail.range.target = JSON_RANGE_DEPTH;
        detail.range.limit = (size_t)parser->max_depth;
        json_set_error(parser, JSON_ERROR_RANGE_DEPTH, &detail);
        return false;
    }

    parser->depth++;
    return true;
}

static bool dec_depth_checked(json_parser *parser)
{
    if (parser->depth <= 0) {
        json_set_error(parser, JSON_ERROR_OTHER_INVALID_STATE, NULL);
        return false;
    }
    parser->depth--;
    return true;
}

bool json_decode_null(json_parser *parser)
{
    if (!json_expect_type(parser, JSON_TOKEN_NULL, JSON_EXPECTED_NULL)) {
        return false;
    }
    json_advance_token(parser);
    return true;
}

bool json_decode_bool(json_parser *parser, bool *out)
{
    if (json_try_consume_token(parser, JSON_TOKEN_TRUE)) {
        *out = true;
        return true;
    } else if (json_try_consume_token(parser, JSON_TOKEN_FALSE)) {
        *out = false;
        return true;
    }
    json_set_type_mismatch(parser, JSON_EXPECTED_BOOL);
    return false;
}
union json_number {
    int64_t i64;
    uint64_t u64;
    double f64;
};

enum json_number_kind {
    JSON_NUMBER_I64,
    JSON_NUMBER_U64,
    JSON_NUMBER_F64,
};

static bool json_parse_number(json_parser *parser, json_slice *slice, enum json_number_kind kind,
                              union json_number *num)
{
#define JSON_NUMBER_STACK_SIZE 32
    size_t slen = json_slice_len(slice);
    char buf[JSON_NUMBER_STACK_SIZE];
    char *real_buf = buf;
    char *heap_buf = NULL;
    if (parser->max_number_len != 0 && slen >= parser->max_number_len) {
        json_error_detail detail = {0};
        detail.range.target = JSON_RANGE_NUMBER_LENGTH;
        detail.range.limit = parser->max_number_len;
        detail.range.value = (json_error_span){slice->ptr, slice->ptr + slice->len};
        json_set_error(parser, JSON_ERROR_RANGE_NUMBER_LENGTH, &detail);
        return false;
    }
    if (slen + 1 > sizeof(buf)) {
        heap_buf = parser->allocator->malloc(slen + 1);
        if (!heap_buf) {
            json_set_error(parser, JSON_ERROR_OTHER_NO_MEMORY, NULL);
            return false;
        }
        real_buf = heap_buf;
    }
    size_t written = 0;
    json_error_code write_code = json_slice_write_to_buf(slice, real_buf, slen + 1, &written);
    if (write_code != JSON_ERROR_NONE) {
        json_error_detail detail = {0};
        detail.range.target = JSON_RANGE_OUTPUT_BUFFER;
        detail.range.limit = written + 1;
        json_set_error(parser, write_code, &detail);
        json_free_nullable(parser->allocator, heap_buf);
        return false;
    }
    const char *const expected_end = real_buf + slen;
    char *real_end = NULL;
    long long parsed_i64 = 0;
    unsigned long long parsed_u64 = 0;
    errno = 0;
    if (kind == JSON_NUMBER_F64) {
        num->f64 = strtod(real_buf, &real_end);
    } else if (kind == JSON_NUMBER_U64) {
        parsed_u64 = strtoull(real_buf, &real_end, 0);
    } else {
        parsed_i64 = strtoll(real_buf, &real_end, 0);
    }
    bool negative_u64 = kind == JSON_NUMBER_U64 && real_buf[0] == '-' && real_end == expected_end;
    bool outside_c_type =
        (kind == JSON_NUMBER_I64 && (parsed_i64 < INT64_MIN || parsed_i64 > INT64_MAX)) ||
        (kind == JSON_NUMBER_U64 && parsed_u64 > UINT64_MAX);
    if (errno == ERANGE || negative_u64 || outside_c_type) {
        json_error_detail detail = {0};
        detail.range.target = JSON_RANGE_NUMBER_VALUE;
        detail.range.value = (json_error_span){slice->ptr, slice->ptr + slice->len};
        json_set_error(parser, JSON_ERROR_RANGE_NUMBER, &detail);
        json_free_nullable(parser->allocator, heap_buf);
        return false;
    }
    if (real_end != expected_end) {
        json_set_error(parser, JSON_ERROR_SYNTAX_INVALID_NUMBER, NULL);
        json_free_nullable(parser->allocator, heap_buf);
        return false;
    }
    if (kind == JSON_NUMBER_I64) {
        num->i64 = (int64_t)parsed_i64;
    } else if (kind == JSON_NUMBER_U64) {
        num->u64 = (uint64_t)parsed_u64;
    }
    json_free_nullable(parser->allocator, heap_buf);
    return true;
}

static void json_set_integer_range_error(json_parser *parser, const json_slice *slice)
{
    json_error_detail detail = {0};
    detail.range.target = JSON_RANGE_NUMBER_VALUE;
    detail.range.value = (json_error_span){slice->ptr, slice->ptr + slice->len};
    json_set_error(parser, JSON_ERROR_RANGE_NUMBER, &detail);
}

static bool json_decode_i64_in_range(json_parser *parser, int64_t *out, int64_t min, int64_t max)
{
    union json_number num = {0};
    json_token *token = json_peek_token(parser);
    json_slice slice;
    if (token->kind == JSON_TOKEN_STRING) {
        slice = (json_slice){token->str.ptr + 1, token->str.len - 2};
    } else {
        if (!json_expect_type(parser, JSON_TOKEN_INT, JSON_EXPECTED_INTEGER)) {
            return false;
        }
        slice = token->str;
    }
    if (!json_parse_number(parser, &slice, JSON_NUMBER_I64, &num)) {
        return false;
    }
    if (num.i64 < min || num.i64 > max) {
        json_set_integer_range_error(parser, &slice);
        return false;
    }
    *out = num.i64;
    json_advance_token(parser);
    return true;
}

bool json_decode_i8(json_parser *parser, int8_t *out)
{
    int64_t value;
    if (!json_decode_i64_in_range(parser, &value, INT8_MIN, INT8_MAX)) {
        return false;
    }
    *out = (int8_t)value;
    return true;
}

bool json_decode_i16(json_parser *parser, int16_t *out)
{
    int64_t value;
    if (!json_decode_i64_in_range(parser, &value, INT16_MIN, INT16_MAX)) {
        return false;
    }
    *out = (int16_t)value;
    return true;
}

bool json_decode_i32(json_parser *parser, int32_t *out)
{
    int64_t value;
    if (!json_decode_i64_in_range(parser, &value, INT32_MIN, INT32_MAX)) {
        return false;
    }
    *out = (int32_t)value;
    return true;
}

bool json_decode_i64(json_parser *parser, int64_t *out)
{
    return json_decode_i64_in_range(parser, out, INT64_MIN, INT64_MAX);
}

bool json_decode_u8(json_parser *parser, uint8_t *out)
{
    int64_t value;
    if (!json_decode_i64_in_range(parser, &value, 0, UINT8_MAX)) {
        return false;
    }
    *out = (uint8_t)value;
    return true;
}

bool json_decode_u16(json_parser *parser, uint16_t *out)
{
    int64_t value;
    if (!json_decode_i64_in_range(parser, &value, 0, UINT16_MAX)) {
        return false;
    }
    *out = (uint16_t)value;
    return true;
}

bool json_decode_u32(json_parser *parser, uint32_t *out)
{
    int64_t value;
    if (!json_decode_i64_in_range(parser, &value, 0, UINT32_MAX)) {
        return false;
    }
    *out = (uint32_t)value;
    return true;
}

bool json_decode_u64(json_parser *parser, uint64_t *out)
{
    union json_number num = {0};
    json_token *token = json_peek_token(parser);
    json_slice slice;
    if (token->kind == JSON_TOKEN_STRING) {
        slice = (json_slice){token->str.ptr + 1, token->str.len - 2};
    } else {
        if (!json_expect_type(parser, JSON_TOKEN_INT, JSON_EXPECTED_INTEGER)) {
            return false;
        }
        slice = token->str;
    }
    if (!json_parse_number(parser, &slice, JSON_NUMBER_U64, &num)) {
        return false;
    }
    *out = num.u64;
    json_advance_token(parser);
    return true;
}

bool json_decode_hex_string(json_parser *parser, uint64_t *out)
{
    if (out == NULL) {
        json_set_error(parser, JSON_ERROR_OTHER_INVALID_STATE, NULL);
        return false;
    }

    json_token *token = json_peek_token(parser);
    json_source_location value_location = token->location;
    json_error_span value_span = {token->str.ptr, token->str.ptr + token->str.len};
    bool is_hex_string = token->kind == JSON_TOKEN_STRING || token->kind == JSON_TOKEN_ESCAPE_STRING;
    bool is_integer = token->kind == JSON_TOKEN_INT;
    if (!is_hex_string && !is_integer) {
        json_set_type_mismatch(parser, JSON_EXPECTED_HEX_INTEGER);
        return false;
    }

    json_cow_str decoded = {0};
    if (is_hex_string) {
        if (!json_decode_string(parser, &decoded)) {
            json_free_cow_str(parser->allocator, &decoded);
            return false;
        }
    } else {
        json_cow_str_borrow(&token->str, &decoded);
    }

    char *text = NULL;
    json_error_code string_code = json_cow_str_into_owned_c_str(parser->allocator, &decoded, &text);
    if (string_code != JSON_ERROR_NONE) {
        json_free_cow_str(parser->allocator, &decoded);
        json_set_error_at(parser, string_code, NULL, value_location);
        return false;
    }

    bool has_hex_prefix = text[0] == '0' && (text[1] == 'x' || text[1] == 'X');
    bool prefix_valid = is_hex_string ? has_hex_prefix : !has_hex_prefix;
    errno = 0;
    char *end = NULL;
    unsigned long long parsed = strtoull(text, &end, is_hex_string ? 0 : 10);
    bool format_valid = prefix_valid && text[0] != '-' && end != text && *end == '\0' &&
                        (!is_hex_string || end > text + 2);
    bool out_of_range = errno == ERANGE;
    parser->allocator->free(text);

    if (out_of_range || parsed > UINT64_MAX) {
        json_error_detail detail = {0};
        detail.range.target = JSON_RANGE_NUMBER_VALUE;
        detail.range.value = value_span;
        json_set_error_at(parser, JSON_ERROR_RANGE_NUMBER, &detail, value_location);
        return false;
    }
    if (!format_valid) {
        json_set_error_at(parser, JSON_ERROR_SYNTAX_INVALID_HEX, NULL, value_location);
        return false;
    }
    if (is_integer) {
        json_advance_token(parser);
    }
    *out = (uint64_t)parsed;
    return true;
}

bool json_decode_f64(json_parser *parser, double *out)
{
    union json_number num = {0};
    json_token *token = json_peek_token(parser);
    if (token->kind == JSON_TOKEN_STRING) {
        json_slice slice = {token->str.ptr + 1, token->str.len - 2};
        if (json_parse_number(parser, &slice, JSON_NUMBER_F64, &num)) {
            *out = num.f64;
            json_advance_token(parser);
            return true;
        }
        return false;
    }
    if (token->kind != JSON_TOKEN_FLOAT && token->kind != JSON_TOKEN_INT) {
        json_set_type_mismatch(parser, JSON_EXPECTED_NUMBER);
        return false;
    }
    if (json_parse_number(parser, &token->str, JSON_NUMBER_F64, &num)) {
        *out = num.f64;
        json_advance_token(parser);
        return true;
    }
    return false;
}

bool json_decode_string(json_parser *parser, json_cow_str *out)
{
    json_token *token = json_peek_token(parser);
    if (token->kind == JSON_TOKEN_STRING) {
        json_free_cow_str(parser->allocator, out);
        json_slice inner = {token->str.ptr + 1, token->str.len - 2};
        json_cow_str_borrow(&inner, out);
        json_advance_token(parser);
        return true;
    } else if (token->kind == JSON_TOKEN_ESCAPE_STRING) {
        json_slice inner = {token->str.ptr + 1, token->str.len - 2};
        json_string decoded = {0};
        size_t error_offset = 0;
        json_error_code code = json_str_unescape(parser->allocator, &inner, &decoded, &error_offset);
        if (code != JSON_ERROR_NONE) {
            const char *error_pos = inner.ptr + error_offset;
            if (error_pos > inner.ptr + inner.len) {
                error_pos = inner.ptr + inner.len;
            }
            json_error_detail detail = {0};
            detail.escape.relative_offset = error_offset;
            if (error_pos < inner.ptr + inner.len) {
                detail.escape.character = (unsigned char)*error_pos;
            }
            json_set_error_at(parser, code, &detail, json_location_at(parser, error_pos));
            return false;
        }
        json_free_cow_str(parser->allocator, out);
        out->string = decoded;
        out->kind = JSON_COW_OWNED_STRING;
        json_advance_token(parser);
        return true;
    } else {
        json_set_type_mismatch(parser, JSON_EXPECTED_STRING);
        return false;
    }
}

bool json_array_begin(json_parser *parser)
{
    if (json_expect_type(parser, JSON_TOKEN_LBRACKET, JSON_EXPECTED_ARRAY)) {
        if (!inc_depth_checked(parser)) {
            return false;
        }
        json_advance_token(parser);
        return true;
    }
    return false;
}

bool json_array_try_end(json_parser *parser)
{
    if (parser->valid && json_peek_token(parser)->kind == JSON_TOKEN_RBRACKET) {
        if (!dec_depth_checked(parser)) {
            return false;
        }
        json_advance_token(parser);
        return true;
    }
    return false;
}

bool json_object_begin(json_parser *parser)
{
    if (json_expect_type(parser, JSON_TOKEN_LBRACE, JSON_EXPECTED_OBJECT)) {
        if (!inc_depth_checked(parser)) {
            return false;
        }
        json_advance_token(parser);
        return true;
    }
    return false;
}

bool json_object_try_end(json_parser *parser)
{
    if (parser->valid && json_peek_token(parser)->kind == JSON_TOKEN_RBRACE) {
        if (!dec_depth_checked(parser)) {
            return false;
        }
        json_advance_token(parser);
        return true;
    }
    return false;
}

bool json_try_consume_comma(json_parser *parser)
{
    return json_try_consume_token(parser, JSON_TOKEN_COMMA);
}

bool json_consume_comma(json_parser *parser)
{
    if (json_try_consume_token(parser, JSON_TOKEN_COMMA)) {
        return true;
    }
    if (parser->valid) {
        json_error_detail detail = {0};
        detail.syntax.expected = JSON_TOKEN_COMMA;
        detail.syntax.actual = json_peek_token(parser)->kind;
        json_set_error(parser, JSON_ERROR_SYNTAX_EXPECTED_COMMA, &detail);
    }
    return false;
}

// 最后一个元素没有尾随逗号，所以冒号必然要consume，但逗号不用，所以逗号仅仅try consume
bool json_consume_colon(json_parser *parser)
{
    return json_consume_token(parser, JSON_TOKEN_COLON);
}

static bool json_skip_object(json_parser *parser)
{
    if (!json_object_begin(parser)) {
        return false;
    }

    if (json_object_try_end(parser)) {
        return true;
    }

    while (true) {
        // key
        json_token_kind key_kind = json_peek_token(parser)->kind;
        if (key_kind != JSON_TOKEN_STRING && key_kind != JSON_TOKEN_ESCAPE_STRING) {
            json_error_detail detail = {0};
            detail.syntax.expected = JSON_TOKEN_STRING;
            detail.syntax.actual = key_kind;
            json_set_error(parser, JSON_ERROR_SYNTAX_EXPECTED_TOKEN, &detail);
            return false;
        }
        json_advance_token(parser);
        // :
        if (!json_consume_colon(parser)) {
            return false;
        }
        // value
        if (!json_skip_value(parser)) {
            return false;
        }
        if (json_object_try_end(parser)) {
            return true;
        }
        if (!json_consume_token(parser, JSON_TOKEN_COMMA)) {
            return false;
        }
    }
}

static bool json_skip_array(json_parser *parser)
{
    if (!json_array_begin(parser)) {
        return false;
    }
    if (json_array_try_end(parser)) {
        return true;
    }
    while (true) {
        if (!json_skip_value(parser)) {
            return false;
        }
        if (json_array_try_end(parser)) {
            return true;
        }
        if (!json_consume_token(parser, JSON_TOKEN_COMMA)) {
            return false;
        }
    }
}

bool json_skip_value(json_parser *parser)
{
    if (!parser->valid) {
        return false;
    }

    json_token_kind kind = json_peek_token(parser)->kind;

    switch (kind) {
        case JSON_TOKEN_NULL:
        case JSON_TOKEN_TRUE:
        case JSON_TOKEN_FALSE:
        case JSON_TOKEN_INT:
        case JSON_TOKEN_FLOAT:
        case JSON_TOKEN_STRING:
        case JSON_TOKEN_ESCAPE_STRING:
            json_advance_token(parser);
            return true;

        case JSON_TOKEN_LBRACKET:
            return json_skip_array(parser);

        case JSON_TOKEN_LBRACE:
            return json_skip_object(parser);

        default:
            json_set_type_mismatch(parser, JSON_EXPECTED_VALUE);
            return false;
    }
}
