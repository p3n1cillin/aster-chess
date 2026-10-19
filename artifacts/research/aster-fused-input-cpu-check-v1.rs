// Copyright (C) 2026 Aster contributors. SPDX-License-Identifier: GPL-3.0-or-later
// Development receipt: records whether this host can exercise the fused path.
fn main() {
    println!(
        "{{\"avx512f\":{},\"avx512bw\":{},\"avx512vnni\":{},\"avx512vbmi2\":{}}}",
        is_x86_feature_detected!("avx512f"),
        is_x86_feature_detected!("avx512bw"),
        is_x86_feature_detected!("avx512vnni"),
        is_x86_feature_detected!("avx512vbmi2"),
    );
}
