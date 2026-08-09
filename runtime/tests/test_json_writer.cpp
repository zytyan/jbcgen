#include <cmath>
#include <cfloat>
#include <cstring>
#include <string>
#include <vector>

#include "json_writer.h"
#include "gtest/gtest.h"

TEST(JsonWriterTest, ReportsActualBytesWrittenOnShortOutput)
{
    const std::string expected = R"({"name":"a\n\"b","ok":true,"n":-42})";
    for (size_t capacity = 0; capacity <= expected.size() + 1; capacity++) {
        std::vector<char> output(capacity == 0 ? 1 : capacity, '#');
        json_writer writer;
        json_writer_init(&writer, capacity == 0 ? nullptr : output.data(), capacity, 0);
        bool encoded = json_writer_write_raw(&writer, expected.data(), expected.size());
        size_t written = 0;
        bool finished = json_writer_finish(&writer, &written);
        size_t actual = capacity == 0 ? 0 : (expected.size() < capacity ? expected.size() : capacity - 1);
        EXPECT_EQ(encoded, capacity > expected.size());
        EXPECT_EQ(finished, capacity > expected.size());
        EXPECT_EQ(written, actual);
        if (capacity != 0) {
            EXPECT_EQ(output[written], '\0');
            EXPECT_EQ(std::string(output.data()), expected.substr(0, written));
        }
    }
}

TEST(JsonWriterTest, PrettyWhitespaceAndExactCapacity)
{
    char output[32];
    json_writer writer;
    json_writer_init(&writer, output, sizeof(output), 2);
    ASSERT_TRUE(json_writer_write_char(&writer, '['));
    ASSERT_TRUE(json_writer_newline_indent(&writer, 1));
    ASSERT_TRUE(json_writer_write_f64(&writer, 1.5));
    ASSERT_TRUE(json_writer_newline_indent(&writer, 0));
    ASSERT_TRUE(json_writer_write_char(&writer, ']'));
    size_t written = 0;
    EXPECT_TRUE(json_writer_finish(&writer, &written));
    EXPECT_EQ(std::string(output), "[\n  1.5\n]");
    EXPECT_EQ(written, strlen(output));
}

TEST(JsonWriterTest, RejectsNonFiniteFloat)
{
    char output[16];
    json_writer writer;
    json_writer_init(&writer, output, sizeof(output), 0);
    EXPECT_FALSE(json_writer_write_f64(&writer, NAN));
    size_t written = 0;
    EXPECT_FALSE(json_writer_finish(&writer, &written));
    EXPECT_EQ(output[0], '\0');
}

TEST(JsonWriterTest, PreservesDoubleRoundTripFormatting)
{
    struct {
        double value;
        const char *expected;
    } cases[] = {
        {0.0, "0"},
        {-0.0, "-0"},
        {0.1, "0.10000000000000001"},
        {1e-300, "1e-300"},
        {1e300, "1.0000000000000001e+300"},
        {DBL_MIN, "2.2250738585072014e-308"},
        {DBL_MAX, "1.7976931348623157e+308"},
    };

    for (const auto &test : cases) {
        char output[64];
        json_writer writer;
        json_writer_init(&writer, output, sizeof(output), 0);
        ASSERT_TRUE(json_writer_write_f64(&writer, test.value));
        size_t written = 0;
        ASSERT_TRUE(json_writer_finish(&writer, &written));
        EXPECT_STREQ(output, test.expected);
        EXPECT_EQ(written, strlen(test.expected));
    }
}

TEST(JsonWriterTest, WritesHexUint64AsJsonString)
{
    char output[32];
    json_writer writer;
    json_writer_init(&writer, output, sizeof(output), 0);
    EXPECT_TRUE(json_writer_write_hex_u64(&writer, UINT64_MAX));
    size_t written = 0;
    EXPECT_TRUE(json_writer_finish(&writer, &written));
    EXPECT_EQ(std::string(output), R"("0xffffffffffffffff")");
    EXPECT_EQ(written, strlen(output));
}

TEST(JsonWriterTest, EscapesAllJsonControlCharacters)
{
    const char input[] = "\"\\\b\f\n\r\t\x01\x1f";
    char output[64];
    json_writer writer;
    json_writer_init(&writer, output, sizeof(output), 0);

    ASSERT_TRUE(json_writer_write_string(&writer, input));
    size_t written = 0;
    ASSERT_TRUE(json_writer_finish(&writer, &written));
    EXPECT_STREQ(output, R"json("\"\\\b\f\n\r\t\u0001\u001f")json");
    EXPECT_EQ(written, strlen(output));
}

TEST(JsonWriterTest, RejectsInvalidWriterInputs)
{
    json_writer writer;
    char output[8];
    size_t written = 0;

    json_writer_init(&writer, nullptr, sizeof(output), 0);
    EXPECT_FALSE(writer.valid);
    EXPECT_FALSE(json_writer_write_raw(&writer, "x", 1));
    EXPECT_FALSE(json_writer_finish(&writer, &written));

    json_writer_init(&writer, output, sizeof(output), 0);
    EXPECT_FALSE(json_writer_write_raw(&writer, nullptr, 1));
    EXPECT_FALSE(json_writer_write_cstr(&writer, nullptr));
    EXPECT_FALSE(json_writer_finish(&writer, nullptr));
}

TEST(JsonWriterTest, SupportsNegativeIndent)
{
    char output[8];
    json_writer writer;
    json_writer_init(&writer, output, sizeof(output), -1);
    ASSERT_TRUE(json_writer_newline_indent(&writer, 2));
    size_t written = 0;
    ASSERT_TRUE(json_writer_finish(&writer, &written));
    EXPECT_EQ(std::string(output), "\n\t\t");
    EXPECT_EQ(written, 3u);
}
