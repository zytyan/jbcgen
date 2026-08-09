cmake_minimum_required(VERSION 3.14)
project(json_c_generator LANGUAGES C CXX)

set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)


option(ENABLE_SANITIZERS "Enable AddressSanitizer and UndefinedBehaviorSanitizer" OFF)
option(ENABLE_LSAN_CHECKS "Enable LeakSanitizer checks for sanitizer tests" OFF)

if(ENABLE_SANITIZERS)
    if(NOT CMAKE_C_COMPILER_ID MATCHES "GNU|Clang" OR
       NOT CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
        message(FATAL_ERROR "ENABLE_SANITIZERS requires GCC or Clang")
    endif()
    add_compile_options(-fsanitize=address,undefined -fno-omit-frame-pointer -g)
    add_link_options(-fsanitize=address,undefined)
    if(ENABLE_LSAN_CHECKS)
        set(ENV{LSAN_OPTIONS} "detect_leaks=1")
        set(ENV{ASAN_OPTIONS} "detect_leaks=1")
    else()
        set(ENV{LSAN_OPTIONS} "detect_leaks=0")
        set(ENV{ASAN_OPTIONS} "detect_leaks=0")
    endif()
endif()

add_library(zjson_pull_api
    json_any_vec.c
    json_error.c
    json_pull.c
    json_str_slice.c
    json_tokenizer.c
    json_writer.c
)
target_include_directories(zjson_pull_api PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})

include(CTest)
if(BUILD_TESTING)
    find_package(GTest REQUIRED)
    enable_testing()
    add_subdirectory(tests)
endif()
