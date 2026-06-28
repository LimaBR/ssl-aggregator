find_package(Protobuf REQUIRED)

set(PROTO_DIR ${CMAKE_SOURCE_DIR}/third_party/proto)
# Lets protoc resolve the cross-imports between the three .proto files.
set(Protobuf_IMPORT_DIRS ${PROTO_DIR})

protobuf_generate_cpp(PROTO_SRCS PROTO_HDRS
    ${PROTO_DIR}/messages_robocup_ssl_detection.proto
    ${PROTO_DIR}/messages_robocup_ssl_geometry.proto
    ${PROTO_DIR}/messages_robocup_ssl_wrapper.proto
)

add_executable(vision_logger
    src/main.cpp
    ${PROTO_SRCS}
)
# Generated *.pb.h land in the build dir.
target_include_directories(vision_logger PRIVATE ${CMAKE_CURRENT_BINARY_DIR})
target_link_libraries(vision_logger PRIVATE common protobuf::libprotobuf)
