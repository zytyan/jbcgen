#include "json_pull.h"
#include "gtest/gtest.h"
#include <cfloat>
#include <climits>
#include <limits>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <string>
#include <vector>

class JsonPullTest : public ::testing::Test {
  protected:
    json_allocator allocator;

    void SetUp() override
    {
        allocator.malloc = malloc;
        allocator.free = free;
    }

    static json_slice make_slice(const char *str) { return {str, strlen(str)}; }

    static std::string format_error(const json_parser &parser)
    {
        size_t needed = json_estimate_error_msg_len(&parser);
        std::vector<char> result(needed + 1);
        if (needed != 0) {
            json_fmt_error(&parser, result.data());
        }
        return std::string(result.data(), needed);
    }

    template <typename T>
    void expect_integer_success(const char *input, bool (*decode)(json_parser *, T *), T expected)
    {
        json_parser parser{};
        json_parser_init(&parser, &allocator, make_slice(input));
        T value{};
        EXPECT_TRUE(decode(&parser, &value)) << input << ": " << format_error(parser);
        EXPECT_EQ(value, expected) << input;
        EXPECT_EQ(json_peek_token(&parser)->kind, JSON_TOKEN_EOF) << input;
    }

    template <typename T>
    void expect_integer_range_failure(const char *input, bool (*decode)(json_parser *, T *),
                                      T initial)
    {
        json_parser parser{};
        json_parser_init(&parser, &allocator, make_slice(input));
        T value = initial;
        EXPECT_FALSE(decode(&parser, &value)) << input;
        EXPECT_EQ(value, initial) << input;
        EXPECT_EQ(parser.error.code, JSON_ERROR_RANGE_NUMBER)
            << input << ": " << format_error(parser);
    }
};

TEST_F(JsonPullTest, ParserInit)
{
    json_parser parser;
    json_parser_init(&parser, &allocator, make_slice("null"));
    EXPECT_TRUE(parser.valid);
}

TEST_F(JsonPullTest, DecodeNull)
{
    json_parser parser;
    json_parser_init(&parser, &allocator, make_slice("null"));
    bool result = json_decode_null(&parser);
    EXPECT_TRUE(result);
}

TEST_F(JsonPullTest, DecodeBool)
{
    struct {
        const char *input;
        bool expected;
    } cases[] = {
        {"true", true},
        {"false", false},
    };

    for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
        json_parser parser;
        json_parser_init(&parser, &allocator, make_slice(cases[i].input));
        bool value = false;
        bool result = json_decode_bool(&parser, &value);
        EXPECT_TRUE(result) << "Input: " << cases[i].input;
        EXPECT_EQ(value, cases[i].expected) << "Input: " << cases[i].input;
    }
}

TEST_F(JsonPullTest, SimpleArray)
{
    json_parser parser;
    json_parser_init(&parser, &allocator, make_slice("[]"));
    EXPECT_TRUE(json_array_begin(&parser));
    EXPECT_TRUE(json_array_try_end(&parser));
}

TEST_F(JsonPullTest, SimpleObject)
{
    json_parser parser;
    json_parser_init(&parser, &allocator, make_slice("{}"));
    EXPECT_TRUE(json_object_begin(&parser));
    EXPECT_TRUE(json_object_try_end(&parser));
}

TEST_F(JsonPullTest, ConsumeCommaReportsMissingComma)
{
    json_parser parser;
    json_parser_init(&parser, &allocator, make_slice("null"));
    EXPECT_FALSE(json_consume_comma(&parser));
    EXPECT_EQ(parser.error.code, JSON_ERROR_SYNTAX_EXPECTED_COMMA);
}

