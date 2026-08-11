#include "json_reflect_internal.h"

#include <string.h>

static void release_elements(
    json_allocator *allocator,
    const json_reflect_type *element_type,
    void *elements,
    size_t count
)
{
    for (size_t index = 0; index < count; ++index) {
        json_reflect_release(
            allocator,
            element_type,
            (unsigned char *)elements + index * element_type->size
        );
    }
}

static size_t storage_count(
    const json_reflect_storage *storage,
    const void *record
)
{
    size_t count = storage->type->capacity;
    if (storage->count_type != NULL) {
        (void)json_reflect_load_count(
            storage->count_type,
            json_reflect_const_at(record, storage->count_offset),
            &count
        );
    }
    return count;
}

static void release_array_storage(
    json_allocator *allocator,
    const json_reflect_storage *storage,
    void *record
)
{
    void *field = json_reflect_at(record, storage->offset);
    void *elements = field;
    if (storage->type->kind == JSON_REFLECT_DYNAMIC_ARRAY) {
        memcpy(&elements, field, sizeof(elements));
    }
    if (elements != NULL) {
        release_elements(
            allocator,
            storage->type->target,
            elements,
            storage_count(storage, record)
        );
    }
    if (storage->type->kind == JSON_REFLECT_DYNAMIC_ARRAY && elements != NULL) {
        allocator->free(elements);
        memset(field, 0, sizeof(elements));
    }
    if (storage->count_type != NULL) {
        memset(
            json_reflect_at(record, storage->count_offset),
            0,
            storage->count_type->size
        );
    }
}

static void release_object(
    json_allocator *allocator,
    const json_reflect_record *record,
    void *value
)
{
    for (size_t index = 0; index < record->storage_count; ++index) {
        const json_reflect_storage *storage = &record->storage[index];
        if (storage->type->kind == JSON_REFLECT_DYNAMIC_ARRAY ||
            storage->type->kind == JSON_REFLECT_FIXED_ARRAY) {
            release_array_storage(allocator, storage, value);
        } else {
            json_reflect_release(
                allocator,
                storage->type,
                json_reflect_at(value, storage->offset)
            );
        }
    }
}

void json_reflect_release_field(
    json_allocator *allocator,
    const json_reflect_field *field,
    void *record
)
{
    const json_reflect_storage storage = {
        .offset = field->offset,
        .type = field->type,
        .count_offset = field->count_offset,
        .count_type = field->count_type,
    };
    if (field->type->kind == JSON_REFLECT_DYNAMIC_ARRAY ||
        field->type->kind == JSON_REFLECT_FIXED_ARRAY) {
        release_array_storage(allocator, &storage, record);
    } else {
        json_reflect_release(
            allocator, field->type, json_reflect_at(record, field->offset)
        );
    }
    memset(json_reflect_at(record, field->offset), 0, field->type->size);
}

static void release_array_record(
    json_allocator *allocator,
    const json_reflect_array_layout *layout,
    void *value
)
{
    void *elements = NULL;
    memcpy(
        &elements,
        json_reflect_at(value, layout->elems_offset),
        sizeof(elements)
    );
    if (elements == NULL) {
        return;
    }
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
    release_elements(allocator, layout->element_type, elements, count);
    allocator->free(elements);
}

void json_reflect_release(
    json_allocator *allocator,
    const json_reflect_type *type,
    void *value
)
{
    if (allocator == NULL || value == NULL ||
        !json_reflect_type_abi_compatible(type)) {
        return;
    }
    if (type->kind == JSON_REFLECT_STRING && type->capacity == 0) {
        void *pointer = NULL;
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
    if (type->kind != JSON_REFLECT_RECORD) {
        return;
    }

    if (type->record->shape == JSON_REFLECT_ARRAY) {
        release_array_record(allocator, type->record->array, value);
    } else {
        release_object(allocator, type->record, value);
    }
    memset(value, 0, type->record->size);
}
