#include "json_reflect.h"

#include "gtest/gtest.h"

#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <limits>

namespace {

struct ReflectedValue {
    uint64_t id;
    char *name;
};

struct ReflectedStringArray {
    char **elements;
    uint8_t length;
};

size_t allocation_count;
size_t free_count;

void *tracking_malloc(size_t size)
{
    ++allocation_count;
    return std::malloc(size);
}

void tracking_free(void *pointer)
{
    if (pointer != nullptr) {
        ++free_count;
    }
    std::free(pointer);
}

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
    json_key_entry keys[3]{
        {slice("id"), 0},
        {slice("name"), 1},
        {slice("identifier"), 0},
    };
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
            {keys, 3},
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

TEST(JsonReflectTest, AliasSharesDuplicateAndRequiredState)
{
    FixtureDescriptors descriptors;
    json_allocator allocator{system_malloc, system_free};
    json_parser parser{};
    json_parser_init(
        &parser,
        &allocator,
        slice(
            R"({"id":9007199254740993,"identifier":9007199254740994,"name":"x"})"
        )
    );
    ReflectedValue value{};

    EXPECT_FALSE(json_reflect_decode(&parser, &descriptors.root_type, &value));
    EXPECT_EQ(parser.error.code, JSON_ERROR_OTHER_DUPLICATE_KEY);
    EXPECT_EQ(value.id, 0U);
    EXPECT_EQ(value.name, nullptr);

    parser = {};
    json_parser_init(
        &parser,
        &allocator,
        slice(R"({"identifier":9007199254740993})")
    );
    EXPECT_FALSE(json_reflect_decode(&parser, &descriptors.root_type, &value));
    EXPECT_EQ(parser.error.code, JSON_ERROR_OTHER_MISSING_REQUIRED_KEY);
}

TEST(JsonReflectTest, UnknownNestedValuesAreSkipped)
{
    FixtureDescriptors descriptors;
    json_allocator allocator{system_malloc, system_free};
    json_parser parser{};
    json_parser_init(
        &parser,
        &allocator,
        slice(
            R"({"unknown":{"array":[1,null,{"x":true}]},"name":"ok","id":9007199254740993})"
        )
    );
    ReflectedValue value{};

    ASSERT_TRUE(json_reflect_decode(&parser, &descriptors.root_type, &value));
    EXPECT_EQ(json_peek_token(&parser)->kind, JSON_TOKEN_EOF);
    EXPECT_STREQ(value.name, "ok");
    json_reflect_release(&allocator, &descriptors.root_type, &value);
}

TEST(JsonReflectTest, ScalarKindsUseTheirDeclaredWidths)
{
    json_allocator allocator{system_malloc, system_free};

    const json_reflect_type i8_type{
        JSON_REFLECT_INTEGER,
        8,
        JSON_REFLECT_SIGNED,
        sizeof(int8_t),
        0,
        nullptr,
        nullptr,
    };
    int8_t i8{};
    json_parser parser{};
    json_parser_init(&parser, &allocator, slice("-128"));
    ASSERT_TRUE(json_reflect_decode(&parser, &i8_type, &i8));
    EXPECT_EQ(i8, std::numeric_limits<int8_t>::min());

    const json_reflect_type u16_type{
        JSON_REFLECT_INTEGER, 16, 0, sizeof(uint16_t), 0, nullptr, nullptr};
    uint16_t u16{};
    parser = {};
    json_parser_init(&parser, &allocator, slice("65535"));
    ASSERT_TRUE(json_reflect_decode(&parser, &u16_type, &u16));
    EXPECT_EQ(u16, std::numeric_limits<uint16_t>::max());

    const json_reflect_type f32_type{
        JSON_REFLECT_FLOAT,
        32,
        JSON_REFLECT_SIGNED,
        sizeof(float),
        0,
        nullptr,
        nullptr,
    };
    float f32{};
    parser = {};
    json_parser_init(&parser, &allocator, slice("1.5"));
    ASSERT_TRUE(json_reflect_decode(&parser, &f32_type, &f32));
    EXPECT_FLOAT_EQ(f32, 1.5F);

    parser = {};
    json_parser_init(&parser, &allocator, slice("3.5e38"));
    EXPECT_FALSE(json_reflect_decode(&parser, &f32_type, &f32));
    EXPECT_EQ(parser.error.code, JSON_ERROR_RANGE_NUMBER);
    EXPECT_EQ(f32, 0.0F);
}

TEST(JsonReflectTest, FixedStringChecksDecodedLengthAndEmbeddedNul)
{
    json_allocator allocator{system_malloc, system_free};
    const json_reflect_type string_type{
        JSON_REFLECT_STRING, 0, 0, sizeof(char[4]), 4, nullptr, nullptr};
    json_reflect_constraints constraints{};
    constraints.flags =
        JSON_REFLECT_HAS_MIN_LENGTH | JSON_REFLECT_HAS_MAX_LENGTH;
    constraints.min_length = 1;
    constraints.max_length = 3;
    char value[4]{};
    json_parser parser{};

    json_parser_init(&parser, &allocator, slice(R"("abc")"));
    ASSERT_TRUE(
        json_reflect_decode(&parser, &string_type, value)
    );
    EXPECT_STREQ(value, "abc");

    parser = {};
    json_parser_init(&parser, &allocator, slice(R"("\u0000")"));
    EXPECT_FALSE(json_reflect_decode(&parser, &string_type, value));
    EXPECT_EQ(parser.error.code, JSON_ERROR_OTHER_EMBEDDED_NUL);
    EXPECT_STREQ(value, "");
}

TEST(JsonReflectTest, ArrayRecordDelaysAllocationAndRollsBackEveryElement)
{
    const json_reflect_type string_type{
        JSON_REFLECT_STRING, 0, 0, sizeof(char *), 0, nullptr, nullptr};
    const json_reflect_type length_type{
        JSON_REFLECT_INTEGER, 8, 0, sizeof(uint8_t), 0, nullptr, nullptr};
    const json_reflect_array_layout layout{
        offsetof(ReflectedStringArray, elements),
        &string_type,
        offsetof(ReflectedStringArray, length),
        &length_type,
        SIZE_MAX,
        nullptr,
    };
    const json_reflect_record record{
        JSON_REFLECT_ARRAY,
        sizeof(ReflectedStringArray),
        {nullptr, 0},
        nullptr,
        0,
        nullptr,
        0,
        &layout,
    };
    const json_reflect_type array_type{
        JSON_REFLECT_RECORD,
        0,
        0,
        sizeof(ReflectedStringArray),
        0,
        nullptr,
        &record,
    };
    json_allocator allocator{tracking_malloc, tracking_free};
    json_parser parser{};
    ReflectedStringArray value{};

    allocation_count = 0;
    free_count = 0;
    json_parser_init(&parser, &allocator, slice("[]"));
    ASSERT_TRUE(json_reflect_decode(&parser, &array_type, &value));
    EXPECT_EQ(value.elements, nullptr);
    EXPECT_EQ(value.length, 0U);
    EXPECT_EQ(allocation_count, 0U);

    parser = {};
    json_parser_init(&parser, &allocator, slice(R"(["a","b"])"));
    ASSERT_TRUE(json_reflect_decode(&parser, &array_type, &value));
    ASSERT_NE(value.elements, nullptr);
    ASSERT_EQ(value.length, 2U);
    EXPECT_STREQ(value.elements[0], "a");
    EXPECT_STREQ(value.elements[1], "b");
    json_reflect_release(&allocator, &array_type, &value);
    EXPECT_EQ(value.elements, nullptr);
    EXPECT_EQ(value.length, 0U);
    EXPECT_EQ(allocation_count, free_count);

    parser = {};
    json_parser_init(
        &parser, &allocator, slice(R"(["kept","bad\u0000value"])"));
    EXPECT_FALSE(json_reflect_decode(&parser, &array_type, &value));
    EXPECT_EQ(parser.error.code, JSON_ERROR_OTHER_EMBEDDED_NUL);
    EXPECT_EQ(value.elements, nullptr);
    EXPECT_EQ(value.length, 0U);
    EXPECT_EQ(allocation_count, free_count);
}

} // namespace