TEST_F(JsonPullTest, FormatsGeneratorErrors)
{
    struct {
        json_error_code code;
        const char *expected;
    } cases[] = {
        {JSON_ERROR_RANGE_STRING_LENGTH, "string length violates limit 7"},
        {JSON_ERROR_RANGE_ARRAY_LENGTH, "array length violates limit 7"},
        {JSON_ERROR_OTHER_MISSING_REQUIRED_KEY, "missing required key: value"},
        {JSON_ERROR_OTHER_NULL_REQUIRED_VALUE, "required value is null: value"},
        {JSON_ERROR_OTHER_EMBEDDED_NUL, "C string contains embedded NUL"},
    };
    for (const auto &item : cases) {
        json_parser parser;
        json_parser_init(&parser, &allocator, make_slice("null"));
        json_error_detail detail = {};
        detail.range.limit = 7;
        if (item.code == JSON_ERROR_OTHER_MISSING_REQUIRED_KEY ||
            item.code == JSON_ERROR_OTHER_NULL_REQUIRED_VALUE) {
            detail.other.context = {"value", "value" + 5};
        }
        json_set_error(&parser, item.code, &detail);
        EXPECT_NE(format_error(parser).find(item.expected), std::string::npos);
    }
}

TEST_F(JsonPullTest, ConsumeColon)
{
    json_parser parser;
    json_parser_init(&parser, &allocator, make_slice(":"));
    bool result = json_consume_colon(&parser);
    EXPECT_TRUE(result);
}

TEST_F(JsonPullTest, ParseLong)
{
    struct {
        const char *input;
        long expected;
    } cases[]{{"9223372036854775807", LONG_MAX},
              {"-9223372036854775808", LONG_MIN},
              {"0", 0LL},
              {"0000", 0LL},
              {"001", 1LL},
              {"00000000000000000000000000000000000000000000000000000000000000000"
               "0000000000000000000000000000000",
               0},
              {R"json("0xf")json", 15LL},
              {R"json("0x3000")json", 12288LL}};
    for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
        json_parser parser = {0};
        json_parser_init(&parser, &allocator, make_slice(cases[i].input));
        long real = 0;
        bool result = json_decode_long(&parser, &real);
        EXPECT_TRUE(result) << "Input: " << cases[i].input << "\n" << format_error(parser);
        EXPECT_EQ(real, cases[i].expected) << "Input: " << cases[i].input << "\n"
                                           << format_error(parser);
        EXPECT_EQ(json_peek_token(&parser)->kind, JSON_TOKEN_EOF);
    }
}

TEST_F(JsonPullTest, ParseAllBasicIntegerTypes)
{
    expect_integer_success<char>("0", json_decode_char, char{0});
    expect_integer_success<signed char>("-128", json_decode_signed_char, SCHAR_MIN);
    expect_integer_success<unsigned char>(R"json("0xff")json", json_decode_unsigned_char,
                                          UCHAR_MAX);
    expect_integer_success<short>("-32768", json_decode_short, SHRT_MIN);
    expect_integer_success<unsigned short>("65535", json_decode_unsigned_short, USHRT_MAX);
    expect_integer_success<int>("-2147483648", json_decode_int, INT_MIN);
    expect_integer_success<unsigned int>("4294967295", json_decode_unsigned_int, UINT_MAX);
    expect_integer_success<long>("9223372036854775807", json_decode_long, LONG_MAX);
    expect_integer_success<unsigned long>("18446744073709551615", json_decode_unsigned_long,
                                          ULONG_MAX);
    expect_integer_success<long long>("-9223372036854775808", json_decode_long_long, LLONG_MIN);
    expect_integer_success<unsigned long long>(R"json("0xffffffffffffffff")json",
                                               json_decode_unsigned_long_long, ULLONG_MAX);
}

TEST_F(JsonPullTest, RejectsOutOfRangeBasicIntegerTypes)
{
    expect_integer_range_failure<signed char>("-129", json_decode_signed_char, 11);
    expect_integer_range_failure<unsigned char>("256", json_decode_unsigned_char, 11);
    expect_integer_range_failure<short>("-32769", json_decode_short, 11);
    expect_integer_range_failure<unsigned short>("65536", json_decode_unsigned_short, 11);
    expect_integer_range_failure<int>("2147483648", json_decode_int, 11);
    expect_integer_range_failure<unsigned int>("4294967296", json_decode_unsigned_int, 11);
    expect_integer_range_failure<unsigned long>("-1", json_decode_unsigned_long, 11);
    expect_integer_range_failure<unsigned long long>("18446744073709551616",
                                                     json_decode_unsigned_long_long, 11);
}

