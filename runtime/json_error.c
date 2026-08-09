#include <stdarg.h>
#include <string.h>

#include <stdio.h>

#include "json_tokenizer.h"

typedef struct {
  char *cursor;
  size_t remaining;
  bool valid;
} json_error_writer;

static bool buffer_append(char **cursor, size_t *remaining, const char *text,
                          size_t text_len) {
  if (text_len >= *remaining) {
    return false;
  }
  memcpy(*cursor, text, text_len);
  *cursor += text_len;
  *remaining -= text_len;
  (*cursor)[0] = '\0';
  return true;
}

static void error_writer_append(json_error_writer *writer, const char *text,
                                size_t text_len) {
  if (!writer->valid) {
    return;
  }
  writer->valid =
      buffer_append(&writer->cursor, &writer->remaining, text, text_len);
}

static void error_writer_printf(json_error_writer *writer, const char *fmt,
                                ...) {
  if (!writer->valid) {
    return;
  }
  va_list args;
  va_start(args, fmt);
  int written = vsnprintf(writer->cursor, writer->remaining, fmt, args);
  va_end(args);
  if (written < 0 || (size_t)written >= writer->remaining) {
    writer->valid = false;
    return;
  }
  writer->cursor += (size_t)written;
  writer->remaining -= (size_t)written;
}

static const char *expected_type_name(json_expected_type type) {
  switch (type) {
  case JSON_EXPECTED_NULL:
    return "NULL";
  case JSON_EXPECTED_BOOL:
    return "BOOL";
  case JSON_EXPECTED_INTEGER:
    return "INTEGER";
  case JSON_EXPECTED_NUMBER:
    return "NUMBER";
  case JSON_EXPECTED_STRING:
    return "STRING";
  case JSON_EXPECTED_HEX_INTEGER:
    return "HEX_INTEGER";
  case JSON_EXPECTED_ARRAY:
    return "ARRAY";
  case JSON_EXPECTED_OBJECT:
    return "OBJECT";
  case JSON_EXPECTED_VALUE:
    return "VALUE";
  default:
    return "UNKNOWN";
  }
}

static size_t decimal_len(size_t value) {
  size_t len = 1;
  while (value >= 10) {
    value /= 10;
    len++;
  }
  return len;
}

static size_t error_body_len(const json_error *error) {
  switch (error->code) {
  case JSON_ERROR_SYNTAX_UNKNOWN_CHARACTER:
    return sizeof("unknown character 0x00") - 1;
  case JSON_ERROR_SYNTAX_INVALID_KEYWORD:
    return sizeof("invalid keyword") - 1;
  case JSON_ERROR_SYNTAX_UNESCAPED_CONTROL:
    return sizeof("unescaped control character 0x00 in string") - 1;
  case JSON_ERROR_SYNTAX_UNTERMINATED_STRING:
    return sizeof("unterminated string") - 1;
  case JSON_ERROR_SYNTAX_INVALID_NUMBER:
    return sizeof("invalid number") - 1;
  case JSON_ERROR_SYNTAX_INVALID_HEX:
    return sizeof("invalid hexadecimal integer") - 1;
  case JSON_ERROR_SYNTAX_EXPECTED_TOKEN:
    return sizeof("expected ") - 1 +
           strlen(token_kind_name(error->detail.syntax.expected)) +
           sizeof(", got ") - 1 +
           strlen(token_kind_name(error->detail.syntax.actual));
  case JSON_ERROR_SYNTAX_EXPECTED_COMMA:
    return sizeof("expected COMMA, got ") - 1 +
           strlen(token_kind_name(error->detail.syntax.actual));
  case JSON_ERROR_ESCAPE_INVALID_SEQUENCE:
    return sizeof("invalid escape sequence \\x") - 1;
  case JSON_ERROR_ESCAPE_INVALID_UNICODE:
    return sizeof("invalid Unicode escape") - 1;
  case JSON_ERROR_TYPE_MISMATCH:
    return sizeof("expected ") - 1 +
           strlen(expected_type_name(error->detail.type.expected)) +
           sizeof(", got ") - 1 +
           strlen(token_kind_name(error->detail.type.actual));
  case JSON_ERROR_RANGE_NUMBER:
    return sizeof("number out of range") - 1;
  case JSON_ERROR_RANGE_NUMBER_LENGTH:
    return sizeof("number length exceeds limit ") - 1 +
           decimal_len(error->detail.range.limit);
  case JSON_ERROR_RANGE_STRING_LENGTH:
    return sizeof("string length violates limit ") - 1 +
           decimal_len(error->detail.range.limit);
  case JSON_ERROR_RANGE_ARRAY_LENGTH:
    return sizeof("array length violates limit ") - 1 +
           decimal_len(error->detail.range.limit);
  case JSON_ERROR_RANGE_DEPTH:
    return sizeof("JSON depth exceeds limit ") - 1 +
           decimal_len(error->detail.range.limit);
  case JSON_ERROR_RANGE_BUFFER_TOO_SMALL:
    return sizeof("output buffer too small; need ") - 1 +
           decimal_len(error->detail.range.limit) + sizeof(" bytes") - 1;
  case JSON_ERROR_OTHER_NO_MEMORY:
    return sizeof("out of memory") - 1;
  case JSON_ERROR_OTHER_DUPLICATE_KEY: {
    size_t context_len = 0;
    if (error->detail.other.context.begin != NULL &&
        error->detail.other.context.end != NULL) {
      context_len = (size_t)(error->detail.other.context.end -
                             error->detail.other.context.begin);
    }
    return sizeof("duplicate key: ") - 1 + context_len;
  }
  case JSON_ERROR_OTHER_MISSING_REQUIRED_KEY:
  case JSON_ERROR_OTHER_NULL_REQUIRED_VALUE: {
    size_t context_len = 0;
    if (error->detail.other.context.begin != NULL &&
        error->detail.other.context.end != NULL) {
      context_len = (size_t)(error->detail.other.context.end -
                             error->detail.other.context.begin);
    }
    size_t prefix = error->code == JSON_ERROR_OTHER_MISSING_REQUIRED_KEY
                        ? sizeof("missing required key: ") - 1
                        : sizeof("required value is null: ") - 1;
    return prefix + context_len;
  }
  case JSON_ERROR_OTHER_EMBEDDED_NUL:
    return sizeof("C string contains embedded NUL") - 1;
  case JSON_ERROR_OTHER_INVALID_STATE:
    return sizeof("invalid parser state") - 1;
  case JSON_ERROR_NONE:
    return 0;
  }
  return 0;
}

