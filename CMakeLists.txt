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

# drone_logger needs GStreamer (gstreamer-1.0, -app, -video). Skipped with a
# message when the development packages are absent, so the other loggers still build.
option(BUILD_DRONE_LOGGER "Build drone_logger (needs GStreamer)" ON)
if(BUILD_DRONE_LOGGER)
    find_package(PkgConfig REQUIRED)
    pkg_check_modules(GST_CHECK QUIET gstreamer-1.0 gstreamer-app-1.0 gstreamer-video-1.0)
    if(GST_CHECK_FOUND)
        add_subdirectory(drone_logger)
    else()
        message(STATUS "GStreamer development packages not found: drone_logger is not built")
    endif()
endif()
