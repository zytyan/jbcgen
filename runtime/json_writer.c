#include "json_writer.h"

#include <math.h>
#include <string.h>

#include <stdio.h>

void json_writer_init(json_writer *writer, char *buf, size_t size, int indent) {
  *writer = (json_writer){
      .buf = buf,
      .size = size,
      .written = 0,
      .indent = indent,
      .valid = size == 0 || buf != NULL,
  };
  if (size > 0 && buf != NULL) {
    buf[0] = '\0';
  }
}

bool json_writer_write_raw(json_writer *writer, const char *value, size_t len) {
  if (!writer->valid || (value == NULL && len != 0)) {
    writer->valid = false;
    return false;
  }

  size_t room = 0;
  if (writer->size > 0 && writer->written < writer->size - 1) {
    room = writer->size - 1 - writer->written;
  }
  size_t copy_len = len < room ? len : room;
  if (copy_len != 0) {
    memcpy(writer->buf + writer->written, value, copy_len);
    writer->written += copy_len;
  }
  if (writer->size > 0 && writer->buf != NULL) {
    writer->buf[writer->written] = '\0';
  }
  if (copy_len != len) {
    writer->valid = false;
    return false;
  }
  return true;
}

bool json_writer_write_char(json_writer *writer, char value) {
  return json_writer_write_raw(writer, &value, 1);
}

bool json_writer_write_cstr(json_writer *writer, const char *value) {
  if (value == NULL) {
    writer->valid = false;
    return false;
  }
  return json_writer_write_raw(writer, value, strlen(value));
}

bool json_writer_write_string(json_writer *writer, const char *value) {
  static const char hex[] = "0123456789abcdef";
  if (value == NULL || !json_writer_write_char(writer, '"')) {
    writer->valid = false;
    return false;
  }

  for (const unsigned char *cursor = (const unsigned char *)value;
       *cursor != '\0'; cursor++) {
    const char *escape = NULL;
    switch (*cursor) {
    case '"':
      escape = "\\\"";
      break;
    case '\\':
      escape = "\\\\";
      break;
    case '\b':
      escape = "\\b";
      break;
    case '\f':
      escape = "\\f";
      break;
    case '\n':
      escape = "\\n";
      break;
    case '\r':
      escape = "\\r";
      break;
    case '\t':
      escape = "\\t";
      break;
    default:
      break;
    }
    if (escape != NULL) {
      if (!json_writer_write_raw(writer, escape, 2)) {
        return false;
      }
    } else if (*cursor < 0x20) {
      char encoded[] = {
          '\\', 'u', '0', '0', hex[*cursor >> 4], hex[*cursor & 0x0f]};
      if (!json_writer_write_raw(writer, encoded, sizeof(encoded))) {
        return false;
      }
    } else if (!json_writer_write_char(writer, (char)*cursor)) {
      return false;
    }
  }
  return json_writer_write_char(writer, '"');
}

bool json_writer_write_bool(json_writer *writer, bool value) {
  return value ? json_writer_write_raw(writer, "true", 4)
               : json_writer_write_raw(writer, "false", 5);
}

bool json_writer_write_i64(json_writer *writer, int64_t value) {
  char number[32];
  int len = snprintf(number, sizeof(number), "%lld", (long long)value);
  if (len < 0 || (size_t)len >= sizeof(number)) {
    writer->valid = false;
    return false;
  }
  return json_writer_write_raw(writer, number, (size_t)len);
}

bool json_writer_write_hex_u64(json_writer *writer, uint64_t value) {
  char number[32];
  int len =
      snprintf(number, sizeof(number), "\"0x%llx\"", (unsigned long long)value);
  if (len < 0 || (size_t)len >= sizeof(number)) {
    writer->valid = false;
    return false;
  }
  return json_writer_write_raw(writer, number, (size_t)len);
}

bool json_writer_write_f64(json_writer *writer, double value) {
  if (!isfinite(value)) {
    writer->valid = false;
    return false;
  }
  char number[32];
  int len = snprintf(number, sizeof(number), "%.17g", value);
  if (len < 0 || (size_t)len >= sizeof(number)) {
    writer->valid = false;
    return false;
  }
  return json_writer_write_raw(writer, number, (size_t)len);
}

bool json_writer_newline_indent(json_writer *writer, size_t depth) {
  if (writer->indent == 0) {
    return writer->valid;
  }
  if (!json_writer_write_char(writer, '\n')) {
    return false;
  }

  size_t count = depth;
  char whitespace = '\t';
  if (writer->indent > 0) {
    whitespace = ' ';
    if ((size_t)writer->indent > SIZE_MAX / (depth == 0 ? 1 : depth)) {
      writer->valid = false;
      return false;
    }
    count = depth * (size_t)writer->indent;
  }
  for (size_t i = 0; i < count; i++) {
    if (!json_writer_write_char(writer, whitespace)) {
      return false;
    }
  }
  return true;
}

bool json_writer_finish(json_writer *writer, size_t *written) {
  if (written == NULL) {
    writer->valid = false;
    return false;
  }
  if (writer->size > 0 && writer->buf != NULL) {
    writer->buf[writer->written] = '\0';
  }
  *written = writer->written;
  return writer->valid;
}
