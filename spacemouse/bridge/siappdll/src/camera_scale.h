#pragma once
#include <windows.h>

// Fusion 2705.1.30: validate the complete camera routine before accessing its
// shared floating-point normalizer. Unknown builds are left untouched.
double* fusion_camera_normalizer(HMODULE module);
bool set_camera_normalizer(double* normalizer, double scale);
void apply_camera_scale();
void restore_camera_scale();
