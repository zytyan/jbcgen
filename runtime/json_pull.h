#ifndef JSON_PULL_H
#define JSON_PULL_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "json_str_slice.h"
#include "json_tokenizer.h"

#ifdef __cplusplus
extern "C" {
#endif

void json_free_nullable(const json_allocator *allocator, void *ptr);

bool json_decode_null(json_parser *parser);

bool json_decode_bool(json_parser *parser, bool *out);

bool json_decode_i8(json_parser *parser, int8_t *out);

bool json_decode_i16(json_parser *parser, int16_t *out);

bool json_decode_i32(json_parser *parser, int32_t *out);

bool json_decode_i64(json_parser *parser, int64_t *out);

bool json_decode_u8(json_parser *parser, uint8_t *out);

bool json_decode_u16(json_parser *parser, uint16_t *out);

bool json_decode_u32(json_parser *parser, uint32_t *out);

bool json_decode_u64(json_parser *parser, uint64_t *out);

bool json_decode_hex_string(json_parser *parser, uint64_t *out);

bool json_decode_f64(json_parser *parser, double *out);

bool json_decode_string(json_parser *parser, json_cow_str *out);

bool json_array_begin(json_parser *parser);

bool json_array_try_end(json_parser *parser);

bool json_object_begin(json_parser *parser);

bool json_object_try_end(json_parser *parser);

bool json_try_consume_comma(json_parser *parser);

// 必须消费逗号；不存在时设置 JSON_ERROR_SYNTAX_EXPECTED_COMMA。
bool json_consume_comma(json_parser *parser);

// 最后一个元素没有尾随逗号，所以冒号必然要consume，但逗号不用，所以逗号仅仅try consume
bool json_consume_colon(json_parser *parser);

bool json_skip_value(json_parser *parser);

#ifdef __cplusplus
}
#endif

#endif
