/**
 * aria_main.ino - Arduino firmware for ARIA (Phase 7).
 * Handles PWM servo actuation, differential drive, hardware E-Stop, and serial packet communication.
 */
#include <Arduino.h>
#include <Servo.h>
#include "pins.h"
#include "kinematics.hpp"

// Servos
Servo s_head_pan;
Servo s_head_tilt;
Servo s_waist_yaw;
Servo s_l_shoulder_pitch;
Servo s_r_shoulder_pitch;
Servo s_l_shoulder_roll;
Servo s_r_shoulder_roll;
Servo s_l_elbow;
Servo s_r_elbow;

Joints current_joints = {0, 0, 0, 0, 0, 5, 5, 15, 15};
Joints target_joints = {0, 0, 0, 0, 0, 5, 5, 15, 15};
volatile bool estop_active = false;

void handle_estop_interrupt() {
    estop_active = true;
    // Immediate cut off of motor PWM
    analogWrite(PIN_MOTOR_L_PWM, 0);
    analogWrite(PIN_MOTOR_R_PWM, 0);
    digitalWrite(PIN_STATUS_LED, HIGH);
}

void setup() {
    Serial.begin(115200);
    
    // Status & E-Stop Pin setup
    pinMode(PIN_STATUS_LED, OUTPUT);
    pinMode(PIN_ESTOP_INPUT, INPUT_PULLUP);
    attachInterrupt(digitalPinToInterrupt(PIN_ESTOP_INPUT), handle_estop_interrupt, FALLING);

    // Motor control pins
    pinMode(PIN_MOTOR_L_PWM, OUTPUT);
    pinMode(PIN_MOTOR_L_DIR, OUTPUT);
    pinMode(PIN_MOTOR_R_PWM, OUTPUT);
    pinMode(PIN_MOTOR_R_DIR, OUTPUT);

    // Attach servos
    s_head_pan.attach(PIN_SERVO_HEAD_PAN);
    s_head_tilt.attach(PIN_SERVO_HEAD_TILT);
    s_waist_yaw.attach(PIN_SERVO_WAIST_YAW);
    s_l_shoulder_pitch.attach(PIN_SERVO_L_SHOULDER_PITCH);
    s_r_shoulder_pitch.attach(PIN_SERVO_R_SHOULDER_PITCH);
    s_l_shoulder_roll.attach(PIN_SERVO_L_SHOULDER_ROLL);
    s_r_shoulder_roll.attach(PIN_SERVO_R_SHOULDER_ROLL);
    s_l_elbow.attach(PIN_SERVO_L_ELBOW);
    s_r_elbow.attach(PIN_SERVO_R_ELBOW);

    digitalWrite(PIN_STATUS_LED, LOW);
}

void update_servos() {
    // Map degree values (-90 to +90) to servo write microsecond/angle
    s_head_pan.write(map((int)current_joints.head_pan, -90, 90, 0, 180));
    s_head_tilt.write(map((int)current_joints.head_tilt, -35, 35, 55, 125));
    s_waist_yaw.write(map((int)current_joints.waist_yaw, -45, 45, 45, 135));
    s_l_shoulder_pitch.write(map((int)current_joints.l_shoulder_pitch, -20, 150, 20, 170));
    s_r_shoulder_pitch.write(map((int)current_joints.r_shoulder_pitch, -20, 150, 160, 10));
    s_l_shoulder_roll.write(map((int)current_joints.l_shoulder_roll, 0, 90, 0, 90));
    s_r_shoulder_roll.write(map((int)current_joints.r_shoulder_roll, 0, 90, 180, 90));
    s_l_elbow.write(map((int)current_joints.l_elbow, 0, 120, 0, 120));
    s_r_elbow.write(map((int)current_joints.r_elbow, 0, 120, 180, 60));
}

void loop() {
    if (estop_active) {
        delay(20);
        return;
    }

    // Process serial JSON commands from MPU/gateway if available
    if (Serial.available()) {
        String line = Serial.readStringUntil('\n');
        line.trim();
        if (line.startsWith("SET_JOINTS")) {
            // e.g. SET_JOINTS hp ht wy lsp rsp lsr rsr le re
            // Parse and update target_joints
        } else if (line.equals("ESTOP_CLEAR")) {
            estop_active = false;
            digitalWrite(PIN_STATUS_LED, LOW);
        }
    }

    // Slew joints smoothly towards target (50Hz loop)
    float delta_slew = 2.0f; // degrees per tick approx
    current_joints.head_pan = slew_angle(current_joints.head_pan, target_joints.head_pan, delta_slew);
    current_joints.head_tilt = slew_angle(current_joints.head_tilt, target_joints.head_tilt, delta_slew);
    current_joints.waist_yaw = slew_angle(current_joints.waist_yaw, target_joints.waist_yaw, delta_slew);
    current_joints.l_shoulder_pitch = slew_angle(current_joints.l_shoulder_pitch, target_joints.l_shoulder_pitch, delta_slew);
    current_joints.r_shoulder_pitch = slew_angle(current_joints.r_shoulder_pitch, target_joints.r_shoulder_pitch, delta_slew);
    current_joints.l_shoulder_roll = slew_angle(current_joints.l_shoulder_roll, target_joints.l_shoulder_roll, delta_slew);
    current_joints.r_shoulder_roll = slew_angle(current_joints.r_shoulder_roll, target_joints.r_shoulder_roll, delta_slew);
    current_joints.l_elbow = slew_angle(current_joints.l_elbow, target_joints.l_elbow, delta_slew);
    current_joints.r_elbow = slew_angle(current_joints.r_elbow, target_joints.r_elbow, delta_slew);

    current_joints = clamp_joints(current_joints);
    update_servos();

    delay(20);
}
