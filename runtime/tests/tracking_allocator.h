#ifndef JBCGEN_TEST_TRACKING_ALLOCATOR_H
#define JBCGEN_TEST_TRACKING_ALLOCATOR_H

#include "json_allocator.h"

#include <cstddef>
#include <limits>

struct allocation_tracker {
    static constexpr size_t max_live_pointers = 4096;

    struct pointer_slot {
        void *pointer;
        bool live;
    };

    pointer_slot pointers[max_live_pointers]{};
    size_t attempt_count{};
    size_t allocation_count{};
    size_t free_count{};
    size_t invalid_free_count{};
    size_t fail_at{std::numeric_limits<size_t>::max()};

    void reset(size_t failure = std::numeric_limits<size_t>::max());
    size_t live_count() const;
    bool clean() const;
};

extern allocation_tracker tracked_allocations;

void *tracking_malloc(size_t size);
void tracking_free(void *pointer);

inline json_allocator tracking_json_allocator()
{
    return {tracking_malloc, tracking_free};
}

#endif
