cmake_minimum_required(VERSION 3.14)

find_package(Python3 COMPONENTS Interpreter REQUIRED)

# Test source files
set(JSON_OBJS_TEST_SRC
        test_json_tokenizer.cpp
        test_json_pull.cpp
        test_json_decode_string.cpp
        test_json_str_slice.cpp
        test_json_writer.cpp
        ${GENERATED_SOURCE}
        ${GENERATED_TEST}
)

add_executable(
    zjson_test
    ${JSON_OBJS_TEST_SRC}
)

target_link_libraries(
    zjson_test
    PRIVATE
    GTest::gtest_main
    zjson_pull_api
)

target_include_directories(zjson_test PRIVATE ${GENERATED_DIR})

include(GoogleTest)
if(NOT ENABLE_SANITIZERS)
    gtest_discover_tests(zjson_test)
endif()

add_test(
    NAME zjson_test
    COMMAND zjson_test
)

if(ENABLE_SANITIZERS)
    if(ENABLE_LSAN_CHECKS)
        set_tests_properties(zjson_test PROPERTIES
            ENVIRONMENT "ASAN_OPTIONS=detect_leaks=1;LSAN_OPTIONS=detect_leaks=1"
        )
    else()
        set_tests_properties(zjson_test PROPERTIES
            ENVIRONMENT "ASAN_OPTIONS=detect_leaks=0;LSAN_OPTIONS=detect_leaks=0"
        )
    endif()
endif()
