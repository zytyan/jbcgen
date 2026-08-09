#ifndef JSON_ALLOCATOR_H
#define JSON_ALLOCATOR_H

#pragma once
#include <stddef.h>

typedef struct json_allocator {
    void *(*malloc)(size_t size);
    void (*free)(void *ptr);
} json_allocator;

#endif