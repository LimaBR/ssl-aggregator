add_executable(robot_logger
    src/main.cpp
    src/parser.cpp
)
target_link_libraries(robot_logger PRIVATE common)
