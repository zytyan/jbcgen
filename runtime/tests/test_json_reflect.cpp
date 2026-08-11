#include "json_reflect.h"

#include "gtest/gtest.h"

#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>

namespace {

struct ReflectedValue {
    uint64_t id;
    char *name;
};

void *system_malloc(size_t size)
{
    return std::malloc(size);
}

void system_free(void *pointer)
{
    std::free(pointer);
}

json_slice slice(const char *text)
{
    return {text, std::strlen(text)};
}

struct FixtureDescriptors {
    json_reflect_type uint64_type{
        JSON_REFLECT_INTEGER, 64, 0, sizeof(uint64_t), 0, nullptr, nullptr};
    json_reflect_type string_type{
        JSON_REFLECT_STRING, 0, 0, sizeof(char *), 0, nullptr, nullptr};
    json_reflect_number minimum{};
    json_reflect_constraints constraints{};
    json_key_entry keys[2]{{slice("id"), 0}, {slice("name"), 1}};
    json_reflect_field fields[2]{};
    json_reflect_storage storage[1]{};
    json_reflect_record record{};
    json_reflect_type root_type{};

    FixtureDescriptors()
    {
        minimum.unsigned_value = UINT64_C(9007199254740993);
        constraints = {
            JSON_REFLECT_HAS_MIN, minimum, {}, 0, 0,
        };
        fields[0] = {
            slice("id"),
            offsetof(ReflectedValue, id),
            &uint64_type,
            &constraints,
            SIZE_MAX,
            nullptr,
            JSON_REFLECT_REQUIRED,
        };
        fields[1] = {
            slice("name"),
            offsetof(ReflectedValue, name),
            &string_type,
            nullptr,
            SIZE_MAX,
            nullptr,
            JSON_REFLECT_REQUIRED,
        };
        storage[0] = {
            offsetof(ReflectedValue, name), &string_type, SIZE_MAX, nullptr};
        record = {
            JSON_REFLECT_OBJECT,
            sizeof(ReflectedValue),
            {keys, 2},
            fields,
            2,
            storage,
            1,
            nullptr,
        };
        root_type = {
            JSON_REFLECT_RECORD,
            0,
            0,
            sizeof(ReflectedValue),
            0,
            nullptr,
            &record,
        };
    }
};

TEST(JsonReflectTest, DecodesExactUint64ConstraintsAndReleasesStorage)
{
    FixtureDescriptors descriptors;
    json_allocator allocator{system_malloc, system_free};
    json_parser parser{};
    json_parser_init(
        &parser,
        &allocator,
        slice(R"({"id":9007199254740993,"name":""})")
    );
    ReflectedValue value{};

    ASSERT_TRUE(json_reflect_decode(&parser, &descriptors.root_type, &value));
    EXPECT_EQ(value.id, UINT64_C(9007199254740993));
    ASSERT_NE(value.name, nullptr);
    EXPECT_STREQ(value.name, "");

    json_reflect_release(&allocator, &descriptors.root_type, &value);
    json_reflect_release(&allocator, &descriptors.root_type, &value);
    EXPECT_EQ(value.id, 0U);
    EXPECT_EQ(value.name, nullptr);
}

TEST(JsonReflectTest, ConstraintFailureRollsBackPreviouslyOwnedFields)
{
    FixtureDescriptors descriptors;
    json_allocator allocator{system_malloc, system_free};
    json_parser parser{};
    json_parser_init(
        &parser,
        &allocator,
        slice(R"({"name":"allocated","id":9007199254740992})")
    );
    ReflectedValue value{};

    EXPECT_FALSE(json_reflect_decode(&parser, &descriptors.root_type, &value));
    EXPECT_EQ(parser.error.code, JSON_ERROR_RANGE_NUMBER);
    EXPECT_EQ(value.id, 0U);
    EXPECT_EQ(value.name, nullptr);
}

} // namespace
