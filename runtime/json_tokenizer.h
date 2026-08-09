#ifndef JSON_TOKENIZER
#define JSON_TOKENIZER

#include <stdint.h>

#include "json_allocator.h"
#include "json_error.h"
#include "json_str_slice.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct json_token {
    json_str_slice str;
    json_token_kind kind;
    json_source_location location;
} json_token;

struct json_parser {
    json_allocator *allocator;

    const char *begin;
    const char *cursor;
    const char *end;
    json_source_location cursor_location;
    json_token current_token;
    int32_t depth;
    int32_t max_depth;
    size_t max_number_len;
    json_error error;
    bool valid;
};

const char *token_kind_name(json_token_kind kind);

void json_advance_token(json_parser *parser);

json_token *json_peek_token(json_parser *parser);

// 空格，回车，制表符，若可能，也有注释
void json_skip_trivia(json_parser *parser);

void json_parser_init(json_parser *parser, json_allocator *allocator, json_str_slice input);

#ifdef __cplusplus
}
#endif

#endif
