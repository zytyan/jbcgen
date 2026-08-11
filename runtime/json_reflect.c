#include "json_reflect.h"

#include <float.h>
#include <string.h>

#include "json_any_vec.h"

static unsigned char *json_reflect_at(void *base, size_t offset)
{
    return (unsigned char *)base + offset;
}

static const unsigned char *json_reflect_const_at(const void *base, size_t offset)
{
    return (const unsigned char *)base + offset;
}

static void json_reflect_context_error(
    json_parser *parser,
    json_error_code code,
    json_slice key,
    json_source_location location
)
{
    json_error_detail detail = {0};
    detail.other.context.begin = key.ptr;
    detail.other.context.end = key.ptr + key.len;
    json_set_error_at(parser, code, &detail, location);
}

static void json_reflect_length_error(
    json_parser *parser,
    json_range_target target,
    size_t limit,
    json_source_location location
)
{
    json_error_detail detail = {0};
    detail.range.target = target;
    detail.range.limit = limit;
    json_set_error_at(
        parser,
        target == JSON_RANGE_STRING_LENGTH ? JSON_ERROR_RANGE_STRING_LENGTH
                                           : JSON_ERROR_RANGE_ARRAY_LENGTH,
        &detail,
        location
    );
}

static void json_reflect_number_error(
    json_parser *parser,
    json_source_location location,
    json_error_span value
)
{
    json_error_detail detail = {0};
    detail.range.target = JSON_RANGE_NUMBER_VALUE;
    detail.range.value = value;
    json_set_error_at(parser, JSON_ERROR_RANGE_NUMBER, &detail, location);
}

static void json_reflect_no_memory(json_parser *parser)
{
    json_set_error(parser, JSON_ERROR_OTHER_NO_MEMORY, NULL);
}

static bool json_reflect_load_count(
    const json_reflect_type *type,
    const void *value,
    size_t *out
)
{
    uint64_t number = 0;
    switch (type->bits) {
    case 8: {
        uint8_t item = 0;
        memcpy(&item, value, sizeof(item));
        number = item;
        break;
    }
    case 16: {
        uint16_t item = 0;
        memcpy(&item, value, sizeof(item));
        number = item;
        break;
    }
    case 32: {
        uint32_t item = 0;
        memcpy(&item, value, sizeof(item));
        number = item;
        break;
    }
    case 64:
        memcpy(&number, value, sizeof(number));
        break;
    default:
        return false;
    }
    if (number > SIZE_MAX) {
        return false;
    }
    *out = (size_t)number;
    return true;
}

static bool json_reflect_store_count(
    json_parser *parser,
    const json_reflect_type *type,
    void *value,
    size_t count,
    json_source_location location
)
{
    uint64_t limit = UINT64_MAX;
    if (type->bits < 64) {
        limit = (UINT64_C(1) << type->bits) - 1;
    }
    if ((uint64_t)count > limit) {
        json_reflect_length_error(
            parser, JSON_RANGE_ARRAY_LENGTH, (size_t)limit, location
        );
        return false;
    }
    switch (type->bits) {
    case 8: {
        uint8_t item = (uint8_t)count;
        memcpy(value, &item, sizeof(item));
        return true;
    }
    case 16: {
        uint16_t item = (uint16_t)count;
        memcpy(value, &item, sizeof(item));
        return true;
    }
    case 32: {
        uint32_t item = (uint32_t)count;
        memcpy(value, &item, sizeof(item));
        return true;
    }
    case 64: {
        uint64_t item = (uint64_t)count;
        memcpy(value, &item, sizeof(item));
        return true;
    }
    default:
        json_set_error(parser, JSON_ERROR_OTHER_INVALID_STATE, NULL);
        return false;
    }
}

