import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    config = os.path.join(get_package_share_directory("password_system"),
                          "config", "password.yaml")
    return LaunchDescription([
        DeclareLaunchArgument("input_mode", default_value="mic"),
        DeclareLaunchArgument("engine", default_value="vosk"),
        DeclareLaunchArgument("vosk_model_path", default_value=""),
        Node(
            package="password_system",
            executable="password_node",
            name="password_node",
            output="screen",
            parameters=[config, {
                "input_mode": LaunchConfiguration("input_mode"),
                "engine": LaunchConfiguration("engine"),
                "vosk_model_path": LaunchConfiguration("vosk_model_path"),
            }],
        ),
    ])
