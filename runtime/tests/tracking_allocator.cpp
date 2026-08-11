#include "tracking_allocator.h"

#include <cstdlib>

allocation_tracker tracked_allocations;

void allocation_tracker::reset(size_t failure)
{
    for (pointer_slot &slot : pointers) {
        slot = {};
    }
    attempt_count = 0;
    allocation_count = 0;
    free_count = 0;
    invalid_free_count = 0;
    fail_at = failure;
}

size_t allocation_tracker::live_count() const
{
    size_t result = 0;
    for (const pointer_slot &slot : pointers) {
        result += slot.live ? 1U : 0U;
    }
    return result;
}

bool allocation_tracker::clean() const
{
    return live_count() == 0 && invalid_free_count == 0 &&
           allocation_count == free_count;
}

void *tracking_malloc(size_t size)
{
    const size_t attempt = tracked_allocations.attempt_count++;
    if (attempt == tracked_allocations.fail_at) {
        return nullptr;
    }
    void *pointer = std::malloc(size);
    if (pointer == nullptr) {
        return nullptr;
    }
    for (allocation_tracker::pointer_slot &slot : tracked_allocations.pointers) {
        if (!slot.live) {
            slot = {pointer, true};
            ++tracked_allocations.allocation_count;
            return pointer;
        }
    }
    std::free(pointer);
    return nullptr;
}

void tracking_free(void *pointer)
{
    if (pointer == nullptr) {
        return;
    }
    for (allocation_tracker::pointer_slot &slot : tracked_allocations.pointers) {
        if (slot.pointer == pointer && slot.live) {
            slot.live = false;
            ++tracked_allocations.free_count;
            std::free(pointer);
            return;
        }
    }
    ++tracked_allocations.invalid_free_count;
}
