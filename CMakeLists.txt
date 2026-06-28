cmake_minimum_required(VERSION 3.16)
project(ssl_aggregator CXX)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS ON)  # GNU extensions (gnu++23)

# Emit compile_commands.json so clangd / the VS Code C/C++ tools get full
# include paths and flags.
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Debug CACHE STRING "" FORCE)
endif()

add_compile_options(-Wall -Wextra -Wpedantic)

add_subdirectory(libcommon)
add_subdirectory(robot_logger)
add_subdirectory(vision_logger)