TEST_F(JsonPullTest, ParseFloat64)
{
    struct {
        const char *input;
        double expected;
    } cases[]{
        {"0.0", 0.0},
        {"0.5", 0.5},
        {"1.0", 1.0},
        {"1e3", 1000.0},
        {"1", 1.0},
        {"-0", -0.0},
        // 解析小数用的是C标准库的strtod
        {"0.1", strtod("0.1", NULL)},
        {"0.33", strtod("0.33", NULL)},
        {"000000000000000000000000000000000.000000000000000000000000000000000", 0.0},
    };
    for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
        json_parser parser = {0};
        json_parser_init(&parser, &allocator, make_slice(cases[i].input));
        double real = 0;
        bool result = json_decode_double(&parser, &real);
        ASSERT_TRUE(parser.valid) << format_error(parser);
        ;
        EXPECT_TRUE(result) << "Input: " << cases[i].input << "\n" << format_error(parser);
        EXPECT_EQ(real, cases[i].expected) << "Input: " << cases[i].input << "\n"
                                           << format_error(parser);
        EXPECT_EQ(json_peek_token(&parser)->kind, JSON_TOKEN_EOF);
    }
}

TEST_F(JsonPullTest, ParseFloatAndRejectNarrowingOverflow)
{
    json_parser parser{};
    json_parser_init(&parser, &allocator, make_slice("1.5"));
    float value = 0.0F;
    ASSERT_TRUE(json_decode_float(&parser, &value));
    EXPECT_FLOAT_EQ(value, 1.5F);

    json_parser_init(&parser, &allocator, make_slice("3.5e38"));
    value = 7.0F;
    EXPECT_FALSE(json_decode_float(&parser, &value));
    EXPECT_FLOAT_EQ(value, 7.0F);
    EXPECT_EQ(parser.error.code, JSON_ERROR_RANGE_NUMBER);
}

TEST_F(JsonPullTest, ParseIntArray)
{
    const char *json = R"json(
    [1,2,3,4,5,0,0000,9223372036854775807,-9223372036854775808]
    )json";
    int64_t data[] = {1, 2, 3, 4, 5, 0, 0000, INT64_MAX, INT64_MIN};
    size_t data_len = sizeof(data) / sizeof(data[0]);
    json_parser parser;
    json_parser_init(&parser, &allocator, make_slice(json));
    EXPECT_TRUE(json_array_begin(&parser));
    EXPECT_FALSE(json_array_try_end(&parser));

    ASSERT_TRUE(parser.valid);
    size_t i = 0;
    while (true) {
        int64_t real = 0xdeadbeef; // 随机值，只要不是 data[i] 就行
        bool result = json_decode_long(&parser, &real);
        ASSERT_LE(i, data_len); // 一旦 i 越界，立刻终止测试避免段错误
        ASSERT_TRUE(parser.valid) << "i = " << i << ", " << format_error(parser);
        EXPECT_TRUE(result);
        EXPECT_EQ(real, data[i]) << format_error(parser);
        ;
        i++;
        if (json_array_try_end(&parser)) {
            break;
        }
        json_consume_comma(&parser);
        ASSERT_TRUE(parser.valid) << "i = " << i << ", " << format_error(parser);
    }
    ASSERT_TRUE(parser.valid) << format_error(parser);
    ;
    EXPECT_EQ(i, data_len);
    EXPECT_EQ(json_peek_token(&parser)->kind, JSON_TOKEN_EOF);
}

