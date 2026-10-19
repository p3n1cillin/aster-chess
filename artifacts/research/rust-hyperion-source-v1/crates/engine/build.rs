use sha2::{Digest, Sha256};
fn main() {
    println!("cargo:rerun-if-changed=viridithas.nnue.zst");
    let bytes = std::fs::read("viridithas.nnue.zst")
        .expect("Run python scripts/fetch_rust_network.py before building Aster");
    assert_eq!(
        format!("{:x}", Sha256::digest(bytes)),
        "2a7d2ef636767d2cf56bbae12cec42e72845156fc2607bf92bdcfc9c98b03944",
        "Aster's pinned neural network checksum does not match"
    );
}
