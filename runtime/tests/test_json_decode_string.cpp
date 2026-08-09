#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <limits>
#include <string>
#include <vector>
#include "gtest/gtest.h"
#include "json_pull.h"
#include "json_str_slice.h"

class JsonPullTest : public ::testing::Test {
  protected:
    json_allocator allocator;

    void SetUp() override
    {
        allocator.malloc = malloc;
        allocator.free = free;
    }

    static json_str_slice make_slice(const char *str)
    {
        return {str, str + strlen(str)};
    }

    static std::string format_error(const json_parser &parser)
    {
        size_t needed = json_estimate_error_msg_len(&parser);
        std::vector<char> message(needed + 1);
        if (needed != 0) {
            json_fmt_error(&parser, message.data());
        }
        return std::string(message.data(), needed);
    }
};

TEST_F(JsonPullTest, DecodeString)
{
    struct {
        const char *input;
        const char *expected;
    } success_cases[] = {
        {R"("")", ""},
        {R"("hello")", "hello"},
        {R"("\n")", "\n"},
        {R"("\n\r")", "\n\r"},
        {R"("\t")", "\t"},
        {R"("\u0040")", "@"},
        {R"("AAA \u5efa\u6750\u738b\u54e5")", "AAA 建材王哥"},
        {R"("\u5c0f\u5b66\u82f1\u8bedABC")", "小学英语ABC"},
        {R"("\u6ca1\u62db\u4e86\u5144\u5f1f\uff0c\ud83d\ude05aa")", "没招了兄弟，😅aa"},
        {R"("中文当然原样")", R"(中文当然原样)"},
        {R"("emoji也原样😅")", R"(emoji也原样😅)"},
    };

    for (size_t i = 0; i < sizeof(success_cases) / sizeof(success_cases[0]); i++) {
        json_parser parser;
        json_parser_init(&parser, &allocator, make_slice(success_cases[i].input));
        json_string result = {0};
        bool decode_result = json_decode_string(&parser, &result);
        EXPECT_TRUE(decode_result) << "Input: " << success_cases[i].input << "\n"
                                   << format_error(parser);
        EXPECT_TRUE(parser.valid) << "Input: " << success_cases[i].input << "\n"
                                  << format_error(parser);
        auto got = std::string(result.text.begin, result.text.end);
        EXPECT_TRUE(json_slice_eq_str(&result.text, success_cases[i].expected))
            << "Input: " << success_cases[i].input << "\n"
            << "Expected: " << success_cases[i].expected << "(size: " << strlen(success_cases[i].expected) << ")\n"
            << "Got: " << got << "(size: " << got.size() << ")\n";
        json_free_string(&allocator, &result);
    }

    struct {
        const char *input;
        const char *description;
        json_error_code code;
        size_t offset;
    } failure_cases[] = {
        {R"json("\x")json", "invalid escape sequence", JSON_ERROR_ESCAPE_INVALID_SEQUENCE, 2},
        {R"json("\u12G4")json", "invalid Unicode escape", JSON_ERROR_ESCAPE_INVALID_UNICODE, 5},
        {R"("unclosed)", "unterminated string", JSON_ERROR_SYNTAX_UNTERMINATED_STRING, 9},
        {"123", "not a string", JSON_ERROR_TYPE_MISMATCH, 0},
    };

    for (size_t i = 0; i < sizeof(failure_cases) / sizeof(failure_cases[0]); i++) {
        json_parser parser;
        json_parser_init(&parser, &allocator, make_slice(failure_cases[i].input));
        json_string result = {0};
        bool decode_result = json_decode_string(&parser, &result);
        EXPECT_FALSE(decode_result) << "Input: " << failure_cases[i].input << " should fail";
        EXPECT_FALSE(parser.valid) << "Input: " << failure_cases[i].input << " should be invalid";
        EXPECT_EQ(parser.error.code, failure_cases[i].code) << failure_cases[i].description;
        EXPECT_EQ(parser.error.location.offset, failure_cases[i].offset) << failure_cases[i].description;
        EXPECT_EQ(result.owner, nullptr);
    }
}
