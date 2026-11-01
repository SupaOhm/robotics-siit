import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    config = os.path.join(get_package_share_directory("gesture_control"),
                          "config", "gesture.yaml")
    return LaunchDescription([
        DeclareLaunchArgument("input_mode", default_value="camera"),
        DeclareLaunchArgument("camera_index", default_value="0"),
        DeclareLaunchArgument("model_path", default_value="~/hand_landmarker.task"),
        DeclareLaunchArgument("show_window", default_value="false"),
        Node(
            package="gesture_control",
            executable="gesture_node",
            name="gesture_node",
            output="screen",
            parameters=[config, {
                "input_mode": LaunchConfiguration("input_mode"),
                "camera_index": ParameterValue(LaunchConfiguration("camera_index"),
                                               value_type=int),
                "model_path": LaunchConfiguration("model_path"),
                "show_window": ParameterValue(LaunchConfiguration("show_window"),
                                              value_type=bool),
            }],
        ),
    ])
