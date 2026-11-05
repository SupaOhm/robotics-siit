
# ROS 2 Humble Environment for Lane 5
# Simulation & QA - CoppeliaSim ROS Bridge

# 1. Use ROS 2 Humble as the base image
FROM ros:humble-ros-base

# 2. Install Python pip
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    python3-pip && \
    rm -rf /var/lib/apt/lists/*

# 3. Install CoppeliaSim ZeroMQ Remote API Client
RUN python3 -m pip install --no-cache-dir \
    coppeliasim-zmqremoteapi-client

# 4. Set ROS 2 environment variables
ENV ROS_DOMAIN_ID=42
ENV RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

# 5. Install Cyclone DDS for ROS 2
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ros-humble-rmw-cyclonedds-cpp && \
    rm -rf /var/lib/apt/lists/*

# 6. Set working directory
WORKDIR /workspace

# 7. Start Bash with ROS 2 environment
CMD ["/bin/bash"]
