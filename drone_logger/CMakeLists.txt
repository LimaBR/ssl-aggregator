pkg_check_modules(GST REQUIRED IMPORTED_TARGET gstreamer-1.0 gstreamer-app-1.0 gstreamer-video-1.0)

add_executable(drone_logger
    src/main.cpp
    src/rtp.cpp
    src/frame_assembler.cpp
    src/pipeline.cpp
)
target_link_libraries(drone_logger PRIVATE common PkgConfig::GST)
