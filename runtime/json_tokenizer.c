#include <stddef.h>
#include <string.h>

#include "json_pull.h"

static bool char_is_space(char c)
{
    return c == ' ' || c == '\t' || c == '\r' || c == '\n';
}

static bool char_is_digit(char c)
{
    return c >= '0' && c <= '9';
}

static void advance_cursor(json_parser *parser)
{
    if (parser->cursor >= parser->end) {
        return;
    }
    if (*parser->cursor == '\r') {
        parser->cursor++;
        parser->cursor_location.offset++;
        if (parser->cursor < parser->end && *parser->cursor == '\n') {
            parser->cursor++;
            parser->cursor_location.offset++;
        }
        parser->cursor_location.line++;
        parser->cursor_location.column = 1;
    } else if (*parser->cursor == '\n') {
        parser->cursor++;
        parser->cursor_location.offset++;
        parser->cursor_location.line++;
        parser->cursor_location.column = 1;
    } else {
        parser->cursor++;
        parser->cursor_location.offset++;
        parser->cursor_location.column++;
    }
}

static void advance_ascii(json_parser *parser, size_t count)
{
    parser->cursor += count;
    parser->cursor_location.offset += count;
    parser->cursor_location.column += count;
}

static void set_token_error(json_parser *parser, json_token *token, const char *pos, json_error_code code,
                            const json_error_detail *detail)
{
    token->kind = JSON_TOKEN_ERROR;
    token->str.begin = pos;
    token->str.end = pos;
    token->location = json_location_at(parser, pos);
    json_set_error_at(parser, code, detail, token->location);
}

static bool char_is_value_end(char c)
{
    return char_is_space(c) || c == ',' || c == ']' || c == '}';
}

void json_skip_trivia(json_parser *parser)
{
    while (parser->cursor < parser->end && char_is_space(*parser->cursor)) {
        advance_cursor(parser);
    }
}

static bool char_is_float_feature(char c)
{
    return c == '.' || c == 'e' || c == 'E';
}

static bool char_is_number(char c)
{
    return char_is_digit(c) || char_is_float_feature(c) || c == '+' || c == '-';
}

static bool try_tokenize_keyword(json_parser *parser, const char *keyword, json_token *token, json_token_kind kind)
{
    const char *begin = parser->cursor;
    size_t len = strlen(keyword);
    if ((size_t)(parser->end - begin) < len || memcmp(begin, keyword, len) != 0) {
        return false;
    }

    const char *end = begin + len;
    if (end < parser->end && !char_is_value_end(*end)) {
        json_error_detail detail = {0};
        detail.syntax.character = (unsigned char)*end;
        set_token_error(parser, token, end, JSON_ERROR_SYNTAX_INVALID_KEYWORD, &detail);
        return true;
    }

    advance_ascii(parser, len);
    token->kind = kind;
    token->str.begin = begin;
    token->str.end = end;
    return true;
}

static void tokenize_str(json_parser *parser, json_token *token)
{
    const char *begin = parser->cursor;
    const char *end = parser->end;
    json_source_location begin_location = parser->cursor_location;

    advance_cursor(parser);
    token->kind = JSON_TOKEN_STRING;
    while (parser->cursor < end) {
        unsigned char ch = (unsigned char)*parser->cursor;
        if (ch == '"') {
            advance_cursor(parser);
            token->str.begin = begin;
            token->str.end = parser->cursor;
            token->location = begin_location;
            return;
        }
        if (ch < 0x20) {
            json_error_detail detail = {0};
            detail.syntax.character = ch;
            set_token_error(parser, token, parser->cursor, JSON_ERROR_SYNTAX_UNESCAPED_CONTROL, &detail);
            return;
        }
        if (ch == '\\') {
            token->kind = JSON_TOKEN_ESCAPE_STRING;
            advance_cursor(parser);
            if (parser->cursor >= end) {
                break;
            }
        }
        advance_cursor(parser);
    }

    set_token_error(parser, token, parser->cursor, JSON_ERROR_SYNTAX_UNTERMINATED_STRING, NULL);
}

