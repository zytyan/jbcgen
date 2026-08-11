#ifndef JSON_PULL_H
#define JSON_PULL_H

#include "json_str_slice.h"
#include "json_tokenizer.h"
#include <stdbool.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

bool json_decode_null(json_parser *parser);

bool json_decode_bool(json_parser *parser, bool *out);

bool json_decode_char(json_parser *parser, char *out);
bool json_decode_signed_char(json_parser *parser, signed char *out);
bool json_decode_unsigned_char(json_parser *parser, unsigned char *out);
bool json_decode_short(json_parser *parser, short *out);
bool json_decode_unsigned_short(json_parser *parser, unsigned short *out);
bool json_decode_int(json_parser *parser, int *out);
bool json_decode_unsigned_int(json_parser *parser, unsigned int *out);
bool json_decode_long(json_parser *parser, long *out);
bool json_decode_unsigned_long(json_parser *parser, unsigned long *out);
bool json_decode_long_long(json_parser *parser, long long *out);
bool json_decode_unsigned_long_long(json_parser *parser, unsigned long long *out);
bool json_decode_float(json_parser *parser, float *out);
bool json_decode_double(json_parser *parser, double *out);

bool json_decode_string(json_parser *parser, json_cow_str *out);

bool json_array_begin(json_parser *parser);

bool json_array_try_end(json_parser *parser);

bool json_object_begin(json_parser *parser);

bool json_object_try_end(json_parser *parser);

// 必须消费逗号；不存在时设置 JSON_ERROR_SYNTAX_EXPECTED_COMMA。
bool json_consume_comma(json_parser *parser);

// 对象键和值之间必须存在冒号。
bool json_consume_colon(json_parser *parser);

bool json_skip_value(json_parser *parser);

#ifdef __cplusplus
}
#endif

#endif