size_t json_estimate_error_msg_len(const json_parser *parser) {
  if (parser == NULL || parser->error.code == JSON_ERROR_NONE) {
    return 0;
  }
  const json_error *error = &parser->error;
  return sizeof("line ") - 1 + decimal_len(error->location.line) +
         sizeof(", column ") - 1 + decimal_len(error->location.column) +
         sizeof(": ") - 1 + error_body_len(error);
}

static void render_error(const json_parser *parser, char *dst,
                         size_t dst_size) {
  json_error_writer writer = {dst, dst_size, true};
  dst[0] = '\0';
  if (parser == NULL || parser->error.code == JSON_ERROR_NONE) {
    return;
  }
  const json_error *error = &parser->error;
  error_writer_printf(&writer, "line %zu, column %zu: ", error->location.line,
                      error->location.column);
  switch (error->code) {
  case JSON_ERROR_SYNTAX_UNKNOWN_CHARACTER:
    error_writer_printf(&writer, "unknown character 0x%02X",
                        (unsigned int)error->detail.syntax.character);
    break;
  case JSON_ERROR_SYNTAX_INVALID_KEYWORD:
    error_writer_append(&writer, "invalid keyword",
                        sizeof("invalid keyword") - 1);
    break;
  case JSON_ERROR_SYNTAX_UNESCAPED_CONTROL:
    error_writer_printf(&writer, "unescaped control character 0x%02X in string",
                        (unsigned int)error->detail.syntax.character);
    break;
  case JSON_ERROR_SYNTAX_UNTERMINATED_STRING:
    error_writer_append(&writer, "unterminated string",
                        sizeof("unterminated string") - 1);
    break;
  case JSON_ERROR_SYNTAX_INVALID_NUMBER:
    error_writer_append(&writer, "invalid number",
                        sizeof("invalid number") - 1);
    break;
  case JSON_ERROR_SYNTAX_INVALID_HEX:
    error_writer_append(&writer, "invalid hexadecimal integer",
                        sizeof("invalid hexadecimal integer") - 1);
    break;
  case JSON_ERROR_SYNTAX_EXPECTED_TOKEN:
    error_writer_printf(&writer, "expected %s, got %s",
                        token_kind_name(error->detail.syntax.expected),
                        token_kind_name(error->detail.syntax.actual));
    break;
  case JSON_ERROR_SYNTAX_EXPECTED_COMMA:
    error_writer_printf(&writer, "expected COMMA, got %s",
                        token_kind_name(error->detail.syntax.actual));
    break;
  case JSON_ERROR_ESCAPE_INVALID_SEQUENCE:
    error_writer_printf(&writer, "invalid escape sequence \\%c",
                        error->detail.escape.character);
    break;
  case JSON_ERROR_ESCAPE_INVALID_UNICODE:
    error_writer_append(&writer, "invalid Unicode escape",
                        sizeof("invalid Unicode escape") - 1);
    break;
  case JSON_ERROR_TYPE_MISMATCH:
    error_writer_printf(&writer, "expected %s, got %s",
                        expected_type_name(error->detail.type.expected),
                        token_kind_name(error->detail.type.actual));
    break;
  case JSON_ERROR_RANGE_NUMBER:
    error_writer_append(&writer, "number out of range",
                        sizeof("number out of range") - 1);
    break;
  case JSON_ERROR_RANGE_NUMBER_LENGTH:
    error_writer_printf(&writer, "number length exceeds limit %zu",
                        error->detail.range.limit);
    break;
  case JSON_ERROR_RANGE_STRING_LENGTH:
    error_writer_printf(&writer, "string length violates limit %zu",
                        error->detail.range.limit);
    break;
  case JSON_ERROR_RANGE_ARRAY_LENGTH:
    error_writer_printf(&writer, "array length violates limit %zu",
                        error->detail.range.limit);
    break;
  case JSON_ERROR_RANGE_DEPTH:
    error_writer_printf(&writer, "JSON depth exceeds limit %zu",
                        error->detail.range.limit);
    break;
  case JSON_ERROR_RANGE_BUFFER_TOO_SMALL:
    error_writer_printf(&writer, "output buffer too small; need %zu bytes",
                        error->detail.range.limit);
    break;
  case JSON_ERROR_OTHER_NO_MEMORY:
    error_writer_append(&writer, "out of memory", sizeof("out of memory") - 1);
    break;
  case JSON_ERROR_OTHER_DUPLICATE_KEY:
    error_writer_append(&writer,
                        "duplicate key: ", sizeof("duplicate key: ") - 1);
    if (error->detail.other.context.begin != NULL &&
        error->detail.other.context.end != NULL) {
      error_writer_append(&writer, error->detail.other.context.begin,
                          (size_t)(error->detail.other.context.end -
                                   error->detail.other.context.begin));
    }
    break;
  case JSON_ERROR_OTHER_MISSING_REQUIRED_KEY:
  case JSON_ERROR_OTHER_NULL_REQUIRED_VALUE: {
    const char *prefix = error->code == JSON_ERROR_OTHER_MISSING_REQUIRED_KEY
                             ? "missing required key: "
                             : "required value is null: ";
    error_writer_append(&writer, prefix, strlen(prefix));
    if (error->detail.other.context.begin != NULL &&
        error->detail.other.context.end != NULL) {
      error_writer_append(&writer, error->detail.other.context.begin,
                          (size_t)(error->detail.other.context.end -
                                   error->detail.other.context.begin));
    }
    break;
  }
  case JSON_ERROR_OTHER_EMBEDDED_NUL:
    error_writer_append(&writer, "C string contains embedded NUL",
                        sizeof("C string contains embedded NUL") - 1);
    break;
  case JSON_ERROR_OTHER_INVALID_STATE:
    error_writer_append(&writer, "invalid parser state",
                        sizeof("invalid parser state") - 1);
    break;
  case JSON_ERROR_NONE:
    break;
  }
  if (!writer.valid) {
    dst[0] = '\0';
  }
}

