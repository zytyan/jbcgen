cmake_minimum_required(VERSION 3.14)
project(json_reflect_api LANGUAGES C)

set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
option(JSON_REFLECT_BUILD_TESTS "Build json_reflect_api tests" OFF)
option(
    JSON_REFLECT_ENABLE_SANITIZERS
    "Enable AddressSanitizer and UndefinedBehaviorSanitizer for json_reflect_api"
    OFF
)
option(
    JSON_REFLECT_ENABLE_LSAN_CHECKS
    "Enable LeakSanitizer checks for json_reflect_api sanitizer tests"
    OFF
)

if(JSON_REFLECT_ENABLE_LSAN_CHECKS AND NOT JSON_REFLECT_ENABLE_SANITIZERS)
    message(FATAL_ERROR
        "JSON_REFLECT_ENABLE_LSAN_CHECKS requires JSON_REFLECT_ENABLE_SANITIZERS"
    )
endif()

if(JSON_REFLECT_ENABLE_SANITIZERS)
    if(NOT CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
        message(FATAL_ERROR "JSON_REFLECT_ENABLE_SANITIZERS requires GCC or Clang")
    endif()
endif()

add_library(json_reflect_api
    json_any_vec.c
    json_error.c
    json_key_dispatch.c
    json_pull.c
    json_reflect.c
    json_reflect_array.c
    json_reflect_basic_types.c
    json_reflect_object.c
    json_reflect_release.c
    json_reflect_scalar.c
    json_reflect_support.c
    json_str_slice.c
    json_tokenizer.c
)
target_include_directories(json_reflect_api PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
if(JSON_REFLECT_ENABLE_SANITIZERS)
    target_compile_options(json_reflect_api PRIVATE
        -fsanitize=address,undefined
        -fno-omit-frame-pointer
        -g
    )
    target_link_options(json_reflect_api PUBLIC -fsanitize=address,undefined)
endif()
set_target_properties(json_reflect_api PROPERTIES
    VERSION 1.0.0
    SOVERSION 1
)

include(${CMAKE_CURRENT_SOURCE_DIR}/cmake/JsonReflectGenerate.cmake)

if(JSON_REFLECT_BUILD_TESTS)
    enable_language(CXX)
    set(CMAKE_CXX_STANDARD 17)
    set(CMAKE_CXX_STANDARD_REQUIRED ON)
    if(JSON_REFLECT_ENABLE_SANITIZERS AND
       NOT CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
        message(FATAL_ERROR "JSON_REFLECT_ENABLE_SANITIZERS requires GCC or Clang")
    endif()
    find_package(GTest REQUIRED)

    set(JBCGEN_ROOT ${CMAKE_CURRENT_SOURCE_DIR}/..)
    set(GENERATED_DIR ${CMAKE_CURRENT_BINARY_DIR}/generated)
    set(GENERATED_SOURCE ${GENERATED_DIR}/example_json.c)
    enable_testing()
    add_subdirectory(tests)
endif()