static bool json_reflect_number_constraints(
    json_parser *parser,
    const json_reflect_type *type,
    const json_reflect_constraints *constraints,
    const void *value,
    json_source_location location,
    json_error_span span
)
{
    if (constraints == NULL) {
        return true;
    }
    const uint32_t flags = constraints->flags;
    bool invalid = (flags & (JSON_REFLECT_MIN_FAIL | JSON_REFLECT_MAX_FAIL)) != 0;
    if (type->kind == JSON_REFLECT_FLOAT) {
        double number = 0.0;
        if (type->bits == 32) {
            float item = 0.0F;
            memcpy(&item, value, sizeof(item));
            number = item;
        } else {
            memcpy(&number, value, sizeof(number));
        }
        invalid = invalid ||
                  ((flags & JSON_REFLECT_HAS_MIN) != 0 &&
                   number < constraints->minimum.float_value) ||
                  ((flags & JSON_REFLECT_HAS_MAX) != 0 &&
                   number > constraints->maximum.float_value);
    } else if ((type->flags & JSON_REFLECT_SIGNED) != 0) {
        int64_t number = 0;
        switch (type->bits) {
        case 8: {
            int8_t item = 0;
            memcpy(&item, value, sizeof(item));
            number = item;
            break;
        }
        case 16: {
            int16_t item = 0;
            memcpy(&item, value, sizeof(item));
            number = item;
            break;
        }
        case 32: {
            int32_t item = 0;
            memcpy(&item, value, sizeof(item));
            number = item;
            break;
        }
        default:
            memcpy(&number, value, sizeof(number));
            break;
        }
        invalid = invalid ||
                  ((flags & JSON_REFLECT_HAS_MIN) != 0 &&
                   number < constraints->minimum.signed_value) ||
                  ((flags & JSON_REFLECT_HAS_MAX) != 0 &&
                   number > constraints->maximum.signed_value);
    } else {
        uint64_t number = 0;
        switch (type->bits) {
        case 8: {
            uint8_t item = 0;
            memcpy(&item, value, sizeof(item));
            number = item;
            break;
        }
        case 16: {
            uint16_t item = 0;
            memcpy(&item, value, sizeof(item));
            number = item;
            break;
        }
        case 32: {
            uint32_t item = 0;
            memcpy(&item, value, sizeof(item));
            number = item;
            break;
        }
        default:
            memcpy(&number, value, sizeof(number));
            break;
        }
        invalid = invalid ||
                  ((flags & JSON_REFLECT_HAS_MIN) != 0 &&
                   number < constraints->minimum.unsigned_value) ||
                  ((flags & JSON_REFLECT_HAS_MAX) != 0 &&
                   number > constraints->maximum.unsigned_value);
    }
    if (invalid) {
        json_reflect_number_error(parser, location, span);
        return false;
    }
    return true;
}

static bool json_reflect_decode_value(
    json_parser *parser,
    const json_reflect_type *type,
    const json_reflect_constraints *constraints,
    void *out,
    void *count_out,
    const json_reflect_type *count_type
);

void json_reflect_release(
    json_allocator *allocator,
    const json_reflect_type *type,
    void *value
)
{
    if (allocator == NULL || type == NULL || value == NULL) {
        return;
    }
    if (type->kind == JSON_REFLECT_STRING && type->capacity == 0) {
        char *pointer = NULL;
        memcpy(&pointer, value, sizeof(pointer));
        if (pointer != NULL) {
            allocator->free(pointer);
            memset(value, 0, sizeof(pointer));
        }
        return;
    }
    if (type->kind == JSON_REFLECT_POINTER) {
        void *pointer = NULL;
        memcpy(&pointer, value, sizeof(pointer));
        if (pointer != NULL) {
            json_reflect_release(allocator, type->target, pointer);
            allocator->free(pointer);
            memset(value, 0, sizeof(pointer));
        }
        return;
    }
    if (type->kind == JSON_REFLECT_RECORD) {
        const json_reflect_record *record = type->record;
        if (record->shape == JSON_REFLECT_ARRAY) {
            const json_reflect_array_layout *layout = record->array;
            void *elems = NULL;
            memcpy(&elems, json_reflect_at(value, layout->elems_offset), sizeof(elems));
            size_t count = 0;
            if (layout->length_type != NULL) {
                (void)json_reflect_load_count(
                    layout->length_type,
                    json_reflect_const_at(value, layout->length_offset),
                    &count
                );
            } else if (layout->capacity_type != NULL) {
                (void)json_reflect_load_count(
                    layout->capacity_type,
                    json_reflect_const_at(value, layout->capacity_offset),
                    &count
                );
            }
            if (elems != NULL) {
                for (size_t index = 0; index < count; ++index) {
                    json_reflect_release(
                        allocator,
                        layout->element_type,
                        (unsigned char *)elems + index * layout->element_type->size
                    );
                }
                allocator->free(elems);
            }
        } else {
            for (size_t index = 0; index < record->storage_count; ++index) {
                const json_reflect_storage *storage = &record->storage[index];
                void *field = json_reflect_at(value, storage->offset);
                if (storage->type->kind == JSON_REFLECT_DYNAMIC_ARRAY ||
                    storage->type->kind == JSON_REFLECT_FIXED_ARRAY) {
                    size_t count = storage->type->capacity;
                    if (storage->count_type != NULL) {
                        (void)json_reflect_load_count(
                            storage->count_type,
                            json_reflect_const_at(value, storage->count_offset),
                            &count
                        );
                    }
                    void *elems = field;
                    if (storage->type->kind == JSON_REFLECT_DYNAMIC_ARRAY) {
                        memcpy(&elems, field, sizeof(elems));
                    }
                    if (elems != NULL) {
                        for (size_t element = 0; element < count; ++element) {
                            json_reflect_release(
                                allocator,
                                storage->type->target,
                                (unsigned char *)elems +
                                    element * storage->type->target->size
                            );
                        }
                    }
                    if (storage->type->kind == JSON_REFLECT_DYNAMIC_ARRAY &&
                        elems != NULL) {
                        allocator->free(elems);
                        memset(field, 0, sizeof(elems));
                    }
                    if (storage->count_type != NULL) {
                        memset(
                            json_reflect_at(value, storage->count_offset),
                            0,
                            storage->count_type->size
                        );
                    }
                } else {
                    json_reflect_release(allocator, storage->type, field);
                }
            }
        }
        memset(value, 0, record->size);
    }
}

