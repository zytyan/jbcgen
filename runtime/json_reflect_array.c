#include "json_reflect_internal.h"

#include <string.h>

typedef struct json_reflect_array_transaction {
    json_any_vec vec;
    void *fixed;
    size_t count;
    const json_reflect_type *element_type;
} json_reflect_array_transaction;

static void *array_element(
    const json_reflect_array_transaction *transaction,
    size_t index
)
{
    unsigned char *base = transaction->fixed != NULL
                              ? transaction->fixed
                              : transaction->vec.data;
    return base + index * transaction->element_type->size;
}

static void rollback_array(
    json_parser *parser,
    json_reflect_array_transaction *transaction
)
{
    for (size_t index = 0; index < transaction->count; ++index) {
        json_reflect_release(
            parser->allocator,
            transaction->element_type,
            array_element(transaction, index)
        );
    }
    if (transaction->vec.data != NULL) {
        parser->allocator->free(transaction->vec.data);
    }
    transaction->vec = (json_any_vec){0};
    transaction->count = 0;
}

static size_t array_limit(
    size_t fixed_capacity,
    const json_reflect_constraints *constraints,
    const json_reflect_type *count_type
)
{
    size_t limit = fixed_capacity == 0 ? SIZE_MAX : fixed_capacity;
    if (constraints != NULL &&
        (constraints->flags & JSON_REFLECT_HAS_MAX_LENGTH) != 0 &&
        constraints->max_length < limit) {
        limit = constraints->max_length;
    }
    const size_t count_limit = json_reflect_count_limit(count_type);
    return count_limit < limit ? count_limit : limit;
}

static bool reserve_element(
    json_parser *parser,
    json_reflect_array_transaction *transaction,
    size_t limit,
    void **out
)
{
    if (transaction->count >= limit) {
        json_reflect_length_error(
            parser,
            JSON_RANGE_ARRAY_LENGTH,
            limit,
            json_peek_token(parser)->location
        );
        return false;
    }
    if (transaction->fixed == NULL &&
        !json_any_vec_reserve(
            parser->allocator,
            &transaction->vec,
            transaction->element_type->size
        )) {
        json_reflect_no_memory(parser);
        return false;
    }
    *out = array_element(transaction, transaction->count);
    if (transaction->fixed == NULL) {
        transaction->vec.byte_len += transaction->element_type->size;
    }
    ++transaction->count;
    return true;
}

static bool decode_sequence(
    json_parser *parser,
    json_reflect_array_transaction *transaction,
    const json_reflect_constraints *constraints,
    size_t fixed_capacity,
    const json_reflect_type *count_type,
    json_source_location location
)
{
    if (!json_array_begin(parser)) {
        return false;
    }
    if (json_array_try_end(parser)) {
        return json_reflect_check_length(
            parser,
            constraints,
            0,
            JSON_RANGE_ARRAY_LENGTH,
            location
        );
    }

    const size_t limit = array_limit(
        fixed_capacity, constraints, count_type
    );
    while (true) {
        void *element = NULL;
        if (!reserve_element(parser, transaction, limit, &element) ||
            !json_reflect_decode_value(
                parser,
                transaction->element_type,
                NULL,
                element,
                NULL,
                NULL
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
    return json_reflect_check_length(
        parser,
        constraints,
        transaction->count,
        JSON_RANGE_ARRAY_LENGTH,
        location
    );
}

bool json_reflect_decode_array(
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

    json_reflect_array_transaction transaction = {
        .fixed = type->kind == JSON_REFLECT_FIXED_ARRAY ? out : NULL,
        .element_type = type->target,
    };
    const json_source_location location = json_peek_token(parser)->location;
    const size_t capacity =
        type->kind == JSON_REFLECT_FIXED_ARRAY ? type->capacity : 0;
    if (!decode_sequence(
            parser,
            &transaction,
            constraints,
            capacity,
            count_type,
            location
        ) ||
        (count_out != NULL &&
         !json_reflect_store_count(
             parser,
             count_type,
             count_out,
             transaction.count,
             location
         ))) {
        rollback_array(parser, &transaction);
        return false;
    }
    if (type->kind == JSON_REFLECT_DYNAMIC_ARRAY) {
        memcpy(out, &transaction.vec.data, sizeof(transaction.vec.data));
    }
    return true;
}

bool json_reflect_decode_array_record(
    json_parser *parser,
    const json_reflect_type *type,
    void *out
)
{
    const json_reflect_array_layout *layout = type->record->array;
    json_reflect_array_transaction transaction = {
        .element_type = layout->element_type,
    };
    const json_source_location location = json_peek_token(parser)->location;
    if (!decode_sequence(
            parser,
            &transaction,
            NULL,
            0,
            layout->length_type,
            location
        )) {
        rollback_array(parser, &transaction);
        return false;
    }

    bool stored = true;
    if (layout->length_type != NULL) {
        stored = json_reflect_store_count(
            parser,
            layout->length_type,
            json_reflect_at(out, layout->length_offset),
            transaction.count,
            location
        );
    }
    if (stored && layout->capacity_type != NULL) {
        const size_t capacity =
            transaction.vec.byte_cap / layout->element_type->size;
        stored = json_reflect_store_count(
            parser,
            layout->capacity_type,
            json_reflect_at(out, layout->capacity_offset),
            capacity,
            location
        );
    }
    if (!stored) {
        rollback_array(parser, &transaction);
        return false;
    }
    memcpy(
        json_reflect_at(out, layout->elems_offset),
        &transaction.vec.data,
        sizeof(transaction.vec.data)
    );
    return true;
}
