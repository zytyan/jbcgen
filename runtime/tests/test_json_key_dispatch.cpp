#include "json_key_dispatch.h"

#include "gtest/gtest.h"

#include <cstring>

namespace {

bool decode_field(struct json_parser *, void *)
{
    return true;
}

json_slice slice(const char *text)
{
    return {text, std::strlen(text)};
}

TEST(JsonKeyDispatchTest, FindsEntriesSortedByLengthThenBytes)
{
    const json_key_entry entries[] = {
        {slice(""), 1, decode_field},
        {slice("a"), 2, decode_field},
        {slice("b"), 3, decode_field},
        {slice("aa"), 4, decode_field},
        {slice("zz"), 5, decode_field},
        {slice("long"), 6, decode_field},
    };
    const json_key_map map{entries, 6};

    for (uint32_t index = 0; index < 6; ++index) {
        const json_key_entry *entry = json_key_dispatch(&map, &entries[index].key);
        ASSERT_EQ(entry, &entries[index]);
        EXPECT_EQ(entry->id, index + 1);
        EXPECT_EQ(entry->decode, decode_field);
    }
}

TEST(JsonKeyDispatchTest, MissesAtLengthAndByteBoundaries)
{
    const json_key_entry entries[] = {
        {slice("a"), 1, decode_field},
        {slice("c"), 2, decode_field},
        {slice("aa"), 3, decode_field},
        {slice("cc"), 4, decode_field},
    };
    const json_key_map map{entries, 4};

    for (const char *text : {"", "b", "d", "ab", "dd", "long"}) {
        json_slice key = slice(text);
        EXPECT_EQ(json_key_dispatch(&map, &key), nullptr);
    }
}

TEST(JsonKeyDispatchTest, RejectsInvalidArguments)
{
    json_slice key = slice("id");
    EXPECT_EQ(json_key_dispatch(nullptr, &key), nullptr);
    const json_key_map empty{nullptr, 0};
    EXPECT_EQ(json_key_dispatch(&empty, nullptr), nullptr);
    const json_key_map invalid{nullptr, 1};
    EXPECT_EQ(json_key_dispatch(&invalid, &key), nullptr);
    const json_slice invalid_key{nullptr, 1};
    EXPECT_EQ(json_key_dispatch(&empty, &invalid_key), nullptr);
}

} // namespace