static bool json_reflect_decode_scalar(
    json_parser *parser,
    const json_reflect_type *type,
    const json_reflect_constraints *constraints,
    void *out
)
{
    const json_token *token = json_peek_token(parser);
    const json_source_location location = token->location;
    const json_error_span span = {token->str.ptr, token->str.ptr + token->str.len};
    bool ok = false;
    if (type->kind == JSON_REFLECT_BOOL) {
        bool value = false;
        ok = json_decode_bool(parser, &value);
        if (ok) {
            memcpy(out, &value, sizeof(value));
        }
        return ok;
    }
    if (type->kind == JSON_REFLECT_FLOAT) {
        double value = 0.0;
        ok = json_decode_f64(parser, &value);
        if (!ok) {
            return false;
        }
        if (type->bits == 32) {
            if (value < -FLT_MAX || value > FLT_MAX) {
                json_reflect_number_error(parser, location, span);
                return false;
            }
            float narrowed = (float)value;
            memcpy(out, &narrowed, sizeof(narrowed));
        } else {
            memcpy(out, &value, sizeof(value));
        }
        return json_reflect_number_constraints(
            parser, type, constraints, out, location, span
        );
    }
    if ((type->flags & JSON_REFLECT_SIGNED) != 0) {
        int64_t value = 0;
        switch (type->bits) {
        case 8: {
            int8_t item = 0;
            ok = json_decode_i8(parser, &item);
            value = item;
            if (ok) memcpy(out, &item, sizeof(item));
            break;
        }
        case 16: {
            int16_t item = 0;
            ok = json_decode_i16(parser, &item);
            value = item;
            if (ok) memcpy(out, &item, sizeof(item));
            break;
        }
        case 32: {
            int32_t item = 0;
            ok = json_decode_i32(parser, &item);
            value = item;
            if (ok) memcpy(out, &item, sizeof(item));
            break;
        }
        default:
            ok = json_decode_i64(parser, &value);
            if (ok) memcpy(out, &value, sizeof(value));
            break;
        }
        (void)value;
    } else {
        uint64_t value = 0;
        switch (type->bits) {
        case 8: {
            uint8_t item = 0;
            ok = json_decode_u8(parser, &item);
            value = item;
            if (ok) memcpy(out, &item, sizeof(item));
            break;
        }
        case 16: {
            uint16_t item = 0;
            ok = json_decode_u16(parser, &item);
            value = item;
            if (ok) memcpy(out, &item, sizeof(item));
            break;
        }
        case 32: {
            uint32_t item = 0;
            ok = json_decode_u32(parser, &item);
            value = item;
            if (ok) memcpy(out, &item, sizeof(item));
            break;
        }
        default:
            ok = json_decode_u64(parser, &value);
            if (ok) memcpy(out, &value, sizeof(value));
            break;
        }
        (void)value;
    }
    return ok && json_reflect_number_constraints(
                     parser, type, constraints, out, location, span
                 );
}