TEST_F(JsonPullTest, StructuredTypeErrorAndFormatting)
{
    json_parser parser{};
    json_parser_init(&parser, &allocator, make_slice("\r\n  123"));
    json_cow_str value{};
    ASSERT_FALSE(json_decode_string(&parser, &value));

    EXPECT_EQ(parser.error.code, JSON_ERROR_TYPE_MISMATCH);
    EXPECT_EQ(parser.error.detail.type.expected, JSON_EXPECTED_STRING);
    EXPECT_EQ(parser.error.detail.type.actual, JSON_TOKEN_INT);
    EXPECT_EQ(parser.error.location.offset, 4u);
    EXPECT_EQ(parser.error.location.line, 2u);
    EXPECT_EQ(parser.error.location.column, 3u);

    const std::string expected = "line 2, column 3: expected STRING, got INT";
    EXPECT_EQ(json_estimate_error_msg_len(&parser), expected.size());
    char exact[64] = {};
    json_fmt_error(&parser, exact);
    EXPECT_EQ(exact, expected);
}

TEST_F(JsonPullTest, FormatsAllErrorKinds)
{
    struct ErrorCase {
        json_error_code code;
        json_error_detail detail;
        const char *expected;
    };
    ErrorCase cases[] = {
        {JSON_ERROR_SYNTAX_UNKNOWN_CHARACTER,
         {.syntax = {.character = '@'}},
         "unknown character 0x40"},
        {JSON_ERROR_SYNTAX_INVALID_KEYWORD, {}, "invalid keyword"},
        {JSON_ERROR_SYNTAX_UNESCAPED_CONTROL,
         {.syntax = {.character = 1}},
         "unescaped control character 0x01 in string"},
        {JSON_ERROR_SYNTAX_UNTERMINATED_STRING, {}, "unterminated string"},
        {JSON_ERROR_SYNTAX_INVALID_NUMBER, {}, "invalid number"},
        {JSON_ERROR_SYNTAX_EXPECTED_TOKEN,
         {.syntax = {.expected = JSON_TOKEN_STRING, .actual = JSON_TOKEN_COMMA}},
         "expected STRING, got COMMA"},
        {JSON_ERROR_SYNTAX_EXPECTED_COMMA,
         {.syntax = {.actual = JSON_TOKEN_RBRACE}},
         "expected COMMA, got RBRACE"},
        {JSON_ERROR_ESCAPE_INVALID_SEQUENCE,
         {.escape = {.character = 'q'}},
         "invalid escape sequence \\q"},
        {JSON_ERROR_ESCAPE_INVALID_UNICODE, {}, "invalid Unicode escape"},
        {JSON_ERROR_TYPE_MISMATCH,
         {.type = {.expected = JSON_EXPECTED_OBJECT, .actual = JSON_TOKEN_NULL}},
         "expected OBJECT, got NULL"},
        {JSON_ERROR_RANGE_NUMBER, {}, "number out of range"},
        {JSON_ERROR_RANGE_NUMBER_LENGTH,
         {.range = {.limit = 12}},
         "number length exceeds limit 12"},
        {JSON_ERROR_RANGE_DEPTH, {.range = {.limit = 3}}, "JSON depth exceeds limit 3"},
        {JSON_ERROR_RANGE_BUFFER_TOO_SMALL,
         {.range = {.limit = 9}},
         "output buffer too small; need 9 bytes"},
        {JSON_ERROR_OTHER_NO_MEMORY, {}, "out of memory"},
        {JSON_ERROR_OTHER_INVALID_STATE, {}, "invalid parser state"},
    };

    for (const auto &test : cases) {
        json_parser parser{};
        parser.error.code = test.code;
        parser.error.location = {0, 2, 4};
        parser.error.detail = test.detail;
        const std::string expected = std::string("line 2, column 4: ") + test.expected;
        EXPECT_EQ(format_error(parser), expected) << test.expected;
    }
}

TEST_F(JsonPullTest, NoErrorFormatsAsEmptyString)
{
    json_parser parser{};
    json_parser_init(&parser, &allocator, make_slice("null"));
    char buf[] = "unchanged";
    EXPECT_EQ(json_estimate_error_msg_len(&parser), 0u);
    json_fmt_error(&parser, buf);
    EXPECT_STREQ(buf, "");
}

