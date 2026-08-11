#include "example/example.h"
#include "gtest/gtest.h"
#include "tracking_allocator.h"

#include <cstring>
#include <string>

namespace {

json_slice slice(const char *text)
{
    return {text, std::strlen(text)};
}

class GeneratedDecoderTest : public ::testing::Test {
  protected:
    json_allocator allocator{tracking_json_allocator()};

    void SetUp() override
    {
        tracked_allocations.reset();
    }

    bool decode(const char *input, User *user, json_parser *parser)
    {
        json_parser_init(parser, &allocator, slice(input));
        return decodeUser(parser, user);
    }
};

template <typename T, typename Decode, typename Cleanup>
void expect_every_allocation_to_fail_cleanly(
    const char *input,
    Decode decode,
    Cleanup cleanup
)
{
    json_allocator allocator = tracking_json_allocator();
    json_parser parser{};
    T value{};

    tracked_allocations.reset();
    json_parser_init(&parser, &allocator, slice(input));
    ASSERT_TRUE(decode(&parser, &value));
    const size_t attempts = tracked_allocations.attempt_count;
    ASSERT_GT(attempts, 0U);
    cleanup(&allocator, &value);
    cleanup(&allocator, &value);
    ASSERT_TRUE(tracked_allocations.clean());

    for (size_t fail_at = 0; fail_at < attempts; ++fail_at) {
        SCOPED_TRACE(fail_at);
        tracked_allocations.reset(fail_at);
        parser = {};
        value = {};
        json_parser_init(&parser, &allocator, slice(input));
        EXPECT_FALSE(decode(&parser, &value));
        EXPECT_EQ(parser.error.code, JSON_ERROR_OTHER_NO_MEMORY);
        cleanup(&allocator, &value);
        cleanup(&allocator, &value);
        const T zero{};
        EXPECT_EQ(std::memcmp(&value, &zero, sizeof(value)), 0);
        EXPECT_TRUE(tracked_allocations.clean());
    }
}

TEST_F(GeneratedDecoderTest, EveryAllocatorFailureRollsBackGeneratedTypes)
{
    expect_every_allocation_to_fail_cleanly<User>(
        R"({"\u0069d":1,"name":"escaped\u0020name","age":18,"bases":[{"id":1},{"id":2},{"id":3}],"metadata":{}})",
        decodeUser,
        releaseUser
    );
    expect_every_allocation_to_fail_cleanly<User>(
        R"({"id":1,"name":"first","name":"second","age":18,"bases":[{"id":1}],"bases":[{"id":2}],"metadata":{}})",
        decodeUser,
        releaseUser
    );
    expect_every_allocation_to_fail_cleanly<StringSlots>(
        R"(["first","second","third"])",
        decodeStringSlots,
        releaseStringSlots
    );
    expect_every_allocation_to_fail_cleanly<VecEnvelope>(
        R"({"optional":[1,2,3],"required":[4,5,6]})",
        decodeVecEnvelope,
        releaseVecEnvelope
    );
}

TEST_F(GeneratedDecoderTest, SemanticFailuresReleaseEarlierAllocations)
{
    struct failure_case {
        const char *input;
        json_error_code code;
    };
    const failure_case cases[] = {
        {R"({"id":1,"name":"owned","age":18,"metadata":{}})",
         JSON_ERROR_OTHER_MISSING_REQUIRED_KEY},
        {R"({"id":1,"name":"owned" "age":18})",
         JSON_ERROR_SYNTAX_EXPECTED_COMMA},
        {R"({"id":1,"name":"owned","bases":[{"id":1}],"age":17})",
         JSON_ERROR_RANGE_NUMBER},
    };

    for (const failure_case &item : cases) {
        SCOPED_TRACE(item.input);
        tracked_allocations.reset();
        User value{};
        json_parser parser{};
        json_parser_init(&parser, &allocator, slice(item.input));
        EXPECT_FALSE(decodeUser(&parser, &value));
        EXPECT_EQ(parser.error.code, item.code);
        releaseUser(&allocator, &value);
        releaseUser(&allocator, &value);
        const User zero{};
        EXPECT_EQ(std::memcmp(&value, &zero, sizeof(value)), 0);
        EXPECT_TRUE(tracked_allocations.clean());
    }
}

TEST_F(GeneratedDecoderTest, EmptyValuesOnlyAllocateRequiredState)
{
    User user{};
    json_parser parser{};
    ASSERT_TRUE(decode(R"({"id":1,"age":18,"bases":[],"metadata":{}})", &user, &parser));
    EXPECT_EQ(user.bases, nullptr);
    EXPECT_EQ(user.basesLen, 0U);
    EXPECT_EQ(tracked_allocations.allocation_count, 1U);
    EXPECT_EQ(json_peek_token(&parser)->kind, JSON_TOKEN_EOF);
    releaseUser(&allocator, &user);
    EXPECT_EQ(tracked_allocations.free_count, 1U);
}

TEST_F(GeneratedDecoderTest, RequiredNullAndMissingAreDistinct)
{
    User user{};
    json_parser parser{};
    EXPECT_FALSE(decode(R"({"id":1,"age":18,"bases":null,"metadata":{}})", &user, &parser));
    EXPECT_EQ(parser.error.code, JSON_ERROR_OTHER_NULL_REQUIRED_VALUE);
    EXPECT_EQ(tracked_allocations.allocation_count, 1U);
    EXPECT_EQ(tracked_allocations.free_count, 1U);

    parser = {};
    user = {};
    EXPECT_FALSE(decode(R"({"id":1,"age":18,"bases":[]})", &user, &parser));
    EXPECT_EQ(parser.error.code, JSON_ERROR_OTHER_MISSING_REQUIRED_KEY);
    EXPECT_EQ(tracked_allocations.allocation_count, 2U);
    EXPECT_EQ(tracked_allocations.free_count, 2U);
}

TEST_F(GeneratedDecoderTest, EscapedKeyUsesGeneratedDispatchMap)
{
    User user{};
    json_parser parser{};
    ASSERT_TRUE(decode(R"({"\u0069d":1,"age":18,"bases":[],"metadata":{}})", &user, &parser));
    EXPECT_EQ(user.id, 1U);
    // The escaped key is temporarily owned, then released after dispatch.
    EXPECT_EQ(tracked_allocations.allocation_count, 2U);
    EXPECT_EQ(tracked_allocations.free_count, 2U);
    releaseUser(&allocator, &user);
}

TEST_F(GeneratedDecoderTest, EmptyStringIsAllocatedAndCleanupIsRepeatable)
{
    User user{};
    json_parser parser{};
    ASSERT_TRUE(decode(R"({"id":1,"name":"","age":18,"bases":[],"metadata":{}})", &user, &parser));
    ASSERT_NE(user.name, nullptr);
    EXPECT_STREQ(user.name, "");
    EXPECT_EQ(tracked_allocations.allocation_count, 2U);
    EXPECT_EQ(tracked_allocations.free_count, 1U);
    releaseUser(&allocator, &user);
    releaseUser(&allocator, &user);
    EXPECT_EQ(tracked_allocations.free_count, 2U);
    EXPECT_EQ(user.name, nullptr);
}

TEST_F(GeneratedDecoderTest, DynamicArrayDecodesAndReleasesElements)
{
    User user{};
    json_parser parser{};
    ASSERT_TRUE(decode(
        R"({"user-id":9,"age":20,"bases":[{"id":7,"name":"city"}],"metadata":{},"accessCnt":3,"lastAccess":4,"unknown":{"x":[1]}})",
        &user, &parser));
    ASSERT_NE(user.bases, nullptr);
    ASSERT_EQ(user.basesLen, 1U);
    EXPECT_EQ(user.bases[0].id, 7);
    EXPECT_STREQ(user.bases[0].name, "city");
    EXPECT_EQ(user.data.accessCnt, 3);
    EXPECT_EQ(user.data.lastAccess, 4);
    EXPECT_EQ(tracked_allocations.allocation_count, 2U);
    releaseUser(&allocator, &user);
    EXPECT_EQ(tracked_allocations.free_count, 2U);
}

TEST_F(GeneratedDecoderTest, DuplicateKeysUseLastValueWithoutLeaking)
{
    User user{};
    json_parser parser{};
    ASSERT_TRUE(decode(
        R"({"id":1,"user-id":2,"name":"first","name":"second","age":18,"bases":[],"metadata":{}})",
        &user, &parser));
    EXPECT_EQ(user.id, 2U);
    ASSERT_NE(user.name, nullptr);
    EXPECT_STREQ(user.name, "second");
    EXPECT_EQ(tracked_allocations.allocation_count, 3U);
    EXPECT_EQ(tracked_allocations.free_count, 2U);
    releaseUser(&allocator, &user);
    EXPECT_TRUE(tracked_allocations.clean());
}

TEST_F(GeneratedDecoderTest, RangeFailureRollsBack)
{
    User user{};
    json_parser parser{};
    tracked_allocations.reset();
    EXPECT_FALSE(decode(
        R"({"id":1,"bases":[{"id":7}],"age":17,"metadata":{}})",
        &user, &parser));
    EXPECT_EQ(parser.error.code, JSON_ERROR_RANGE_NUMBER);
    EXPECT_EQ(tracked_allocations.allocation_count, 2U);
    EXPECT_EQ(tracked_allocations.free_count, 2U);
    EXPECT_EQ(user.bases, nullptr);
    EXPECT_EQ(user.basesLen, 0U);
}

TEST_F(GeneratedDecoderTest, ArrayRecordEmptyAndNullNeverAllocate)
{
    IntVec values{};
    json_parser parser{};
    json_parser_init(&parser, &allocator, slice("[]"));
    ASSERT_TRUE(decodeIntVec(&parser, &values));
    EXPECT_EQ(values.elems, nullptr);
    EXPECT_EQ(values.len, 0U);
    EXPECT_EQ(values.cap, 0U);
    EXPECT_EQ(values.reserved, 0U);
    EXPECT_EQ(tracked_allocations.allocation_count, 0U);

    parser = {};
    values = {};
    json_parser_init(&parser, &allocator, slice("null"));
    EXPECT_FALSE(decodeIntVec(&parser, &values));
    EXPECT_EQ(parser.error.code, JSON_ERROR_TYPE_MISMATCH);
    EXPECT_EQ(tracked_allocations.allocation_count, 0U);
    EXPECT_EQ(values.elems, nullptr);
}

TEST_F(GeneratedDecoderTest, ArrayRecordStoresLengthAndActualCapacity)
{
    IntVec values{};
    json_parser parser{};
    json_parser_init(&parser, &allocator, slice("[10,20]"));
    ASSERT_TRUE(decodeIntVec(&parser, &values));
    ASSERT_NE(values.elems, nullptr);
    EXPECT_EQ(values.len, 2U);
    EXPECT_EQ(values.cap, 16U / sizeof(i32));
    EXPECT_EQ(values.elems[0], 10);
    EXPECT_EQ(values.elems[1], 20);
    EXPECT_EQ(values.reserved, 0U);
    releaseIntVec(&allocator, &values);
    releaseIntVec(&allocator, &values);
    EXPECT_EQ(tracked_allocations.allocation_count, 1U);
    EXPECT_EQ(tracked_allocations.free_count, 1U);
    EXPECT_EQ(values.elems, nullptr);
}

TEST_F(GeneratedDecoderTest, LenOnlyAndElemsOnlyArrayRecordsDecode)
{
    NarrowIntVec with_len{};
    BareIntVec bare{};
    json_parser parser{};
    json_parser_init(&parser, &allocator, slice("[3,4]"));
    ASSERT_TRUE(decodeNarrowIntVec(&parser, &with_len));
    ASSERT_NE(with_len.elems, nullptr);
    EXPECT_EQ(with_len.len, 2U);

    parser = {};
    json_parser_init(&parser, &allocator, slice("[7]"));
    ASSERT_TRUE(decodeBareIntVec(&parser, &bare));
    ASSERT_NE(bare.elems, nullptr);
    EXPECT_EQ(bare.elems[0], 7);

    releaseNarrowIntVec(&allocator, &with_len);
    releaseBareIntVec(&allocator, &bare);
    EXPECT_TRUE(tracked_allocations.clean());
}

TEST_F(GeneratedDecoderTest, CapOnlyResourceElementsUseZeroedSpareSlots)
{
    StringSlots values{};
    json_parser parser{};
    json_parser_init(&parser, &allocator, slice(R"(["first"])"));
    ASSERT_TRUE(decodeStringSlots(&parser, &values));
    ASSERT_NE(values.elems, nullptr);
    ASSERT_EQ(values.cap, 16U / sizeof(char *));
    ASSERT_GE(values.cap, 1U);
    EXPECT_STREQ(values.elems[0], "first");
    for (size_t index = 1; index < values.cap; ++index) {
        EXPECT_EQ(values.elems[index], nullptr);
    }
    releaseStringSlots(&allocator, &values);
    releaseStringSlots(&allocator, &values);
    EXPECT_TRUE(tracked_allocations.clean());
    EXPECT_EQ(values.elems, nullptr);
}

TEST_F(GeneratedDecoderTest, ArrayRecordPointerNullAndRequiredRules)
{
    VecEnvelope envelope{};
    json_parser parser{};
    json_parser_init(&parser, &allocator, slice(R"({"optional":null,"required":[]})"));
    ASSERT_TRUE(decodeVecEnvelope(&parser, &envelope));
    EXPECT_EQ(envelope.optional, nullptr);
    ASSERT_NE(envelope.required, nullptr);
    EXPECT_EQ(envelope.required->elems, nullptr);
    EXPECT_EQ(envelope.required->len, 0U);
    EXPECT_EQ(envelope.required->cap, 0U);
    EXPECT_EQ(tracked_allocations.allocation_count, 2U);
    releaseVecEnvelope(&allocator, &envelope);
    EXPECT_TRUE(tracked_allocations.clean());

    parser = {};
    envelope = {};
    tracked_allocations.reset();
    json_parser_init(&parser, &allocator, slice(R"({"required":null})"));
    EXPECT_FALSE(decodeVecEnvelope(&parser, &envelope));
    EXPECT_EQ(parser.error.code, JSON_ERROR_OTHER_NULL_REQUIRED_VALUE);
    EXPECT_EQ(tracked_allocations.allocation_count, 1U);
    EXPECT_EQ(tracked_allocations.free_count, 1U);

    parser = {};
    envelope = {};
    tracked_allocations.reset();
    json_parser_init(&parser, &allocator, slice("{}"));
    EXPECT_FALSE(decodeVecEnvelope(&parser, &envelope));
    EXPECT_EQ(parser.error.code, JSON_ERROR_OTHER_MISSING_REQUIRED_KEY);
    EXPECT_EQ(tracked_allocations.allocation_count, 1U);
    EXPECT_EQ(tracked_allocations.free_count, 1U);
}

TEST_F(GeneratedDecoderTest, ArrayRecordElementFailureRollsBackCurrentSlot)
{
    StringSlots values{};
    json_parser parser{};
    json_parser_init(&parser, &allocator, slice(R"(["first",1])"));
    EXPECT_FALSE(decodeStringSlots(&parser, &values));
    EXPECT_EQ(parser.error.code, JSON_ERROR_TYPE_MISMATCH);
    EXPECT_EQ(values.elems, nullptr);
    EXPECT_EQ(values.cap, 0U);
    EXPECT_TRUE(tracked_allocations.clean());
}

TEST_F(GeneratedDecoderTest, ArrayRecordAllocatorFailureRollsBack)
{
    StringSlots values{};
    json_parser parser{};
    tracked_allocations.fail_at = 1;
    json_parser_init(&parser, &allocator, slice(R"(["first"])"));
    EXPECT_FALSE(decodeStringSlots(&parser, &values));
    EXPECT_EQ(parser.error.code, JSON_ERROR_OTHER_NO_MEMORY);
    EXPECT_EQ(values.elems, nullptr);
    EXPECT_EQ(values.cap, 0U);
    EXPECT_EQ(tracked_allocations.allocation_count, 1U);
    EXPECT_EQ(tracked_allocations.free_count, 1U);
}

TEST_F(GeneratedDecoderTest, NarrowLengthOverflowReportsArrayRangeAndRollsBack)
{
    std::string input = "[";
    for (int index = 0; index < 256; ++index) {
        if (index != 0) input += ',';
        input += '0';
    }
    input += ']';

    NarrowIntVec values{};
    json_parser parser{};
    json_parser_init(&parser, &allocator, {input.data(), input.size()});
    EXPECT_FALSE(decodeNarrowIntVec(&parser, &values));
    EXPECT_EQ(parser.error.code, JSON_ERROR_RANGE_ARRAY_LENGTH);
    EXPECT_EQ(values.elems, nullptr);
    EXPECT_EQ(values.len, 0U);
    EXPECT_TRUE(tracked_allocations.clean());
}

}  // namespace