static bool json_reflect_decode_string(
    json_parser *parser,
    const json_reflect_type *type,
    const json_reflect_constraints *constraints,
    void *out
)
{
    if (type->capacity == 0 && json_peek_token(parser)->kind == JSON_TOKEN_NULL) {
        return json_decode_null(parser);
    }
    const json_source_location location = json_peek_token(parser)->location;
    json_cow_str string = {0};
    if (!json_decode_string(parser, &string)) {
        return false;
    }
    const json_slice slice = json_cow_str_as_slice(&string);
    if (memchr(slice.ptr, '\0', slice.len) != NULL) {
        json_free_cow_str(parser->allocator, &string);
        json_set_error_at(
            parser, JSON_ERROR_OTHER_EMBEDDED_NUL, NULL, location
        );
        return false;
    }
    size_t limit = 0;
    bool invalid = false;
    if (constraints != NULL &&
        (constraints->flags & JSON_REFLECT_HAS_MIN_LENGTH) != 0 &&
        slice.len < constraints->min_length) {
        limit = constraints->min_length;
        invalid = true;
    } else if (constraints != NULL &&
               (constraints->flags & JSON_REFLECT_HAS_MAX_LENGTH) != 0 &&
               slice.len > constraints->max_length) {
        limit = constraints->max_length;
        invalid = true;
    } else if (type->capacity != 0 && slice.len >= type->capacity) {
        limit = type->capacity - 1;
        invalid = true;
    }
    if (invalid) {
        json_free_cow_str(parser->allocator, &string);
        json_reflect_length_error(
            parser, JSON_RANGE_STRING_LENGTH, limit, location
        );
        return false;
    }
    if (type->capacity == 0) {
        char *owned = NULL;
        const json_error_code code = json_cow_str_into_owned_c_str(
            parser->allocator, &string, &owned
        );
        if (code != JSON_ERROR_NONE) {
            json_free_cow_str(parser->allocator, &string);
            json_set_error_at(parser, code, NULL, location);
            return false;
        }
        memcpy(out, &owned, sizeof(owned));
    } else {
        size_t written = 0;
        (void)json_slice_write_to_buf(
            &slice, (char *)out, type->capacity, &written
        );
        json_free_cow_str(parser->allocator, &string);
    }
    return true;
}

static bool json_reflect_check_array_length(
    json_parser *parser,
    const json_reflect_constraints *constraints,
    size_t count,
    json_source_location location
)
{
    if (constraints != NULL &&
        (constraints->flags & JSON_REFLECT_HAS_MIN_LENGTH) != 0 &&
        count < constraints->min_length) {
        json_reflect_length_error(
            parser, JSON_RANGE_ARRAY_LENGTH, constraints->min_length, location
        );
        return false;
    }
    if (constraints != NULL &&
        (constraints->flags & JSON_REFLECT_HAS_MAX_LENGTH) != 0 &&
        count > constraints->max_length) {
        json_reflect_length_error(
            parser, JSON_RANGE_ARRAY_LENGTH, constraints->max_length, location
        );
        return false;
    }
    return true;
}

static size_t json_reflect_count_limit(const json_reflect_type *type)
{
    if (type == NULL || type->bits >= sizeof(size_t) * 8) {
        return SIZE_MAX;
    }
    return ((size_t)1 << type->bits) - 1;
}

