/**
 * pins.h - Hardware pin mappings and hardware-enforced limits for ARIA on Arduino UNO Q (Phase 7).
 * Spec 8.3.2, 12.6.3, 12.6.4
 */
#pragma once

#ifndef ARIA_PINS_H
#define ARIA_PINS_H

// --- PWM Servo Pin Map ---
#define PIN_SERVO_HEAD_PAN         2
#define PIN_SERVO_HEAD_TILT        3
#define PIN_SERVO_WAIST_YAW        4
#define PIN_SERVO_L_SHOULDER_PITCH 5
#define PIN_SERVO_R_SHOULDER_PITCH 6
#define PIN_SERVO_L_SHOULDER_ROLL  7
#define PIN_SERVO_R_SHOULDER_ROLL  8
#define PIN_SERVO_L_ELBOW          9
#define PIN_SERVO_R_ELBOW          10

// --- Motor Driver Pins (Differential Base) ---
#define PIN_MOTOR_L_PWM            11
#define PIN_MOTOR_L_DIR            12
#define PIN_MOTOR_R_PWM            13
#define PIN_MOTOR_R_DIR            14

// --- Safety & E-Stop Pin ---
#define PIN_ESTOP_INPUT            18 // Hardware interrupt pin
#define PIN_STATUS_LED             19

// --- Joint Servo Limits (Degrees) ---
// MUST stay in sync with backend/app/core/kinematics.py LIMITS
#define LIM_HEAD_PAN_MIN         -90.0f
#define LIM_HEAD_PAN_MAX          90.0f
#define LIM_HEAD_TILT_MIN        -35.0f
#define LIM_HEAD_TILT_MAX         35.0f
#define LIM_WAIST_YAW_MIN        -45.0f
#define LIM_WAIST_YAW_MAX         45.0f
#define LIM_L_SHOULDER_PITCH_MIN -20.0f
#define LIM_L_SHOULDER_PITCH_MAX 150.0f
#define LIM_R_SHOULDER_PITCH_MIN -20.0f
#define LIM_R_SHOULDER_PITCH_MAX 150.0f
#define LIM_L_SHOULDER_ROLL_MIN    0.0f
#define LIM_L_SHOULDER_ROLL_MAX   90.0f
#define LIM_R_SHOULDER_ROLL_MIN    0.0f
#define LIM_R_SHOULDER_ROLL_MAX   90.0f
#define LIM_L_ELBOW_MIN            0.0f
#define LIM_L_ELBOW_MAX          120.0f
#define LIM_R_ELBOW_MIN            0.0f
#define LIM_R_ELBOW_MAX          120.0f

#endif // ARIA_PINS_H
