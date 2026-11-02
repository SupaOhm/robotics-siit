# Context

Project glossary for the gesture-controlled security robot.

## Terms

**Password**:
A secret the person says aloud into the robot's microphone to pass the checkpoint. It is spoken, not a hand gesture. What exactly is said (a fixed phrase, spoken digits, or an answer to a question) is not yet decided.
_Avoid_: gesture password, finger-count sequence (an earlier, superseded reading).

**Gesture command**:
A hand gesture the operator uses to drive the robot. Gestures are for driving only, not for the password.
_Avoid_: gesture password.

**Checkpoint**:
The state in which the robot has stopped for a person and asks for the password.

**Operator**:
The person who drives the robot with gestures and answers Telegram alerts (Allow / Deny).

**Obstacle**:
Anything the distance sensor stops the robot for.

**Object**:
An obstacle named from the name table, such as a chair.
_Avoid_: using "object" for an obstacle the robot can't name.

**Person**:
A human detected in the camera frame, whether or not they are the operator.

**Unknown obstacle**:
An obstacle the detector can't name. The robot announces it as "Found an obstacle".
