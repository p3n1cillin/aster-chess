use sha2::{Digest, Sha256};
fn main() {
    println!("cargo:rerun-if-changed=viridithas.nnue.zst");
    let bytes = std::fs::read("viridithas.nnue.zst")
        .expect("Run python scripts/fetch_rust_network.py before building Aster");
    assert_eq!(
        format!("{:x}", Sha256::digest(bytes)),
        "066c172e22c25ee3d3b4084ad44ff761426f906a9c536cabd0127d17413d0585",
        "Aster's pinned neural network checksum does not match"
    );
}