static bool json_reflect_decode_array_elements(
    json_parser *parser,
    const json_reflect_type *element_type,
    const json_reflect_constraints *constraints,
    size_t fixed_capacity,
    json_any_vec *vec,
    void *fixed,
    size_t *count,
    const json_reflect_type *count_type,
    json_source_location location
)
{
    if (!json_array_begin(parser)) {
        return false;
    }
    if (json_array_try_end(parser)) {
        return json_reflect_check_array_length(parser, constraints, 0, location);
    }
    while (true) {
        size_t limit = fixed_capacity != 0 ? fixed_capacity : SIZE_MAX;
        if (constraints != NULL &&
            (constraints->flags & JSON_REFLECT_HAS_MAX_LENGTH) != 0 &&
            constraints->max_length < limit) {
            limit = constraints->max_length;
        }
        const size_t counter_limit = json_reflect_count_limit(count_type);
        if (counter_limit < limit) {
            limit = counter_limit;
        }
        if (*count >= limit) {
            json_reflect_length_error(
                parser,
                JSON_RANGE_ARRAY_LENGTH,
                limit,
                json_peek_token(parser)->location
            );
            return false;
        }
        void *element = NULL;
        if (fixed_capacity != 0) {
            element = (unsigned char *)fixed + *count * element_type->size;
        } else {
            if (!json_any_vec_reserve(
                    parser->allocator, vec, element_type->size
                )) {
                json_reflect_no_memory(parser);
                return false;
            }
            element = vec->data + vec->byte_len;
            vec->byte_len += element_type->size;
        }
        ++*count;
        if (!json_reflect_decode_value(
                parser, element_type, NULL, element, NULL, NULL
            )) {
            return false;
        }
        if (json_peek_token(parser)->kind == JSON_TOKEN_RBRACKET) {
            if (!json_array_try_end(parser)) {
                return false;
            }
            break;
        }
        if (!json_consume_comma(parser)) {
            return false;
        }
    }
    return json_reflect_check_array_length(
        parser, constraints, *count, location
    );
}

static bool json_reflect_decode_array(
    json_parser *parser,
    const json_reflect_type *type,
    const json_reflect_constraints *constraints,
    void *out,
    void *count_out,
    const json_reflect_type *count_type
)
{
    if (type->kind == JSON_REFLECT_DYNAMIC_ARRAY &&
        json_peek_token(parser)->kind == JSON_TOKEN_NULL) {
        return json_decode_null(parser);
    }
    const json_source_location location = json_peek_token(parser)->location;
    json_any_vec vec = {0};
    size_t count = 0;
    void *fixed = type->kind == JSON_REFLECT_FIXED_ARRAY ? out : NULL;
    const size_t capacity =
        type->kind == JSON_REFLECT_FIXED_ARRAY ? type->capacity : 0;
    if (!json_reflect_decode_array_elements(
            parser,
            type->target,
            constraints,
            capacity,
            &vec,
            fixed,
            &count,
            count_type,
            location
        )) {
        void *elements = fixed != NULL ? fixed : vec.data;
        for (size_t index = 0; index < count; ++index) {
            json_reflect_release(
                parser->allocator,
                type->target,
                (unsigned char *)elements + index * type->target->size
            );
        }
        if (vec.data != NULL) {
            parser->allocator->free(vec.data);
        }
        return false;
    }
    if (count_out != NULL &&
        !json_reflect_store_count(
            parser, count_type, count_out, count, location
        )) {
        for (size_t index = 0; index < count; ++index) {
            json_reflect_release(
                parser->allocator,
                type->target,
                (fixed != NULL ? (unsigned char *)fixed : vec.data) +
                    index * type->target->size
            );
        }
        if (vec.data != NULL) parser->allocator->free(vec.data);
        return false;
    }
    if (type->kind == JSON_REFLECT_DYNAMIC_ARRAY) {
        memcpy(out, &vec.data, sizeof(vec.data));
    }
    return true;
}

static bool json_reflect_decode_record_array(
    json_parser *parser,
    const json_reflect_type *type,
    void *out
)
{
    const json_reflect_array_layout *layout = type->record->array;
    const json_source_location location = json_peek_token(parser)->location;
    json_any_vec vec = {0};
    size_t count = 0;
    if (!json_reflect_decode_array_elements(
            parser,
            layout->element_type,
            NULL,
            0,
            &vec,
            NULL,
            &count,
            layout->length_type,
            location
        )) {
        for (size_t index = 0; index < count; ++index) {
            json_reflect_release(
                parser->allocator,
                layout->element_type,
                vec.data + index * layout->element_type->size
            );
        }
        if (vec.data != NULL) parser->allocator->free(vec.data);
        return false;
    }
    if (layout->length_type != NULL &&
        !json_reflect_store_count(
            parser,
            layout->length_type,
            json_reflect_at(out, layout->length_offset),
            count,
            location
        )) {
        goto fail;
    }
    if (layout->capacity_type != NULL) {
        const size_t capacity = vec.byte_cap / layout->element_type->size;
        if (!json_reflect_store_count(
                parser,
                layout->capacity_type,
                json_reflect_at(out, layout->capacity_offset),
                capacity,
                location
            )) {
            goto fail;
        }
    }
    memcpy(json_reflect_at(out, layout->elems_offset), &vec.data, sizeof(vec.data));
    return true;

fail:
    for (size_t index = 0; index < count; ++index) {
        json_reflect_release(
            parser->allocator,
            layout->element_type,
            vec.data + index * layout->element_type->size
        );
    }
    if (vec.data != NULL) parser->allocator->free(vec.data);
    return false;
}