TEST_F(JsonPullTest, FormatsEntireEstimatedErrorMessage)
{
    std::string key(300, 'k');
    json_parser parser{};
    parser.error.code = JSON_ERROR_OTHER_MISSING_REQUIRED_KEY;
    parser.error.location = {0, 12, 34};
    parser.error.detail.other.context = {key.data(), key.data() + key.size()};

    const std::string expected = "line 12, column 34: missing required key: " + key;
    const size_t needed = json_estimate_error_msg_len(&parser);
    ASSERT_EQ(needed, expected.size());

    std::vector<char> buffer(needed + 2, 'x');
    json_fmt_error(&parser, buffer.data());
    EXPECT_EQ(std::string(buffer.data()), expected);
    EXPECT_EQ(buffer[needed], '\0');
    EXPECT_EQ(buffer[needed + 1], 'x');
}

TEST_F(JsonPullTest, EstimatesMaximumSizeValuesWithoutPrintf)
{
    json_parser parser{};
    parser.error.code = JSON_ERROR_RANGE_BUFFER_TOO_SMALL;
    parser.error.location = {SIZE_MAX, SIZE_MAX, SIZE_MAX};
    parser.error.detail.range.limit = SIZE_MAX;

    const std::string number = std::to_string(SIZE_MAX);
    const std::string expected = "line " + number + ", column " + number +
                                 ": output buffer too small; need " + number + " bytes";
    const size_t needed = json_estimate_error_msg_len(&parser);
    ASSERT_EQ(needed, expected.size());

    std::vector<char> buffer(needed + 1);
    json_fmt_error(&parser, buffer.data());
    EXPECT_EQ(std::string(buffer.data()), expected);
}

TEST_F(JsonPullTest, PreservesTokenizerRootCause)
{
    json_parser parser{};
    json_parser_init(&parser, &allocator, make_slice("nul"));
    ASSERT_EQ(parser.error.code, JSON_ERROR_SYNTAX_INVALID_KEYWORD);
    bool value = false;
    EXPECT_FALSE(json_decode_bool(&parser, &value));
    EXPECT_EQ(parser.error.code, JSON_ERROR_SYNTAX_INVALID_KEYWORD);
    EXPECT_EQ(parser.error.location.offset, 0u);
}

TEST_F(JsonPullTest, ReportsNumberAndDepthRanges)
{
    json_parser parser{};
    long integer = 0;
    json_parser_init(&parser, &allocator, make_slice("9223372036854775808"));
    EXPECT_FALSE(json_decode_long(&parser, &integer));
    EXPECT_EQ(parser.error.code, JSON_ERROR_RANGE_NUMBER);
    EXPECT_EQ(parser.error.detail.range.target, JSON_RANGE_NUMBER_VALUE);

    const char *long_number = "000000000000000000000000000000000";
    json_parser_init(&parser, &allocator, make_slice(long_number));
    parser.max_number_len = strlen(long_number);
    EXPECT_FALSE(json_decode_long(&parser, &integer));
    EXPECT_EQ(parser.error.code, JSON_ERROR_RANGE_NUMBER_LENGTH);
    EXPECT_EQ(parser.error.detail.range.limit, strlen(long_number));

    json_parser_init(&parser, &allocator, make_slice("[[0]]"));
    parser.max_depth = 1;
    ASSERT_TRUE(json_array_begin(&parser));
    EXPECT_FALSE(json_array_begin(&parser));
    EXPECT_EQ(parser.error.code, JSON_ERROR_RANGE_DEPTH);
    EXPECT_EQ(parser.error.detail.range.limit, 1u);
}

TEST_F(JsonPullTest, ReportsAllocationFailure)
{
    json_allocator failing_allocator = allocator;
    failing_allocator.malloc = [](size_t) -> void * { return nullptr; };
    json_parser parser{};
    json_parser_init(&parser, &failing_allocator, make_slice(R"json("\n")json"));
    json_cow_str value{};
    EXPECT_FALSE(json_decode_string(&parser, &value));
    EXPECT_EQ(parser.error.code, JSON_ERROR_OTHER_NO_MEMORY);
    EXPECT_EQ(json_cow_str_as_slice(&value).ptr, nullptr);
}