static void tokenize_number(json_parser *parser, json_token *token)
{
    bool is_float = false;
    const char *begin = parser->cursor;
    const char *cursor = parser->cursor;
    while (cursor < parser->end && char_is_number(*cursor)) {
        if (char_is_float_feature(*cursor)) {
            is_float = true;
        }
        cursor++;
    }
    advance_ascii(parser, (size_t)(cursor - parser->cursor));
    token->str.begin = begin;
    token->str.end = cursor;
    token->kind = is_float ? JSON_TOKEN_FLOAT : JSON_TOKEN_INT;
}

static void tokenize_punc(json_parser *parser, json_token *token)
{
    const char *begin = parser->cursor;
    switch (*begin) {
        case '[':
            token->kind = JSON_TOKEN_LBRACKET;
            break;
        case ']':
            token->kind = JSON_TOKEN_RBRACKET;
            break;
        case '{':
            token->kind = JSON_TOKEN_LBRACE;
            break;
        case '}':
            token->kind = JSON_TOKEN_RBRACE;
            break;
        case ',':
            token->kind = JSON_TOKEN_COMMA;
            break;
        case ':':
            token->kind = JSON_TOKEN_COLON;
            break;
        default:
            if ((*begin >= 'a' && *begin <= 'z') || (*begin >= 'A' && *begin <= 'Z')) {
                set_token_error(parser, token, begin, JSON_ERROR_SYNTAX_INVALID_KEYWORD, NULL);
            } else {
                json_error_detail detail = {0};
                detail.syntax.character = (unsigned char)*begin;
                set_token_error(parser, token, begin, JSON_ERROR_SYNTAX_UNKNOWN_CHARACTER, &detail);
            }
            return;
    }
    advance_cursor(parser);
    token->str.begin = begin;
    token->str.end = parser->cursor;
}

static void json_next_token_impl(json_parser *parser, json_token *token)
{
    json_skip_trivia(parser);
    token->location = parser->cursor_location;
    if (parser->cursor >= parser->end) {
        token->kind = JSON_TOKEN_EOF;
        token->str.begin = parser->end;
        token->str.end = parser->end;
        return;
    }

    if (try_tokenize_keyword(parser, "null", token, JSON_TOKEN_NULL) ||
        try_tokenize_keyword(parser, "true", token, JSON_TOKEN_TRUE) ||
        try_tokenize_keyword(parser, "false", token, JSON_TOKEN_FALSE)) {
        return;
    }

    char c = *parser->cursor;
    if (c == '"') {
        tokenize_str(parser, token);
    } else if (c == '-' || char_is_digit(c)) {
        tokenize_number(parser, token);
    } else {
        tokenize_punc(parser, token);
    }
}

void json_advance_token(json_parser *parser)
{
    json_token token = {0};
    if (!parser->valid) {
        token.kind = JSON_TOKEN_ERROR;
        token.str.begin = parser->cursor;
        token.str.end = parser->cursor;
        token.location = parser->error.location;
        parser->current_token = token;
        return;
    }
    json_next_token_impl(parser, &token);
    parser->current_token = token;
}

json_token *json_peek_token(json_parser *parser)
{
    return &parser->current_token;
}

const char *token_kind_name(json_token_kind kind)
{
    switch (kind) {
        case JSON_TOKEN_EOF:
            return "EOF";
        case JSON_TOKEN_ERROR:
            return "ERROR";
        case JSON_TOKEN_NULL:
            return "NULL";
        case JSON_TOKEN_TRUE:
            return "TRUE";
        case JSON_TOKEN_FALSE:
            return "FALSE";
        case JSON_TOKEN_ESCAPE_STRING:
            return "ESCAPE_STRING";
        case JSON_TOKEN_FLOAT:
            return "NUMBER";
        case JSON_TOKEN_INT:
            return "INT";
        case JSON_TOKEN_STRING:
            return "STRING";
        case JSON_TOKEN_LBRACKET:
            return "LBRACKET";
        case JSON_TOKEN_RBRACKET:
            return "RBRACKET";
        case JSON_TOKEN_LBRACE:
            return "LBRACE";
        case JSON_TOKEN_RBRACE:
            return "RBRACE";
        case JSON_TOKEN_COLON:
            return "COLON";
        case JSON_TOKEN_COMMA:
            return "COMMA";
        default:
            return "UNKNOWN";
    }
}
