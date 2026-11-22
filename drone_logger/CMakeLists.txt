pkg_check_modules(GST REQUIRED IMPORTED_TARGET gstreamer-1.0 gstreamer-app-1.0 gstreamer-video-1.0)
find_package(nlohmann_json 3 REQUIRED)   # JSON messages on UDP 5601 (apt: nlohmann-json3-dev)

add_executable(drone_logger
    src/main.cpp
    src/rtp.cpp
    src/frame_assembler.cpp
    src/pipeline.cpp
    src/messages.cpp
)
target_link_libraries(drone_logger PRIVATE common PkgConfig::GST nlohmann_json::nlohmann_json)
