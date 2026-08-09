#ifndef JSON_ERROR_H
#define JSON_ERROR_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct json_parser json_parser;

typedef enum {
    JSON_TOKEN_UNKNOWN = 0,
    JSON_TOKEN_ERROR,
    JSON_TOKEN_EOF,
    JSON_TOKEN_NULL,
    JSON_TOKEN_TRUE,
    JSON_TOKEN_FALSE,
    JSON_TOKEN_FLOAT,
    JSON_TOKEN_INT,
    JSON_TOKEN_STRING,
    JSON_TOKEN_ESCAPE_STRING,
    JSON_TOKEN_LBRACKET,
    JSON_TOKEN_RBRACKET,
    JSON_TOKEN_LBRACE,
    JSON_TOKEN_RBRACE,
    JSON_TOKEN_COLON,
    JSON_TOKEN_COMMA,
} json_token_kind;

typedef enum {
    JSON_ERROR_NONE = 0,

    JSON_ERROR_SYNTAX_UNKNOWN_CHARACTER,
    JSON_ERROR_SYNTAX_INVALID_KEYWORD,
    JSON_ERROR_SYNTAX_UNESCAPED_CONTROL,
    JSON_ERROR_SYNTAX_UNTERMINATED_STRING,
    JSON_ERROR_SYNTAX_INVALID_NUMBER,
    JSON_ERROR_SYNTAX_INVALID_HEX,
    JSON_ERROR_SYNTAX_EXPECTED_TOKEN,
    JSON_ERROR_SYNTAX_EXPECTED_COMMA,

    JSON_ERROR_ESCAPE_INVALID_SEQUENCE,
    JSON_ERROR_ESCAPE_INVALID_UNICODE,

    JSON_ERROR_TYPE_MISMATCH,

    JSON_ERROR_RANGE_NUMBER,
    JSON_ERROR_RANGE_NUMBER_LENGTH,
    JSON_ERROR_RANGE_STRING_LENGTH,
    JSON_ERROR_RANGE_ARRAY_LENGTH,
    JSON_ERROR_RANGE_DEPTH,
    JSON_ERROR_RANGE_BUFFER_TOO_SMALL,

    JSON_ERROR_OTHER_NO_MEMORY,
    JSON_ERROR_OTHER_DUPLICATE_KEY,
    JSON_ERROR_OTHER_MISSING_REQUIRED_KEY,
    JSON_ERROR_OTHER_NULL_REQUIRED_VALUE,
    JSON_ERROR_OTHER_EMBEDDED_NUL,
    JSON_ERROR_OTHER_INVALID_STATE,
} json_error_code;

typedef enum {
    JSON_EXPECTED_UNKNOWN = 0,
    JSON_EXPECTED_NULL,
    JSON_EXPECTED_BOOL,
    JSON_EXPECTED_INTEGER,
    JSON_EXPECTED_NUMBER,
    JSON_EXPECTED_STRING,
    JSON_EXPECTED_HEX_INTEGER,
    JSON_EXPECTED_ARRAY,
    JSON_EXPECTED_OBJECT,
    JSON_EXPECTED_VALUE,
} json_expected_type;

typedef enum {
    JSON_RANGE_UNKNOWN = 0,
    JSON_RANGE_NUMBER_VALUE,
    JSON_RANGE_NUMBER_LENGTH,
    JSON_RANGE_STRING_LENGTH,
    JSON_RANGE_ARRAY_LENGTH,
    JSON_RANGE_DEPTH,
    JSON_RANGE_OUTPUT_BUFFER,
} json_range_target;

typedef struct {
    const char *begin;
    const char *end;
} json_error_span;

typedef struct {
    size_t offset;
    size_t line;
    size_t column;
} json_source_location;

typedef union {
    /* The JSON_ERROR_* prefix selects the active member. */
    struct {
        json_token_kind expected;
        json_token_kind actual;
        unsigned char character;
    } syntax;
    struct {
        unsigned char character;
        size_t relative_offset;
    } escape;
    struct {
        json_expected_type expected;
        json_token_kind actual;
    } type;
    struct {
        json_range_target target;
        size_t limit;
        json_error_span value;
    } range;
    struct {
        json_error_span context;
    } other;
} json_error_detail;

typedef struct {
    json_error_code code;
    /* offset is zero-based; line and column are one-based byte positions. */
    json_source_location location;
    json_error_detail detail;
} json_error;

// 保留 parser 中的首个错误；位置取自 current_token
void json_set_error(json_parser *parser, json_error_code code, const json_error_detail *detail);

void json_set_error_at(json_parser *parser, json_error_code code, const json_error_detail *detail,
                       json_source_location location);

json_source_location json_location_at(const json_parser *parser, const char *pos);

// 返回完整错误消息的字节数，不含结尾 NUL。
size_t json_estimate_error_msg_len(const json_parser *parser);

// 一次写入完整错误消息并以 NUL 结尾；dst 至少需要 estimate + 1 字节。
void json_fmt_error(const json_parser *parser, char *dst);

#ifdef __cplusplus
}
#endif

#endif
