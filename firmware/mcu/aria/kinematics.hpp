/**
 * kinematics.hpp - Joint clamping, forward kinematics, and slew interpolation in C++.
 * Mirrors backend/app/core/kinematics.py precisely.
 */
#pragma once

#ifndef ARIA_KINEMATICS_HPP
#define ARIA_KINEMATICS_HPP

#include <math.h>
#include <algorithm>
#include "pins.h"

struct Joints {
    float head_pan;
    float head_tilt;
    float waist_yaw;
    float l_shoulder_pitch;
    float r_shoulder_pitch;
    float l_shoulder_roll;
    float r_shoulder_roll;
    float l_elbow;
    float r_elbow;
};

inline float clamp(float val, float min_val, float max_val) {
    return std::max(min_val, std::min(max_val, val));
}

inline Joints clamp_joints(Joints j) {
    return {
        clamp(j.head_pan, LIM_HEAD_PAN_MIN, LIM_HEAD_PAN_MAX),
        clamp(j.head_tilt, LIM_HEAD_TILT_MIN, LIM_HEAD_TILT_MAX),
        clamp(j.waist_yaw, LIM_WAIST_YAW_MIN, LIM_WAIST_YAW_MAX),
        clamp(j.l_shoulder_pitch, LIM_L_SHOULDER_PITCH_MIN, LIM_L_SHOULDER_PITCH_MAX),
        clamp(j.r_shoulder_pitch, LIM_R_SHOULDER_PITCH_MIN, LIM_R_SHOULDER_PITCH_MAX),
        clamp(j.l_shoulder_roll, LIM_L_SHOULDER_ROLL_MIN, LIM_L_SHOULDER_ROLL_MAX),
        clamp(j.r_shoulder_roll, LIM_R_SHOULDER_ROLL_MIN, LIM_R_SHOULDER_ROLL_MAX),
        clamp(j.l_elbow, LIM_L_ELBOW_MIN, LIM_L_ELBOW_MAX),
        clamp(j.r_elbow, LIM_R_ELBOW_MIN, LIM_R_ELBOW_MAX)
    };
}

inline float slew_angle(float current, float target, float max_delta) {
    float diff = target - current;
    if (fabs(diff) <= max_delta) return target;
    return current + (diff > 0 ? max_delta : -max_delta);
}

#endif // ARIA_KINEMATICS_HPP