void json_fmt_error(const json_parser *parser, char *dst) {
  if (dst != NULL) {
    render_error(parser, dst, json_estimate_error_msg_len(parser) + 1);
  }
}

json_source_location json_location_at(const json_parser *parser,
                                      const char *pos) {
  json_source_location location = {0, 1, 1};
  const char *cursor = parser->begin;
  while (cursor < pos) {
    if (*cursor == '\r') {
      cursor++;
      location.offset++;
      if (cursor < pos && *cursor == '\n') {
        cursor++;
        location.offset++;
      }
      location.line++;
      location.column = 1;
    } else if (*cursor == '\n') {
      cursor++;
      location.offset++;
      location.line++;
      location.column = 1;
    } else {
      cursor++;
      location.offset++;
      location.column++;
    }
  }
  return location;
}

void json_set_error_at(json_parser *parser, json_error_code code,
                       const json_error_detail *detail,
                       json_source_location location) {
  if (parser == NULL || code == JSON_ERROR_NONE ||
      parser->error.code != JSON_ERROR_NONE) {
    return;
  }
  parser->error.code = code;
  parser->error.location = location;
  parser->error.detail = detail == NULL ? (json_error_detail){0} : *detail;
  parser->valid = false;
}

void json_set_error(json_parser *parser, json_error_code code,
                    const json_error_detail *detail) {
  json_source_location location = parser != NULL
                                      ? parser->current_token.location
                                      : (json_source_location){0};
  json_set_error_at(parser, code, detail, location);
}