static bool json_reflect_decode_record_object(
    json_parser *parser,
    const json_reflect_type *type,
    void *out
)
{
    const json_reflect_record *record = type->record;
    unsigned char seen[record->field_count == 0 ? 1 : record->field_count];
    memset(seen, 0, sizeof(seen));
    json_source_location object_end = {0};
    if (!json_object_begin(parser)) {
        return false;
    }
    if (!json_object_try_end(parser)) {
        while (true) {
            const json_source_location key_location =
                json_peek_token(parser)->location;
            json_cow_str key = {0};
            if (!json_decode_string(parser, &key)) {
                return false;
            }
            if (!json_consume_colon(parser)) {
                json_free_cow_str(parser->allocator, &key);
                return false;
            }
            const json_slice key_slice = json_cow_str_as_slice(&key);
            const json_key_entry *entry = json_key_dispatch(&record->keys, &key_slice);
            json_free_cow_str(parser->allocator, &key);
            if (entry == NULL) {
                if (!json_skip_value(parser)) {
                    return false;
                }
            } else {
                const json_reflect_field *field = &record->fields[entry->id];
                if (seen[entry->id] != 0) {
                    json_reflect_context_error(
                        parser,
                        JSON_ERROR_OTHER_DUPLICATE_KEY,
                        field->primary_key,
                        key_location
                    );
                    return false;
                }
                seen[entry->id] = 1;
                if ((field->flags & JSON_REFLECT_REQUIRED) != 0 &&
                    json_peek_token(parser)->kind == JSON_TOKEN_NULL) {
                    json_reflect_context_error(
                        parser,
                        JSON_ERROR_OTHER_NULL_REQUIRED_VALUE,
                        field->primary_key,
                        json_peek_token(parser)->location
                    );
                    return false;
                }
                void *count = field->count_type == NULL
                                  ? NULL
                                  : json_reflect_at(out, field->count_offset);
                if (!json_reflect_decode_value(
                        parser,
                        field->type,
                        field->constraints,
                        json_reflect_at(out, field->offset),
                        count,
                        field->count_type
                    )) {
                    return false;
                }
            }
            if (json_peek_token(parser)->kind == JSON_TOKEN_RBRACE) {
                object_end = json_peek_token(parser)->location;
                if (!json_object_try_end(parser)) {
                    return false;
                }
                break;
            }
            if (!json_consume_comma(parser)) {
                return false;
            }
        }
    } else {
        object_end = parser->current_token.location;
    }
    for (size_t index = 0; index < record->field_count; ++index) {
        if ((record->fields[index].flags & JSON_REFLECT_REQUIRED) != 0 &&
            seen[index] == 0) {
            json_reflect_context_error(
                parser,
                JSON_ERROR_OTHER_MISSING_REQUIRED_KEY,
                record->fields[index].primary_key,
                object_end
            );
            return false;
        }
    }
    return true;
}

static bool json_reflect_decode_value(
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
    case JSON_REFLECT_POINTER: {
        if (json_peek_token(parser)->kind == JSON_TOKEN_NULL) {
            return json_decode_null(parser);
        }
        if (type->target->kind == JSON_REFLECT_RECORD) {
            const json_token_kind actual = json_peek_token(parser)->kind;
            const bool array =
                type->target->record->shape == JSON_REFLECT_ARRAY;
            const json_token_kind expected =
                array ? JSON_TOKEN_LBRACKET : JSON_TOKEN_LBRACE;
            if (actual != expected) {
                json_error_detail detail = {0};
                detail.type.expected =
                    array ? JSON_EXPECTED_ARRAY : JSON_EXPECTED_OBJECT;
                detail.type.actual = actual;
                json_set_error(parser, JSON_ERROR_TYPE_MISMATCH, &detail);
                return false;
            }
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
    case JSON_REFLECT_RECORD:
        if (type->record->shape == JSON_REFLECT_ARRAY) {
            return json_reflect_decode_record_array(parser, type, out);
        }
        return json_reflect_decode_record_object(parser, type, out);
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
